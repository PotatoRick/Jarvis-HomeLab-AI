# Changelog

All notable changes to Jarvis AI Remediation Service will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
| BackupStale (homeassistant) | skynet | `/home/t1/homelab/scripts/backup/backup_homeassistant_notify.sh` |
| BackupStale (nexus) | nexus | `cd /home/jordan/docker/home-stack && ./backup.sh` |
| BackupStale (skynet) | skynet | `/home/t1/homelab/scripts/backup/backup_skynet.sh` |
| BackupStale (outpost) | outpost | `cd /opt/burrow && ./backup.sh` |
| BackupHealthCheckStale | skynet | `/home/t1/homelab/scripts/backup/check_b2_backups.sh` |

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
- `/home/t1/homelab/scripts/backup/check_b2_backups.sh` now checks both Daily and Sunday folders
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
    remediation_commands: "/home/t1/homelab/scripts/backup/backup_homeassistant_notify.sh"
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
- Jarvis can now investigate and remediate on Skynet (192.168.0.13) where it runs
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
- All backup destinations changed from `gdrive:` to `b2:theburrow-backups/`
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
