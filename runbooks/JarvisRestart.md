# Jarvis Self-Restart Troubleshooting

## Overview

This runbook covers troubleshooting for Jarvis's self-preservation system, which allows Jarvis to safely restart itself and its dependencies via n8n orchestration.

## Architecture

```
Jarvis API                n8n Workflow               Docker/Host
    |                         |                          |
    | POST /self-restart      |                          |
    |------------------------>|                          |
    |                         | SSH: docker restart      |
    |                         |------------------------->|
    |                         |                          |
    |                         | Poll /health             |
    |                         |<-------------------------|
    |                         |                          |
    | POST /resume            |                          |
    |<------------------------|                          |
```

## Common Issues

### 1. n8n Workflow Times Out

**Symptom:** Discord notification says "Self-Restart Timeout - Manual intervention required"

**Possible Causes:**

1. **Jarvis container failed to start**
   ```bash
   # Check container status
   docker ps -a | grep jarvis

   # Check logs for startup errors
   docker logs jarvis --tail 100
   ```

2. **Database connection failed**
   ```bash
   # Check postgres-jarvis is running
   docker ps | grep postgres-jarvis

   # Test database connection
   docker exec postgres-jarvis psql -U jarvis -d jarvis -c "SELECT 1"
   ```

3. **Port conflict**
   ```bash
   # Check if port 8000 is in use
   ss -tlnp | grep 8000
   ```

4. **Health endpoint unreachable from n8n**
   ```bash
   # Test from VPS-Host (where n8n runs)
   ssh vps-host 'curl -s http://<management-host-ip>:8000/health'
   ```

**Remediation:**
1. Check Docker logs for specific errors
2. Manually restart if needed: `docker restart jarvis`
3. Verify health: `curl http://<management-host-ip>:8000/health`
4. Check network connectivity between VPS-Host and Management-Host

### 2. Handoff Not Triggering n8n

**Symptom:** `/self-restart` returns success but n8n never executes

**Diagnosis:**
```bash
# Check Jarvis logs for n8n trigger
docker logs jarvis 2>&1 | grep -E "(n8n|trigger|webhook)"

# Verify n8n URL is configured
docker exec jarvis env | grep N8N_URL
```

**Possible Causes:**

1. **N8N_URL not set or incorrect**
   - Check `.env` file: `grep N8N_URL .env`
   - Should be: `N8N_URL=https://n8n.yourdomain.com`

2. **n8n workflow not active**
   - Login to n8n.yourdomain.com
   - Check "Jarvis Self-Restart Orchestrator" workflow is active (green toggle)

3. **Network connectivity**
   ```bash
   # Test from Management-Host
   curl -s https://n8n.yourdomain.com/webhook/jarvis-self-restart
   ```

**Remediation:**
1. Fix N8N_URL in `.env` and restart Jarvis
2. Activate the workflow in n8n UI
3. Check firewall rules and VPN connectivity

### 3. Existing Handoff Blocking New Request

**Symptom:** `/self-restart` returns "Existing handoff X is still active"

**Diagnosis:**
```bash
# Check current handoff status
curl -s http://<management-host-ip>:8000/self-restart/status

# Query database for active handoffs
docker exec postgres-jarvis psql -U jarvis -d jarvis -c \
  "SELECT handoff_id, status, created_at FROM self_preservation_handoffs WHERE status IN ('pending', 'in_progress')"
```

**Remediation:**
```bash
# Cancel stale handoff
curl -X POST "http://<management-host-ip>:8000/self-restart/cancel?handoff_id=<handoff_id>&reason=Manual%20cleanup"
```

### 4. SSH Command Fails in n8n

**Symptom:** n8n execution shows error at "Execute Restart Command" node

**Diagnosis:**
1. Check n8n execution logs for SSH error details
2. Verify SSH credentials in n8n are correct

**Common SSH Errors:**

1. **Authentication failed**
   - Check SSH key in n8n credentials matches Management-Host's authorized_keys
   - Verify username is correct (should be `t1`)

2. **Host key verification failed**
   - SSH to Management-Host once from VPS-Host to accept host key
   - Or add StrictHostKeyChecking=no to SSH config

3. **Connection refused**
   - Verify SSH service running on Management-Host: `systemctl status sshd`
   - Check firewall allows SSH from VPS-Host

**Remediation:**
```bash
# Test SSH from VPS-Host manually
ssh vps-host 'ssh -i /path/to/key t1@<management-host-ip> "echo test"'
```

### 5. Resume Endpoint Fails

**Symptom:** Jarvis restarts but `/resume` call fails (404 or 500)

**Diagnosis:**
```bash
# Check if handoff exists in database
docker exec postgres-jarvis psql -U jarvis -d jarvis -c \
  "SELECT * FROM self_preservation_handoffs WHERE handoff_id = '<handoff_id>'"
```

**Possible Causes:**

1. **Handoff not found (404)**
   - Handoff wasn't saved before restart
   - Database was reset/migrated

2. **Handoff in wrong state**
   - Already completed or cancelled

**Remediation:**
- If test handoff (prefix `test-`), it will be auto-accepted
- For real handoffs, check database state and manually mark as completed if needed

## Preventive Measures

### Regular Checks

1. **Weekly: Test self-restart with echo command**
   ```bash
   curl -X POST https://n8n.yourdomain.com/webhook/jarvis-self-restart \
     -H "Content-Type: application/json" \
     -d '{"handoff_id": "test-weekly", "restart_target": "jarvis", "restart_command": "echo WEEKLY_TEST", "restart_reason": "Weekly test", "ssh_host": "<management-host-ip>", "ssh_user": "t1", "jarvis_health_url": "http://<management-host-ip>:8000/health", "callback_url": "http://<management-host-ip>:8000/resume", "timeout_minutes": 2}'
   ```

2. **Monitor Prometheus metrics**
   - `jarvis_self_restarts_total` - count of self-restarts
   - `jarvis_self_restart_failures_total` - failed self-restarts
   - Alert if failure rate > 50%

### Ensure High Availability

1. **n8n workflow always active**
   - Add monitoring for workflow active state
   - Alert if workflow becomes inactive

2. **Database backups**
   - Handoff state is persisted in postgres-jarvis
   - Include in regular backup rotation

3. **Network redundancy**
   - Ensure VPN tunnel stable between VPS-Host and Management-Host
   - Consider fallback paths

## Manual Recovery

If the self-preservation system completely fails, manually restart:

```bash
# SSH to Management-Host
ssh management-host

# Restart Jarvis manually
docker restart jarvis

# Verify health
curl http://localhost:8000/health

# Clear any stale handoffs
docker exec postgres-jarvis psql -U jarvis -d jarvis -c \
  "UPDATE self_preservation_handoffs SET status = 'cancelled', error_message = 'Manual recovery' WHERE status IN ('pending', 'in_progress')"
```

## Related Documentation

- Main CLAUDE.md: `/home/<user>/homelab/projects/ai-remediation-service/CLAUDE.md`
- n8n workflow: `/home/<user>/homelab/configs/n8n-workflows/jarvis-self-restart-workflow.json`
- Self-preservation module: `/home/<user>/homelab/projects/ai-remediation-service/app/self_preservation.py`
