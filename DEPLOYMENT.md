# Jarvis Deployment Guide

Complete step-by-step instructions for deploying the AI remediation service to production.

---

## Table of Contents

1. [Deployment Overview](#deployment-overview)
2. [Prerequisites](#prerequisites)
3. [Initial Deployment](#initial-deployment)
4. [Alertmanager Integration](#alertmanager-integration)
5. [Verification & Testing](#verification--testing)
6. [Updates & Maintenance](#updates--maintenance)
7. [Rollback Procedures](#rollback-procedures)
8. [Production Checklist](#production-checklist)

---

## Deployment Overview

**Target System:** Outpost VPS (Skynet - 192.168.0.13)

**Why Outpost/Skynet:**
- Already hosts PostgreSQL database (n8n-db)
- Has SSH access to all homelab systems
- External IP for monitoring remote services
- Not a critical service host (safe to restart)

**Architecture:**
```
Nexus (192.168.0.11)                  Skynet/Outpost (this system)
┌────────────────────┐                ┌──────────────────────────┐
│  Alertmanager      │───webhook────▶ │  Jarvis                  │
│  (Prometheus)      │                │  ├─ FastAPI webhook      │
└────────────────────┘                │  ├─ Claude AI analyzer   │
                                      │  ├─ SSH executor         │
┌────────────────────┐                │  └─ Discord notifier     │
│  Target Hosts      │◀──SSH─────────┤                          │
│  ├─ Nexus          │                │  PostgreSQL (n8n-db)     │
│  ├─ Home Assistant │                │  ├─ remediation_log      │
│  └─ Outpost        │                │  └─ attempt tracking     │
└────────────────────┘                └──────────────────────────┘
```

---

## Prerequisites

### Required Services

1. **PostgreSQL Database**
   - Running on Outpost (n8n-db container)
   - Database: `finance_db`
   - Access: `postgresql://n8n:password@host:5432/finance_db`

2. **SSH Access**
   - SSH key with access to Nexus, Home Assistant, Outpost
   - Key stored at: `~/.ssh/homelab_ed25519`
   - Key authorized on all target hosts

3. **Claude API Key**
   - Account at https://console.anthropic.com/
   - Free tier: $5 credit
   - API key format: `sk-ant-api03-...`

4. **Discord Webhook (Optional)**
   - Discord server with webhook enabled
   - Webhook URL format: `https://discord.com/api/webhooks/{id}/{token}`

5. **Prometheus + Alertmanager**
   - Running on Nexus
   - Accessible at: http://192.168.0.11:9093

### System Requirements

**Minimum:**
- CPU: 1 core
- RAM: 256 MB
- Disk: 100 MB
- Network: Internet access (Claude API)

**Recommended:**
- CPU: 2 cores
- RAM: 512 MB
- Disk: 500 MB
- Network: Low latency to target hosts

---

## Initial Deployment

### Step 1: Prepare Project Directory

```bash
# On Skynet/Outpost
cd /home/t1/homelab/projects/ai-remediation-service

# Verify files exist
ls -la
# Should see:
# - app/           (Python code)
# - docker-compose.yml
# - Dockerfile
# - .env.example
# - README.md
```

### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env
```

**Required settings:**
```bash
# Database
DATABASE_URL=postgresql://n8n:YOUR_PASSWORD@72.60.163.242:5432/finance_db

# Claude API
ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY_HERE
CLAUDE_MODEL=claude-3-5-haiku-20241022

# SSH Configuration (use defaults)
SSH_NEXUS_HOST=192.168.0.11
SSH_NEXUS_USER=jordan
SSH_HOMEASSISTANT_HOST=192.168.0.10
SSH_HOMEASSISTANT_USER=jordan
SSH_OUTPOST_HOST=72.60.163.242
SSH_OUTPOST_USER=jordan

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
DISCORD_ENABLED=true

# Security
WEBHOOK_AUTH_USERNAME=alertmanager
WEBHOOK_AUTH_PASSWORD=$(openssl rand -base64 32)

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Remediation Settings
MAX_ATTEMPTS_PER_ALERT=20
ATTEMPT_WINDOW_HOURS=2
COMMAND_EXECUTION_TIMEOUT=60
```

**Save the `WEBHOOK_AUTH_PASSWORD`** - you'll need it for Alertmanager configuration.

### Step 3: Set Up SSH Key

```bash
# Copy SSH key to project directory
cp ~/.ssh/homelab_ed25519 ./ssh_key

# CRITICAL: Set correct permissions
chmod 600 ./ssh_key

# Verify permissions
ls -la ./ssh_key
# Should show: -rw------- (600)

# Test SSH key works
ssh -i ./ssh_key jordan@192.168.0.11 'echo "SSH test successful"'
ssh -i ./ssh_key jordan@192.168.0.10 'echo "SSH test successful"'
```

### Step 4: Verify Database

```bash
# Test database connection
docker exec n8n-db psql -U n8n -d finance_db -c "SELECT 1;"

# If database doesn't exist, create it
docker exec n8n-db createdb -U n8n finance_db

# Verify
docker exec n8n-db psql -U n8n -l | grep finance_db
```

### Step 5: Build and Deploy

```bash
# Build Docker image
docker compose build

# Start service
docker compose up -d

# Verify container is running
docker ps | grep jarvis

# Check logs for startup
docker logs -f jarvis
```

**Expected startup output:**
```json
{"timestamp":"2025-11-11T20:00:00Z","level":"info","event":"service_starting","version":"2.0.0"}
{"timestamp":"2025-11-11T20:00:01Z","level":"info","event":"database_connected","database":"finance_db"}
{"timestamp":"2025-11-11T20:00:02Z","level":"info","event":"ssh_keys_loaded","hosts":["nexus","homeassistant","outpost"]}
{"timestamp":"2025-11-11T20:00:03Z","level":"info","event":"service_ready","port":8000}
```

### Step 6: Health Check

```bash
# Test health endpoint
curl http://localhost:8000/health | jq

# Expected response:
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2025-11-11T20:00:00Z",
  "version": "2.0.0",
  "model": "claude-3-5-haiku-20241022"
}
```

---

## Alertmanager Integration

### Step 1: Configure Alertmanager on Nexus

```bash
# SSH to Nexus
ssh nexus

# Edit Alertmanager config
nano /home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml
```

**Add Jarvis receiver:**
```yaml
receivers:
  # Existing Discord receiver
  - name: 'discord-homelab'
    webhook_configs:
      - url: 'YOUR_DISCORD_WEBHOOK'

  # NEW: Add Jarvis receiver
  - name: 'jarvis'
    webhook_configs:
      - url: 'http://jarvis:8000/webhook'
        send_resolved: true
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'YOUR_WEBHOOK_AUTH_PASSWORD'  # From .env
```

**Update routing:**
```yaml
route:
  receiver: 'discord-homelab'  # Default receiver
  group_by: ['alertname', 'instance']
  group_wait: 5s
  group_interval: 1m
  repeat_interval: 30m
  resolve_timeout: 5m

  routes:
    # Route 1: Send to Discord (existing)
    - matchers:
        - alertname =~ ".+"
      receiver: 'discord-homelab'
      continue: true  # IMPORTANT: Continue to next route

    # Route 2: Send to Jarvis for auto-remediation
    - matchers:
        - alertname =~ ".+"
      receiver: 'jarvis'
```

**Key parameters:**
- `send_resolved: true` - Enables attempt cleanup when alerts resolve
- `continue: true` - Ensures alerts go to BOTH Discord and Jarvis
- `group_wait: 5s` - Send first webhook 5 seconds after alert fires
- `group_interval: 1m` - Retry every 1 minute if alert persists (prevents webhook spam)
- `repeat_interval: 30m` - Resend after 30 minutes if still unresolved
- `resolve_timeout: 5m` - Wait 5 min before confirming alert is resolved

**Important:** The `group_interval: 1m` setting was optimized on November 11, 2025. Previously `10s`, which caused excessive duplicate webhooks. The 1-minute interval provides ~120 retry opportunities in the 2-hour attempt window while preventing spam.

### Step 2: Reload Alertmanager

```bash
# Still on Nexus
docker exec alertmanager kill -HUP 1

# Verify reload succeeded
docker logs alertmanager --tail 20

# Should see: "Loading configuration file"
```

### Step 3: Verify Network Connectivity

```bash
# From Nexus, test Jarvis webhook endpoint
docker exec alertmanager wget -O- http://jarvis:8000/health

# Expected: {"status":"healthy",...}
```

If this fails:

```bash
# Check Docker networks
docker network ls

# Jarvis must be on same network as Alertmanager
# If not, add to network:
docker network connect home-stack_default jarvis
```

---

## Verification & Testing

### Test 1: Manual Webhook

```bash
# Send test alert to Jarvis
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -u alertmanager:YOUR_PASSWORD \
  -d '{
    "version": "4",
    "groupKey": "test",
    "status": "firing",
    "receiver": "jarvis",
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "TestAlert",
        "instance": "nexus:9090",
        "severity": "warning"
      },
      "annotations": {
        "description": "Manual test alert"
      },
      "startsAt": "2025-11-11T20:00:00Z",
      "fingerprint": "test123"
    }]
  }'

# Check Jarvis logs
docker logs jarvis | grep "webhook_received"
```

### Test 2: Real Alert (Container Stop)

```bash
# Stop a non-critical container to trigger alert
ssh nexus 'docker stop omada'

# Wait 1-2 minutes for:
# 1. Prometheus to detect container down
# 2. Alertmanager to fire alert
# 3. Jarvis to receive webhook and remediate

# Monitor Jarvis logs
docker logs -f jarvis

# Expected log sequence:
# 1. webhook_received
# 2. processing_alert
# 3. claude_api_call
# 4. command_validated
# 5. ssh_connection_established (or reusing_ssh_connection)
# 6. command_executed
# 7. remediation_success
# 8. discord_notification_sent

# Verify container restarted
ssh nexus 'docker ps | grep omada'
```

### Test 3: Discord Notification

Check Discord for success notification:

**Expected message:**
```
✅ Alert Auto-Remediated
ContainerDown on nexus:omada has been automatically fixed.

Severity: CRITICAL
Attempt: 1/20
Duration: 5 seconds

AI Analysis:
Container 'omada' stopped unexpectedly. Restarting service.

Commands Executed:
docker restart omada

Expected Outcome:
Container should be healthy within 30 seconds.
```

### Test 4: SSH Connection Pooling

```bash
# Stop another container
ssh nexus 'docker stop scrypted'

# After remediation, check connection stats
docker logs jarvis --since 3m | grep -E "(ssh_connection_established|reusing_ssh_connection)"

# Expected:
# ssh_connection_established (count: 1)
# reusing_ssh_connection (count: many)
```

### Test 5: Database Logging

```bash
# Query remediation log
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT timestamp, alert_name, alert_instance, success, commands_executed
  FROM remediation_log
  ORDER BY timestamp DESC LIMIT 5;
"'

# Verify entries exist for test alerts
```

---

## Updates & Maintenance

### Updating Jarvis

```bash
# On Skynet/Outpost
cd /home/t1/homelab/projects/ai-remediation-service

# Pull latest changes
git pull origin main

# Rebuild image
docker compose build

# Restart with new image
docker compose down
docker compose up -d

# Verify
docker logs jarvis | head -20
```

### Configuration Changes

```bash
# Edit .env
nano .env

# Restart to apply changes
docker compose restart jarvis

# Verify new configuration
docker exec jarvis python -c "
from app.config import settings
print(f'Max attempts: {settings.max_attempts_per_alert}')
print(f'Model: {settings.claude_model}')
"
```

### Log Rotation

```bash
# Logs stored in Docker
docker logs jarvis --since 24h > jarvis_logs_$(date +%Y%m%d).log

# Trim old logs
docker logs jarvis --tail 10000 > /tmp/jarvis_trimmed.log
docker compose restart jarvis
```

### Database Maintenance

```bash
# Check database size
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  SELECT pg_size_pretty(pg_database_size('\''finance_db'\'')) as db_size;
"'

# Archive old logs (older than 30 days)
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
  DELETE FROM remediation_log
  WHERE timestamp < NOW() - INTERVAL '\''30 days'\'';
"'

# Vacuum database
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "VACUUM ANALYZE remediation_log;"'
```

---

## Rollback Procedures

### Rollback to Previous Version

```bash
# Stop current version
docker compose down

# Checkout previous commit
git log --oneline -10  # Find previous version
git checkout COMMIT_HASH

# Rebuild and deploy
docker compose build
docker compose up -d

# Verify
docker logs jarvis
```

### Disable Jarvis Temporarily

```bash
# Option 1: Stop container
docker stop jarvis

# Option 2: Disable in Alertmanager
ssh nexus 'nano /home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml'
# Comment out Jarvis route
# Reload: docker exec alertmanager kill -HUP 1

# Option 3: Enable maintenance mode (not yet implemented)
```

### Emergency Shutdown

```bash
# Stop Jarvis immediately
docker stop jarvis

# Prevent restart on reboot
docker update --restart=no jarvis

# Or remove completely
docker rm jarvis
```

---

## Production Checklist

### Pre-Deployment

- [ ] PostgreSQL database exists and accessible
- [ ] SSH key authorized on all target hosts
- [ ] SSH key has 600 permissions
- [ ] Claude API key is valid and has credit
- [ ] Discord webhook URL is correct
- [ ] `.env` file configured with all required variables
- [ ] `WEBHOOK_AUTH_PASSWORD` generated and saved
- [ ] Network connectivity verified (Docker network)
- [ ] Alertmanager configuration backed up

### Post-Deployment

- [ ] Container started successfully (`docker ps`)
- [ ] Health endpoint returns 200 OK
- [ ] Database connection verified (health check)
- [ ] SSH connections tested to all hosts
- [ ] Manual webhook test passed
- [ ] Real alert test passed (container stop/restart)
- [ ] Discord notification received
- [ ] Database logging verified (remediation_log table)
- [ ] Alertmanager receiving webhooks (check logs)
- [ ] SSH connection pooling working (check logs)

### Monitoring

- [ ] Set up daily log review
- [ ] Monitor Discord for escalations
- [ ] Check database size weekly
- [ ] Review API costs monthly
- [ ] Verify backups (`.env` file, database)
- [ ] Test rollback procedure quarterly

---

## Post-Deployment Notes (November 11, 2025)

### Recent Bug Fixes Applied

If deploying after November 11, 2025, these fixes are already included:

1. **Discord Notifications**
   - Username corrected to "Jarvis" (was "Homelab SRE")
   - Fixed `NameError` in success notifications (missing `max_attempts` parameter)

2. **Container Instance Detection**
   - Improved logic to handle Prometheus pre-formatted instances
   - Prevents multiple containers on same host from sharing attempt counters

3. **Alertmanager Configuration**
   - `group_interval` optimized to `1m` (was `10s`)
   - Prevents duplicate webhook spam
   - Maintains retry capability (~120 attempts in 2-hour window)

### Verify Fixes After Deployment

```bash
# 1. Check Discord username
docker logs jarvis | grep '"username":"Jarvis"'

# 2. Verify container instance format
docker logs jarvis | grep "alert_instance" | grep ":"
# Should see: alert_instance=nexus:omada (not just "nexus")

# 3. Confirm Alertmanager timing
ssh nexus 'cat /home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml | grep -A 3 "group_interval"'
# Should see: group_interval: 1m
```

---

**Last Updated:** November 11, 2025
**Version:** 2.0.0
**Deployment Target:** Outpost/Skynet (192.168.0.13)
