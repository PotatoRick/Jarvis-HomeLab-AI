# Jarvis Troubleshooting Guide

Comprehensive solutions for common issues with the AI remediation service.

---

## Table of Contents

1. [Service Won't Start](#service-wont-start)
2. [Alerts Not Being Processed](#alerts-not-being-processed)
3. [SSH Connection Failures](#ssh-connection-failures)
4. [Database Errors](#database-errors)
5. [Claude API Issues](#claude-api-issues)
6. [Discord Notification Failures](#discord-notification-failures)
7. [Command Validation Issues](#command-validation-issues)
8. [Performance Problems](#performance-problems)
9. [False Escalations](#false-escalations)
10. [Debugging Techniques](#debugging-techniques)

---

## Service Won't Start

### Container Exits Immediately

**Symptoms:**
```bash
docker ps | grep jarvis
# No output - container not running
```

**Diagnosis:**
```bash
# Check container logs
docker logs jarvis

# Check exit code
docker inspect jarvis --format='{{.State.ExitCode}}'
```

**Common Causes:**

#### 1. Missing Environment Variables
**Error:** `ValidationError: field required`

**Solution:**
```bash
# Check .env file exists
ls -la .env

# Verify required variables
cat .env | grep -E "(DATABASE_URL|ANTHROPIC_API_KEY|SSH_KEY_PATH)"

# Copy from example if missing
cp .env.example .env
nano .env
```

#### 2. Invalid DATABASE_URL
**Error:** `asyncpg.exceptions.InvalidCatalogNameError`

**Solution:**
```bash
# Test database connection
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT 1;"'

# Create database if missing
ssh outpost 'docker exec n8n-db createdb -U n8n finance_db'

# Verify URL format
echo $DATABASE_URL
# Should be: postgresql://user:password@host:port/database
```

#### 3. SSH Key Not Found
**Error:** `FileNotFoundError: [Errno 2] No such file or directory: '/app/ssh_key'`

**Solution:**
```bash
# Check SSH key exists
ls -la ./ssh_key

# Copy SSH key
cp ~/.ssh/homelab_ed25519 ./ssh_key

# Fix permissions
chmod 600 ./ssh_key

# Restart service
docker compose down && docker compose up -d
```

#### 4. Port Already in Use
**Error:** `Error starting userland proxy: listen tcp 0.0.0.0:8000: bind: address already in use`

**Solution:**
```bash
# Find process using port 8000
sudo lsof -i :8000

# Option 1: Kill conflicting process
sudo kill $(sudo lsof -t -i:8000)

# Option 2: Change Jarvis port
nano docker-compose.yml
# Change: ports: - "8080:8000"

docker compose up -d
```

---

## Alerts Not Being Processed

### No Webhook Reception

**Symptoms:**
- Alerts fire in Prometheus
- No Discord notifications
- Logs show no `webhook_received` events

**Diagnosis:**
```bash
# Check if Jarvis is running
docker ps | grep jarvis

# Check recent logs
docker logs jarvis --since 10m | grep webhook_received

# Test webhook manually
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -u alertmanager:your_password \
  -d '{"status":"firing","alerts":[{"labels":{"alertname":"test"}}]}'
```

**Common Causes:**

#### 1. Alertmanager Not Configured
**Solution:**
```bash
# Check Alertmanager config
ssh nexus 'cat /home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml | grep jarvis'

# Should see:
# - name: 'jarvis'
#   webhook_configs:
#     - url: 'http://jarvis:8000/webhook'

# If missing, add receiver
ssh nexus 'nano /home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml'

# Reload Alertmanager
ssh nexus 'docker exec alertmanager kill -HUP 1'
```

#### 2. Wrong Network
**Error:** `dial tcp: lookup jarvis on 127.0.0.11:53: no such host`

**Solution:**
```bash
# Check Jarvis network
docker inspect jarvis --format='{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}'

# Check Alertmanager network
ssh nexus 'docker inspect alertmanager --format="{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}"'

# If different, add Jarvis to alertmanager network
docker network connect alertmanager_network jarvis
```

#### 3. Authentication Failure
**Error in Alertmanager logs:** `401 Unauthorized`

**Solution:**
```bash
# Verify password matches
cat .env | grep WEBHOOK_AUTH_PASSWORD
ssh nexus 'cat /home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml | grep password'

# Update Alertmanager config
ssh nexus 'nano /home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml'

# Reload Alertmanager
ssh nexus 'docker exec alertmanager kill -HUP 1'
```

### Alerts Received But Not Processed

**Symptoms:**
- Logs show `webhook_received`
- No remediation attempts
- No Discord notifications

**Diagnosis:**
```bash
# Check for processing errors
docker logs jarvis | grep -E "(processing_alert|error)"

# Check attempt count
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT alert_name, alert_instance, COUNT(*)
  FROM remediation_log
  WHERE timestamp > NOW() - INTERVAL '\''2 hours'\''
  GROUP BY alert_name, alert_instance;
"'
```

**Common Causes:**

#### 1. Max Attempts Reached
**Log:** `max_attempts_reached attempt_count=20`

**Solution:**
```bash
# Check attempt history
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT timestamp, success, error_message
  FROM remediation_log
  WHERE alert_name = '\''ContainerDown'\''
    AND alert_instance = '\''nexus:omada'\''
  ORDER BY timestamp DESC LIMIT 10;
"'

# If old attempts are blocking, clear them
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  DELETE FROM remediation_log
  WHERE alert_name = '\''ContainerDown'\''
    AND alert_instance = '\''nexus:omada'\'';
"'
```

#### 2. Maintenance Mode Enabled
**Log:** `maintenance_mode_active skipping remediation`

**Solution:**
```bash
# Check maintenance mode
curl http://localhost:8000/health | jq '.maintenance_mode'

# Disable maintenance mode (not yet implemented)
# Manual: Clear maintenance_windows table
```

---

## SSH Connection Failures

### Connection Timeout

**Symptoms:**
- Remediation fails with timeout errors
- Logs show `ssh_connection_timeout`

**Diagnosis:**
```bash
# Test SSH manually
docker exec jarvis ssh -i /app/ssh_key jordan@<service-host-ip> 'echo test'

# Check network connectivity
docker exec jarvis ping -c 3 <service-host-ip>
```

**Common Causes:**

#### 1. SSH Key Permissions
**Error:** `asyncssh.misc.PermissionDenied: Permissions for '/app/ssh_key' are too open`

**Solution:**
```bash
# Check permissions on host
ls -la ./ssh_key
# Should be: -rw------- (600)

# Fix permissions
chmod 600 ./ssh_key

# Restart container to remount
docker compose restart jarvis
```

#### 2. Key Not Authorized on Host
**Error:** `asyncssh.misc.PermissionDenied: Permission denied (publickey)`

**Solution:**
```bash
# Check authorized_keys on target
ssh nexus 'cat ~/.ssh/authorized_keys'

# Add public key if missing
cat ~/.ssh/homelab_ed25519.pub | ssh nexus 'cat >> ~/.ssh/authorized_keys'

# Fix authorized_keys permissions
ssh nexus 'chmod 600 ~/.ssh/authorized_keys'
```

#### 3. Host Unreachable
**Error:** `asyncssh.misc.ConnectionLost: Connection lost`

**Solution:**
```bash
# Test connectivity
ping -c 3 <service-host-ip>

# Check SSH daemon
ssh nexus 'systemctl status sshd'

# Check firewall
ssh nexus 'sudo ufw status | grep 22'
```

### SSH Commands Timing Out

**Symptoms:**
- Commands exceed 60-second timeout
- Logs show `command_timeout`

**Diagnosis:**
```bash
# Check command execution time
docker logs jarvis | grep -E "(command_executed|command_timeout)" | tail -20

# Test command manually
ssh nexus 'time docker restart omada'
```

**Solutions:**

#### 1. Increase Timeout
```bash
# Edit .env
echo "COMMAND_EXECUTION_TIMEOUT=120" >> .env

# Restart
docker compose down && docker compose up -d
```

#### 2. SSH Connection Pooling Not Working
**Symptoms:** Multiple `ssh_connection_established` logs, no `reusing_ssh_connection`

**Diagnosis:**
```bash
# Check connection pooling
docker logs jarvis --since 5m | grep -c "ssh_connection_established"
docker logs jarvis --since 5m | grep -c "reusing_ssh_connection"

# Should see: 1 new connection, many reuses
```

**Solution:**
```bash
# Verify ssh_executor.py has pooling code
docker exec jarvis cat /app/app/ssh_executor.py | grep -A 10 "_get_connection"

# If missing, update code and rebuild
docker compose build --no-cache
docker compose up -d
```

---

## Database Errors

### Connection Refused

**Symptoms:**
- Service won't start
- Error: `asyncpg.exceptions.InvalidPasswordError` or `connection refused`

**Diagnosis:**
```bash
# Test database from Jarvis container
docker exec jarvis python -c "
import asyncio
import asyncpg

async def test():
    conn = await asyncpg.connect('postgresql://n8n:PASSWORD@<vps-ip>:5432/finance_db')
    print('Connected!')
    await conn.close()

asyncio.run(test())
"
```

**Common Causes:**

#### 1. Database Not Running
**Solution:**
```bash
# Check if n8n-db is running
ssh outpost 'docker ps | grep n8n-db'

# Start if stopped
ssh outpost 'cd /opt/burrow && docker compose up -d n8n-db'
```

#### 2. Wrong Password
**Solution:**
```bash
# Verify password
cat .env | grep DATABASE_URL

# Test connection with password
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT 1;"'
```

#### 3. Database Doesn't Exist
**Error:** `asyncpg.exceptions.InvalidCatalogNameError: database "finance_db" does not exist`

**Solution:**
```bash
# Create database
ssh outpost 'docker exec n8n-db createdb -U n8n finance_db'

# Verify
ssh outpost 'docker exec n8n-db psql -U n8n -l | grep finance_db'
```

### Table Schema Errors

**Error:** `asyncpg.exceptions.UndefinedTableError: relation "remediation_log" does not exist`

**Solution:**
```bash
# Tables should be created automatically on startup
# If missing, create manually

ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db' <<'SQL'
CREATE TABLE IF NOT EXISTS remediation_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    alert_name VARCHAR(255) NOT NULL,
    alert_instance VARCHAR(255) NOT NULL,
    severity VARCHAR(50),
    alert_labels JSONB,
    alert_annotations JSONB,
    attempt_number INT NOT NULL,
    ai_analysis TEXT,
    ai_reasoning TEXT,
    remediation_plan TEXT,
    commands_executed TEXT[],
    success BOOLEAN NOT NULL,
    error_message TEXT,
    duration_seconds INT,
    ssh_host VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_remediation_log_alert
ON remediation_log(alert_name, alert_instance, timestamp);

CREATE INDEX IF NOT EXISTS idx_remediation_log_timestamp
ON remediation_log(timestamp);
SQL
```

---

## Claude API Issues

### Invalid API Key

**Error:** `anthropic.APIError: Invalid API key`

**Diagnosis:**
```bash
# Check API key format
cat .env | grep ANTHROPIC_API_KEY
# Should start with: sk-ant-api03-

# Test API key
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-3-5-haiku-20241022","max_tokens":100,"messages":[{"role":"user","content":"test"}]}'
```

**Solution:**
```bash
# Get new API key from console.anthropic.com
# Update .env
nano .env

# Restart
docker compose restart jarvis
```

### Rate Limiting

**Error:** `anthropic.APIError: rate_limit_error`

**Diagnosis:**
```bash
# Check API call frequency
docker logs jarvis | grep "claude_api_call" | tail -20

# Check rate limit headers in logs
docker logs jarvis | grep "rate_limit"
```

**Solutions:**

#### 1. Reduce Request Rate
```bash
# Lower max attempts
echo "MAX_ATTEMPTS_PER_ALERT=5" >> .env

# Restart
docker compose restart jarvis
```

#### 2. Upgrade API Tier
- Visit https://console.anthropic.com/settings/limits
- Request higher rate limits
- Upgrade to paid tier

### Model Not Found

**Error:** `anthropic.APIError: model not found`

**Solution:**
```bash
# Check model name
cat .env | grep CLAUDE_MODEL

# Use valid model
echo "CLAUDE_MODEL=claude-3-5-haiku-20241022" >> .env

# Valid options:
# - claude-3-5-haiku-20241022 (recommended)
# - claude-sonnet-4-5-20250929
# - claude-3-5-sonnet-20241022

docker compose restart jarvis
```

---

## Discord Notification Failures

### Discord Notification Errors

**Symptoms:**
- Remediation succeeds but Discord notification fails
- Logs show Python exceptions in `discord_notifier.py`

**Common Errors:**

#### 1. NameError: name 'max_attempts' is not defined

**Fixed:** November 11, 2025

**Symptoms:**
```
NameError: name 'max_attempts' is not defined
  at discord_notifier.py line 69
```

**Root Cause:**
`notify_success()` method referenced `max_attempts` variable but didn't receive it as a parameter.

**Solution:**
Already fixed in current version. If you encounter this on older versions:
```bash
# Update to latest version
git pull origin main
docker compose build
docker compose up -d
```

**Technical Details:**
- Fixed by adding `max_attempts: int` parameter to `notify_success()` method
- Caller in `main.py:521` now passes `settings.max_attempts_per_alert`

#### 2. Wrong Username in Notifications

**Fixed:** November 11, 2025

**Symptoms:**
Discord notifications show username as "Homelab SRE" instead of "Jarvis"

**Solution:**
Already fixed in current version. Updated all webhook calls in `discord_notifier.py` (lines 69, 123, 184, 261, 358) to use `username="Jarvis"`.

### Webhook Not Found (404)

**Error:** `discord_webhook_failed status=404`

**Diagnosis:**
```bash
# Test webhook URL
curl -X POST "$DISCORD_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"content":"Test from terminal"}'
```

**Solutions:**

#### 1. Regenerate Webhook
- Discord Server Settings → Integrations → Webhooks
- Delete old webhook
- Create new webhook
- Copy URL to .env

#### 2. Verify URL Format
```bash
# Should be: https://discord.com/api/webhooks/{id}/{token}
cat .env | grep DISCORD_WEBHOOK_URL

# No extra characters or spaces
# Must be single line
```

### Rate Limited (429)

**Error:** `discord_webhook_failed status=429`

**Solution:**
Discord limits webhooks to 30 requests per minute.

```bash
# Reduce notification frequency
# Increase Alertmanager repeat_interval
ssh nexus 'nano /home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml'

# Set: repeat_interval: 30m
```

### No Notifications Sent

**Symptoms:**
- Remediation succeeds
- No Discord message

**Diagnosis:**
```bash
# Check if Discord is enabled
cat .env | grep DISCORD_ENABLED
# Should be: DISCORD_ENABLED=true

# Check logs for Discord attempts
docker logs jarvis | grep discord_notification
```

**Solutions:**

#### 1. Discord Disabled
```bash
echo "DISCORD_ENABLED=true" >> .env
docker compose restart jarvis
```

#### 2. Webhook URL Missing
```bash
# Add webhook URL
echo "DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/..." >> .env
docker compose restart jarvis
```

---

## Command Validation Issues

### All Commands Rejected

**Symptoms:**
- Remediation fails immediately
- Logs show `command_rejected`
- Discord shows dangerous command notification

**Diagnosis:**
```bash
# Check which commands were rejected
docker logs jarvis | grep command_rejected | tail -10
```

**Common Causes:**

#### 1. Commands Match Blacklist Pattern
**Example:** `docker restart jarvis` rejected (self-protection)

**Solution:**
- This is intentional behavior
- Cannot disable self-protection
- Use different remediation approach

#### 2. Overly Aggressive Blacklist
**Solution:**
```bash
# Review blacklist patterns
docker exec jarvis cat /app/app/command_validator.py | grep -A 2 "DANGEROUS_PATTERNS"

# If pattern is too broad, update code
nano app/command_validator.py

# Rebuild
docker compose build
docker compose up -d
```

### Valid Commands Rejected

**Example:** `curl -I https://service.com/` rejected as "pipe to bash"

**Diagnosis:**
```bash
# Test command validation
docker exec jarvis python -c "
from app.command_validator import CommandValidator

validator = CommandValidator()
result = validator.validate_command('curl -I https://service.com/')
print(f'Safe: {result[0]}, Risk: {result[1]}, Reason: {result[2]}')
"
```

**Solution:**
```bash
# Update blacklist pattern to be more specific
nano app/command_validator.py

# Change:
# (r'curl.*\|.*bash', "Pipe to bash detected")
# To:
# (r'curl.*\|\s*bash', "Pipe to bash detected")

docker compose build && docker compose up -d
```

---

## Performance Problems

### Slow Remediation (>5 seconds)

**Symptoms:**
- Remediation takes 10+ seconds
- Logs show high duration

**Diagnosis:**
```bash
# Check remediation duration
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT alert_name, AVG(duration_seconds) as avg_duration
  FROM remediation_log
  WHERE timestamp > NOW() - INTERVAL '\''24 hours'\''
  GROUP BY alert_name
  ORDER BY avg_duration DESC;
"'

# Check SSH connection stats
docker logs jarvis --since 10m | grep -E "(ssh_connection_established|reusing_ssh_connection)"
```

**Common Causes:**

#### 1. SSH Connection Pooling Not Working
**Solution:** See [SSH Connection Pooling Not Working](#2-ssh-connection-pooling-not-working)

#### 2. Claude API Slow
**Symptoms:** `claude_api_duration_seconds > 5`

**Solutions:**
```bash
# Switch to Haiku (faster)
echo "CLAUDE_MODEL=claude-3-5-haiku-20241022" >> .env

# Reduce prompt size (if needed)
nano app/ai_analyzer.py
```

#### 3. Database Query Slow
**Solution:**
```bash
# Check indexes exist
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "\d remediation_log"'

# Should see:
# idx_remediation_log_alert
# idx_remediation_log_timestamp

# Recreate if missing (see Database Schema Errors section)
```

### High Memory Usage

**Symptoms:**
- Container using >512MB RAM
- Host running out of memory

**Diagnosis:**
```bash
# Check container memory
docker stats jarvis --no-stream

# Check for memory leaks
docker exec jarvis python -c "
import psutil
process = psutil.Process()
print(f'Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB')
"
```

**Solutions:**

#### 1. Limit Container Memory
```yaml
# docker-compose.yml
services:
  jarvis:
    mem_limit: 512m
    mem_reservation: 256m
```

#### 2. SSH Connection Cleanup
```bash
# Verify connections are being closed
docker logs jarvis | grep "closing_ssh_connection"

# If missing, add cleanup on shutdown
```

---

## False Escalations

### Duplicate Remediation Attempts

**Symptoms:**
- Same alert triggers multiple remediation attempts in quick succession
- Logs show many attempts within 1-2 minutes
- Alertmanager sending duplicate webhooks

**Diagnosis:**
```bash
# Check webhook frequency
docker logs jarvis | grep "webhook_received" | grep "ContainerDown" | tail -20

# Check Alertmanager group_interval
ssh nexus 'cat /home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml | grep group_interval'
```

**Common Causes:**

#### 1. Alertmanager group_interval Too Low

**Fixed:** November 11, 2025 (changed from 10s to 1m)

**Symptoms:**
- Webhooks arriving every 10 seconds
- 5-7 attempts for single container failure
- Logs show rapid-fire `webhook_received` events

**Root Cause:**
`group_interval: 10s` caused Alertmanager to resend webhook every 10 seconds while alert was still firing.

**Solution:**
```bash
ssh nexus 'nano /home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml'

# Change:
# group_interval: 10s
# To:
group_interval: 1m

# Reload Alertmanager
ssh nexus 'docker exec alertmanager kill -HUP 1'
```

**Recommended Configuration:**
```yaml
routes:
  - match_re:
      alertname: '.+'
    receiver: 'ai-remediation'
    group_wait: 5s          # First webhook after 5s
    group_interval: 1m      # Retry every 1 minute
    repeat_interval: 30m    # After 30 min, resend if unresolved
```

**Impact:**
- Allows ~120 attempts in 2-hour window (above 20-attempt limit)
- Prevents webhook spam
- First webhook still sent quickly (5 seconds)

### Escalation After 1 Attempt

**Symptoms:**
- Alert fires for first time
- Immediately escalates to Discord
- Log shows `attempt_number=20`

**Diagnosis:**
```bash
# Check attempt history
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT timestamp, alert_name, alert_instance, attempt_number
  FROM remediation_log
  WHERE alert_name = '\''ContainerDown'\''
  ORDER BY timestamp DESC LIMIT 20;
"'
```

**Common Causes:**

#### 1. Stale Attempt Data
**Solution:**
```bash
# Clear old attempts
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  DELETE FROM remediation_log
  WHERE timestamp < NOW() - INTERVAL '\''24 hours'\'';
"'

# Or clear specific alert
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  DELETE FROM remediation_log
  WHERE alert_name = '\''ContainerDown'\''
    AND alert_instance = '\''nexus:omada'\'';
"'
```

#### 2. Wrong Instance Format

**Fixed:** November 11, 2025 (improved detection logic)

**Symptoms:**
- Multiple containers on same host sharing attempt counters
- Instance showing as just hostname (e.g., "nexus" instead of "nexus:omada")

**Root Cause:**
Prometheus alert rules already formatted instance as "host:container", but Jarvis tried to rebuild it from separate labels, sometimes failing to detect the existing format.

**Solution:**
Already fixed in current version. Update if on older version:
```bash
git pull origin main
docker compose build && docker compose up -d
```

**Verify Fix:**
```bash
docker logs jarvis | grep "alert_instance"

# Should see: alert_instance=nexus:omada
# Not: alert_instance=nexus
```

**Technical Details:**
Improved logic in `main.py:268-296` now checks if instance already contains ":" before attempting to build container-specific format:
```python
# First check if Prometheus already formatted it
if ":" in alert.labels.instance and alert_name == "ContainerDown":
    alert_instance = alert.labels.instance
elif alert_name == "ContainerDown":
    alert_instance = f"{host}:{container}"
```

---

## Debugging Techniques

### Enable Debug Logging

```bash
# Edit .env
echo "LOG_LEVEL=DEBUG" >> .env

# Restart
docker compose restart jarvis

# View detailed logs
docker logs -f jarvis
```

### Trace Specific Alert

```bash
# Follow logs for specific alert
docker logs -f jarvis | grep "alert_name=ContainerDown"

# Filter for specific instance
docker logs -f jarvis | grep "alert_instance=nexus:omada"
```

### Simulate Alert Webhook

```bash
# Create test alert JSON
cat > test_alert.json <<'EOF'
{
  "version": "4",
  "groupKey": "test",
  "status": "firing",
  "receiver": "jarvis",
  "alerts": [{
    "status": "firing",
    "labels": {
      "alertname": "ContainerDown",
      "instance": "nexus:9090",
      "host": "nexus",
      "container": "test-container",
      "severity": "warning"
    },
    "annotations": {
      "description": "Test alert for debugging"
    },
    "startsAt": "2025-11-11T20:00:00Z",
    "fingerprint": "test123"
  }]
}
EOF

# Send to Jarvis
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -u alertmanager:your_password \
  -d @test_alert.json

# Watch logs
docker logs -f jarvis
```

### Check SSH Connection Pool

```bash
# View active connections
docker exec jarvis python -c "
from app.ssh_executor import ssh_executor

print(f'Active connections: {len(ssh_executor._connections)}')
for host, conn in ssh_executor._connections.items():
    print(f'  {host}: closed={conn.is_closed()}')
"
```

### Database Query Recent Activity

```bash
# Last 10 remediations
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT
    timestamp,
    alert_name,
    alert_instance,
    attempt_number,
    success,
    ARRAY_LENGTH(commands_executed, 1) as num_commands,
    duration_seconds
  FROM remediation_log
  ORDER BY timestamp DESC
  LIMIT 10;
"'

# Success rate by alert
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT
    alert_name,
    COUNT(*) as total,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
  FROM remediation_log
  WHERE timestamp > NOW() - INTERVAL '\''7 days'\''
  GROUP BY alert_name;
"'
```

### Inspect Container Environment

```bash
# Check all environment variables
docker exec jarvis env | sort

# Check specific settings
docker exec jarvis python -c "
from app.config import settings
import json

print(json.dumps({
    'max_attempts': settings.max_attempts_per_alert,
    'attempt_window': settings.attempt_window_hours,
    'model': settings.claude_model,
    'discord_enabled': settings.discord_enabled,
}, indent=2))
"
```

### Network Connectivity Tests

```bash
# Test Prometheus/Alertmanager connectivity
docker exec jarvis ping -c 3 alertmanager

# Test SSH connectivity
docker exec jarvis nc -zv <service-host-ip> 22

# Test database connectivity
docker exec jarvis nc -zv <vps-ip> 5432

# Test Discord webhook
docker exec jarvis curl -I "$DISCORD_WEBHOOK_URL"
```

---

## Getting Help

If issues persist after trying these solutions:

1. **Gather diagnostic info:**
   ```bash
   # Service status
   docker ps -a | grep jarvis
   docker logs jarvis --tail 100 > jarvis_logs.txt

   # Configuration
   docker exec jarvis env | grep -v "PASSWORD\|KEY" > jarvis_config.txt

   # Database state
   ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
     SELECT COUNT(*) FROM remediation_log;
   "' > db_state.txt
   ```

2. **Check documentation:**
   - [README.md](./README.md) - Overview and quick start
   - [ARCHITECTURE.md](./ARCHITECTURE.md) - System design
   - [CONFIGURATION.md](./CONFIGURATION.md) - All settings

3. **Review recent changes:**
   ```bash
   git log --oneline -10
   git diff HEAD~1
   ```

4. **Contact:**
   - Email: hoelscher.jordan@gmail.com
   - Discord: #homelab-alerts channel

---

## Recent Fixes Summary (November 11, 2025)

### Fixed Issues
1. **Discord Username**: Changed from "Homelab SRE" to "Jarvis" for consistent branding
2. **Notification Errors**: Fixed `NameError: name 'max_attempts' is not defined` in success notifications
3. **Container Instance Detection**: Improved logic to handle Prometheus pre-formatted instances
4. **Duplicate Webhooks**: Alertmanager `group_interval` optimized from 10s to 1m

### Success Metrics After Fixes
- Octoprint container: Successfully remediated in 1 attempt, 17 seconds
- Scrypted: 7 attempts properly tracked and cleared on resolution
- Discord notifications: Correct branding and no errors
- No more duplicate webhook spam

### If You're Still Experiencing Issues
Ensure you're running the latest version:
```bash
cd /home/<user>/homelab/projects/ai-remediation-service
git pull origin main
docker compose build
docker compose up -d
```

---

**Last Updated:** November 11, 2025
**Version:** 2.0.0
