# Changelog

All notable changes to Jarvis AI Remediation Service will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.13.0] - 2025-12-20

### Added: Autonomous Dockerfile Remediation (Phase 7)

**"Jarvis now fixes container crash loops the same way you would - by patching the Dockerfile"**

This release enables Jarvis to autonomously resolve container crash loops that require Docker image modifications. Previously, when a container was stuck restarting due to a missing binary (like curl in python-slim images), Jarvis could only escalate. Now Jarvis can diagnose the root cause, patch the Dockerfile, rebuild the image, and verify the fix - all without human intervention.

---

### Added

#### Autonomous Health Check Remediation (`app/health_check_remediation.py`)
- **Full diagnosis flow**: Extracts health check config, runs check inside container, identifies failure cause
- **Error pattern recognition**: Maps common errors ("curl: not found") to package installations
- **Base image awareness**: Knows which package manager to use for debian, alpine, etc.
- **Dockerfile patching**: Locates compose directory, backs up Dockerfile, inserts fix instruction
- **Automatic rebuild**: Runs `docker compose build` and `docker compose up -d`
- **Verification loop**: Waits for container to become healthy, rolls back on failure

#### New Claude Tools
- **`fix_container_crash_loop`**: Full autonomous fix - diagnose, patch, rebuild, verify
- **`diagnose_health_check`**: Read-only diagnosis without making changes

#### Intelligent Model Routing
- **Crash loop detection**: Identifies when container alerts indicate a crash loop (2+ attempts)
- **Model selection**: Routes to Sonnet 4.5 for complex crash loops, Haiku 4.5 for simple alerts
- **Cost optimization**: Most alerts still use Haiku, Sonnet only for complex scenarios

#### Safe Dockerfile Operations
- **Command validator patterns**: Whitelisted operations for reading, backing up, and writing Dockerfiles
- **Heredoc file writing**: Uses `cat > file << 'EOF'` to write Dockerfiles safely
- **Rollback support**: Automatic restore from backup if fix doesn't resolve the issue

#### New Runbook
- **`runbooks/ContainerCrashLoop.md`**: Guidance for crash loop scenarios, includes tool usage

### Changed

- **Default model**: Upgraded from Haiku 3.5 to Haiku 4.5 for better reasoning capability
- **Config settings**: Added `crash_loop_model` setting (defaults to Sonnet 4.5)
- **Version**: Bumped to 3.13.0

### Technical Details

#### Crash Loop Detection Flow
1. Alert received for container health issue
2. Check attempt count for this alert
3. If attempt_count >= 2: Flag as crash loop scenario
4. Select Sonnet model for complex reasoning
5. Claude has access to `fix_container_crash_loop` tool
6. Tool handles: diagnose → patch → build → restart → verify → rollback

#### Error Pattern Mapping
```python
ERROR_PATTERNS = {
    "curl: not found": ("curl", "curl"),
    "wget: not found": ("wget", "wget"),
    "nc: not found": ("nc", "netcat-openbsd"),
    "/bin/sh: curl: not found": ("curl", "curl"),
    "exec: \"curl\": executable file not found": ("curl", "curl"),
}
```

#### Package Manager Detection
```python
PACKAGE_MANAGERS = {
    "python:*-slim": "apt-get update && apt-get install -y --no-install-recommends {} && rm -rf /var/lib/apt/lists/*",
    "alpine:*": "apk add --no-cache {}",
    "debian:*": "apt-get update && apt-get install -y {} && rm -rf /var/lib/apt/lists/*",
    "ubuntu:*": "apt-get update && apt-get install -y {} && rm -rf /var/lib/apt/lists/*",
}
```

#### Cost Impact
- **95% of alerts**: Haiku 4.5 (~$0.01/alert)
- **5% crash loops**: Sonnet 4.5 (~$0.03/alert)
- **Haiku 4.5 vs 3.5**: ~25% cost increase but significantly better reasoning
- **Estimated monthly**: ~$1.50 (assuming 100 alerts, 5 crash loops)

---

## [3.12.0] - 2025-12-14

### Added: Proactive Anomaly Remediation (Phase 6 Enhancement)

**"Jarvis now silently fixes sustained anomalies before they become critical alerts"**

This release enhances Phase 6 anomaly detection to trigger autonomous remediation when anomalies persist, rather than just sending notifications. Temporary spikes (like Docker builds) are filtered out, and daily reports summarize what was proactively fixed.

---

### Added

#### Sustained Anomaly Tracking
- **Consecutive detection counting**: Anomalies must persist for 3+ consecutive checks (~15 minutes) before triggering remediation
- **Automatic clearing**: When anomaly resolves, the sustained count resets
- **Spike filtering**: Temporary CPU/memory spikes from builds, backups, etc. are ignored

#### Proactive Remediation Pipeline
- **Synthetic alert generation**: Sustained anomalies create alerts that flow through the standard remediation pipeline
- **Remediation callback**: `_anomaly_remediation_callback()` converts anomaly data to Alert objects
- **Silent resolution**: Issues are fixed without notification unless escalation is needed
- **Full audit trail**: All synthetic alerts logged for daily reporting

#### Daily Anomaly Reports
- **Scheduled at 8 AM local time**: Summary sent to Discord (only if there were synthetic alerts)
- **No spam**: Report is skipped if no anomalies were remediated
- **Severity breakdown**: Shows count of critical/warning/info anomalies handled
- **Alert list**: Top 10 alerts with details, indicates if more were truncated

#### New API Endpoints
- **`GET /anomalies/synthetic-alerts`**: View pending alerts for daily report
- **`POST /anomalies/send-daily-report`**: Manually trigger daily report (requires auth)

### Changed

- **Anomaly detector initialization**: Now wires up remediation callback and starts daily report task
- **Lifespan cleanup**: Properly cancels daily report task on shutdown
- **Version**: Bumped to 3.12.0

### Technical Details

#### Sustained Anomaly Flow
1. Anomaly detected (z-score > threshold)
2. Increment sustained count for that metric/labels combo
3. If count < 3: Continue monitoring (might be temporary spike)
4. If count == 3: Trigger remediation via synthetic alert
5. If count > 3: Already triggered, continue monitoring
6. When anomaly resolves: Clear from sustained tracking

#### Synthetic Alert Format
```python
{
    "alert_name": "AnomalyDetected_CPUUsage",
    "instance": "192.168.0.13:9100",
    "severity": "warning",
    "labels": {
        "anomaly_source": "jarvis_anomaly_detector",
        "metric_name": "CPU Usage",
        "z_score": "4.52",
        "consecutive_detections": "3"
    },
    "annotations": {
        "description": "Statistical anomaly detected...",
        "remediation_hint": "High CPU usage detected..."
    }
}
```

---

## [3.11.0] - 2025-12-14

### Added: Anomaly Detection (Phase 6)

**"Jarvis now detects unusual metric behavior before alerts fire"**

This release introduces Phase 6 of the Self-Sufficiency Roadmap: statistical anomaly detection. Jarvis continuously monitors key infrastructure metrics and detects deviations from normal patterns using z-score analysis against rolling 7-day baselines.

---

### Added

#### Statistical Anomaly Detection Engine (`app/anomaly_detector.py`)
- **Z-score based detection**: Compares current values against 7-day rolling baselines
- **Configurable thresholds**: Warning at z-score 3.0, critical at 4.0 (configurable)
- **Background monitoring**: Runs every 5 minutes (configurable)
- **Cooldown system**: Prevents duplicate notifications for same anomaly

#### Monitored Metrics
| Metric | Query | Description |
|--------|-------|-------------|
| Disk Usage | `node_filesystem_avail_bytes` | Available disk space per mount |
| Memory Usage | `node_memory_MemAvailable_bytes` | Available system memory |
| CPU Usage | `node_cpu_seconds_total` | CPU utilization percentage |
| Container Restarts | `container_restarts_total` | Unexpected container restart spikes |
| Network Errors | `node_network_receive_errs_total` | Network interface errors |
| Disk I/O | `node_disk_io_time_seconds_total` | Disk I/O saturation |

#### Database Schema
- **`anomaly_history` table**: Stores detected anomalies with z-scores, severity, resolution status
- **`metric_baselines` table**: Stores rolling baselines for comparison

#### New API Endpoints
- **`GET /anomalies`**: List currently detected anomalies
- **`GET /anomalies/history`**: Query historical anomalies with filters
- **`GET /anomalies/stats`**: Statistics on anomaly detection performance
- **`POST /anomalies/check`**: Manually trigger anomaly detection check

#### Prometheus Metrics (`app/metrics.py`)
- **`jarvis_anomalies_detected_total`**: Counter by metric name and severity
- **`jarvis_anomaly_checks_total`**: Counter of check cycles (success/error)
- **`jarvis_anomaly_detector_running`**: Gauge (1 = running, 0 = stopped)
- **`jarvis_current_anomalies`**: Gauge of active anomalies by severity

#### Configuration (`app/config.py`)
```python
anomaly_detection_enabled: bool = True
anomaly_check_interval: int = 300  # 5 minutes
anomaly_cooldown_minutes: int = 30
anomaly_z_score_warning: float = 3.0
anomaly_z_score_critical: float = 4.0
```

### Changed

- **Application startup**: Now initializes and starts anomaly detector
- **Application shutdown**: Properly stops anomaly detector
- **Metrics initialization**: Adds anomaly-related gauges
- **Version**: Bumped to 3.11.0

### Technical Details

#### Z-Score Calculation
```
z_score = (current_value - baseline_mean) / baseline_stddev
```

Where baseline is calculated from 7 days of historical data at the same time of day.

#### Anomaly Severity Mapping
- `info`: z-score 2.0-3.0 (unusual but not concerning)
- `warning`: z-score 3.0-4.0 (significant deviation)
- `critical`: z-score > 4.0 (severe anomaly)

---

## [3.10.0] - 2025-12-13

### Added: Jarvis Discord Bot Integration

**"Interactive Claude Code access via Discord - ask questions, get answers, have conversations"**

This release introduces the Jarvis Discord Bot, a companion service that provides interactive access to Claude Code through Discord. Users can @mention Jarvis to ask questions, troubleshoot issues, and have multi-turn conversations with full homelab context.

---

### Added

#### Jarvis Discord Bot (New Companion Service)
- **Location**: `projects/jarvis-discord-bot/`
- **Architecture**: Python Discord.py bot + n8n workflow orchestration + PostgreSQL session tracking
- **Features**:
  - Interactive Claude Code access via Discord @mentions
  - Multi-turn conversational AI with 30-minute session persistence
  - Autonomous command execution (no approval prompts)
  - Role-based access control (homelab-admin required)
  - Rate limiting (10 requests per 5 minutes per user)
  - Agent hints support for specialized expertise
  - Full audit trail for all Discord interactions

#### Discord Bot Components
- **`app/bot.py`** - Main Discord bot (listens for @mentions)
- **`app/message_parser.py`** - Parse agent hints, session commands
- **`app/n8n_client.py`** - HTTP client for n8n webhook
- **`app/rate_limiter.py`** - Per-user rate limiting
- **`app/config.py`** - Environment variable loader

#### n8n Workflow Integration
- **11-node workflow** for Discord-to-Claude orchestration
- Webhook trigger at `/webhook/jarvis-discord-claude`
- SSH execution of Claude Code on Skynet
- Session management via PostgreSQL functions
- Response formatting and Discord callback

#### PostgreSQL Session Management
- **`discord_sessions` table** - Track conversation sessions
  - Session UUID passed to Claude Code `--session-id`
  - 30-minute inactivity timeout
  - Status tracking (active/completed/timeout)
  - Agent hint storage for specialized expertise
- **`discord_messages` table** - Store conversation history
  - Full audit trail of all messages
  - Execution time tracking
  - Model information for analytics
- **Session cleanup automation** - Background cleanup of expired sessions

#### Documentation
- **README.md** - Project overview and quick start
- **USER_GUIDE.md** - User documentation with examples
- **ADMIN_GUIDE.md** - Administration and troubleshooting
- **ARCHITECTURE.md** - Technical architecture diagrams
- **IMPLEMENTATION_STATUS.md** - Complete status tracking

### Fixed
- **Self-Preservation Regex Overmatch**: Fixed command validator incorrectly blocking `docker restart jarvis-discord-bot`
  - **Issue**: Regex pattern `.*jarvis` was too broad, matching all containers with "jarvis" in the name
  - **Impact**: jarvis-discord-bot ContainerUnhealthy alerts were rejected instead of auto-remediated
  - **Fix**: Updated patterns to use negative lookahead `(?!\S)` for exact matching of "jarvis" and "postgres-jarvis" containers only
  - **Result**: jarvis-discord-bot can now be restarted directly; self-preservation still protects critical components
  - **File**: `app/command_validator.py` (DANGEROUS_PATTERNS and SELF_PROTECTION_PATTERNS)

### Removed
- **Old Discord Integration (v3.10.0-alpha)**: Removed incomplete Discord bot integration that was abandoned due to n8n community package bugs
  - Removed `app/discord_handler.py` (Discord request handler)
  - Removed `/analyze` endpoint from `app/main.py`
  - Removed Discord metrics from `app/metrics.py` (`discord_requests_total`, `discord_request_duration`, `discord_rate_limit_hits`)
  - Removed documentation files: `DISCORD_INTEGRATION_STATUS.md`, `DISCORD_INTEGRATION_SUMMARY.md`, `DISCORD_INTEGRATION_DESIGN.md`, `PLAN_DISCORD_INTEGRATION.md`
  - Removed migration: `migrations/v3.10.0_discord_integration.sql`
  - **Note**: `app/discord_notifier.py` retained (used for outgoing webhook notifications, not bot integration)
  - **Reason**: Original implementation relied on buggy n8n Discord trigger package. New standalone Discord bot implementation in progress at `jarvis-discord-bot/`

### Technical Details

#### Discord Command Syntax
- `@Jarvis <prompt>` - Ask question (new session or continue existing)
- `@Jarvis ask <agent> "<prompt>"` - Use specific Claude Code agent
- `@Jarvis done` - End current session

#### Available Agents (via agent hints)
- `homelab-architect` - Infrastructure design, system planning
- `homelab-service-deployer` - Deploy Docker services
- `n8n-workflow-architect` - n8n workflow creation/debugging
- `home-assistant-expert` - HA automations, sensors, integrations
- `homelab-security-auditor` - Security review, audit configs
- `python-claude-code-expert` - Python development
- `technical-documenter` - Documentation creation

#### Session Flow
1. User @mentions Jarvis in Discord
2. Bot validates role (homelab-admin required)
3. Bot checks rate limit (10 req / 5 min)
4. Bot parses message for agent hints
5. Bot POSTs to n8n webhook
6. n8n creates/retrieves session from PostgreSQL
7. n8n executes Claude Code via SSH
8. Response formatted and sent to Discord

### Configuration

#### Environment Variables
```env
# Required
DISCORD_BOT_TOKEN=<from Discord Developer Portal>
DISCORD_CHANNEL_ID=<#jarvis-requests channel ID>
DISCORD_REQUIRED_ROLE=homelab-admin
N8N_WEBHOOK_URL=https://n8n.yourdomain.com/webhook/jarvis-discord-claude

# Optional
RATE_LIMIT_REQUESTS=10
RATE_LIMIT_WINDOW=300
LOG_LEVEL=INFO
```

#### Deployment
```bash
cd projects/jarvis-discord-bot
docker compose build
docker compose up -d
```

### Migration Notes

1. **New service**: No migration needed for existing Jarvis installations
2. **PostgreSQL**: Add tables by running the n8n workflow once (auto-creates via SQL nodes)
3. **n8n**: Import workflow from `configs/n8n-workflows/jarvis-discord-integration.json`
4. **Discord**: Create bot at Discord Developer Portal, add to server with MESSAGE_CONTENT intent

---

## [3.9.1] - 2025-12-07

### Fixed: QA Review Issues for Phase 5

**Comprehensive fixes from QA review addressing security, reliability, and robustness issues.**

---

### Fixed

#### Critical Issues
- **CRITICAL-002**: Added n8n workflow existence validation on startup - Jarvis now checks if the self-restart webhook is accessible and logs warnings if not (`app/main.py` lifespan)
- **CRITICAL-003**: Added Phase 5 prerequisite health checks on startup - validates JARVIS_EXTERNAL_URL, n8n connectivity, and webhook availability with clear warnings (`app/main.py` lifespan)

#### High Priority Issues
- **HIGH-001**: Added Pydantic validator for `JARVIS_EXTERNAL_URL` with URL format validation and localhost warnings (`app/config.py`)
- **HIGH-002**: Added size limits to `RemediationContext` serialization - prevents database overflow with `MAX_COMMANDS=50`, `MAX_OUTPUT_LENGTH=10KB`, `MAX_ANALYSIS_LENGTH=20KB` (`app/self_preservation.py`)
- **HIGH-003**: Improved n8n error differentiation - `trigger_webhook()` now returns specific error types (`workflow_not_found`, `n8n_server_error`, `n8n_client_error`) for better debugging (`app/n8n_client.py`)
- **HIGH-004**: Fixed potential DB pool exhaustion during stale cleanup - now uses `LIMIT 100` batching to prevent unbounded queries (`app/self_preservation.py`)
- **HIGH-006**: Fixed race condition in concurrent restart requests - now uses PostgreSQL advisory lock (`pg_advisory_xact_lock`) within transaction to ensure atomicity (`app/self_preservation.py`)
- **HIGH-007**: Added Pydantic validators for all Phase 5 configuration with bounds checking for `stale_handoff_cleanup_minutes` (10-1440) and `self_restart_timeout_minutes` (2-60) (`app/config.py`)

#### Medium Priority Issues
- **MEDIUM-003**: Added exception handling wrapper for continuation background task - catches exceptions, logs with full traceback, and sends Discord notification on crash (`app/main.py`)
- **MEDIUM-004**: Added authentication to `/resume` endpoint - now accepts HTTP Basic Auth or `X-Jarvis-Handoff-Token` header (`app/main.py`)
- **MEDIUM-008**: Added restart count tracking to `RemediationContext` to prevent infinite restart loops - defaults to `max_restarts=2` (`app/self_preservation.py`)

### Added

#### n8n Client Enhancements (`app/n8n_client.py`)
- **`check_webhook_exists()`**: Probes webhook URL to verify n8n workflow is active
- **`health_check()`**: Checks n8n API health for startup validation

#### Configuration Validators (`app/config.py`)
- `validate_jarvis_external_url()`: URL format validation with localhost warning
- `validate_stale_handoff_cleanup()`: Bounds checking (10-1440 minutes)
- `validate_self_restart_timeout()`: Bounds checking (2-60 minutes)
- `validate_n8n_url()`: URL format validation with trailing slash normalization

#### RemediationContext Improvements (`app/self_preservation.py`)
- `restart_count` field: Tracks number of restarts for this remediation
- `max_restarts` field: Configurable limit (default 2)
- Size limits constants: `MAX_COMMANDS`, `MAX_OUTPUT_LENGTH`, `MAX_ANALYSIS_LENGTH`
- Safe serialization fallback: Returns minimal context if JSON serialization fails

### Changed

- **Startup flow**: Now validates Phase 5 prerequisites before accepting traffic
- **Stale cleanup**: Uses batched processing instead of unbounded query
- **Self-restart initiation**: Uses database transaction with advisory lock for atomicity
- **Resume endpoint**: Requires authentication (was previously unauthenticated)

---

## [3.9.0] - 2025-12-07

### Added: Self-Preservation Mechanism (Phase 5)

**"Jarvis can now safely restart itself and its dependencies via n8n orchestration"**

This release introduces a self-preservation mechanism that allows Jarvis to safely restart its own container, database, or even the host system without bricking itself. The restart is orchestrated by n8n which handles the handoff, executes the restart, polls until healthy, and resumes any interrupted work.

**Tested and verified working in production** - Full self-restart cycle completed successfully with Discord notifications.

---

### Added

#### Remediation Context Continuation (v3.9.0 Enhancement)
- **Context preservation**: When Jarvis triggers a self-restart mid-remediation, it saves the full context:
  - Alert details (name, instance, fingerprint, severity)
  - Commands already executed with their outputs
  - Claude's analysis and reasoning
  - Target host and service information
- **Automatic continuation**: After restart, Jarvis automatically continues the interrupted remediation
- **Smart resumption**: Claude receives context about what was already done to avoid repeating commands
- **Discord notifications**: Updates sent for continuation progress and results

#### Claude Agent Context Tracking (`app/claude_agent.py`)
- **`set_remediation_context()`**: Sets current remediation state before analysis
- **`update_context_commands()`**: Tracks commands as they're executed
- **`update_context_analysis()`**: Stores Claude's analysis for handoff
- **`get_remediation_context()`**: Retrieves context for serialization
- **`clear_remediation_context()`**: Cleans up after successful completion

#### Background Continuation (`app/main.py`)
- **`continue_interrupted_remediation()`**: Background task that:
  - Reconstructs context from saved state
  - Builds continuation prompt with previous work summary
  - Re-invokes Claude with awareness of what's already been done
  - Executes any new commands needed
  - Notifies Discord of continuation results

#### Self-Preservation Manager (`app/self_preservation.py`)
- **SelfPreservationManager class**: Coordinates safe self-restart operations
- **RemediationContext model**: Serializable state for in-progress remediations
- **SelfPreservationHandoff model**: Tracks handoff lifecycle
- **State serialization**: Saves current remediation state before restart
- **n8n workflow trigger**: Hands off restart to external orchestrator
- **Resume capability**: Continues from saved state after restart

#### New API Endpoints
- **POST `/resume`**: Called by n8n after restart to resume operations
- **POST `/self-restart`**: Initiate self-restart via n8n handoff (requires auth)
- **GET `/self-restart/status`**: Check status of active handoffs
- **POST `/self-restart/cancel`**: Cancel an active handoff

#### Claude Agent Tool
- **`initiate_self_restart` tool**: Allows Claude to request safe self-restarts
- Supports targets: `jarvis`, `postgres-jarvis`, `docker-daemon`, `skynet-host`
- Requires reason for audit trail

#### Command Validator Updates (`app/command_validator.py`)
- **Self-protection awareness**: Recognizes commands targeting Jarvis dependencies
- **Handoff override**: Can allow blocked commands when handoff is active
- **Helpful guidance**: Provides `/self-restart` API instructions when blocking self-restart attempts
- **`SELF_PROTECTION_PATTERNS`**: List of commands that require handoff mechanism

#### n8n Workflow
- **`jarvis-self-restart-workflow.json`**: Complete workflow for self-restart orchestration
- Webhook trigger at `/webhook/jarvis-self-restart`
- SSH execution of restart commands
- Health polling with configurable timeout
- Automatic callback to `/resume` endpoint
- Discord notifications for start, success, and timeout

#### Database Schema
- **`self_preservation_handoffs` table**: Persists handoff state across restarts
- Unique index prevents concurrent handoffs
- Tracks status, context, n8n execution ID, and timestamps

#### Prometheus Metrics (`app/metrics.py`)
- **`jarvis_self_restarts_total`**: Counter for self-restart operations by target and status
- **`jarvis_self_restart_failures_total`**: Counter for failures with specific reason codes
- **`jarvis_self_restart_duration_seconds`**: Histogram of restart duration by target
- **`jarvis_self_restart_active`**: Gauge indicating active handoff (1/0)

#### Runbook (`runbooks/JarvisRestart.md`)
- Comprehensive troubleshooting guide for self-preservation system
- Covers timeout issues, n8n trigger failures, SSH problems
- Includes manual recovery procedures

### Changed

- **main.py lifespan**: Initializes SelfPreservationManager on startup
- **main.py lifespan**: Checks for pending handoffs on startup for recovery
- **n8n_client.py**: Now initializes even without API key (webhook-only mode)
- **n8n workflow**: Added 10-minute execution timeout to prevent runaway executions

### Fixed

- **n8n client initialization**: Fixed variable reference so n8n client is properly passed to SelfPreservationManager
- **Test handoffs**: `/resume` endpoint now accepts test handoff IDs (prefix `test-`) without database record
- **Context tracking during tool execution**: `update_context_commands()` now called for `restart_service` and `execute_safe_command` tools
- **Analysis context preservation**: `update_context_analysis()` now called after Claude returns its analysis
- **Callback URL configuration**: Added `JARVIS_EXTERNAL_URL` setting to ensure n8n can reach Jarvis callback
- **Stale handoff cleanup**: Added `cleanup_stale_handoffs()` method that runs on startup to clear abandoned handoffs

### Technical Details

The self-preservation flow:
1. Claude or API initiates self-restart with target and reason
2. SelfPreservationManager serializes current remediation state to database
   - Captures: alert details, commands executed, outputs, Claude analysis, target host
3. n8n workflow is triggered via webhook with restart details
4. n8n responds immediately with handoff acknowledgment
5. n8n executes restart command via SSH
6. n8n polls Jarvis `/health` endpoint until healthy (10s intervals)
7. n8n calls `/resume` endpoint with handoff_id
8. Jarvis marks handoff complete
9. **If remediation context exists**, Jarvis schedules background continuation:
   - Reconstructs context from saved state
   - Re-invokes Claude with summary of previous work
   - Claude determines if additional actions needed after restart
   - Executes any new commands (avoids repeating already-executed ones)
10. Discord notifications sent at each stage (including continuation results)

### Protected Targets

| Target | Command | Description |
|--------|---------|-------------|
| `jarvis` | `docker restart jarvis` | Jarvis container |
| `postgres-jarvis` | `docker restart postgres-jarvis && sleep 10 && docker restart jarvis` | Database + Jarvis |
| `docker-daemon` | `sudo systemctl restart docker` | Docker service |
| `skynet-host` | `sudo reboot` | Full host reboot |

### Migration

For existing databases, run:
```sql
\i migrations/v3.9.0_self_preservation.sql
```

### Configuration

Ensure these are configured in `.env`:
```env
# n8n integration
N8N_URL=https://n8n.theburrow.casa
N8N_API_KEY=your_api_key  # Optional for webhook-only mode

# Self-preservation (IMPORTANT: must be reachable from n8n host)
JARVIS_EXTERNAL_URL=http://192.168.0.13:8000
SELF_RESTART_TIMEOUT_MINUTES=10
STALE_HANDOFF_CLEANUP_MINUTES=30
```

Import the workflow `configs/n8n-workflows/jarvis-self-restart-workflow.json` into n8n.

Configure SSH credentials in n8n:
- Create credential named `skynet-ssh` with SSH key access to Skynet (192.168.0.13)

---

## [3.8.1] - 2025-12-06

### Fixed: BackupStale Multi-System Remediation + Frigate Monitoring Enhancement

**"Jarvis now correctly handles BackupStale alerts for all systems and has enhanced Frigate database corruption detection"**

This release includes two major improvements:
1. BackupStale alerts now correctly route to the appropriate host based on the `system` label
2. Enhanced Frigate health monitoring to detect database corruption that prevents event storage

---

### Part 1: BackupStale Multi-System Remediation

This fixes a critical issue where BackupStale alerts were failing with exit code 127 (command not found) because:
1. The Prometheus alert rule had static `remediation_host: skynet` and `remediation_commands` that only applied to homeassistant
2. The database seed patterns had incorrect script paths
3. The `system` label was not being used to derive the correct host and script

### Changed

#### System-Aware Hint Extraction (`app/utils.py`)
- **Enhanced `extract_hints_from_alert()`**: Now detects BackupStale alerts and derives correct `target_host` and `remediation_commands` from the `system` label
- Added `backup_remediation_map` with system-to-script mappings:
  - `homeassistant` -> skynet -> `/home/t1/homelab/scripts/backup/backup_homeassistant_notify.sh`
  - `skynet` -> skynet -> `/home/t1/homelab/scripts/backup/backup_skynet_notify.sh`
  - `nexus` -> nexus -> `/home/jordan/docker/backups/backup_notify.sh`
  - `outpost` -> outpost -> `/opt/burrow/backups/backup_vps_notify.sh`

#### Corrected Database Seed Patterns (`init-db.sql`)
- Fixed all BackupStale patterns with correct script paths
- Now uses separate INSERT statement with `target_host` column explicitly populated
- Added `BackupHealthCheckStale` pattern with correct path

#### Updated Runbook (`runbooks/BackupStale.md`)
- Complete rewrite with system-specific remediation table
- Added data flow diagram explaining metrics vs fix locations
- Clear documentation that `instance` label is misleading (always shows nexus:9100)
- System-specific command sections for each backup type

### Added

- **Migration script**: `migrations/v3.8.1_fix_backup_patterns.sql`
  - Safely updates existing database with correct patterns
  - Clears old failure patterns to give fresh start
  - Includes verification step
- **Prometheus alert reference**: `configs/prometheus_backup_alerts.yml`
  - Reference configuration without misleading static hints
  - Should be deployed to Nexus to replace current BackupStale rules

### Technical Details

The root cause was a mismatch between:
1. **Where metrics come from**: Nexus textfile collector (scraped via node_exporter)
2. **Where the `system` label indicates**: Which backup is stale
3. **Where fixes should run**: Varies by system (skynet, nexus, or outpost)

The static `remediation_host: skynet` label in the Prometheus alert rule was correct for homeassistant backups but wrong for outpost/nexus backups. Now Jarvis dynamically determines the correct host from the `system` label.

### Configuration Updates

#### `.env` additions
```env
# Prometheus & Loki (on Nexus)
PROMETHEUS_URL=http://192.168.0.11:9090
LOKI_URL=http://192.168.0.11:3100

# Verification Settings
VERIFICATION_ENABLED=true
VERIFICATION_MAX_WAIT_SECONDS=120
VERIFICATION_POLL_INTERVAL=10
```

#### `docker-compose.yml` additions
- Added `PROMETHEUS_URL`, `LOKI_URL` environment variables
- Added `VERIFICATION_ENABLED`, `VERIFICATION_MAX_WAIT_SECONDS`, `VERIFICATION_POLL_INTERVAL`

#### Prometheus Alert Rules (on Nexus)
- Updated `BackupStale` and `BackupAgingWarning` alerts to remove static `remediation_host` and `remediation_commands`
- Added notes explaining Jarvis v3.8.1+ handles routing dynamically

### Deployment Steps

1. Apply database migration:
```bash
docker exec -i postgres-jarvis psql -U jarvis -d jarvis < migrations/v3.8.1_fix_backup_patterns.sql
```

2. Rebuild and restart Jarvis with new config:
```bash
cd /home/t1/homelab/projects/ai-remediation-service
docker compose up -d --force-recreate jarvis
```

3. Verify Prometheus connectivity:
```bash
docker exec jarvis curl -s http://192.168.0.11:9090/api/v1/status/runtimeinfo
```

4. Prometheus alert rules have been updated on Nexus (static hints removed)

---

### Part 2: Enhanced Frigate Database Corruption Detection

A Frigate database corruption incident revealed a gap in monitoring: the existing health checks passed (API responding, cameras online) even when the database was corrupted and unable to store new events.

#### Problem
- Frigate SQLite database corruption prevented event storage
- Cameras showed "no events found" despite motion detection working
- Existing monitoring showed "healthy" because API responded with cached data

#### Solution

**1. Enhanced Frigate Health Exporter v2** (`scripts/exporters/frigate_health_exporter.sh`)

New metrics added:
- `frigate_events_api_up` - Direct database access check via `/api/events`
- `frigate_events_recent` - Whether events were recorded in last hour (staleness detection)
- `frigate_events_last_hour` - Count of recent events for trending
- Expanded error pattern matching (8 patterns, last 500 lines)

**2. New Prometheus Alert Rules** (`configs/prometheus/alert_rules.yml`)

```yaml
- alert: FrigateEventsStale
  expr: frigate_events_recent == 0 and frigate_cameras_receiving_frames == 1 and frigate_api_up == 1
  for: 30m
  # Fires when cameras are online but no events recorded for 1+ hour

- alert: FrigateEventsAPIDown
  expr: frigate_events_api_up == 0 and frigate_api_up == 1
  for: 5m
  # Fires when events API fails but main API works (direct DB corruption detection)
```

**3. New Jarvis Runbook** (`runbooks/FrigateDatabaseError.md`)
- Covers FrigateDatabaseError, FrigateEventsAPIDown, FrigateEventsStale, FrigateCamerasNotReceivingFrames
- Investigation steps, common causes, remediation commands
- Verification steps after restart

**4. Docker Compose Update**
- Added `./runbooks:/app/runbooks:ro` volume mount for hot-reload of runbooks

#### Deployment

1. Deploy updated exporter to Nexus:
```bash
scp scripts/exporters/frigate_health_exporter.sh nexus:/opt/exporters/
ssh nexus 'sudo chmod 755 /opt/exporters/frigate_health_exporter.sh'
```

2. Deploy updated alert rules to Nexus:
```bash
scp configs/prometheus/alert_rules.yml nexus:/home/jordan/docker/home-stack/prometheus/
ssh nexus 'docker exec prometheus kill -HUP 1'
```

3. Restart Jarvis to pick up new runbook mount:
```bash
docker compose up -d jarvis
```

#### Additional Fixes in This Session

- **Pydantic v2 Extra Field Access**: Fixed `_get_extra_field()` helper in `utils.py` to properly access `model_extra` dict for extra fields like `system` label
- **Hints Passed to Claude**: Updated `claude_agent.py` to include extracted hints (system, target_host, system_specific_command) in the Claude prompt
- **Skynet Host Added**: Added "skynet" to all 4 host enums in Claude tool definitions
- **Skynet SSH Configuration**: Added `SSH_SKYNET_HOST=192.168.0.13` and `SSH_SKYNET_USER=t1` to `.env` and `docker-compose.yml`
- **Command Timeout Increased**: Raised `COMMAND_EXECUTION_TIMEOUT` from 60 to 300 seconds for backup scripts
- **Self-Protection Pattern Fixed**: Changed broad `.*skynet` pattern to specific `skynet\.service` to allow `skynet-backup.service` restarts
- **Discord Instance Display**: BackupStale alerts now show system name instead of "nexus:9100" in Discord notifications

---

## [3.8.0] - 2025-12-01

### Phase 4: Self-Sufficiency Roadmap - Polish & Scale

**"Jarvis now exposes Prometheus metrics for self-monitoring and uses runbooks for structured remediation guidance"**

This release implements Phase 4 of the Self-Sufficiency Roadmap, targeting improvement from 85% to 95%+ success rate through:

1. **Prometheus Metrics Export** - Self-monitoring via `/metrics` endpoint
2. **Runbook Integration** - Structured remediation guidance for Claude

[Previous changelog entries truncated for length - see full file for complete history]
