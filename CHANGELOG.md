# Changelog

All notable changes to Jarvis AI Remediation Service will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
