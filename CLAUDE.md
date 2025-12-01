# Jarvis AI Remediation Service

AI-powered infrastructure alert remediation for homelabs. Automatically analyzes and fixes alerts from Prometheus/Alertmanager using Claude AI.

**Current Version:** 3.8.0 (Phase 4 Complete)

## Quick Reference

```bash
# Start development
docker compose up -d

# View logs
docker logs -f jarvis

# Check health
curl http://localhost:8000/health

# View learned patterns
curl http://localhost:8000/patterns

# Analytics
curl http://localhost:8000/analytics

# Prometheus metrics (Phase 4)
curl http://localhost:8000/metrics

# List runbooks (Phase 4)
curl http://localhost:8000/runbooks
```

## Architecture

```
Alertmanager -> Jarvis (FastAPI) -> Claude AI -> SSH Executor -> Target Hosts
                    |                  |              |
                    v                  |              v
               PostgreSQL <------------+       Your Infrastructure
                    |
                    v
    +---------------------------------------+
    |           Phase 1-4 Features           |
    +---------------------------------------+
    | - Prometheus verification loop         |
    | - Loki log context queries            |
    | - Alert correlation engine            |
    | - Home Assistant API integration      |
    | - n8n workflow orchestration          |
    | - Proactive monitoring                |
    | - Rollback capability                 |
    | - Runbook-guided remediation          |
    | - Prometheus metrics export           |
    +---------------------------------------+
                    |
                    v
            Discord Notifications
```

**Tech Stack:**
- Python 3.11 + FastAPI + asyncio
- PostgreSQL 16 (postgres-jarvis container, port 5433)
- Claude 3.5 Haiku API for analysis
- asyncssh for remote execution
- prometheus-client for metrics export
- Discord webhooks for notifications

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, webhook handler, orchestration |
| `app/claude_agent.py` | Claude API integration, agentic tool calling |
| `app/ssh_executor.py` | SSH connection pooling, command execution |
| `app/command_validator.py` | Safety checks, dangerous pattern blocking |
| `app/database.py` | PostgreSQL operations, attempt tracking |
| `app/learning_engine.py` | Pattern learning from successful fixes |
| `app/discord_notifier.py` | Rich Discord embeds |
| `app/prometheus_client.py` | Prometheus API queries, verification (Phase 1) |
| `app/loki_client.py` | Loki log queries for context (Phase 1) |
| `app/alert_correlator.py` | Root cause correlation engine (Phase 2) |
| `app/homeassistant_client.py` | HA Supervisor API client (Phase 2) |
| `app/n8n_client.py` | n8n workflow orchestration (Phase 3) |
| `app/proactive_monitor.py` | Proactive issue detection (Phase 3) |
| `app/rollback_manager.py` | State snapshots and rollback (Phase 3) |
| `app/metrics.py` | Prometheus metrics definitions (Phase 4) |
| `app/runbook_manager.py` | Runbook loading and parsing (Phase 4) |
| `runbooks/*.md` | Alert-specific remediation guidance (Phase 4) |
| `docker-compose.yml` | Container orchestration |
| `init-db.sql` | Database schema + pre-seeded patterns |

## Database Schema

```sql
-- Main remediation log
remediation_log (
  id, timestamp, alert_name, alert_instance, severity,
  attempt_number, ai_analysis, commands_executed,
  success, error_message, duration_seconds
)

-- Learned patterns (machine learning)
remediation_patterns (
  id, alert_name, pattern_signature, commands,
  success_count, failure_count, confidence_score,
  last_used, created_at
)
```

## Common Development Tasks

### Testing Alerts
```bash
# Send test alert
./test_alert.sh

# Manual webhook test
curl -X POST http://localhost:8000/webhook \
  -u alertmanager:YOUR_PASSWORD \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/container_down.json
```

### Database Operations
```bash
# Connect to database
docker exec -it postgres-jarvis psql -U jarvis -d jarvis

# View recent remediations
SELECT alert_name, alert_instance, success, timestamp
FROM remediation_log ORDER BY timestamp DESC LIMIT 10;

# Check pattern confidence
SELECT alert_name, pattern_signature, confidence_score, success_count
FROM remediation_patterns ORDER BY confidence_score DESC;

# Clear test data
DELETE FROM remediation_log WHERE alert_name LIKE 'Test%';
```

### Deployment
```bash
# Build and deploy
docker compose build
docker compose up -d

# View version
cat VERSION

# Restart after code changes
docker compose restart jarvis
```

## Maintenance Windows

Before performing planned maintenance on infrastructure:

```bash
# Start maintenance (suppresses auto-remediation)
curl -X POST "http://localhost:8000/maintenance/start?host=myhost&reason=Upgrade&created_by=admin"

# Check status
curl http://localhost:8000/maintenance/status

# End maintenance
curl -X POST http://localhost:8000/maintenance/end
```

## Key Configuration

Environment variables (`.env`):

**Core Settings:**
- `ANTHROPIC_API_KEY` - Claude API key (required)
- `DATABASE_URL` - PostgreSQL connection string (required)
- `DISCORD_WEBHOOK_URL` - Notifications channel (required)
- `WEBHOOK_AUTH_PASSWORD` - Alertmanager auth password (required)
- `MAX_ATTEMPTS_PER_ALERT` - Default 3
- `ATTEMPT_WINDOW_HOURS` - Default 2

**SSH Configuration (required for each host):**
- `SSH_NEXUS_HOST`, `SSH_NEXUS_USER` - Primary service host
- `SSH_HOMEASSISTANT_HOST`, `SSH_HOMEASSISTANT_USER` - Home Assistant
- `SSH_OUTPOST_HOST`, `SSH_OUTPOST_USER` - Cloud/VPS host
- `SSH_SKYNET_HOST`, `SSH_SKYNET_USER` - Management host

**Phase 1 - Verification & Logs:**
- `PROMETHEUS_URL` - Prometheus API (default: http://localhost:9090)
- `LOKI_URL` - Loki log API (default: http://localhost:3100)
- `VERIFICATION_ENABLED` - Enable alert verification (default: true)
- `VERIFICATION_MAX_WAIT_SECONDS` - Max verification wait (default: 120)

**Phase 2 - Home Assistant:**
- `HA_URL` - Home Assistant API (default: http://localhost:8123)
- `HA_SUPERVISOR_URL` - Supervisor API (default: http://supervisor/core)
- `HA_TOKEN` - Long-lived access token

**Phase 3 - Orchestration:**
- `N8N_URL` - n8n API (default: http://localhost:5678)
- `N8N_API_KEY` - n8n API key
- `PROACTIVE_MONITORING_ENABLED` - Enable proactive checks (default: true)
- `PROACTIVE_CHECK_INTERVAL` - Check interval seconds (default: 300)

## Safety Features

**Blocked Commands (68 patterns):**
- `rm -rf`, `reboot`, `shutdown`
- `docker stop jarvis` (self-protection)
- `iptables`, `firewall-cmd`
- `systemctl stop` on critical services

**Diagnostic Commands (don't count as attempts):**
- `docker ps`, `docker logs`
- `systemctl status`
- `curl -I`, `ping`

## Troubleshooting

### SSH Connection Failures
```bash
# Verify SSH key
ls -la ssh_key
# Should be 600 permissions

# Test manually
ssh -i ssh_key user@host 'echo test'
```

### Database Issues
```bash
# Check container health
docker ps | grep postgres-jarvis

# View postgres logs
docker logs postgres-jarvis --tail 50

# Restart database
docker compose restart postgres-jarvis
```

### Claude API Errors
- Check API key validity in `.env`
- Verify credit balance at console.anthropic.com
- Rate limits: 4000 requests/minute for Haiku

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhook` | POST | Alertmanager webhook receiver |
| `/patterns` | GET | List learned remediation patterns |
| `/analytics` | GET | Remediation analytics and stats |
| `/metrics` | GET | Prometheus metrics export (Phase 4) |
| `/runbooks` | GET | List available runbooks (Phase 4) |
| `/runbooks/{alert_name}` | GET | Get specific runbook (Phase 4) |
| `/runbooks/reload` | POST | Hot-reload runbooks from disk (Phase 4) |
| `/maintenance/start` | POST | Start maintenance window |
| `/maintenance/end` | POST | End maintenance window |
| `/maintenance/status` | GET | Check maintenance status |

## Phase Features Summary

### Phase 1: Foundation (v3.5.0)
- **Alert Verification Loop** - Confirms fixes via Prometheus, not just exit codes
- **Loki Log Context** - Queries aggregated logs for application errors
- **Failure Pattern Learning** - Learns from failed attempts to avoid repeating mistakes

### Phase 2: Intelligence (v3.6.0)
- **Prometheus Metric History** - Trend analysis, exhaustion prediction
- **Root Cause Correlation** - Links related alerts, prioritizes root cause
- **Home Assistant Integration** - Restarts addons, reloads automations via API

### Phase 3: Advanced (v3.7.0)
- **n8n Workflow Orchestration** - Triggers complex multi-step workflows
- **Proactive Monitoring** - Detects issues before alerts fire
- **Rollback Capability** - Snapshots state before changes, enables undo

### Phase 4: Polish (v3.8.0)
- **Prometheus Metrics Export** - Self-monitoring via `/metrics` endpoint
- **Runbook Integration** - Structured remediation guidance for Claude
- **Sample Runbooks** - ContainerDown, WireGuardVPNDown, DiskSpaceLow, HighMemoryUsage, BackupStale

## Documentation

| Doc | Contents |
|-----|----------|
| `ARCHITECTURE.md` | Deep dive into system design |
| `DEPLOYMENT.md` | Production deployment guide |
| `TROUBLESHOOTING.md` | Common issues and fixes |
| `COST-OPTIMIZATION.md` | API cost reduction strategies |
| `CHANGELOG.md` | Version history |
| `SELF_SUFFICIENCY_ROADMAP.md` | Phase 1-4 implementation plan |
| `runbooks/*.md` | Alert-specific remediation guides |
