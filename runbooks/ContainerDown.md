# ContainerDown Remediation Runbook

<!-- risk_level: medium -->
<!-- estimated_duration: 2-5 minutes -->

## Overview

This alert fires when a Docker container stops unexpectedly or fails health checks.
Container downtime can impact dependent services, so quick investigation and restart is typically the first approach.

## Investigation Steps

1. Check container logs for error messages: `docker logs <container> --tail 100`
2. Verify container exit code: `docker inspect <container> --format '{{.State.ExitCode}}'`
3. Check available system resources: `docker stats --no-stream`
4. Verify disk space isn't exhausted: `df -h`
5. Check for OOM kill events: `dmesg | grep -i "oom\|killed process"`

## Common Causes

- Out of memory (exit code 137, OOMKilled)
- Application crash or exception (exit code 1)
- Missing or unavailable dependencies
- Configuration file errors
- Disk space exhaustion
- Network connectivity issues to required services
- Corrupted container filesystem

## Remediation Steps

1. **First**: Check the exit code to understand why it stopped
2. **If exit code 137**: Container was OOM killed - check memory limits and usage
3. **If exit code 1**: Application error - check logs for stack trace
4. **If exit code 0**: Clean shutdown - may have been intentional or compose issue
5. **Default**: Attempt container restart if no critical errors found
6. **If restart fails**: Check docker daemon health and disk space

## Commands

```bash
# Check container status and exit code
docker inspect <container> --format '{{.State.Status}} (Exit: {{.State.ExitCode}}, OOMKilled: {{.State.OOMKilled}})'

# View recent logs
docker logs <container> --tail 200

# Check disk space
df -h /var/lib/docker

# Check memory pressure
free -h

# Restart container
docker restart <container>

# If that fails, try stop then start
docker stop <container> && docker start <container>

# Nuclear option - remove and recreate
docker compose -f /path/to/compose.yml up -d <container>
```

## Notes

- Exit code 137 indicates OOM kill - consider increasing memory limits
- Exit code 143 indicates SIGTERM - clean shutdown, likely intentional
- Exit code 139 indicates SIGSEGV - memory corruption, may need image rebuild
- Always check logs before restart to avoid masking the root cause
