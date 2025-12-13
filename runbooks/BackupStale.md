# BackupStale Remediation Runbook

<!-- risk_level: low -->
<!-- estimated_duration: 5-10 minutes -->

## Overview

This alert fires when a system's backup hasn't completed successfully within the expected timeframe (28 hours).
The alert includes a `system` label indicating which backup is stale.

**CRITICAL**: The `instance` label is MISLEADING for this alert! It always shows `service-host:9100` because
the metrics are scraped from Service-Host textfile collector. Use the `system` label to determine which
backup is actually stale and where to run the fix.

## System-Specific Remediation

| System Label | Where to Run Fix | Script Path |
|--------------|------------------|-------------|
| `ha-host` | **management-host** | `/home/<user>/homelab/scripts/backup/backup_ha-host_notify.sh` |
| `management-host` | **management-host** | `/home/<user>/homelab/scripts/backup/backup_management-host_notify.sh` |
| `service-host` | **service-host** | `/home/<user>/docker/backups/backup_notify.sh` |
| `vps-host` | **vps-host** | `/opt/<app>/backups/backup_vps_notify.sh` |

## Quick Remediation Commands

### For `system=ha-host` (SSH to Management-Host)
```bash
# Run the Home Assistant backup script (runs on Management-Host, backs up HA to B2)
/home/<user>/homelab/scripts/backup/backup_ha-host_notify.sh
```

### For `system=management-host` (SSH to Management-Host)
```bash
# Run the Management-Host backup script
/home/<user>/homelab/scripts/backup/backup_management-host_notify.sh
```

### For `system=service-host` (SSH to Service-Host)
```bash
# Run the Service-Host backup script
/home/<user>/docker/backups/backup_notify.sh
```

### For `system=vps-host` (SSH to VPS-Host)
```bash
# Run the VPS-Host VPS backup script
/opt/<app>/backups/backup_vps_notify.sh
```

## Investigation Steps

1. **Check the `system` label** in the alert to identify the affected backup
2. **SSH to the correct host** based on the table above (NOT always the instance!)
3. **Check if script exists** and has execute permissions
4. **Check rclone configuration** for B2 access
5. **Verify disk space** on source system
6. **Check B2 bucket** for recent uploads

## Common Causes

- Backup script/timer not running or failed
- Network connectivity to B2 (Backblaze) failed
- B2 API authentication expired or invalid
- Disk space full on source system
- Large file causing backup timeout
- Backup script crashed mid-execution
- SSH key issues (for HA backup which SCPs from HA to Management-Host first)

## Diagnostic Commands

### Check backup timer status (systemd systems)
```bash
# On Management-Host
systemctl status management-host-backup.timer
systemctl list-timers --all | grep backup

# Check last run
journalctl -u management-host-backup.service --since "1 hour ago"
```

### Check rclone config
```bash
# List configured remotes
rclone listremotes

# Test B2 connectivity
rclone lsd b2:<your-b2-bucket> --max-depth 1

# Check recent backups for specific system
rclone ls b2:<your-b2-bucket>/Management-Host/ | tail -10
rclone ls b2:<your-b2-bucket>/HomeAssistant/Daily/ | tail -10
rclone ls b2:<your-b2-bucket>/Service-Host/ | tail -10
rclone ls b2:<your-b2-bucket>/VPS-Host/ | tail -10
```

### Manually update backup metrics (on Management-Host)
```bash
# Re-run the backup health check and push metrics to Service-Host
/home/<user>/homelab/scripts/backup/check_b2_backups.sh
```

## Data Flow Explanation

```
Backup Scripts          B2 Cloud Storage        Health Check         Prometheus
(Run on each host)  --> (<your-b2-bucket>) <-- (check_b2_backups.sh) --> (Scrapes Service-Host)
                                                      |
                                                      | SCP metrics file
                                                      v
                                            Service-Host textfile_collector
                                                      |
                                                      v
                                            Prometheus scrapes service-host:9100
                                                      |
                                                      v
                                            Alert fires with instance=service-host:9100
                                            BUT system label tells the truth!
```

## Notes

- **ALWAYS check the `system` label**, NOT the `instance` label
- Instance always shows `service-host:9100` because that's where metrics are scraped
- The `check_b2_backups.sh` script runs on Management-Host and SCPs metrics to Service-Host
- If backup consistently fails, check logs and B2 API errors
- Rate limiting from B2 can cause intermittent failures
- Large database dumps may cause timeouts - check for growing data

## Verification

After running the backup script, wait 5-10 minutes for:
1. Backup to complete and upload to B2
2. Next run of `check_b2_backups.sh` (runs hourly via cron on Management-Host)
3. Prometheus to scrape updated metrics

Or force a verification:
```bash
# On Management-Host - re-check B2 and update metrics immediately
/home/<user>/homelab/scripts/backup/check_b2_backups.sh

# Then check the metric value
curl -s 'http://<service-host-ip>:9090/api/v1/query?query=backup_status' | jq
```
