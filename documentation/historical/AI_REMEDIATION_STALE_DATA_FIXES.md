# AI Remediation Service - Stale Data and Attempt Counting Fixes

**Date:** November 11, 2025
**Issue:** AI remediation escalating alerts due to stale data and incorrect attempt counting
**Status:** In Progress

---

## Problems Identified

### 1. Non-Specific Alert Instance Labels
**Problem:** Prometheus alert uses `{{ $labels.instance }}` which is just the hostname (e.g., "nexus")

```yaml
# CURRENT (INCORRECT):
- alert: ContainerDown
  expr: docker_container_state == 0
  annotations:
    description: "Container {{ $labels.container }} on {{ $labels.instance }}..."
```

**Impact:** All ContainerDown alerts on same host share the same alert_instance
- ContainerDown for Vaultwarden on nexus = "nexus"
- ContainerDown for Omada on nexus = "nexus"
- ContainerDown for Scrypted on nexus = "nexus"

**Result:** AI service counts ALL attempts across different containers as attempts for ONE alert

**Evidence from logs:**
```
2025-11-12 00:34:44 [info] attempt_count_retrieved alert_instance=nexus alert_name=ContainerDown count=8
```

Those 8 attempts were:
- Omada x4
- Vaultwarden x2
- Scrypted x1
- Octoprint x1

But AI service thinks they're all for the same alert.

---

### 2. Attempt Window Too Long
**Problem:** 24-hour attempt window means old attempts affect new alerts

**Current Setting:**
```env
ATTEMPT_WINDOW_HOURS=24
```

**Impact:** Backup script runs at 3 AM and stops containers. Some fail to restart. AI service fixes them. 21 hours later at midnight, a different container goes down for testing, but AI service sees 8 attempts already and escalates immediately.

**Evidence:**
- Backup issues: 03:16 - 03:26 AM
- Test alert: 00:34 AM (21 hours later)
- Counted as 8 attempts → immediate escalation

---

### 3. Read-Only Commands Counted as Attempts
**Problem:** Diagnostic commands like `docker ps` are logged as remediation attempts

**Evidence from database:**
```sql
commands_executed: {"docker ps -a --filter name=vaultwarden", "docker restart vaultwarden"}
success: f
```

**Impact:** If Claude tries to diagnose before fixing (which is good practice), each diagnostic command counts against the max attempts limit.

**Example:**
- Attempt 1: `docker ps -a --filter name=vaultwarden` (diagnostic) - FAIL (but counted)
- Attempt 2: `docker restart vaultwarden` (actionable) - SUCCESS

Should only count attempt 2.

---

### 4. No Cleanup on Alert Resolution
**Problem:** When alert resolves, attempt counter is not reset

**Current Flow:**
1. Alert fires → AI fixes → Alert resolves
2. Alert fires again (same service, different issue) → Still sees old attempts

**Impact:** Legitimate new issues are escalated immediately due to historical attempts

---

## Fixes Required

### Fix 1: Container-Specific Alert Instance

**File:** `/home/jordan/docker/home-stack/prometheus/alert_rules.yml` (on Nexus)

**Change:**
```yaml
# BEFORE:
- alert: ContainerDown
  expr: docker_container_state == 0
  for: 2m
  labels:
    severity: critical
    category: containers
  annotations:
    summary: "Container {{ $labels.container }} is DOWN"
    description: "Container {{ $labels.container }} on {{ $labels.instance }}..."

# AFTER:
- alert: ContainerDown
  expr: docker_container_state == 0
  for: 2m
  labels:
    severity: critical
    category: containers
    instance: "{{ $labels.host }}:{{ $labels.container }}"  # Override instance label
  annotations:
    summary: "Container {{ $labels.container }} is DOWN"
    description: "Container {{ $labels.container }} on {{ $labels.host }}..."
```

**Result:**
- Vaultwarden alert_instance = "nexus:vaultwarden"
- Omada alert_instance = "nexus:omada"
- Each container tracked separately

---

### Fix 2: Reduce Attempt Window

**File:** `/home/t1/homelab/projects/ai-remediation-service/.env`

**Change:**
```env
# BEFORE:
ATTEMPT_WINDOW_HOURS=24

# AFTER:
ATTEMPT_WINDOW_HOURS=2
```

**Rationale:**
- 2 hours is enough to prevent rapid retry loops
- Old issues don't affect new alerts
- Still allows 3 attempts with 30-minute repeat_interval

**Timeline with 2-hour window:**
- 00:00: Alert fires, attempt 1
- 00:30: Still firing, attempt 2 (repeat_interval)
- 01:00: Still firing, attempt 3 → escalate
- 02:01: Window expired, counter resets

---

### Fix 3: Only Count Actionable Commands

**File:** `/home/t1/homelab/projects/ai-remediation-service/app/main.py`

**New Function:**
```python
def is_actionable_command(command: str) -> bool:
    """
    Determine if a command is actionable (modifies state) vs diagnostic (read-only).

    Only actionable commands should count toward remediation attempts.
    """
    # Diagnostic/read-only commands (do NOT count)
    diagnostic_patterns = [
        r'^docker ps',
        r'^docker logs',
        r'^docker inspect',
        r'^docker stats',
        r'^systemctl status',
        r'^journalctl',
        r'^curl\s+-[IfsSkLv]',  # GET requests only
        r'^ping',
        r'^uptime',
        r'^free',
        r'^df',
        r'^ls\s',
        r'^cat\s',
        r'^grep\s',
        r'^which\s',
        r'^ps\s+aux',
        r'^netstat',
        r'^ss\s+-',
        r'^ha\s+core\s+info',
        r'^ha\s+core\s+check',
    ]

    import re
    for pattern in diagnostic_patterns:
        if re.match(pattern, command, re.IGNORECASE):
            return False

    # Everything else is actionable
    return True
```

**Change in `process_alert()`:**
```python
# After command execution, filter to only actionable commands
actionable_commands = [cmd for cmd in analysis.commands if is_actionable_command(cmd)]
diagnostic_commands = [cmd for cmd in analysis.commands if not is_actionable_command(cmd)]

logger.info(
    "command_classification",
    total=len(analysis.commands),
    actionable=len(actionable_commands),
    diagnostic=len(diagnostic_commands)
)

# Only log attempt if actionable commands were executed
if actionable_commands:
    attempt = RemediationAttempt(
        alert_name=alert_name,
        alert_instance=alert_instance,
        commands_executed=analysis.commands,  # Log all for debugging
        # ... but only count as attempt if actionable commands present
    )
    await db.log_remediation_attempt(attempt)
else:
    logger.info("diagnostic_only_no_attempt_logged")
```

---

### Fix 4: Clear Attempts on Alert Resolution

**File:** `/home/t1/homelab/projects/ai-remediation-service/app/main.py`

**Add webhook handler for resolved alerts:**
```python
@app.post("/webhook/alertmanager")
async def alertmanager_webhook(
    request: Request,
    webhook: AlertmanagerWebhook,
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    """Handle Alertmanager webhook."""

    # Process firing alerts
    if webhook.status == "firing":
        for alert in webhook.alerts:
            await process_alert(alert)

    # NEW: Clear attempt counters for resolved alerts
    elif webhook.status == "resolved":
        for alert in webhook.alerts:
            alert_name = alert.labels.alertname
            alert_instance = alert.labels.instance

            await db.clear_attempts(alert_name, alert_instance)

            logger.info(
                "attempts_cleared_on_resolution",
                alert_name=alert_name,
                alert_instance=alert_instance
            )

    return {"status": "ok"}
```

**New Database Method:**
```python
# In app/database.py

async def clear_attempts(self, alert_name: str, alert_instance: str) -> int:
    """
    Clear (delete) remediation attempts for a specific alert.

    Called when alert resolves to reset the counter.

    Args:
        alert_name: Alert name
        alert_instance: Alert instance

    Returns:
        Number of deleted records
    """
    query = """
        DELETE FROM remediation_log
        WHERE alert_name = $1
          AND alert_instance = $2
          AND timestamp > NOW() - INTERVAL '24 hours'
    """

    async with self.pool.acquire() as conn:
        result = await conn.execute(query, alert_name, alert_instance)

    # Extract count from result string like "DELETE 5"
    count = int(result.split()[-1]) if result else 0

    self.logger.info(
        "attempts_cleared",
        alert_name=alert_name,
        alert_instance=alert_instance,
        count=count
    )

    return count
```

---

## Implementation Order

1. **Fix Prometheus alert rule** (requires Prometheus reload)
2. **Update .env file** (requires service restart)
3. **Add `is_actionable_command()` function** to main.py
4. **Add `clear_attempts()` method** to database.py
5. **Modify webhook handler** to process resolved alerts
6. **Update command logging logic** to only count actionable commands
7. **Restart AI remediation service**
8. **Test with container stop/start**

---

## Testing Plan

### Test 1: Container-Specific Tracking
```bash
# Stop two different containers
ssh nexus 'docker stop omada'
ssh nexus 'docker stop vaultwarden'

# Wait 2 minutes for alerts to fire

# Check AI service logs - should see TWO separate alerts:
# - alert_instance=nexus:omada
# - alert_instance=nexus:vaultwarden

# Each should have attempt_count=1 (not shared)
```

### Test 2: Diagnostic Commands Don't Count
```bash
# Trigger alert
ssh nexus 'docker stop omada'

# AI should run diagnostics like:
# - docker ps -a --filter name=omada
# - docker logs --tail 50 omada
# Then run actionable command:
# - docker restart omada

# Check database: only 1 attempt logged (not 3)
```

### Test 3: Resolution Clears Attempts
```bash
# Stop container
ssh nexus 'docker stop omada'

# Let AI fix it (should auto-restart)

# Verify alert resolves in Prometheus

# Check database: attempts for nexus:omada should be cleared

# Stop again - should start fresh at attempt 1
```

### Test 4: Short Window Works
```bash
# Create attempt at 00:00
ssh nexus 'docker stop omada && sleep 5 && docker start omada'

# Wait 2.5 hours

# Create new attempt at 02:35
ssh nexus 'docker stop omada'

# Check: should show attempt_count=1 (not 2)
# Old attempt outside 2-hour window
```

---

## Expected Behavior After Fixes

### Scenario 1: Single Container Failure
1. Omada container stops
2. Alert fires: "ContainerDown" instance="nexus:omada"
3. AI receives webhook, checks attempts: 0
4. AI runs diagnostics (not counted): `docker ps -a`, `docker logs`
5. AI runs fix (counted as attempt 1): `docker restart omada`
6. Container starts, alert resolves
7. AI clears attempts for "nexus:omada"
8. Counter reset to 0

### Scenario 2: Persistent Issue
1. Container keeps crashing
2. Attempt 1 (00:00): restart, fails
3. Attempt 2 (00:30): restart, fails
4. Attempt 3 (01:00): restart, fails
5. Escalate to Discord for manual intervention
6. All attempts for "nexus:specificcontainer" (not affecting other containers)

### Scenario 3: Old Data Doesn't Affect New Alerts
1. Backup runs at 03:00, multiple containers fail
2. AI fixes all between 03:15-03:30
3. At 06:00 (3 hours later), different container fails
4. Window is 2 hours, so 03:00 attempts don't count
5. Fresh attempt counter starts at 1

---

## Rollback Procedure

If issues arise:

1. **Revert Prometheus alert rule:**
   ```bash
   ssh nexus 'cd /home/jordan/docker/home-stack/prometheus && git checkout alert_rules.yml'
   ssh nexus 'docker exec prometheus kill -HUP 1'
   ```

2. **Revert .env:**
   ```bash
   cd /home/t1/homelab/projects/ai-remediation-service
   # Change ATTEMPT_WINDOW_HOURS back to 24
   docker compose restart
   ```

3. **Revert code changes:**
   ```bash
   cd /home/t1/homelab/projects/ai-remediation-service
   git checkout app/main.py app/database.py
   docker compose restart
   ```

---

## Success Metrics

After implementation, monitor for:

1. **No false escalations** - Only escalate after 3 genuine failed attempts
2. **Container-specific tracking** - Each container has independent attempt counter
3. **Fresh start on resolution** - Resolved alerts don't carry old attempt counts
4. **Diagnostic transparency** - Logs show diagnostic vs actionable commands clearly

---

## Files Changed

1. `/home/jordan/docker/home-stack/prometheus/alert_rules.yml` (Nexus)
2. `/home/t1/homelab/projects/ai-remediation-service/.env` (Skynet)
3. `/home/t1/homelab/projects/ai-remediation-service/app/main.py` (Skynet)
4. `/home/t1/homelab/projects/ai-remediation-service/app/database.py` (Skynet)

---

## Next Steps

1. Review this document for accuracy
2. Implement changes in order listed
3. Test each fix independently
4. Create comprehensive test for all fixes together
5. Document results
6. Commit changes to git with detailed commit message
