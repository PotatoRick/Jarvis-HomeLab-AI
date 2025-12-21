# Changelog

All notable changes to Jarvis AI Remediation Service will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [4.0.0] - 2025-12-20

### Major: Phase 8 - Reasoning-First Architecture

**"Tools gather information. Claude does the thinking."**

This is a major architectural transformation that changes how Jarvis solves problems. Instead of relying on developer-hardcoded patterns, Jarvis now uses Claude's reasoning to diagnose and fix issues, then learns from successful reasoning to reduce future API costs.

---

### The Problem with v3.x

Version 3.0.0 promised an "Intelligent Investigator" that would reason about problems. But we kept adding hardcoded patterns:
- `ERROR_PATTERNS` dictionary (9 error-to-binary mappings)
- `PACKAGE_MANAGERS` dictionary (7 base image patterns)
- `CASCADE_PATTERNS` in alert_correlator.py (15 patterns)
- `DEPENDENCIES` in alert_correlator.py (18 service mappings)
- Remediation hints in anomaly_detector.py (6 hardcoded suggestions)

When novel problems appeared, Jarvis couldn't solve them because they weren't in the dictionary.

### The Phase 8 Solution

**Tiered Execution Model:**

| Tier | Criteria | What Happens | API Cost |
|------|----------|--------------|----------|
| **1. Cached** | 90%+ confidence, 5+ successes | Execute cached fix directly | **Zero** |
| **2. Hint-Assisted** | 70-90% confidence, 3+ successes | Give Claude the cached solution as hint | **~50%** |
| **3. Full Reasoning** | Novel or low confidence | Full diagnostic + reasoning | **100%** |

**Key Difference:** Patterns come from Claude's successful reasoning, NOT developer hardcoding.

---

### Added

#### Diagnostic Tools (`app/tools/diagnostics.py`)
- **Information-gathering tools that don't decide anything**
- `get_container_diagnostics()` - Health check, Dockerfile, binaries, logs, resources
- `get_service_dependencies()` - Dynamic discovery from compose files, network connections
- `get_system_state()` - Disk, memory, CPU, Docker state, network
- `get_infrastructure_hosts()` - Dynamic host discovery (replaces hardcoded enum)
- `run_diagnostic_command()` - Run arbitrary diagnostic commands

#### Safe Executor (`app/tools/safe_executor.py`)
- **Validates and executes Claude's proposed fixes**
- `apply_dockerfile_patch()` - Apply Dockerfile changes with backup/rollback
- `execute_remediation_plan()` - Multi-step plans with rollback on failure
- `execute_validated_command()` - Single command with validation
- `execute_cleanup_plan()` - Claude-directed disk cleanup

#### Tiered Learning Engine (`app/learning_engine.py`)
- `ExecutionTier` enum: CACHED, HINT_ASSISTED, FULL_REASONING
- `PatternSource` enum: REASONED vs SEEDED (goal: 100% reasoned)
- `get_execution_tier()` - Determine which tier to use for an alert
- `cache_successful_reasoning()` - Cache Claude's reasoning + diagnostics
- `demote_pattern_on_failure()` - Patterns can be demoted, not just promoted
- `get_tier_statistics()` - Monitor tier usage and API savings
- `get_hint_context()` - Build hint context for Tier 2 execution

#### Database Migration (`migrations/v3.14.0_phase8_tiered_caching.sql`)
- New columns: `cached_diagnostics`, `cached_reasoning`, `pattern_source`, `last_failure_reason`
- View `v_tier_statistics` for monitoring tier distribution

#### Anti-Backsliding Guardrails
- Deprecation logging for hardcoded pattern usage
- `get_deprecated_pattern_metrics()` - Track usage of deprecated patterns
- Warning logs when `ERROR_PATTERNS`, `PACKAGE_MANAGERS`, etc. are used
- Goal: These counters trend toward zero over time

### Changed

#### Health Check Remediation (`app/health_check_remediation.py`)
- Added deprecation logging to `_analyze_error()`, `_get_install_command()`, `_locate_dockerfile()`
- Hardcoded patterns still work but log warnings
- Module docstring explains Phase 8 transformation

#### Alert Correlator (`app/alert_correlator.py`)
- Added deprecation logging to DEPENDENCIES and CASCADE_PATTERNS usage
- Added `get_deprecated_pattern_metrics()` for monitoring
- Tracks: dependencies, cascade_patterns, resource_alerts, suffixes usage
- Phase 8 goal: Replace with dynamic dependency discovery

#### Anomaly Detector (`app/anomaly_detector.py`)
- Added deprecation logging to `_get_remediation_hint()`
- Hardcoded hints logged when used
- Phase 8 goal: Claude reasons about diagnostics, not generic hints

#### Runbooks (Phase 8 Diagnostic Format)
Restructured all runbooks from "run these commands" to "gather this data for Claude":
- **ContainerDown.md** - Diagnostic questions for exit codes, dependencies, system state
- **ContainerCrashLoop.md** - Health check diagnostics, base image analysis, Dockerfile location
- **DiskSpaceLow.md** - What's consuming space, Docker resources, log files
- **HighMemoryUsage.md** - Memory consumers, leak detection, OOM history
- **BackupStale.md** - System mapping, failure diagnosis, B2 connectivity
- **WireGuardVPNDown.md** - Both-side diagnostics, handshake analysis
- **FrigateDatabaseError.md** - Database integrity, corruption detection

New runbook structure:
- "Diagnostic Questions for Claude" (what to gather)
- "Information Claude Needs" (data points and why they matter)
- "Claude Should Decide" (reasoning prompts)
- "Common Remediation Actions" (examples, not prescriptions)

#### Phase 8 Metrics Endpoint
- `GET /phase8-metrics` - Monitor migration progress
- Tracks deprecated pattern usage counts
- Shows tiered execution breakdown
- Reports pattern source distribution (reasoned vs seeded)
- Guardrails status reporting

### Migration Notes

1. **Database Migration Required:**
   ```bash
   psql -U jarvis -d jarvis -f migrations/v3.14.0_phase8_tiered_caching.sql
   ```

2. **Breaking Changes:**
   - None - existing functionality preserved with deprecation warnings
   - Hardcoded patterns continue to work during transition

3. **Monitoring:**
   - Watch for `deprecated_hardcoded_pattern_used` log events
   - Query `v_tier_statistics` view for tier distribution
   - Goal: `reasoned_percent` should approach 100%

### Philosophy

> "The right question isn't 'what pattern matches this error?' It's 'what is Claude's diagnosis?'"

Phase 8 Jarvis solves novel problems through reasoning, then learns from success. The hardcoded patterns were training wheels - now Jarvis can ride without them.

---

## [3.13.4] - 2025-12-20

### Fixed: Wire Through `allow_dockerfile_ops` Parameter

#### Bug #4: SSHExecutor Missing `allow_dockerfile_ops` Parameter
- **Issue**: `health_check_remediation.py` passed `allow_dockerfile_ops=True` to `execute_commands()`, but the method didn't accept it
- **Error**: `SSHExecutor.execute_commands() got an unexpected keyword argument 'allow_dockerfile_ops'`
- **Fix**: Added `allow_dockerfile_ops` parameter to:
  - `validate_command_safety()` function
  - `execute_command()` method
  - `execute_commands()` method
- Added `SAFE_DOCKERFILE_PATTERNS` list for heredoc writes and docker compose commands
- Allow newlines in commands containing heredoc syntax (`<<`)

## [3.13.3] - 2025-12-20

### Fixed: Complete Fix for `&&` Shell Operator

#### Bug #3 Continued: `&&` Still Blocked by Command Validator
- **Issue**: Previous fix `r'(?<!\d)&(?![&\d>])'` only handled the FIRST `&` in `&&`, not the second
- **Root cause**: The second `&` in `&&` is preceded by `&` (not a digit), so the lookbehind passed
- **Fix**: Updated lookbehind to `(?<![&\d])` - now excludes both digits AND ampersands

Final pattern: `r'(?<![&\d])&(?![&\d>])'`
- Allows: `&&` (sequential), `2>&1` (stderr redirect), `&>` (redirect)
- Blocks: `command &` (background execution)

## [3.13.2] - 2025-12-20

### Fixed: Allow `&&` Shell Operator (Incomplete)

**Note: This fix was incomplete - see v3.13.3 for the complete fix.**

#### Bug #3: `&&` Blocked by Command Validator
- **Issue**: Pattern `r'(?<!\d)&(?![\d>])'` was blocking `test -f ... && echo 'exists'` commands
- **Root cause**: The pattern was designed to block background `&` but didn't account for `&&` (sequential execution)
- **Partial Fix**: Updated pattern to `r'(?<!\d)&(?![&\d>])'` - but this only fixed the first `&` in `&&`

## [3.13.1] - 2025-12-20

### Fixed: Critical Bug Fixes for Dockerfile Remediation

Two bugs discovered during end-to-end testing prevented the autonomous Dockerfile remediation from working:

#### Bug #1: Health Check Command Extraction
- **Issue**: Docker inspect returns `{"Test": [...]}` (capitalized) but code was looking for `{"test": [...]}`
- **Fix**: Changed `health_config.get("test", [])` to `health_config.get("Test", [])` in health_check_remediation.py

#### Bug #2: `docker exec` Blocked by Validator
- **Issue**: Pattern `r'\bexec\s'` was blocking `docker exec container sh -c` diagnostic commands
- **Fix**: Updated pattern to `r'(?<!docker\s)\bexec\s'` to allow `docker exec` while still blocking shell builtin `exec`

### Changed
- Health check remediation now correctly extracts health check configuration from Docker

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

### Added

#### Prometheus Metrics Export
- **New file**: `app/metrics.py` - Prometheus metric definitions and recording
  - `remediation_total` - Counter of remediation attempts by alert and status
  - `pattern_matches` - Counter of pattern cache hits vs API calls
  - `api_calls` - Counter of Claude API calls by model and status
  - `command_executions` - Counter of SSH commands by host and result
  - `alerts_received` - Counter of alerts from Alertmanager
  - `verification_results` - Counter of verification outcomes
  - `proactive_checks` - Counter of proactive monitoring results
  - `rollback_operations` - Counter of rollback attempts
  - `n8n_workflow_executions` - Counter of n8n workflow triggers
  - `remediation_duration` - Histogram of remediation durations
  - `api_call_duration` - Histogram of Claude API latency
  - `ssh_execution_duration` - Histogram of SSH command latency
  - `active_remediations` - Gauge of currently processing alerts
  - `database_connected` - Gauge of database connection status
  - `pattern_count` - Gauge of learned patterns by confidence
  - `queue_depth` - Gauge of queued alerts (degraded mode)
  - `maintenance_mode` - Gauge of maintenance status
  - `proactive_monitor_running` - Gauge of proactive monitor status
  - `build_info` - Info metric with version details
- **New endpoint**: `GET /metrics` - Prometheus-compatible metrics endpoint

**Example Prometheus Configuration:**
```yaml
- job_name: 'jarvis'
  static_configs:
    - targets: ['your-jarvis-host:8000']
```

#### Runbook Integration
- **New file**: `app/runbook_manager.py` - Runbook loading and management
  - `load_runbooks()` - Load all markdown runbooks from directory
  - `get_runbook()` - Retrieve runbook for specific alert type
  - `get_runbook_context()` - Format runbook for Claude system prompt
  - `list_runbooks()` - List all available runbooks
  - `reload()` - Hot reload runbooks without restart
- **New directory**: `runbooks/` - Markdown runbook files
  - `ContainerDown.md` - Container restart and recovery procedures
  - `WireGuardVPNDown.md` - Cross-system VPN troubleshooting
  - `DiskSpaceLow.md` - Disk cleanup and space recovery
  - `HighMemoryUsage.md` - Memory pressure diagnosis and resolution
  - `BackupStale.md` - Backup system troubleshooting
- **New endpoints**:
  - `GET /runbooks` - List all available runbooks
  - `GET /runbooks/{alert_name}` - Get specific runbook details
  - `POST /runbooks/reload` - Hot reload runbooks from disk
- **Claude integration**: Runbooks automatically included in analysis prompts

**Runbook Format:**
```markdown
# AlertName Remediation Runbook

<!-- risk_level: medium -->
<!-- estimated_duration: 5-10 minutes -->

## Overview
Brief description of the alert and its impact.

## Investigation Steps
1. First thing to check
2. Second thing to check

## Common Causes
- Cause 1
- Cause 2

## Remediation Steps
1. Do this first
2. Then this

## Commands
```bash
# Commands Claude can use
docker restart container
```
```

### Changed

- **Claude Agent**: Now includes runbook context in analysis prompts
- **Main Application**: Initializes metrics and runbook manager on startup
- **Dockerfile**: Now copies `runbooks/` directory into container
- **Requirements**: Added `prometheus-client==0.21.0`
- **Version**: Bumped to 3.8.0

### Metrics Recording

Metrics are automatically recorded throughout the remediation pipeline:
- Alert received → `alerts_received` counter incremented
- Remediation complete → `remediation_total` counter + duration histogram
- Pattern used → `pattern_matches` counter (hit/miss)
- API call made → `api_calls` counter + duration histogram
- SSH command executed → `command_executions` counter

### Technical Details

**Metrics Endpoint:**
- Path: `/metrics`
- Format: Prometheus text exposition format
- No authentication required (internal network only)

**Runbook Loading:**
- Default path: `/app/runbooks/` (Docker) or `./runbooks/` (local dev)
- Format: Markdown with optional YAML frontmatter
- Hot reload: `POST /runbooks/reload`

### Migration Notes

1. No database migration required
2. Add Prometheus scrape target for `/metrics` endpoint
3. Optionally add custom runbooks to `runbooks/` directory
4. Rebuild Docker image to include new runbook files

---

## [3.7.0] - 2025-12-01

### Phase 3: Self-Sufficiency Roadmap - Advanced Capabilities

**"Jarvis now orchestrates complex workflows, proactively detects issues, and can rollback failed changes"**

This release implements Phase 3 of the Self-Sufficiency Roadmap, targeting improvement from 70% to 85% success rate through three key enhancements:

1. **n8n Workflow Orchestration** - Execute multi-step remediation workflows
2. **Proactive Issue Detection** - Detect and fix issues before alerts fire
3. **Rollback Capability** - Snapshot state before changes, enable recovery

### Added

#### n8n Workflow Orchestration
- **New file**: `app/n8n_client.py` - n8n API client for workflow execution
  - `execute_workflow()` - Trigger workflow and optionally wait for completion
  - `execute_workflow_by_name()` - Find and execute workflow by name
  - `list_workflows()` - List all available workflows
  - `get_execution_status()` - Check workflow execution status
  - `trigger_webhook()` - Trigger webhook-based workflows
- **New Claude tools**:
  - `execute_n8n_workflow` - Execute workflow for complex operations
  - `list_n8n_workflows` - Discover available workflows
- **Database table**: `n8n_executions` - Track workflow executions

**Known Jarvis Workflows:**
- `jarvis-database-recovery` - Database backup, restore, and verify
- `jarvis-certificate-renewal` - Certificate renewal and deployment
- `jarvis-full-health-check` - Comprehensive system health check
- `jarvis-docker-cleanup` - Clean up Docker resources across systems

#### Proactive Issue Detection
- **New file**: `app/proactive_monitor.py` - Background monitoring for preventable issues
  - `check_disk_fill_rates()` - Predict disk exhaustion, cleanup if <6h remaining
  - `check_certificate_expiry()` - Warn if certs expire in <30 days
  - `check_memory_trends()` - Detect container memory leaks
  - `check_container_restarts()` - Detect restart loops
  - `check_backup_freshness()` - Verify backups are recent
- **Database table**: `proactive_checks` - Log proactive findings and actions
- **Discord notifications**: Proactive alerts sent as orange embeds

**Proactive Checks (Default: every 5 minutes):**
- Disk fill rate prediction (warn if <24h to exhaustion)
- Certificate expiry monitoring (warn if <30 days)
- Memory leak detection (>5MB/hour growth rate)
- Container restart loop detection (>3 restarts/hour)
- Backup freshness verification (>36 hours stale)

#### Rollback Capability
- **New file**: `app/rollback_manager.py` - State snapshot and recovery
  - `snapshot_container_state()` - Capture container state before changes
  - `snapshot_service_state()` - Capture systemd service state
  - `rollback_container()` - Restore container to snapshot state
  - `should_rollback()` - Analyze if rollback is recommended
  - `list_recent_snapshots()` - View recent snapshots
- **Database table**: `state_snapshots` - Store state snapshots with 24h retention

### Changed

- **Application startup**: Now initializes n8n client, proactive monitor, and rollback manager
- **Application shutdown**: Properly stops proactive monitoring loop
- **Version**: Bumped to 3.7.0

### Configuration

New settings in `app/config.py`:
```python
# Phase 3: n8n workflow orchestration
n8n_url: str = "http://localhost:5678"
n8n_api_key: Optional[str] = None

# Phase 3: Proactive monitoring
proactive_monitoring_enabled: bool = True
proactive_check_interval: int = 300  # 5 minutes
disk_exhaustion_warning_hours: int = 24
cert_expiry_warning_days: int = 30
memory_leak_threshold_mb_per_hour: float = 5.0
```

### Technical Details

**n8n Workflow Tool:**
```json
{
  "name": "execute_n8n_workflow",
  "input_schema": {
    "workflow_name": "jarvis-database-recovery",
    "data": {"optional": "input data"},
    "wait_for_completion": true
  }
}
```

**Proactive Monitoring Flow:**
1. Every 5 minutes, run all check functions
2. Query Prometheus for predictive metrics
3. If issue predicted (e.g., disk fills in <24h):
   - Log to `proactive_checks` table
   - Send Discord notification (4-hour cooldown)
   - Optionally take preemptive action (cleanup, restart)

**Rollback Flow:**
1. Before remediation, capture current state
2. Store snapshot in database
3. If remediation fails or makes things worse:
   - Analyze `should_rollback()`
   - Execute `rollback_container()` (restart container)
4. Snapshots auto-expire after 24 hours

### Migration Notes

1. Database migration required - run `init-db.sql` to create new tables:
   - `proactive_checks` - Proactive monitoring log
   - `state_snapshots` - Rollback snapshots
   - `n8n_executions` - Workflow execution tracking
2. Set `N8N_API_KEY` environment variable if using n8n integration
3. Proactive monitoring is enabled by default, disable with `PROACTIVE_MONITORING_ENABLED=false`

---

## [3.6.0] - 2025-12-01

### Phase 2: Self-Sufficiency Roadmap - Intelligence

**"Jarvis now understands metric trends, correlates related alerts, and can restart Home Assistant addons"**

This release implements Phase 2 of the Self-Sufficiency Roadmap, targeting improvement from 50% to 70% success rate through three key enhancements:

1. **Prometheus Metric History** - Understand trends, predict exhaustion, correlate with events
2. **Root Cause Correlation** - Identify root cause when multiple alerts fire together
3. **Home Assistant Integration** - Restart addons and reload automations via Supervisor API

### Added

#### Prometheus Metric History Tool
- **Enhanced `app/prometheus_client.py`**:
  - `get_metric_trend()` - Analyze metric trends (current, min, max, avg, trend direction)
  - `predict_exhaustion()` - Predict when resources will hit threshold (hours remaining)
- **New Claude tool**: `query_metric_history`
  - Query metric trends for memory, disk, CPU over time
  - Optional exhaustion prediction for proactive remediation
  - Helps Claude understand if problems are getting worse

#### Root Cause Alert Correlation
- **New file**: `app/alert_correlator.py` - Correlation engine for root cause analysis
  - `DEPENDENCIES` map - Service dependency tree (grafana->prometheus, zigbee2mqtt->mosquitto, etc.)
  - `CASCADE_PATTERNS` - Known cascade patterns (VPN down -> remote services, Docker down -> containers)
  - `correlate_alert()` - Check if alert correlates with others
  - `get_correlation_context()` - Generate context string for Claude
  - `should_skip_alert()` - Determine if alert should be skipped (not root cause)
- **Integration in `app/main.py`**:
  - Correlator initialized on startup
  - Each alert checked for correlation before processing
  - Dependent alerts skipped while root cause is being handled
  - Correlation context added to Claude's system prompt

#### Home Assistant Supervisor API Integration
- **New file**: `app/homeassistant_client.py` - HA Supervisor API client
  - `restart_addon()` - Restart HA addons (Zigbee2MQTT, Mosquitto, etc.)
  - `get_addon_info()` - Get addon status, version, state
  - `reload_automations()` - Reload all automations
  - `reload_scripts()` - Reload all scripts
  - `call_service()` - Call any HA service
  - `restart_core()` - Restart Home Assistant Core
  - `ADDON_SLUGS` - Common addon name to slug mapping
- **New Claude tools**:
  - `restart_ha_addon` - Restart HA addon by name or slug
  - `reload_ha_automations` - Reload all automations
  - `get_ha_addon_info` - Get addon status info

### Changed

- **Alert processing flow**: Now checks for alert correlation before remediation
- **Claude context**: Receives correlation information when alerts are related
- **Dependent alerts**: Automatically skipped when root cause is being handled
- **Version**: Bumped to 3.6.0

### Configuration

New settings in `app/config.py`:
```python
# Phase 2: Home Assistant integration
ha_url: str = "http://localhost:8123"
ha_supervisor_url: str = "http://supervisor/core"
ha_token: Optional[str] = None  # Long-lived access token
```

### Technical Details

**Alert Correlation Flow:**
1. Alert received from Alertmanager
2. Check against cascade patterns (VPN+Outpost, Docker+Containers, etc.)
3. Check against dependency map (service dependencies)
4. Check for same-host correlation (multiple alerts on same host)
5. If correlated and not root cause: Skip alert, return status "skipped"
6. If root cause: Add correlation context to Claude prompt

**Supported Cascade Patterns:**
- `WireGuardVPNDown` -> `OutpostDown`, `N8NDown`, `ActualBudgetDown`
- `DockerDaemonUnresponsive` -> `ContainerDown`, `ContainerUnhealthy`
- `HighMemoryUsage` -> `ContainerOOMKilled`
- `DiskSpaceCritical` -> `ContainerDown`
- `PostgreSQLDown` -> `N8NDown`, `GrafanaDown`
- `MQTTBrokerDown` -> `Zigbee2MQTTDown`
- `AdGuardDown` -> `DNSResolutionFailed`

**Home Assistant Tools:**
```json
{
  "name": "restart_ha_addon",
  "input_schema": {
    "addon_slug": "zigbee2mqtt|mosquitto|matter|etc."
  }
}
{
  "name": "reload_ha_automations",
  "input_schema": {}
}
{
  "name": "get_ha_addon_info",
  "input_schema": {
    "addon_slug": "addon name or full slug"
  }
}
```

### Migration Notes

1. Set `HA_TOKEN` environment variable with long-lived access token if using HA integration
2. HA integration is optional - Jarvis works without it but can't restart addons
3. No database migration required for this release

---

## [3.5.0] - 2025-12-01

### Phase 1: Self-Sufficiency Roadmap - Foundation

**"Jarvis now verifies fixes actually worked instead of just checking exit codes"**

This release implements Phase 1 of the Self-Sufficiency Roadmap, targeting improvement from 22% to 50% success rate through three key enhancements:

1. **Alert Verification Loop** - Query Prometheus after remediation to verify alerts resolved
2. **Loki Log Context** - Give Claude access to aggregated logs for better diagnosis
3. **Failure Pattern Learning** - Track what doesn't work to avoid repeating mistakes

### Added

#### Prometheus Alert Verification
- **New file**: `app/prometheus_client.py` - Prometheus API client for alert verification
  - `get_alert_status()` - Check if alert is firing, pending, or resolved
  - `verify_remediation()` - Poll Prometheus to confirm fix worked
  - `query_instant()` and `query_range()` - PromQL query support
  - `get_metric_trend()` - Analyze metric trends over time
  - `predict_exhaustion()` - Predict when resources will exhaust (Phase 2 prep)
- Verification occurs after successful command execution (before declaring success)
- Configurable timeouts: `verification_max_wait_seconds`, `verification_poll_interval`
- Graceful fallback to exit code success if Prometheus unavailable

#### Loki Log Context for Claude
- **New file**: `app/loki_client.py` - Loki API client for centralized log queries
  - `get_container_errors()` - Recent errors from specific container
  - `get_service_logs()` - All logs from a service
  - `search_logs()` - Pattern search across all logs
  - `get_logs_around_time()` - Logs around specific timestamp for correlation
- **New Claude tool**: `query_loki_logs` - Claude can now query Loki directly
  - Query types: `container_errors`, `service_logs`, `search`
  - No SSH required - direct API access to aggregated logs

#### Failure Pattern Learning
- **New database table**: `remediation_failures`
  - Tracks failed remediation patterns with signatures
  - Records failure count, reason, and commands attempted
- **New learning engine methods**:
  - `record_failure_pattern()` - Store failed attempts
  - `get_failed_patterns()` - Retrieve failures for an alert type
  - `should_avoid_commands()` - Check if commands have repeatedly failed
  - `get_failure_stats()` - Statistics on failure patterns

### Changed

- **Success determination**: Now requires Prometheus verification (exit code + alert resolved)
- **Pattern learning**: Only learns from VERIFIED successful remediations
- **Failure handling**: Records failure patterns for future avoidance
- **Response format**: API now includes `verified` and `verification_message` fields

### Configuration

New settings in `app/config.py`:
```python
prometheus_url: str = "http://localhost:9090"
loki_url: str = "http://localhost:3100"
verification_enabled: bool = True
verification_max_wait_seconds: int = 120
verification_poll_interval: int = 10
verification_initial_delay: int = 10
```

### Technical Details

**Verification Flow:**
1. Execute remediation commands
2. If commands succeed (exit code 0):
   a. Wait `initial_delay` seconds for fix to take effect
   b. Poll Prometheus every `poll_interval` seconds
   c. Check if alert state is "resolved"
   d. Continue up to `max_wait_seconds`
3. If verified: Success, learn pattern
4. If not verified: Failure, record failure pattern, potentially escalate

**Loki Query Tool:**
```json
{
  "name": "query_loki_logs",
  "input_schema": {
    "query_type": "container_errors|service_logs|search",
    "target": "container/service name or search pattern",
    "minutes": 15
  }
}
```

### Migration Notes

1. Database migration required - run `init-db.sql` to create `remediation_failures` table
2. Prometheus URL will default to `http://localhost:9090` if not set
3. Loki URL will default to `http://localhost:3100` if not set
4. Verification can be disabled with `VERIFICATION_ENABLED=false` for testing

### Roadmap Progress

| Metric | Before | After Phase 1 | Target |
|--------|--------|---------------|--------|
| Success Rate | 22.2% | 50% (target) | 95%+ |
| Escalation Rate | 63% | 40% (target) | <10% |
| Pattern Coverage | 25 | 35 (target) | 80+ |

Next: Phase 2 (Weeks 3-6) - Prometheus metric history, root cause correlation, HA integration

## [3.4.0] - 2025-12-01

### BackupStale Pattern Matching Fixes

**"Jarvis can now properly identify which system's backup is stale and run the correct fix"**

This release fixes critical issues with BackupStale alert handling where Jarvis was:
1. Not recognizing the `system` label in alerts (e.g., `system=skynet`)
2. Matching generic patterns instead of system-specific patterns
3. Generating wrong commands like `docker run skynet-backup` (doesn't exist)

### Fixed

#### Critical Pattern Matching Fixes
- **PATTERN-001**: Learning engine now uses `system` label for fingerprinting
  - Added `system`, `remediation_host`, and `category` as priority labels
  - These labels are checked first when building symptom fingerprints
  - Example: BackupStale alerts now fingerprint as `BackupStale|system:skynet` instead of just `BackupStale`
  - Location: `learning_engine.py:_build_symptom_fingerprint()`

- **PATTERN-002**: Pattern matching now checks `target_host` in database
  - Patterns with `target_host` column are now matched against alert's `system` or `remediation_host` labels
  - Generic patterns (no `target_host`) are skipped when alert has system info
  - Prevents matching wrong patterns (e.g., homeassistant pattern for skynet backup)
  - Location: `learning_engine.py:find_similar_patterns()`

- **PATTERN-003**: Improved similarity calculation for subset matching
  - If a stored pattern is a subset of the incoming alert, it now scores high (0.7+)
  - Critical labels (`system:`, `container:`, `remediation_host:`) must match for high confidence
  - Location: `learning_engine.py:_calculate_similarity()`

- **PATTERN-004**: Fixed pre-seeded BackupStale patterns in database
  - Pattern ID 23: `system:homeassistant` → runs on `skynet` (HA backup script)
  - Pattern ID 24: `system:nexus` → runs on `nexus`
  - Pattern ID 25: `system:skynet` → runs on `skynet` (backup_skynet.sh)
  - Pattern ID 26: `system:outpost` → runs on `outpost`
  - Deleted broken generic pattern (ID 28) with wrong commands

#### Safe Pipe Commands
- **PIPE-001**: Added safe pipe command whitelist for diagnostics
  - `dmesg | tail`, `dmesg | grep`, `docker ps | grep`, etc. now allowed
  - Prevents blocking legitimate diagnostic commands during investigation
  - Commands must match both left and right side patterns to be allowed
  - Still blocks dangerous pipes like `curl | bash`, arbitrary pipes
  - Location: `ssh_executor.py:SAFE_PIPE_PATTERNS`, `_is_safe_pipe_command()`

### Technical Details

**Root Cause Analysis:**
The original `DANGEROUS_COMMAND_PATTERNS` blocked ALL pipes (`\|(?!\|)`) which:
1. Blocked `gather_logs()` from running `dmesg | tail -N`
2. Blocked Claude's diagnostic commands like `docker ps | grep backup`
3. Forced Claude to generate alternative (wrong) commands

**Solution:**
1. Removed blanket pipe blocking from `DANGEROUS_COMMAND_PATTERNS`
2. Added explicit `SAFE_PIPE_PATTERNS` whitelist for known-safe diagnostic pipes
3. Added `_is_safe_pipe_command()` to validate pipe commands against whitelist
4. Still blocks `| bash`, `| sh`, and arbitrary unknown pipes

**Testing:**
- Sent test BackupStale alert with `system=skynet` label
- Jarvis correctly matched pattern ID 25 (`target_host=skynet`)
- Executed backup script on correct host
- Backup completed successfully, verified against B2

## [3.3.1] - 2025-12-01

### QA Review Bug Fixes (Part 2)

**"Comprehensive QA Review Complete - All 40 Issues Resolved"**

This release completes the QA review that began in v3.3.0, addressing the remaining 28 issues identified during comprehensive code review.

### Security

- **SECURITY-003**: Added shell command injection prevention
  - New `validate_command_safety()` function checks for dangerous patterns
  - Blocks: command chaining (`;`), backgrounding (`&`), pipes to shells, eval, source
  - Allows safe patterns like `2>&1` for stderr redirection
  - Defense-in-depth measure complementing existing whitelist
  - Location: `ssh_executor.py`

- **SECURITY-004**: Truncated webhook URL in error logs
  - Discord webhook URLs now show only first 50 chars in logs
  - Prevents accidental credential exposure in log aggregators
  - Location: `discord_notifier.py:send_webhook()`

### Fixed

#### Critical Fixes
- **CRITICAL-004**: Added error handling to `clear_escalation_cooldown()`
  - Now logs and re-raises database errors instead of silently failing
  - Prevents stuck escalation cooldowns on transient DB errors
  - Location: `database.py`

- **CRITICAL-005**: Fixed learning engine silent failures
  - Added JSON serialization validation for pattern metadata
  - Truncates oversized symptom fingerprints (max 5000 chars)
  - Falls back to minimal metadata on serialization errors
  - Location: `learning_engine.py:extract_pattern()`

#### High Priority Fixes
- **HIGH-001**: Fixed ContainerDown instance parsing
  - Now always prefers explicit `container` and `host` labels over instance format
  - Prevents misrouting when instance label format varies
  - Location: `main.py:process_alert()`

- **HIGH-002**: Added continue-on-failure for diagnostic commands
  - Diagnostic commands (status, logs, inspect) no longer stop batch execution on failure
  - Only action commands (restart, exec) halt on error
  - Location: `ssh_executor.py:execute_commands()`

- **HIGH-005**: Fixed attempt count query for NULL arrays
  - Uses `COALESCE(array_length(commands_executed, 1), 0)` for proper NULL handling
  - Empty arrays and NULL now correctly treated as zero commands
  - Location: `database.py:get_attempt_count()`

- **HIGH-006**: Fixed `record_outcome()` return value
  - Now returns the new confidence score after pattern update
  - Enables callers to track pattern improvement
  - Location: `learning_engine.py`

- **HIGH-007**: Reduced Discord webhook timeout to 3 seconds
  - Fail-fast behavior prevents blocking remediation on Discord issues
  - Location: `discord_notifier.py`

- **HIGH-008**: Improved pattern similarity with weighted matching
  - Alert name: 4x weight (most important)
  - Host/container/service: 2.5-3x weight (routing critical)
  - Generic labels: 1x weight
  - Location: `learning_engine.py:_calculate_similarity()`

- **HIGH-009**: Handle sudo in local execution
  - Strips `sudo` prefix when running in Docker container (already root)
  - Prevents "sudo not found" errors on local commands
  - Location: `ssh_executor.py:_execute_local()`

- **HIGH-012**: Added explicit failure case to retry decorator
  - Logs `retry_exhausted` event on final failure with full error details
  - Includes safety net for unexpected loop exit
  - Location: `database.py:retry_with_backoff()`

#### Medium Priority Fixes
- **MEDIUM-001**: Added 80+ comprehensive diagnostic command patterns
  - Docker: images, port, top, events, info, version, compose config/ls
  - Systemd: is-active, is-enabled, is-failed, show, list-*
  - Network: traceroute, dig, nslookup, host, ip addr/link/route
  - System: vmstat, iostat, mpstat, sar, lscpu, lsmem
  - Files: head, tail, less, more, find, stat, file, wc, diff, checksums
  - Home Assistant: core info/check/stats, backups list, addons/network info
  - Location: `main.py:is_actionable_command()`

- **MEDIUM-002**: Added `force_refresh` parameter to pattern cache
  - Bypasses TTL check when immediate refresh needed
  - Location: `learning_engine.py:_refresh_pattern_cache()`

- **MEDIUM-003**: Added command length validation (10,000 char limit)
  - Prevents potential buffer/injection issues from overly long commands
  - Location: `ssh_executor.py:execute_commands()`

- **MEDIUM-006**: Added external service cache cleanup method
  - `cleanup_stale_cache(max_age_minutes=30)` removes old entries
  - Prevents unbounded memory growth
  - Location: `external_service_monitor.py`

- **MEDIUM-007**: Made Discord @here ping severity-conditional
  - Only pings @here for `critical` severity escalations
  - Warning/info escalations notify without ping
  - Location: `discord_notifier.py:notify_escalation()`

- **MEDIUM-008**: Pattern creation uses INSERT ON CONFLICT
  - Handles race conditions when two processes create same pattern
  - Merges metadata on conflict instead of failing
  - Location: `learning_engine.py:_create_pattern()`

- **MEDIUM-009**: Added tool input validation in Claude agent
  - Validates tool_input is dict before processing
  - Checks required 'host' parameter exists and is string
  - Returns clear error messages for invalid inputs
  - Location: `claude_agent.py:_execute_tool()`

- **MEDIUM-010**: Added Unicode handling for hint extraction
  - `_sanitize_hint_value()` normalizes Unicode characters
  - Removes control characters, handles encoding errors gracefully
  - Location: `utils.py:extract_hints_from_alert()`

- **MEDIUM-015**: Fixed pattern cache timestamp to use timezone-aware datetime
  - Uses `datetime.now(timezone.utc)` for accurate TTL comparisons
  - Prevents timezone-related cache invalidation issues
  - Location: `learning_engine.py:_refresh_pattern_cache()`

#### Low Priority Fixes
- **LOW-003**: Added truncation indicator to Discord notifications
  - `_truncate_with_indicator()` method adds "... (truncated)" suffix
  - Users now know when content was cut off
  - Location: `discord_notifier.py`

- **LOW-007**: Replaced magic numbers with named constants
  - `DISCORD_WEBHOOK_TIMEOUT_SECONDS = 3`
  - `MAX_EMBED_FIELD_LENGTH = 1000`
  - `MAX_TRUNCATED_INDICATOR = "... (truncated)"`
  - Location: `discord_notifier.py`

### Performance

- **PERF-003**: Added connection pooling for Discord webhooks
  - Reusable `aiohttp.ClientSession` instead of new session per request
  - Added `close()` method for cleanup on shutdown
  - Location: `discord_notifier.py`

### Already Implemented (Verified)
- **MEDIUM-013**: Alert queue already has size limit (MAX_QUEUE_SIZE = 500)
- **LOW-002**: SSH connection logging already implemented
- **PERF-001**: Query ordering already optimal (fingerprint check → attempt count)

### Technical Details

#### Command Safety Validation
```python
# Dangerous patterns blocked:
DANGEROUS_COMMAND_PATTERNS = [
    r';',                 # Command separator
    r'(?<!\d)&(?![\d>])', # Backgrounding (but allows 2>&1)
    r'\|(?!\|)',          # Pipe (but allows ||)
    r'`',                 # Backtick substitution
    r'\$\(',              # Command substitution
    r'\$\{',              # Variable expansion
    r'\$[A-Za-z_]',       # Variable reference
    # ... redirects, eval, source, exec
]
```

#### Weighted Similarity Scoring
```python
label_weights = {
    'host': 3.0,        # Most important for routing
    'container': 2.5,   # Service specificity
    'service': 2.5,
    'system': 2.0,      # For backup alerts
    'job': 1.5,
    'severity': 1.0,    # Generic
}
alert_name_weight = 4.0  # Highest weight
```

### Migration Notes

- No database migration required
- Rebuild Docker image to get all fixes: `docker compose build jarvis`
- All changes are backward compatible
- Existing patterns and configurations continue to work

---

## [3.3.0] - 2025-11-30

### QA Review Bug Fixes

**"Comprehensive QA Review & Critical Fixes"**

This release addresses issues identified during a comprehensive QA review of the codebase, including critical bugs, security improvements, and general code quality fixes.

### Security

- **SECURITY-001**: Added `.gitignore` to prevent credential exposure
  - `.env` files now properly excluded from git
  - SSH keys excluded (`ssh_key`, `*.pem`, `id_*`)
  - All sensitive file patterns blocked

### Fixed

#### Critical Fixes
- **CRITICAL-001**: Fixed database connection leak during retry attempts
  - Pool cleanup now occurs before each retry to prevent connection exhaustion
  - Location: `database.py:connect()`

- **CRITICAL-002**: Fixed race condition in fingerprint deduplication
  - New atomic `check_and_set_fingerprint_atomic()` function
  - Uses single PostgreSQL upsert operation to prevent simultaneous alerts from bypassing deduplication
  - Location: `database.py`, `main.py:process_alert()`

- **CRITICAL-003**: Added SSH key permission validation on startup
  - Validates key files exist and have 0o600 permissions
  - Logs warnings for missing or insecure keys
  - New method: `ssh_executor.validate_ssh_keys()`

#### High Priority Fixes
- **HIGH-003**: Fixed SSH key path inconsistency
  - All hosts now consistently use `/app/ssh_key` path
  - Previously some hosts had `/app/ssh-keys/homelab_ed25519`
  - Location: `config.py`

- **HIGH-004**: Fixed database column name mismatches
  - Updated `learning_engine.py` to use `last_used_at` and `updated_at` (matching schema)
  - Fixed SQL index and view in `init-db.sql`

- **HIGH-010**: Added alert fingerprint validation
  - Rejects alerts with empty, None, or whitespace-only fingerprints
  - Normalizes fingerprints by stripping whitespace
  - Location: `main.py:process_alert()`

- **HIGH-011**: Added SSH connection cleanup on shutdown
  - `ssh_executor.close_all_connections()` now called during app shutdown
  - Prevents connection resource leaks

#### Medium Priority Fixes
- **MEDIUM-005**: Fixed maintenance window host case sensitivity
  - Host matching now case-insensitive (e.g., "Nexus" matches "nexus")
  - Uses `LOWER()` SQL function for comparison
  - Location: `database.py:get_active_maintenance_window()`

#### Low Priority Fixes
- **LOW-005**: Fixed Docker healthcheck reliability
  - Changed from `python -c "import httpx; ..."` to `curl -f http://localhost:8000/health`
  - Added `curl` to Dockerfile dependencies
  - More reliable and faster execution

- **LOW-006**: Added `/version` endpoint
  - Returns app name, version, and Python version
  - Useful for monitoring and quick version checks

### Added

- **New API Endpoint**: `GET /version` - Returns version information
- **SSH Key Validation**: `SSHExecutor.validate_ssh_keys()` and `get_key_validation_errors()`
- **Atomic Fingerprint Check**: `Database.check_and_set_fingerprint_atomic()`

### Changed

- Deprecated `check_fingerprint_cooldown()` and `set_fingerprint_processed()` - use `check_and_set_fingerprint_atomic()` instead
- SSH keys now validated on application startup (warnings logged, startup not blocked)
- Dockerfile now includes `curl` package

### Technical Details

#### Atomic Fingerprint Deduplication
```python
# Old approach (race condition vulnerable):
in_cooldown, _ = await db.check_fingerprint_cooldown(fp, 300)
if not in_cooldown:
    await db.set_fingerprint_processed(fp, name, instance)
    # Process alert...

# New approach (atomic):
in_cooldown, _ = await db.check_and_set_fingerprint_atomic(fp, name, instance, 300)
if not in_cooldown:
    # Process alert...  (fingerprint already set atomically)
```

#### SSH Key Validation
```python
# On startup, validates all SSH keys:
ssh_key_errors = ssh_executor.get_key_validation_errors()
# Returns: ["nexus: SSH key not found: /app/ssh_key", ...]
```

### Migration Notes

- No database migration required
- Rebuild Docker image to get new healthcheck and curl
- Review `.gitignore` and ensure no credentials are committed

---

## [3.2.0] - 2025-12-01

### BackupStale Host Determination Fix

**"Fixing Alerts on the Right Host"**

This release fixes a critical issue where Jarvis was executing backup remediation commands on the wrong host. BackupStale alerts for Home Assistant were being fixed on Nexus (where Prometheus scrapes metrics) instead of Skynet (where backup scripts actually run).

### Added

#### Prometheus Alert Enhancements
- **`remediation_host` label**: All alerts now include explicit label specifying where fixes should run
- **`remediation_hint` annotation**: Human-readable guidance for AI
- **`remediation_commands` annotation**: Suggested commands to execute
- **`data_flow` annotation**: Explains where metrics come from vs where problems are

#### Target Host Override in Patterns
- New `target_host` column in `remediation_patterns` table
- Patterns can now override automatic host determination
- Essential for backup alerts where scrape instance differs from remediation host

#### New Pre-Seeded Backup Patterns
| Alert | Target Host | Solution |
|-------|-------------|----------|
| BackupStale (system) | varies | Run the appropriate backup script for the system |
| BackupHealthCheckStale | management-host | Run backup health check script |

### Changed

#### Utils: Improved Host Determination
- `extract_hints_from_alert()` now reads `remediation_host` label first
- `determine_target_host()` prioritizes: explicit label > pattern override > instance parsing
- Backup alerts with `system` label now default to correct host

#### Learning Engine Updates
- Pattern cache now includes `target_host` field
- Fingerprint generation includes `system` label for backup alerts
- Pattern creation supports `target_host` parameter

#### Backup Check Script
- Backup health check script now checks both Daily and Sunday backup folders
- Previously only checked Daily, causing false positives on weekends

### Fixed

- **BackupStale executing on wrong host**: Home Assistant backup alerts now correctly target Skynet
- **Misleading instance labels**: `skynet:9100` (node_exporter) no longer confuses the host resolver
- **Sunday backup false positives**: Backup health check now finds most recent backup across all folders

### Technical Details

#### Database Migration
```sql
-- v3.2.0: Add target_host column
ALTER TABLE remediation_patterns
ADD COLUMN IF NOT EXISTS target_host VARCHAR(50);

-- Update existing backup patterns
UPDATE remediation_patterns SET target_host = 'skynet'
WHERE alert_name = 'BackupStale' AND alert_instance LIKE '%homeassistant%';
```

#### Alert Rule Example
```yaml
- alert: BackupStale
  labels:
    remediation_host: skynet  # NEW: Where to run fixes
  annotations:
    remediation_hint: "Run backup script on Skynet"
    remediation_commands: "/path/to/backup_script.sh"
    data_flow: "Skynet pulls HA backup -> uploads to B2 -> updates metrics"
```

### Test Results

Sent test BackupStale alert for Home Assistant:
- **Target Host**: skynet:9100 (correctly resolved to skynet)
- **Commands Executed**: `sudo systemctl restart homeassistant-backup.timer`, `sudo systemctl restart homeassistant-backup.service`
- **Success**: true
- **Escalated**: false

---

## [3.1.0] - 2025-11-29

### Anti-Spam Overhaul

**"From Alert Storm to Calm Notifications"**

This release fixes a critical issue where Jarvis would spam Discord with 40+ escalation messages when an alert kept firing. Now Jarvis intelligently deduplicates alerts and respects cooldown periods.

### Added

#### Fingerprint-Based Deduplication
- **5-minute cooldown** on identical alerts (same Alertmanager fingerprint)
- Prevents reprocessing when Alertmanager sends repeated webhooks for ongoing alerts
- New database table `alert_processing_cache` tracks recently processed fingerprints
- Returns `"status": "deduplicated"` for skipped alerts

#### Escalation Cooldown System
- **4-hour cooldown** after escalating an alert to Discord
- Prevents "escalation snowball" where same alert spams Discord every minute
- New database table `escalation_cooldowns` tracks when alerts were escalated
- **Resolution-aware**: Cooldown clears when alert resolves, so new incidents get escalated
- Silent logging during cooldown (`escalation_skipped_cooldown` event)

### Changed

#### Attempt Counting Fix (Option D)
- `get_attempt_count()` now **excludes escalation-only records** from the count
- Previously: Each escalation incremented the counter, causing infinite escalations
- Now: Only actual remediation attempts (with commands) count toward `max_attempts_per_alert`
- Query filter: `NOT (escalated = TRUE AND commands_executed IS NULL)`

#### Configuration Updates
- `attempt_window_hours` reduced from 24 to **2 hours** (more reasonable window)
- New setting: `fingerprint_cooldown_seconds: 300` (5 minutes)
- New setting: `escalation_cooldown_hours: 4`

### Fixed

- **Discord spam during alert storms**: BackupAgingWarning incident caused 46+ Discord messages in 2 hours
- **Escalation snowball effect**: Each escalation was counting as an "attempt", triggering more escalations
- **Repeated processing of identical alerts**: Same fingerprint was processed every Alertmanager evaluation interval

### Technical Details

#### New Database Tables
```sql
-- Escalation cooldown tracking
CREATE TABLE escalation_cooldowns (
    alert_name VARCHAR(255) NOT NULL,
    alert_instance VARCHAR(255) NOT NULL,
    escalated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(alert_name, alert_instance)
);

-- Fingerprint deduplication cache
CREATE TABLE alert_processing_cache (
    fingerprint VARCHAR(64) NOT NULL UNIQUE,
    alert_name VARCHAR(255),
    alert_instance VARCHAR(255),
    processed_at TIMESTAMP DEFAULT NOW()
);
```

#### New Database Functions
```python
# Escalation cooldown
await db.check_escalation_cooldown(alert_name, instance, hours=4)
await db.set_escalation_cooldown(alert_name, instance)
await db.clear_escalation_cooldown(alert_name, instance)  # Called on resolve

# Fingerprint deduplication
await db.check_fingerprint_cooldown(fingerprint, seconds=300)
await db.set_fingerprint_processed(fingerprint, alert_name, instance)
await db.cleanup_fingerprint_cache(max_age_hours=24)
```

#### Expected Behavior After Fix

| Time | Event | Old Behavior | New Behavior |
|------|-------|--------------|--------------|
| 10:00 | Alert fires | Attempt 1 | Attempt 1 |
| 10:01 | Same fingerprint | Attempt 2 | **SKIP** (5min cooldown) |
| 10:05 | Cooldown expired | Attempt 3 | Attempt 2 |
| 10:10 | Max attempts | Escalate #1 | Attempt 3 → Escalate |
| 10:15 | Still firing | Escalate #2 | **SKIP** (4hr cooldown) |
| 10:20 | Still firing | Escalate #3 | **SKIP** (4hr cooldown) |
| ... | 40 more times | 40 more escalations | Silent logging |
| 11:00 | Alert resolves | - | Clear cooldowns |
| 11:30 | Alert fires again | - | Fresh incident → Escalate ✅ |

### Migration Notes

- **Database migration required**: Run `init-db.sql` to create new tables
- Tables use `IF NOT EXISTS` so safe to run on existing database
- No changes to existing tables or data
- Cooldowns start fresh after deployment (no pre-existing cooldowns)

---

## [3.0.1] - 2025-11-28

### Fixed

- **RiskLevel enum lookup bug**: Fixed case-sensitivity issue when loading learned patterns from database
  - Pattern matching failed with `KeyError: 'low'` when `risk_level` was stored in lowercase
  - Now normalizes to uppercase before enum lookup (`RiskLevel[risk_level.upper()]`)
  - Affected alerts like `BackupHealthCheckStale` that matched learned patterns

## [3.0.0] - 2025-11-27

### MAJOR OVERHAUL: Investigation-First AI

**"From Runbook Executor to Intelligent Investigator"**

This release fundamentally transforms how Jarvis approaches alert remediation. Instead of blindly executing playbook commands, Jarvis now thinks like a senior SRE - investigating before acting, questioning assumptions, and building confidence before taking action.

### Added

#### Investigation-First Architecture
- **New Investigation Tools**: `read_file`, `check_crontab`, `check_file_age`, `list_directory`, `test_connectivity`
- **Confidence-Gated Execution**: Actions are now limited by confidence level
  - `<30%`: Only read-only diagnostic commands
  - `30-50%`: Safe investigative commands
  - `50-70%`: Can restart services with verification
  - `70-90%`: Can apply learned patterns
  - `>90%`: Full remediation capability
- **Self-Verification Step**: `verify_hypothesis` tool for sanity-checking before taking action
- **Adaptive Iteration Limits**: 10 base iterations, extends to 15 if making progress

#### Skynet Host Support
- Jarvis can now investigate and remediate on the local host where it runs
- Local execution via subprocess when targeting Skynet
- Essential for backup health check alerts that originate from Skynet cron jobs

#### Alert Hint Extraction
- Parses alert descriptions for actionable hints before calling Claude
- Detects mentioned hosts (e.g., "Check cron job on Skynet")
- Extracts suggested commands, file paths, and service names
- `remediation_host_hint` can override misleading instance labels

#### Enhanced Learning Engine
- Stores investigation chains (not just fix commands)
- Tracks when instance labels are misleading vs actual remediation host
- Learns which hosts to investigate for specific alert types
- Metadata includes full investigation history for pattern improvement

### Changed

#### Claude System Prompt Overhaul
- Complete rewrite focused on investigation-first approach
- Detailed data flow documentation (where metrics come from vs where problems are)
- Infrastructure overview includes Skynet
- Example investigation walkthrough for `BackupHealthCheckStale`
- Explicit instructions to question instance labels

#### Improved Target Host Detection
- `determine_target_host()` now accepts hints parameter
- Can override instance label when alert description specifies a different host
- Recognizes Skynet patterns (backup health checks run there)

#### ClaudeAnalysis Model Enhancements
- Added `target_host`: Where commands should actually run
- Added `confidence`: Numeric confidence level 0.0-1.0
- Added `investigation_steps`: List of steps taken during investigation
- Added `instance_label_misleading`: Flag when instance doesn't match fix host

### Fixed

- **BackupHealthCheckStale alerts**: Now correctly identified as Skynet issues
  - Previously: Jarvis tried to fix on Nexus (where metrics are scraped)
  - Now: Jarvis checks Skynet cron jobs (where the script runs)

### Technical Details

#### New Tool Definitions
```python
# Investigation tools (always allowed)
read_file(host, path, lines)       # Read files to understand configs/scripts
check_crontab(host, user)          # Essential for scheduled task issues
check_file_age(host, path)         # Verify if scripts ran recently
list_directory(host, path)         # Explore file structure
test_connectivity(from_host, to)   # Network/VPN troubleshooting

# Meta tools (self-reflection)
update_confidence(new, reason)     # Track investigation progress
verify_hypothesis(...)             # Sanity check before acting
```

#### Confidence Level Thresholds
```python
class ConfidenceLevel(str, Enum):
    UNCERTAIN = "uncertain"      # < 30%
    LOW = "low"                  # 30-50%
    MEDIUM = "medium"            # 50-70%
    HIGH = "high"                # 70-90%
    VERY_HIGH = "very_high"      # > 90%
```

### Migration Notes

- No database migration required (metadata column already exists as JSONB)
- Existing learned patterns will continue to work
- New patterns will include investigation chains automatically
- Claude API usage may increase slightly due to more thorough investigations, but accuracy should improve significantly

---

## [2.1.0] - 2025-11-27

### Added
- **Backup Health Monitoring**: New `BackupUploadFailed` alert pattern for B2/cloud backup failures
- Jarvis can now detect and report backup upload failures (rclone errors)
- Automatic verification of rclone remote connectivity

### Changed
- Backup scripts (Skynet, Nexus, Outpost, Home Assistant) migrated from Google Drive to Backblaze B2
- Backup scripts now exit with error code on upload failure (enables proper alert triggering)

### Infrastructure
- All backup destinations changed from Google Drive to Backblaze B2
- B2 Application Key configured on all 3 systems (never expires, unlike OAuth tokens)

## [2.0.0] - 2025-11-14

### Added
- **Distributable Package**: Jarvis can now be deployed to other homelabs
- Setup wizard (`setup.sh`) for guided installation
- Validation script (`validate.sh`) to verify configuration
- Health check script (`health-check.sh`) for monitoring
- Comprehensive documentation for external users

### Changed
- Refactored configuration to use environment variables exclusively
- Removed hardcoded homelab-specific values
- Improved error messages and logging

## [1.5.0] - 2025-11-11

### Added
- **Frigate Auto-Fix**: Automatic detection and remediation of Frigate database corruption
- Pattern `FrigateDatabaseError` with 90% confidence after successful fixes
- Cross-system correlation for VPN/network alerts

### Changed
- Improved risk assessment for safe container restarts
- Enhanced alert suppression during cascading failures (80%+ noise reduction)

## [1.4.0] - 2025-11-10

### Added
- **External Service Monitor**: Intelligent detection of offline hosts with auto-recovery
- Maintenance window REST API for planned upgrades
- Learning feedback loop for pattern refinement

### Changed
- Resilient architecture survives database outages, host failures, network issues

## [1.3.0] - 2025-11-08

### Added
- **Machine Learning Engine**: Learns from successful fixes
- Pattern database with 16 pre-seeded remediation patterns
- 60-80% API cost reduction after learning period

### Changed
- All remediation attempts now logged to PostgreSQL
- Confidence scoring for pattern matching

## [1.2.0] - 2025-11-07

### Added
- **Alert Queue**: Queues alerts when database is unavailable
- Complete audit trail for all attempts (including escalations and no-action)

### Changed
- Improved Discord notification formatting
- Better error handling for SSH connection failures

## [1.1.0] - 2025-11-05

### Added
- **Multi-Host Support**: Nexus, Home Assistant, Outpost
- Safe command validator (blocks dangerous operations)
- Escalation to Discord after max retry attempts

## [1.0.0] - 2025-11-03

### Added
- Initial release of Jarvis AI Remediation Service
- Claude AI integration for alert analysis
- SSH command execution on monitored hosts
- Basic container restart remediation
- Discord webhook notifications
- PostgreSQL attempt tracking
