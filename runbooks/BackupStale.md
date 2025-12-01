# BackupStale Remediation Runbook

<!-- risk_level: low -->
<!-- estimated_duration: 5-10 minutes -->

## Overview

This alert fires when a system's backup hasn't completed successfully within the expected timeframe.
The alert includes a `system` label indicating which host's backup is stale.

**IMPORTANT**: The `instance` label may be misleading. Always use the `system` label to determine
which host to check and remediate.

## Investigation Steps

1. Check the `system` label in the alert to identify the affected host
2. SSH to that specific host and check backup service status
3. Review backup logs for errors
4. Verify the backup destination is accessible (cloud storage, local, etc.)
5. Check disk space on both source and destination

## Common Causes

- Backup service/timer not running
- Network connectivity to backup destination
- Cloud storage authentication expired or invalid
- Disk space full on source or destination
- Large file causing backup timeout
- Backup script crashed mid-execution

## Remediation Steps

1. **Identify the system** from alert labels (not instance!)
2. **Check timer status**: `systemctl status <backup-timer>`
3. **Check last run**: `systemctl status <backup-service>`
4. **If timer disabled**: Re-enable and start
5. **If script failed**: Check logs and re-run manually
6. **Verify success**: Check backup destination for recent files

## Commands

```bash
# First, identify which system from alert labels
# The 'system' label tells you which host to check

# Check backup timer status
systemctl status backup.timer
systemctl list-timers --all | grep backup

# Check backup service logs
journalctl -u backup.service --since "1 hour ago"

# Manually trigger backup
systemctl start backup.service

# Check rclone config (if using rclone)
rclone listremotes

# Test cloud storage connectivity
rclone lsd remote:bucket-name

# Check recent backups
rclone ls remote:bucket-name --max-depth 1 | tail -10
```

## Notes

- Always check the `system` label, NOT the `instance` label
- Instance may show the Prometheus exporter address, not the backup source
- If backup consistently fails, check logs for API errors
- Rate limiting from cloud providers can cause intermittent failures
- Large database dumps may cause timeouts - check for growing data
