# Jarvis - AI-Powered Homelab Remediation Service

**Autonomous service health monitoring and remediation for homelab infrastructure.**

Jarvis monitors Prometheus alerts and automatically remediates common service failures using Claude AI to analyze issues and execute safe corrective actions via SSH.

---

## Quick Start

### Option 1: Pull Pre-Built Image (Fastest)

```bash
# Pull the latest release
docker pull registry.theburrow.casa/jarvis:latest

# Or pull a specific version
docker pull registry.theburrow.casa/jarvis:v4.0.2

# Download docker-compose.yml and .env.example
curl -O https://raw.githubusercontent.com/PotatoRick/Jarvis-HomeLab-AI/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/PotatoRick/Jarvis-HomeLab-AI/main/.env.example

# Configure and deploy
cp .env.example .env
# Edit .env with your credentials
docker compose up -d
```

### Option 2: Clone and Use Setup Wizard (Recommended for new users)

```bash
# Clone the repository
git clone https://github.com/PotatoRick/Jarvis-HomeLab-AI.git
cd Jarvis-HomeLab-AI

# Run the interactive setup wizard
./setup.sh
```

The setup wizard will:
1. Guide you through configuration (Quick Start or Full Setup)
2. Generate a secure `.env` file with your credentials
3. Set up or import your SSH key
4. Validate all connections
5. Deploy Jarvis with Docker Compose

### Option 3: Manual Setup

```bash
# Clone and configure manually
git clone https://github.com/PotatoRick/Jarvis-HomeLab-AI.git
cd Jarvis-HomeLab-AI
cp .env.example .env

# Edit with your values
nano .env

# Set up SSH key
cp ~/.ssh/your_key ./ssh_key
chmod 600 ./ssh_key

# Deploy
docker compose up -d
```

### Verify Installation

```bash
# Check health endpoint
curl http://localhost:8000/health

# View logs
docker logs -f jarvis
```

---

## Prerequisites

- Docker and Docker Compose
- SSH access to your homelab hosts
- Claude API key from [Anthropic](https://console.anthropic.com/)
- (Optional) Discord webhook for notifications
- (Optional) Prometheus + Alertmanager for automatic alert triggering

---

## Features

### Core Capabilities
- **Autonomous Remediation**: Analyzes alerts and executes corrective commands automatically
- **Multi-Host Support**: SSH into multiple servers to fix issues across your infrastructure
- **Smart Command Validation**: Blacklist-only safety checks prevent destructive actions
- **Attempt Tracking**: Rolling window with configurable max attempts before escalation
- **Container-Specific Tracking**: Separate attempt counters for each container
- **Diagnostic Command Filtering**: Only state-changing commands count toward attempts
- **Self-Preservation Mechanism**: Can safely restart itself or dependencies via n8n orchestration
- **Context Continuation**: Automatically resumes interrupted remediations after restart
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
- After max failed attempts (default: 3 in 2 hours)
- When dangerous commands are suggested by AI
- When maintenance mode is enabled

---

## Architecture

Jarvis operates as a FastAPI service that:

1. **Receives webhook** from Alertmanager when alert fires
2. **Queries database** to check attempt history
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

### Interactive Setup (Recommended)

Run `./setup.sh` for guided configuration with validation.

### Environment Variables

See [CONFIGURATION.md](./CONFIGURATION.md) for complete reference, or view the fully-documented `.env.example` file.

**Key Settings:**
- `MAX_ATTEMPTS_PER_ALERT=3` - Attempts before escalation
- `ATTEMPT_WINDOW_HOURS=2` - Rolling window for attempt tracking
- `CLAUDE_MODEL=claude-3-5-haiku-20241022` - AI model (Haiku for cost optimization)
- `COMMAND_EXECUTION_TIMEOUT=60` - SSH command timeout in seconds

### SSH Hosts

Configure your hosts in `.env`:
- `SSH_NEXUS_HOST` - Primary service host (required)
- `SSH_HOMEASSISTANT_HOST` - Home Assistant (optional)
- `SSH_OUTPOST_HOST` - Cloud/VPS host (optional)
- `SSH_SKYNET_HOST` - Management host (optional)

---

## Safety Features

### Blacklist-Only Validation

Jarvis uses a **permissive validation approach**: all commands are allowed unless they match dangerous patterns.

**Blocked Actions:**
- System destruction (`rm -rf`, `mkfs`, `dd`)
- Reboots/shutdowns (`reboot`, `poweroff`, `halt`)
- Firewall changes (`iptables`, `ufw`, `nft`)
- Package management (`apt`, `yum`, `dnf`)
- Self-sabotage (stopping jarvis or its database)

**Allowed (Examples):**
- Service restarts (`docker restart`, `systemctl restart`)
- Diagnostics (`docker ps`, `curl -I`, `systemctl status`)
- Log inspection (`docker logs`, `journalctl`)
- Health checks (`curl`, `ping`, `nc`)

### Self-Protection & Self-Preservation

**Blocked direct execution** (use self-preservation API instead):
- Restarting the `jarvis` container
- Restarting `postgres-jarvis` (its database)
- Restarting Docker daemon
- Rebooting the management host

**Self-Preservation Mechanism:**
When Jarvis needs to restart itself or dependencies, it safely hands off to n8n:
1. Saves current remediation state to database
2. Triggers n8n workflow via webhook
3. n8n executes restart command via SSH
4. n8n polls health endpoint until Jarvis is responsive
5. n8n calls `/resume` to signal completion
6. Jarvis automatically continues interrupted work

**API:**
```bash
# Initiate safe self-restart
curl -X POST "http://localhost:8000/self-restart?target=jarvis&reason=Memory+leak" \
  -u "alertmanager:$WEBHOOK_AUTH_PASSWORD"

# Check status
curl http://localhost:8000/self-restart/status
```

See [CLAUDE.md](./CLAUDE.md#self-preservation-mechanism-phase-5) for complete documentation.

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
# Connect to database
docker exec -it postgres-jarvis psql -U jarvis -d jarvis

# View recent attempts
SELECT timestamp, alert_name, alert_instance, success, commands_executed
FROM remediation_log
ORDER BY timestamp DESC LIMIT 10;

# Check attempt counts by alert
SELECT alert_name, alert_instance, COUNT(*) as attempts
FROM remediation_log
WHERE timestamp > NOW() - INTERVAL '2 hours'
GROUP BY alert_name, alert_instance;
```

---

## Cost Optimization

Jarvis uses **Claude 3.5 Haiku** for AI-powered remediation:

- **Input cost**: $0.80 per 1M tokens (vs $3 for Sonnet)
- **Output cost**: $4 per 1M tokens (vs $15 for Sonnet)
- **Savings**: 73% cost reduction
- **Performance**: Equivalent success rate for remediation tasks

**Typical remediation costs:**
- Average: ~$0.008 per alert (10K input, 500 output tokens)
- With 3 attempts: ~$0.024 total before escalation

For cost analysis and model comparison, see [COST-OPTIMIZATION.md](./COST-OPTIMIZATION.md)

---

## Alertmanager Integration

Add webhook receiver to your Alertmanager config:

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

## Troubleshooting

### Common Issues

**Jarvis not responding to alerts:**
```bash
# Check if service is running
docker ps | grep jarvis

# Check logs for webhook reception
docker logs jarvis | grep webhook_received

# Test webhook manually
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -u alertmanager:your_password \
  -d '{"status":"firing","alerts":[{"labels":{"alertname":"test"}}]}'
```

**SSH connection failures:**
```bash
# Test SSH key manually
ssh -i ./ssh_key user@your-host 'docker ps'

# Check SSH key permissions
ls -la ./ssh_key  # Should be 600

# Run setup validation
./setup.sh --validate
```

**Database connection errors:**
```bash
# Verify database is running
docker ps | grep postgres-jarvis

# Test connection
docker exec postgres-jarvis psql -U jarvis -d jarvis -c "SELECT 1;"
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
├── runbooks/                # Alert-specific remediation guides
├── docker-compose.yml       # Container orchestration
├── Dockerfile               # Image build
├── setup.sh                 # Interactive setup wizard
├── .env.example             # Configuration template
└── ssh_key                  # SSH private key (not committed)
```

### Adding Support for New Alert Types

1. Add alert context to `ai_analyzer.py` prompt
2. Update SSH host selection in `main.py` if needed
3. Create a runbook in `runbooks/` for structured guidance
4. Test with manual webhook:
   ```bash
   curl -X POST http://localhost:8000/webhook \
     -H "Content-Type: application/json" \
     -u alertmanager:password \
     -d @test_alert.json
   ```

### Running Tests
```bash
# Manual alert simulation
ssh your-host 'docker stop some-container'  # Trigger ContainerDown alert
# Watch logs: docker logs -f jarvis
# Container should restart automatically

# Validate configuration
./setup.sh --validate
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Deep dive into system design |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Advanced deployment guide |
| [CONFIGURATION.md](./CONFIGURATION.md) | All configuration options |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | Common issues and fixes |
| [COST-OPTIMIZATION.md](./COST-OPTIMIZATION.md) | API cost reduction strategies |
| [CHANGELOG.md](./CHANGELOG.md) | Version history |
| [CLAUDE.md](./CLAUDE.md) | Developer reference |

---

## Changelog

See [CHANGELOG.md](./CHANGELOG.md) for complete version history.

### Recent Releases

**v4.0.2 - Phase 8 Metadata & Escalation Fixes**
- Fixed escalation reason detection for stagnation
- Added Phase 8 metadata to database schema
- Improved Discord notification formatting

**v4.0.0 - Phase 8 Reasoning-First Architecture**
- New reasoning-first AI analysis approach
- Tiered caching for improved performance
- Enhanced diagnostic command handling

**v3.12.0 - Proactive Anomaly Remediation**
- Statistical anomaly detection with Z-score based analysis
- Automatic remediation of sustained anomalies
- Daily anomaly reports to Discord

**v3.9.0 - Self-Preservation**
- Safe self-restart via n8n orchestration
- Context preservation across restarts
- Automatic continuation of interrupted remediations

---

## Support

**Issues & Feature Requests:** [GitHub Issues](https://github.com/PotatoRick/Jarvis-HomeLab-AI/issues)

**Documentation:**
- Setup wizard: `./setup.sh --help`
- Configuration: `.env.example`
- Troubleshooting: [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)

---

## License

MIT License - See [LICENSE](./LICENSE) for details.

Copyright (c) 2025 PotatoRick

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
