# Jarvis Deployment Guide

Complete step-by-step instructions for deploying the AI remediation service to production.

> **Note:** Most users should use the interactive setup wizard (`./setup.sh`) instead of this guide.
> This document is for advanced deployments, custom configurations, or troubleshooting.

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

**Recommended Deployment Location:**
- A management server or VPS with SSH access to all monitored hosts
- Not a critical service host (safe to restart without affecting production)
- Has network connectivity to Prometheus/Alertmanager

**Architecture:**
```
Service Host (your-server-ip)            Management Host (jarvis-host-ip)
┌────────────────────┐                ┌──────────────────────────┐
│  Alertmanager      │───webhook────▶ │  Jarvis                  │
│  (Prometheus)      │                │  ├─ FastAPI webhook      │
└────────────────────┘                │  ├─ Claude AI analyzer   │
                                      │  ├─ SSH executor         │
┌────────────────────┐                │  └─ Discord notifier     │
│  Target Hosts      │◀──SSH─────────┤                          │
│  ├─ Primary Host   │                │  PostgreSQL              │
│  ├─ Home Assistant │                │  ├─ remediation_log      │
│  └─ Other servers  │                │  └─ attempt tracking     │
└────────────────────┘                └──────────────────────────┘
```

---

## Prerequisites

### Required Services

1. **PostgreSQL Database**
   - Included in docker-compose.yml (postgres-jarvis container)
   - Or use an existing PostgreSQL instance
   - Database: `jarvis`
   - Access: `postgresql://jarvis:password@postgres-jarvis:5432/jarvis`

2. **SSH Access**
   - SSH key with access to your target hosts
   - Key authorized on all servers you want Jarvis to manage

3. **Claude API Key**
   - Account at https://console.anthropic.com/
   - Free tier: $5 credit
   - API key format: `sk-ant-api03-...`

4. **Discord Webhook (Optional)**
   - Discord server with webhook enabled
   - Webhook URL format: `https://discord.com/api/webhooks/{id}/{token}`

5. **Prometheus + Alertmanager**
   - Running somewhere in your infrastructure
   - Can send webhooks to Jarvis

### System Requirements

**Minimum:**
- CPU: 1 core
- RAM: 256 MB (512 MB with included PostgreSQL)
- Disk: 100 MB
- Network: Internet access (Claude API)

**Recommended:**
- CPU: 2 cores
- RAM: 512 MB
- Disk: 500 MB
- Network: Low latency to target hosts

---

## Initial Deployment

### Option 1: Interactive Setup (Recommended)

```bash
# Clone repository
git clone https://github.com/PotatoRick/Jarvis-HomeLab-AI.git
cd Jarvis-HomeLab-AI

# Run setup wizard
./setup.sh

# Follow prompts for Quick Start or Full Setup
```

### Option 2: Manual Deployment

#### Step 1: Prepare Project Directory

```bash
cd /path/to/Jarvis-HomeLab-AI

# Verify files exist
ls -la
# Should see:
# - app/           (Python code)
# - docker-compose.yml
# - Dockerfile
# - .env.example
# - setup.sh
# - README.md
```

#### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit configuration
nano .env
```

**Required settings:**
```bash
# Database (use included postgres-jarvis container)
DATABASE_URL=postgresql://jarvis:YOUR_PASSWORD@postgres-jarvis:5432/jarvis
POSTGRES_PASSWORD=YOUR_PASSWORD

# Claude API
ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY_HERE
CLAUDE_MODEL=claude-3-5-haiku-20241022

# SSH Configuration
SSH_NEXUS_HOST=192.168.1.100        # Your primary service host
SSH_NEXUS_USER=your_username

# Optional additional hosts
SSH_HOMEASSISTANT_HOST=192.168.1.101
SSH_HOMEASSISTANT_USER=root
SSH_OUTPOST_HOST=your.vps.hostname
SSH_OUTPOST_USER=your_username

# Discord (optional but recommended)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE
DISCORD_ENABLED=true

# Security
WEBHOOK_AUTH_USERNAME=alertmanager
WEBHOOK_AUTH_PASSWORD=$(openssl rand -base64 32)

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Remediation Settings
MAX_ATTEMPTS_PER_ALERT=3
ATTEMPT_WINDOW_HOURS=2
COMMAND_EXECUTION_TIMEOUT=60
```

**Save the `WEBHOOK_AUTH_PASSWORD`** - you'll need it for Alertmanager configuration.

#### Step 3: Set Up SSH Key

```bash
# Copy SSH key to project directory
cp ~/.ssh/your_key ./ssh_key

# CRITICAL: Set correct permissions
chmod 600 ./ssh_key

# Verify permissions
ls -la ./ssh_key
# Should show: -rw------- (600)

# Test SSH key works
ssh -i ./ssh_key your_user@your-host 'echo "SSH test successful"'
```

#### Step 4: Build and Deploy

```bash
# Build Docker image
docker compose build

# Start service (includes postgres-jarvis database)
docker compose up -d

# Verify containers are running
docker ps | grep -E "(jarvis|postgres-jarvis)"

# Check logs for startup
docker logs -f jarvis
```

**Expected startup output:**
```json
{"timestamp":"...","level":"info","event":"service_starting","version":"3.12.0"}
{"timestamp":"...","level":"info","event":"database_connected","database":"jarvis"}
{"timestamp":"...","level":"info","event":"ssh_keys_loaded","hosts":["nexus"]}
{"timestamp":"...","level":"info","event":"service_ready","port":8000}
```

#### Step 5: Health Check

```bash
# Test health endpoint
curl http://localhost:8000/health | jq

# Expected response:
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "...",
  "version": "3.12.0",
  "model": "claude-3-5-haiku-20241022"
}
```

---

## Alertmanager Integration

### Step 1: Configure Alertmanager

Edit your Alertmanager configuration:

```yaml
receivers:
  # Your existing receiver (optional)
  - name: 'discord'
    webhook_configs:
      - url: 'YOUR_DISCORD_WEBHOOK'

  # Add Jarvis receiver
  - name: 'jarvis'
    webhook_configs:
      - url: 'http://jarvis-host:8000/webhook'
        send_resolved: true
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'YOUR_WEBHOOK_AUTH_PASSWORD'  # From .env
```

**Update routing:**
```yaml
route:
  receiver: 'discord'  # Default receiver
  group_by: ['alertname', 'instance']
  group_wait: 5s
  group_interval: 1m
  repeat_interval: 30m
  resolve_timeout: 5m

  routes:
    # Route 1: Send to Discord (existing)
    - matchers:
        - alertname =~ ".+"
      receiver: 'discord'
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
- `group_interval: 1m` - Retry every 1 minute if alert persists
- `repeat_interval: 30m` - Resend after 30 minutes if still unresolved

### Step 2: Reload Alertmanager

```bash
# Reload configuration
docker exec alertmanager kill -HUP 1

# Verify reload succeeded
docker logs alertmanager --tail 20
# Should see: "Loading configuration file"
```

### Step 3: Verify Network Connectivity

```bash
# From Alertmanager host, test Jarvis webhook endpoint
curl http://jarvis-host:8000/health

# If on same Docker network
docker exec alertmanager wget -O- http://jarvis:8000/health
```

If connectivity fails, ensure Jarvis is on the same Docker network:

```bash
# Check Docker networks
docker network ls

# Connect Jarvis to Alertmanager's network if needed
docker network connect your-network jarvis
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
        "instance": "test-host:9090",
        "severity": "warning"
      },
      "annotations": {
        "description": "Manual test alert"
      },
      "startsAt": "2025-01-01T00:00:00Z",
      "fingerprint": "test123"
    }]
  }'

# Check Jarvis logs
docker logs jarvis | grep "webhook_received"
```

### Test 2: Real Alert (Container Stop)

```bash
# Stop a non-critical container to trigger alert
ssh your-host 'docker stop some-test-container'

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
# 5. ssh_connection_established
# 6. command_executed
# 7. remediation_success
# 8. discord_notification_sent

# Verify container restarted
ssh your-host 'docker ps | grep some-test-container'
```

### Test 3: Discord Notification

Check Discord for success notification:

**Expected message:**
```
✅ Alert Auto-Remediated
ContainerDown on your-host:container has been automatically fixed.

Severity: CRITICAL
Attempt: 1/3
Duration: 5 seconds

AI Analysis:
Container 'container' stopped unexpectedly. Restarting service.

Commands Executed:
docker restart container

Expected Outcome:
Container should be healthy within 30 seconds.
```

### Test 4: Database Logging

```bash
# Query remediation log
docker exec -it postgres-jarvis psql -U jarvis -d jarvis -c "
  SELECT timestamp, alert_name, alert_instance, success, commands_executed
  FROM remediation_log
  ORDER BY timestamp DESC LIMIT 5;
"
```

---

## Updates & Maintenance

### Updating Jarvis

```bash
cd /path/to/Jarvis-HomeLab-AI

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
curl http://localhost:8000/health
```

### Log Management

```bash
# Export logs to file
docker logs jarvis --since 24h > jarvis_logs_$(date +%Y%m%d).log

# View recent logs
docker logs jarvis --tail 100
```

### Database Maintenance

```bash
# Check database size
docker exec postgres-jarvis psql -U jarvis -d jarvis -c "
  SELECT pg_size_pretty(pg_database_size('jarvis')) as db_size;
"

# Archive old logs (older than 30 days)
docker exec postgres-jarvis psql -U jarvis -d jarvis -c "
  DELETE FROM remediation_log
  WHERE timestamp < NOW() - INTERVAL '30 days';
"

# Vacuum database
docker exec postgres-jarvis psql -U jarvis -d jarvis -c "VACUUM ANALYZE remediation_log;"
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
# Comment out Jarvis route in alertmanager.yml
# Reload: docker exec alertmanager kill -HUP 1

# Option 3: Enable maintenance mode
curl -X POST "http://localhost:8000/maintenance/start?reason=planned+upgrade"
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

- [ ] PostgreSQL database accessible (included or external)
- [ ] SSH key authorized on all target hosts
- [ ] SSH key has 600 permissions
- [ ] Claude API key is valid and has credit
- [ ] Discord webhook URL is correct (if using)
- [ ] `.env` file configured with all required variables
- [ ] `WEBHOOK_AUTH_PASSWORD` generated and saved
- [ ] Network connectivity verified to all hosts
- [ ] Alertmanager configuration backed up

### Post-Deployment

- [ ] Container started successfully (`docker ps`)
- [ ] Health endpoint returns 200 OK
- [ ] Database connection verified (health check)
- [ ] SSH connections tested to all hosts
- [ ] Manual webhook test passed
- [ ] Real alert test passed (container stop/restart)
- [ ] Discord notification received (if enabled)
- [ ] Database logging verified (remediation_log table)
- [ ] Alertmanager receiving webhooks (check logs)

### Monitoring

- [ ] Set up daily log review
- [ ] Monitor Discord for escalations
- [ ] Check database size weekly
- [ ] Review API costs monthly
- [ ] Verify backups (`.env` file, database)
- [ ] Test rollback procedure quarterly

---

## Troubleshooting

### Setup Validation

Run the setup wizard in validate mode:

```bash
./setup.sh --validate
```

This will check:
- All required environment variables
- SSH connectivity to configured hosts
- Database connection
- Claude API key validity

### Common Issues

**Container won't start:**
```bash
docker logs jarvis
# Look for configuration or dependency errors
```

**SSH connection failures:**
```bash
# Test manually
ssh -i ./ssh_key -o StrictHostKeyChecking=no user@host 'echo test'

# Check key permissions
ls -la ./ssh_key  # Must be 600
```

**Database connection errors:**
```bash
# Check postgres-jarvis is running
docker ps | grep postgres-jarvis

# Test connection
docker exec postgres-jarvis psql -U jarvis -d jarvis -c "SELECT 1;"
```

**Alertmanager not sending webhooks:**
```bash
# Check Alertmanager logs
docker logs alertmanager | grep jarvis

# Verify webhook URL is reachable from Alertmanager
```

---

**Last Updated:** December 2025
**Version:** 3.12.0
