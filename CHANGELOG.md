# Changelog

All notable changes to Jarvis AI Remediation Service will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
