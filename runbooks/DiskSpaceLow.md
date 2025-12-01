# DiskSpaceLow Remediation Runbook

<!-- risk_level: medium -->
<!-- estimated_duration: 5-15 minutes -->

## Overview

This alert fires when available disk space drops below the configured threshold.
Low disk space can cause service failures, database corruption, and system instability.
Act quickly but carefully - verify what's consuming space before deleting.

## Investigation Steps

1. Identify which filesystem is affected: `df -h`
2. Find large directories: `du -sh /* 2>/dev/null | sort -hr | head -10`
3. Check Docker disk usage: `docker system df`
4. Look for large log files: `find /var/log -size +100M`
5. Check container volumes: `docker volume ls` and sizes

## Common Causes

- Docker build cache and unused images
- Log files growing without rotation
- Video recordings filling up (NVR/Frigate)
- Database WAL files
- Old backup files not cleaned up
- Container tmpfs growing

## Remediation Steps

1. **Safe first**: Clean Docker resources (pruning is safe)
2. **Check logs**: Rotate and compress old logs
3. **Check video storage**: Verify retention settings, clean old clips
4. **Check backups**: Remove backups older than retention policy
5. **Last resort**: Identify and remove specific large files

## Commands

```bash
# Check disk usage summary
df -h

# Find largest directories in root
du -sh /* 2>/dev/null | sort -hr | head -10

# Docker cleanup (SAFE - only removes unused resources)
docker system prune -f

# More aggressive Docker cleanup (removes all unused images)
docker system prune -af

# Clean old Docker volumes (CAREFUL - verify nothing important)
docker volume prune -f

# Vacuum old journal logs (keep last 3 days)
journalctl --vacuum-time=3d

# Find files larger than 100MB
find / -xdev -type f -size +100M 2>/dev/null | head -20

# Check and clean /tmp if needed
du -sh /tmp && find /tmp -type f -mtime +7 -delete

# Check database sizes
du -sh /var/lib/postgresql/data/* 2>/dev/null
```

## Safe vs Risky Actions

### Safe (Always OK):
- `docker system prune -f` - Removes stopped containers, unused networks, dangling images
- `journalctl --vacuum-time=3d` - Keeps last 3 days of logs
- Removing files in `/tmp` older than 7 days

### Moderate Risk:
- `docker system prune -af` - Removes ALL unused images (may need re-pull)
- `docker volume prune -f` - Removes unused volumes (verify first!)
- Cleaning video recordings (verify retention settings)

### High Risk (Avoid automatically):
- Deleting database files
- Removing config directories
- Clearing container data directories

## Notes

- Always `df -h` before and after cleanup to verify results
- If disk is 100% full, services may fail - act quickly
- Prometheus TSDB can be compacted: restart Prometheus to trigger compaction
- Docker overlay2 storage can fragment - may need `fstrim` on SSD
