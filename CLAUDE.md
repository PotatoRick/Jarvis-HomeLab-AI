# Jarvis AI Remediation Service

AI-powered infrastructure alert remediation for homelabs. Automatically analyzes and fixes alerts from Prometheus/Alertmanager using Claude AI.

**Current Version:** 4.0.0 (Phase 8 - Reasoning-First Architecture)

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
docker pull registry.theburrow.casa/jarvis:4.0.0

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
curl https://registry.theburrow.casa/v2/jarvis/manifests/4.0.0
```

### Jarvis Hub Features

The Jarvis Hub website (jarvis.theburrow.casa) provides:

- **Dashboard** - Real-time status from connected Jarvis instance
- **Deploy Page** - Step-by-step deployment instructions
- **Changelog** - Full version history with features and fixes
- **Registry Browser** - View available Docker image versions
- **GitHub Link** - Direct link to source repository

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

# Prometheus metrics
curl http://localhost:8000/metrics

# List runbooks
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
    |        Phase 1-8 Features             |           |
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
    | - Reasoning-first diagnostic tools    |   (Phase 8)
    | - Tiered learning engine              |   (Phase 8)
    +---------------------------------------+
                    |
                    v
            Discord Notifications
```

**Tech Stack:**
- Python 3.11 + FastAPI + asyncio
- PostgreSQL 16 (postgres-jarvis container, port 5433)
- Claude API for analysis (Haiku for simple, Sonnet for complex)
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
| `app/learning_engine.py` | Tiered learning: Cached/Hint-Assisted/Full Reasoning (Phase 8) |
| `app/tools/diagnostics.py` | Information-gathering diagnostic tools (Phase 8) |
| `app/tools/safe_executor.py` | Validated execution of Claude's proposals (Phase 8) |
| `app/discord_notifier.py` | Rich Discord embeds |
| `app/prometheus_client.py` | Prometheus API queries, verification |
| `app/loki_client.py` | Loki log queries for context |
| `app/alert_correlator.py` | Root cause correlation engine |
| `app/homeassistant_client.py` | HA Supervisor API client |
| `app/n8n_client.py` | n8n workflow orchestration |
| `app/proactive_monitor.py` | Proactive issue detection |
| `app/rollback_manager.py` | State snapshots and rollback |
| `app/metrics.py` | Prometheus metrics definitions |
| `app/runbook_manager.py` | Runbook loading and parsing |
| `app/self_preservation.py` | Self-restart via n8n handoff |
| `app/anomaly_detector.py` | Statistical anomaly detection |
| `app/health_check_remediation.py` | Autonomous Dockerfile patching |
| `runbooks/*.md` | Alert-specific remediation guidance |
| `docker-compose.yml` | Container orchestration |
| `init-db.sql` | Database schema + pre-seeded patterns |

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
- **Daily Anomaly Reports** - Discord summary at 8 AM of proactive remediations

### Phase 7: Autonomous Dockerfile Remediation (v3.13.0)
- **Health Check Diagnosis** - Extracts and runs health checks inside containers
- **Error Pattern Recognition** - Maps errors to package installations
- **Dockerfile Patching** - Automatically fixes missing binaries
- **Automatic Rebuild** - Rebuilds and verifies container health

### Phase 8: Reasoning-First Architecture (v4.0.0)
- **Diagnostic Tools** - Information-gathering tools that don't decide anything
- **Safe Executor** - Validates and executes Claude's proposed fixes with rollback
- **Tiered Learning Engine** - Cached (zero cost) -> Hint-Assisted (~50% cost) -> Full Reasoning
- **Dynamic Discovery** - No hardcoded host/service lists, discovers infrastructure dynamically
- **Anti-Backsliding Guardrails** - Deprecation tracking for hardcoded patterns

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/webhook` | POST | Alertmanager webhook receiver |
| `/patterns` | GET | List learned remediation patterns |
| `/analytics` | GET | Remediation analytics and stats |
| `/metrics` | GET | Prometheus metrics export |
| `/runbooks` | GET | List available runbooks |
| `/runbooks/{alert_name}` | GET | Get specific runbook |
| `/runbooks/reload` | POST | Hot-reload runbooks from disk |
| `/maintenance/start` | POST | Start maintenance window |
| `/maintenance/end` | POST | End maintenance window |
| `/maintenance/status` | GET | Check maintenance status |
| `/resume` | POST | Resume from n8n handoff after restart |
| `/self-restart` | POST | Initiate safe self-restart via n8n |
| `/self-restart/status` | GET | Check active handoff status |
| `/self-restart/cancel` | POST | Cancel active handoff |
| `/anomalies` | GET | List current detected anomalies |
| `/anomalies/history` | GET | Query historical anomalies |
| `/anomalies/stats` | GET | Anomaly detection statistics |
| `/anomalies/check` | POST | Manually trigger anomaly check |
| `/phase8-metrics` | GET | Phase 8 migration progress (Phase 8) |

## Documentation

| Doc | Contents |
|-----|----------|
| `ARCHITECTURE.md` | Deep dive into system design |
| `DEPLOYMENT.md` | Production deployment guide |
| `TROUBLESHOOTING.md` | Common issues and fixes |
| `COST-OPTIMIZATION.md` | API cost reduction strategies |
| `CHANGELOG.md` | Version history |
| `runbooks/*.md` | Alert-specific remediation guides |
