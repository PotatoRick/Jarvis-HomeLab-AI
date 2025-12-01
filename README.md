# Jarvis - AI-Powered Homelab Remediation Service

**Autonomous service health monitoring and remediation for The Burrow homelab infrastructure.**

Jarvis monitors Prometheus alerts and automatically remediates common service failures using Claude AI to analyze issues and execute safe corrective actions via SSH.

---

## Quick Start

### Prerequisites
- PostgreSQL database (for attempt tracking)
- SSH access to monitored hosts
- Claude API key (Anthropic)
- Discord webhook (optional, for notifications)
- Prometheus + Alertmanager (sending webhooks)

### Basic Setup

1. **Clone and configure:**
   ```bash
   cd /home/t1/homelab/projects/ai-remediation-service
   cp .env.example .env
   # Edit .env with your credentials
   ```

2. **Set up SSH key:**
   ```bash
   # Copy your SSH private key
   cp ~/.ssh/your_key ./ssh_key
   chmod 600 ./ssh_key
   ```

3. **Deploy:**
   ```bash
   docker compose up -d
   ```

4. **Verify:**
   ```bash
   docker logs jarvis
   curl http://localhost:8000/health
   ```

### Configure Alertmanager

Add webhook receiver to `/prometheus/alertmanager.yml`:

```yaml
receivers:
  - name: 'jarvis'
    webhook_configs:
      - url: 'http://jarvis:8000/webhook'
        send_resolved: true
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'your_webhook_password'

route:
  receiver: 'jarvis'
  group_by: ['alertname', 'instance']
  group_wait: 5s
  group_interval: 1m
  repeat_interval: 30m
```

---

## Features

### Core Capabilities
- **Autonomous Remediation**: Analyzes alerts and executes corrective commands automatically
- **Multi-Host Support**: SSH into Nexus, Home Assistant, or Outpost to fix issues
- **Smart Command Validation**: Blacklist-only safety checks prevent destructive actions
- **Attempt Tracking**: 2-hour rolling window with configurable max attempts
- **Container-Specific Tracking**: Separate attempt counters for each container
- **Diagnostic Command Filtering**: Only state-changing commands count toward attempts
- **Self-Protection**: Cannot stop/restart itself or critical dependencies
- **SSH Connection Pooling**: Reuses connections for 96% faster execution
- **Discord Notifications**: Real-time alerts for successes, failures, and escalations

### What Jarvis Can Fix

**Common Issues Automatically Resolved:**
- Container crashes (ContainerDown alerts)
- Service health check failures (TargetDown, HealthCheckFailed)
- Disk space warnings (automated cleanup)
- Network connectivity issues (service restarts)
- Certificate renewal failures (automated retry)

**Escalation to Human:**
- After 20 failed attempts in 2 hours
- When dangerous commands are suggested by AI
- When maintenance mode is enabled

---

## Architecture

Jarvis operates as a FastAPI service that:

1. **Receives webhook** from Alertmanager when alert fires
2. **Queries database** to check attempt history (2-hour window)
3. **Calls Claude AI** with alert context and homelab knowledge
4. **Validates commands** against safety blacklist
5. **Executes via SSH** on target host (connection pooling)
6. **Logs results** to PostgreSQL database
7. **Sends Discord notification** with outcome
8. **Clears attempts** when alert resolves

**Key Components:**
- `main.py` - FastAPI webhook receiver and orchestration
- `ssh_executor.py` - SSH connection pooling and command execution
- `command_validator.py` - Blacklist-only safety validation
- `discord_notifier.py` - Rich Discord embed notifications
- `database.py` - PostgreSQL attempt tracking and history
- `ai_analyzer.py` - Claude API integration for remediation planning

For detailed architecture, see [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## Configuration

### Environment Variables

See [CONFIGURATION.md](./CONFIGURATION.md) for complete reference.

**Key Settings:**
- `MAX_ATTEMPTS_PER_ALERT=20` - Attempts before escalation
- `ATTEMPT_WINDOW_HOURS=2` - Rolling window for attempt tracking
- `CLAUDE_MODEL=claude-3-5-haiku-20241022` - AI model (Haiku for cost optimization)
- `COMMAND_EXECUTION_TIMEOUT=60` - SSH command timeout in seconds

### SSH Hosts

Configure three hosts in `.env`:
- `SSH_NEXUS_HOST=192.168.0.11` (service host)
- `SSH_HOMEASSISTANT_HOST=192.168.0.10` (automation hub)
- `SSH_OUTPOST_HOST=72.60.163.242` (cloud gateway)

---

## Safety Features

### Blacklist-Only Validation

Jarvis uses a **permissive validation approach**: all commands are allowed unless they match dangerous patterns.

**Blocked Actions:**
- System destruction (`rm -rf`, `mkfs`, `dd`)
- Reboots/shutdowns (`reboot`, `poweroff`, `halt`)
- Firewall changes (`iptables`, `ufw`, `nft`)
- Package management (`apt`, `yum`, `dnf`)
- Self-sabotage (stopping jarvis, n8n-db, or Skynet services)

**Allowed (Examples):**
- Service restarts (`docker restart`, `systemctl restart`)
- Diagnostics (`docker ps`, `curl -I`, `systemctl status`)
- Log inspection (`docker logs`, `journalctl`)
- Health checks (`curl`, `ping`, `nc`)

### Self-Protection

Jarvis cannot execute commands that would:
- Stop or restart the `jarvis` container
- Stop or restart `n8n-db` (its database)
- Reboot or stop Skynet services (the host it runs on)

---

## Monitoring

### Health Check
```bash
curl http://localhost:8000/health
# {"status": "healthy", "database": "connected"}
```

### Logs
```bash
# Real-time logs
docker logs -f jarvis

# Search for specific alert
docker logs jarvis | grep "alert_name=ContainerDown"

# View SSH connection stats
docker logs jarvis | grep -E "(ssh_connection_established|reusing_ssh_connection)"
```

### Database Queries
```bash
# View recent attempts
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT timestamp, alert_name, alert_instance, success, commands_executed
  FROM remediation_log
  ORDER BY timestamp DESC LIMIT 10;
"'

# Check attempt counts by alert
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT alert_name, alert_instance, COUNT(*) as attempts
  FROM remediation_log
  WHERE timestamp > NOW() - INTERVAL '\''2 hours'\''
  GROUP BY alert_name, alert_instance;
"'
```

---

## Cost Optimization

Jarvis uses **Claude 3.5 Haiku** for AI-powered remediation:

- **Input cost**: $0.80 per 1M tokens (vs $3 for Sonnet 4.5)
- **Output cost**: $4 per 1M tokens (vs $15 for Sonnet 4.5)
- **Savings**: 73% cost reduction
- **Performance**: Equivalent success rate for remediation tasks

**Typical remediation costs:**
- Average: ~$0.008 per alert (10K input, 500 output tokens)
- With 20 attempts: ~$0.16 total before escalation

For cost analysis and model comparison, see [COST-OPTIMIZATION.md](./COST-OPTIMIZATION.md)

---

## Troubleshooting

### Common Issues

**Jarvis not responding to alerts:**
```bash
# Check if service is running
docker ps | grep jarvis

# Check logs for webhook reception
docker logs jarvis | grep webhook_received

# Verify Alertmanager configuration
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -u alertmanager:your_password \
  -d '{"status":"firing","alerts":[{"labels":{"alertname":"test"}}]}'
```

**SSH connection failures:**
```bash
# Test SSH key manually
ssh -i ./ssh_key jordan@192.168.0.11 'docker ps'

# Check SSH key permissions
ls -la ./ssh_key  # Should be 600
```

**Database connection errors:**
```bash
# Verify database is accessible
docker exec n8n-db psql -U n8n -d finance_db -c "SELECT 1;"

# Check DATABASE_URL format
echo $DATABASE_URL  # Should be: postgresql://user:pass@host:port/db
```

For more troubleshooting guides, see [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)

---

## Discord Notifications

Jarvis sends rich embeds to Discord for:

### Success Notification (Green)
- Alert name and instance
- Commands executed
- AI analysis and outcome
- Attempt number and duration

### Failure Notification (Orange)
- Error message and attempted commands
- Attempts remaining
- Diagnostic information

### Escalation Notification (Red, @here ping)
- Summary of all previous attempts
- AI's suggested next action
- Manual intervention request

### Dangerous Command Rejection (Red)
- Rejected commands and reasons
- Alert escalated for manual review

---

## Development

### Project Structure
```
ai-remediation-service/
├── app/
│   ├── main.py              # FastAPI webhook receiver
│   ├── ssh_executor.py      # SSH connection pooling
│   ├── command_validator.py # Safety validation
│   ├── discord_notifier.py  # Discord notifications
│   ├── database.py          # PostgreSQL operations
│   ├── ai_analyzer.py       # Claude API integration
│   ├── models.py            # Pydantic data models
│   └── config.py            # Settings from .env
├── docker-compose.yml       # Container definition
├── Dockerfile               # Image build
├── .env                     # Configuration (not committed)
└── ssh_key                  # SSH private key (not committed)
```

### Adding Support for New Alert Types

1. Add alert context to `ai_analyzer.py` prompt
2. Update SSH host selection in `main.py` if needed
3. Test with manual webhook:
   ```bash
   curl -X POST http://localhost:8000/webhook \
     -H "Content-Type: application/json" \
     -u alertmanager:password \
     -d @test_alert.json
   ```

### Running Tests
```bash
# Manual alert simulation
ssh nexus 'docker stop omada'  # Trigger ContainerDown alert
# Watch logs: docker logs -f jarvis
# Container should restart automatically

# SSH connection pooling verification
docker logs jarvis | grep -E "(ssh_connection_established|reusing_ssh_connection)" | tail -20
```

---

## Deployment

For production deployment instructions, see [DEPLOYMENT.md](./DEPLOYMENT.md)

**Quick deployment on Outpost (Skynet):**
```bash
cd /home/t1/homelab/projects/ai-remediation-service
git pull origin main
docker compose down
docker compose build
docker compose up -d
docker logs -f jarvis
```

---

## Changelog

### November 11, 2025 - Bug Fixes
- **Discord Username Fix**: Changed notification username from "Homelab SRE" to "Jarvis" for consistent branding
- **Notification Parameter Fix**: Fixed `NameError` in success notifications - now correctly passes `max_attempts` parameter
- **Container Instance Detection**: Improved logic to detect when Prometheus already formatted instance as "host:container"
- **Alertmanager Timing**: Optimized `group_interval` from 10s to 1m to prevent duplicate webhook spam while maintaining retry capability

### November 11, 2025 - Major Upgrades
- **SSH Connection Pooling**: 96% faster execution (1 connection + reuses vs 24 new connections)
- **Blacklist-Only Validation**: Removed whitelist, allow all non-destructive commands
- **Self-Protection**: Cannot stop jarvis, n8n-db, or Skynet services
- **Increased Attempts**: 3 → 20 max attempts before escalation
- **Shortened Window**: 24 hours → 2 hours for attempt tracking
- **Cost Optimization**: Switched to Haiku 3.5 (73% cost savings)
- **Service Rename**: "AI Remediation Service" → "Jarvis"
- **Diagnostic Filtering**: Only actionable commands count toward attempts
- **Container-Specific Tracking**: Independent counters for each container
- **Resolution Cleanup**: Attempt history cleared when alerts resolve

For detailed fix history, see [documentation/historical/](./documentation/historical/)

---

## Support

**Owner:** Jordan Hoelscher (hoelscher.jordan@gmail.com)

**Logs & Monitoring:**
- Jarvis logs: `docker logs jarvis`
- Discord: Real-time notifications
- Prometheus: http://prometheus.theburrow.casa
- Grafana: http://grafana.theburrow.casa

**Repository:** `/home/t1/homelab/projects/ai-remediation-service/`

---

## License

Internal homelab project - Not licensed for external use.
