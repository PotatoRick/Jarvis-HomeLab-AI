# HighMemoryUsage Remediation Runbook

<!-- risk_level: high -->
<!-- estimated_duration: 5-15 minutes -->

## Overview

This alert fires when system memory usage exceeds the configured threshold.
High memory can lead to OOM kills, swapping (severe performance degradation), and service instability.
Investigation is critical - identify the memory consumer before taking action.

## Investigation Steps

1. Identify top memory consumers: `docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'`
2. Check system memory breakdown: `free -h`
3. Look for memory leaks: `docker stats` over time to see growth patterns
4. Check if OOM killer has been active: `dmesg | grep -i "oom\|killed"`
5. Review swap usage: `swapon -s` and `vmstat 1 5`

## Common Causes

- Memory leak in container application (Frigate, n8n common culprits)
- Too many containers for available RAM
- Database cache growing without limits (PostgreSQL, InfluxDB)
- Application cache not bounded (Redis, in-app caches)
- Log buffers filling up
- Multiple instances of same service running

## Remediation Steps

1. **First**: Identify the top memory consumer
2. **If Frigate**: Often has memory leaks - restart usually helps
3. **If database**: Check if connection/cache limits are set
4. **If system-wide**: May need to restart multiple containers
5. **Emergency**: If OOM imminent, restart highest consumer immediately

## Commands

```bash
# Check memory status
free -h

# Top memory consumers (system-wide)
ps aux --sort=-%mem | head -10

# Docker container memory usage (sorted)
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' | sort -k3 -hr

# Check for OOM events
dmesg | grep -i "oom\|killed" | tail -10

# Check swap usage
swapon -s

# Restart specific high-memory container
docker restart <container_name>

# Clear system caches (if desperate, not recommended)
sync && echo 3 > /proc/sys/vm/drop_caches

# Check container memory limits
docker inspect <container> --format '{{.HostConfig.Memory}}'
```

## Container-Specific Actions

### Frigate
Known to have memory growth over time. Safe to restart:
```bash
docker restart frigate
```

### n8n
Can accumulate memory from workflow executions:
```bash
docker restart n8n
```

### PostgreSQL databases
Check connection count and shared buffers:
```bash
docker exec postgres-jarvis psql -U jarvis -c "SELECT count(*) FROM pg_stat_activity;"
```

### Prometheus
Time series data can grow; check data directory size:
```bash
du -sh /path/to/prometheus/data
```

## Memory Limits

Recommended memory limits for common containers:

| Container | Recommended Limit | Notes |
|-----------|-------------------|-------|
| Frigate | 4-8GB | Depends on camera count |
| Prometheus | 2GB | Based on scrape targets |
| Grafana | 512MB | Mostly UI |
| n8n | 1GB | Workflow dependent |
| PostgreSQL | 1GB | Per database |

## Notes

- Memory alerts are often symptoms, not root causes
- Memory leaks get worse over time - identify and restart leaking containers
- Consider adding memory limits to docker-compose if not already present
- Swap is NOT a solution - it causes severe performance issues
- If a container repeatedly causes memory issues, file an issue upstream
