# Jarvis AI Remediation Service

AI-powered infrastructure alert remediation for homelabs. Automatically analyzes and fixes alerts from Prometheus/Alertmanager using Claude AI.

**Current Version:** 3.12.0 (Phase 6 - Proactive Anomaly Remediation)

## Distribution Architecture

Jarvis is distributed through three interconnected components:

```
+---------------------------+     +---------------------------+     +---------------------------+
|    GitHub Repository      |     |    Jarvis Hub Website     |     |    Docker Registry        |
|  github.com/PotatoRick/   |     |  jarvis.theburrow.casa    |     | registry.theburrow.casa   |
|   Jarvis-HomeLab-AI       |     |                           |     |                           |
+---------------------------+     +---------------------------+     +---------------------------+
|                           |     |                           |     |                           |
| - Source code             |     | - Dashboard UI            |     | - Docker images           |
| - Documentation           |     | - Changelog viewer        |     | - Version tags            |
| - Release tags            |     | - Deploy instructions     |     | - Public pulls            |
| - Issue tracking          |     | - Registry browser        |     | - Auth-protected pushes   |
|                           |     | - Live status from Jarvis |     |                           |
+---------------------------+     +---------------------------+     +---------------------------+
           |                                   |                                |
           |                                   |                                |
           v                                   v                                v
     git clone / fork                  View docs & status              docker pull images
```

### Component Details

| Component | URL | Purpose |
|-----------|-----|---------|
| **GitHub** | https://github.com/PotatoRick/Jarvis-HomeLab-AI | Source code, documentation, issues |
| **Jarvis Hub** | https://jarvis.theburrow.casa | Dashboard, changelog, deploy guide |
| **Registry** | https://registry.theburrow.casa | Docker image distribution |

### Docker Images

Pull images directly from the registry:

```bash
# Latest stable release
docker pull registry.theburrow.casa/jarvis:latest

# Specific version
docker pull registry.theburrow.casa/jarvis:3.9.0

# List available tags
curl -s https://registry.theburrow.casa/v2/jarvis/tags/list
```

### Registry API

```bash
# List repositories
curl https://registry.theburrow.casa/v2/_catalog

# List tags for jarvis
curl https://registry.theburrow.casa/v2/jarvis/tags/list

# Get image manifest
curl https://registry.theburrow.casa/v2/jarvis/manifests/3.8.0
```

### Jarvis Hub Features

The Jarvis Hub website (jarvis.theburrow.casa) provides:

- **Dashboard** - Real-time status from connected Jarvis instance
- **Deploy Page** - Step-by-step deployment instructions
- **Changelog** - Full version history with features and fixes
- **Registry Browser** - View available Docker image versions
- **GitHub Link** - Direct link to source repository

### Publishing New Releases (Maintainers)

The registry runs on Outpost and doesn't accept remote pushes. To publish a new version:

```bash
# 1. Build the image locally (from ai-remediation-service directory)
docker build -t registry.theburrow.casa/jarvis:X.Y.Z \
             -t registry.theburrow.casa/jarvis:latest .

# 2. Save image to tarball
docker save registry.theburrow.casa/jarvis:X.Y.Z | gzip > /tmp/jarvis-X.Y.Z.tar.gz

# 3. Copy tarball to Outpost
scp /tmp/jarvis-X.Y.Z.tar.gz outpost:/tmp/

# 4. SSH to Outpost, load image, and push to local registry
ssh outpost
gunzip -c /tmp/jarvis-X.Y.Z.tar.gz | docker load

# 5. Tag for local registry (registry container IP may vary)
REGISTRY_IP=$(docker inspect jarvis-registry --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
docker tag registry.theburrow.casa/jarvis:X.Y.Z ${REGISTRY_IP}:5000/jarvis:X.Y.Z
docker tag registry.theburrow.casa/jarvis:X.Y.Z ${REGISTRY_IP}:5000/jarvis:latest

# 6. Push to registry
docker push ${REGISTRY_IP}:5000/jarvis:X.Y.Z
docker push ${REGISTRY_IP}:5000/jarvis:latest

# 7. Verify
curl -s https://registry.theburrow.casa/v2/jarvis/tags/list
```

**Note:** The registry container is on Docker's internal network, so pushes must go to the container IP (e.g., `172.18.0.5:5000`), not `localhost` or the public URL.

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
                    |                                  |
                    v                                  |
    +---------------------------------------+           |
    |        Phase 1-5 Features             |           |
    +---------------------------------------+           |
    | - Prometheus verification loop         |          |
    | - Loki log context queries            |          |
    | - Alert correlation engine            |          |
    | - Home Assistant API integration      |          |
    | - n8n workflow orchestration          |<---------+
    | - Proactive monitoring                |   (Phase 5: Self-restart handoff)
    | - Rollback capability                 |
    | - Runbook-guided remediation          |
    | - Prometheus metrics export           |
    | - Self-preservation mechanism         |
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
| `app/self_preservation.py` | Self-restart via n8n handoff (Phase 5) |
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

**Phase 5 - Self-Preservation:**
- `JARVIS_EXTERNAL_URL` - External URL for n8n callbacks (default: http://localhost:8000)
- `SELF_RESTART_TIMEOUT_MINUTES` - n8n polling timeout (default: 10)
- `STALE_HANDOFF_CLEANUP_MINUTES` - Cleanup threshold for abandoned handoffs (default: 30)

## Safety Features

**Blocked Commands (68 patterns):**
- `rm -rf`, `reboot`, `shutdown`
- `docker stop jarvis` (self-protection - use `/self-restart` API instead)
- `iptables`, `firewall-cmd`
- `systemctl stop` on critical services

**Self-Protection (Phase 5):**
Commands targeting Jarvis or its dependencies are blocked but can be safely executed via the self-preservation mechanism:
- `docker restart jarvis` -> Use `POST /self-restart?target=jarvis`
- `docker restart postgres-jarvis` -> Use `POST /self-restart?target=postgres-jarvis`
- This triggers n8n to orchestrate the restart and resume after Jarvis is healthy

**Diagnostic Commands (don't count as attempts):**
- `docker ps`, `docker logs`
- `systemctl status`
- `curl -I`, `ping`

## Self-Preservation Mechanism (Phase 5)

Jarvis can safely restart itself or its dependencies via n8n orchestration without bricking itself.

### How It Works

When Jarvis needs to restart (e.g., after fixing a database corruption issue that requires postgres-jarvis restart):

1. **Initiation**: Claude or API initiates self-restart with `POST /self-restart?target=<jarvis|postgres-jarvis|docker-daemon|skynet-host>`
2. **Context Preservation**: Current remediation state is serialized to database (alert details, commands executed, AI analysis)
3. **n8n Handoff**: Jarvis triggers n8n workflow via webhook with handoff ID
4. **External Orchestration**: n8n executes restart command via SSH to Skynet
5. **Health Polling**: n8n polls `/health` endpoint every 10s until Jarvis is responsive
6. **Resume Callback**: n8n calls `/resume` endpoint with handoff_id to signal completion
7. **Automatic Continuation**: If remediation was in progress, Jarvis continues from where it left off

### Protected Restart Targets

| Target | Command | Use Case |
|--------|---------|----------|
| `jarvis` | `docker restart jarvis` | Jarvis container issues (stuck processes, memory leaks) |
| `postgres-jarvis` | `docker restart postgres-jarvis && sleep 10 && docker restart jarvis` | Database corruption or connection exhaustion |
| `docker-daemon` | `sudo systemctl restart docker` | Docker daemon unresponsive |
| `skynet-host` | `sudo reboot` | Host-level issues (kernel panics, system resource exhaustion) |

### Self-Restart API

```bash
# Initiate self-restart (requires webhook auth)
curl -X POST "http://localhost:8000/self-restart?target=jarvis&reason=Memory+leak+detected" \
  -u "alertmanager:$WEBHOOK_AUTH_PASSWORD"

# Check handoff status
curl http://localhost:8000/self-restart/status

# Cancel active handoff (if stuck)
curl -X POST http://localhost:8000/self-restart/cancel \
  -u "alertmanager:$WEBHOOK_AUTH_PASSWORD"
```

### Remediation Context Continuation

If Jarvis restarts mid-remediation, it automatically continues the work:

```
Before Restart:
- Alert: PostgreSQLDown (jarvis database)
- Commands executed: ["docker logs postgres-jarvis", "docker exec postgres-jarvis pg_isready"]
- Analysis: "Database has too many idle connections, restart needed"

After Restart:
- Jarvis resumes with: "Previously executed diagnostic commands, identified connection exhaustion"
- Claude continues: "Connection pool cleared by restart, now verify database health"
- Executes: ["docker exec postgres-jarvis psql -c 'SELECT count(*) FROM pg_stat_activity'"]
- Completes remediation
```

### n8n Workflow Setup

Import `configs/n8n-workflows/jarvis-self-restart-workflow.json` into n8n:

**Requirements:**
- SSH credential named `skynet-ssh` with access to Skynet (192.168.0.13)
- Webhook URL: `https://n8n.theburrow.casa/webhook/jarvis-self-restart`
- Jarvis callback URL configured in `.env` as `JARVIS_EXTERNAL_URL=http://192.168.0.13:8000`

**Workflow Features:**
- 10-minute timeout to prevent runaway executions
- Health polling every 10 seconds
- Discord notifications on timeout or failure
- Automatic callback to `/resume` when healthy

### Troubleshooting Self-Preservation

#### Handoff Timeout (n8n workflow times out)

**Symptoms:** Discord notification "Jarvis self-restart timed out after 10 minutes"

**Diagnosis:**
```bash
# Check if Jarvis is actually running
docker ps | grep jarvis

# Check health endpoint
curl http://192.168.0.13:8000/health

# View handoff status
curl http://192.168.0.13:8000/self-restart/status
```

**Common Causes:**
- Jarvis failed to start after restart (check `docker logs jarvis`)
- Database connection issues preventing health check from passing
- Network connectivity between n8n and Jarvis

**Manual Recovery:**
```bash
# Cancel stuck handoff
curl -X POST http://192.168.0.13:8000/self-restart/cancel \
  -u "alertmanager:$WEBHOOK_AUTH_PASSWORD"

# Manually restart Jarvis
docker restart jarvis

# Verify health
docker logs jarvis --tail 50
```

#### n8n Workflow Not Triggered

**Symptoms:** `/self-restart` returns success but n8n workflow never executes

**Diagnosis:**
```bash
# Check n8n workflow exists and is active
curl https://n8n.theburrow.casa/api/v1/workflows \
  -H "X-N8N-API-KEY: $N8N_API_KEY" | jq '.data[] | select(.name | contains("jarvis"))'

# Check n8n logs
ssh outpost 'docker logs n8n --tail 100 | grep jarvis'

# Verify webhook URL configured correctly in Jarvis
docker exec jarvis env | grep N8N_URL
```

**Common Causes:**
- n8n workflow is inactive (toggle to active in n8n UI)
- Incorrect n8n webhook URL in Jarvis config
- n8n container not running

#### Resume Callback Fails

**Symptoms:** Jarvis restarts successfully but never resumes remediation

**Diagnosis:**
```bash
# Check if n8n can reach Jarvis callback URL
ssh outpost 'curl http://192.168.0.13:8000/health'

# Check handoff table for pending handoffs
docker exec -it postgres-jarvis psql -U jarvis -d jarvis \
  -c "SELECT * FROM self_preservation_handoffs WHERE status = 'active';"

# Check Jarvis logs for resume attempt
docker logs jarvis | grep resume
```

**Common Causes:**
- `JARVIS_EXTERNAL_URL` incorrect or not reachable from n8n host
- Firewall blocking n8n -> Jarvis communication
- Handoff record corrupted or missing from database

**Manual Resume:**
```bash
# Get handoff ID from database
HANDOFF_ID=$(docker exec postgres-jarvis psql -U jarvis -d jarvis -t \
  -c "SELECT handoff_id FROM self_preservation_handoffs WHERE status = 'active' LIMIT 1;" | xargs)

# Manually trigger resume
curl -X POST "http://192.168.0.13:8000/resume?handoff_id=$HANDOFF_ID"
```

#### Stale Handoffs Accumulating

**Symptoms:** Database has many old handoff records with status 'active'

**Automatic Cleanup:** Jarvis automatically cleans up handoffs older than 30 minutes on startup

**Manual Cleanup:**
```bash
# View stale handoffs
docker exec -it postgres-jarvis psql -U jarvis -d jarvis \
  -c "SELECT handoff_id, created_at, status FROM self_preservation_handoffs WHERE created_at < NOW() - INTERVAL '30 minutes';"

# Delete stale handoffs
docker exec -it postgres-jarvis psql -U jarvis -d jarvis \
  -c "DELETE FROM self_preservation_handoffs WHERE created_at < NOW() - INTERVAL '30 minutes';"
```

### See Also

- **Runbook:** `/runbooks/JarvisRestart.md` - Complete troubleshooting guide
- **n8n Workflow:** `/configs/n8n-workflows/jarvis-self-restart-workflow.json`
- **Database Migration:** `/migrations/v3.9.0_self_preservation.sql`

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
| `/resume` | POST | Resume from n8n handoff after restart (Phase 5) |
| `/self-restart` | POST | Initiate safe self-restart via n8n (Phase 5) |
| `/self-restart/status` | GET | Check active handoff status (Phase 5) |
| `/self-restart/cancel` | POST | Cancel active handoff (Phase 5) |
| `/anomalies` | GET | List current detected anomalies (Phase 6) |
| `/anomalies/history` | GET | Query historical anomalies (Phase 6) |
| `/anomalies/stats` | GET | Anomaly detection statistics (Phase 6) |
| `/anomalies/check` | POST | Manually trigger anomaly check (Phase 6) |
| `/anomalies/synthetic-alerts` | GET | View pending synthetic alerts for daily report (Phase 6) |
| `/anomalies/send-daily-report` | POST | Manually send daily anomaly report (Phase 6) |

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

### Phase 5: Self-Preservation (v3.9.0)
- **Safe Self-Restart** - Restart Jarvis or dependencies via n8n orchestration
- **State Serialization** - Save remediation context before restart
- **Automatic Resume** - Continue interrupted work after restart
- **n8n Handoff** - External workflow handles restart polling and callback

### Phase 6: Proactive Anomaly Remediation (v3.12.0)
- **Statistical Anomaly Detection** - Z-score based detection against 7-day baselines
- **Metric Monitoring** - Tracks disk, memory, CPU, container restarts, network errors, disk I/O
- **Sustained Anomaly Tracking** - Only acts on anomalies persisting 3+ consecutive checks (~15 min)
- **Proactive Remediation** - Triggers automatic fixes via synthetic alerts (silent resolution)
- **Daily Anomaly Reports** - Discord summary at 8 AM of proactive remediations (only if any occurred)
- **Anomaly History** - Database persistence for historical analysis
- **Prometheus Metrics** - Self-monitoring of anomaly detection performance

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
