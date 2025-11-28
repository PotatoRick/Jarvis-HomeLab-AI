# AI Remediation System - Deployment Checklist

## Pre-Deployment Requirements

### Infrastructure
- [ ] Outpost VPS running with n8n and PostgreSQL (n8n-db container)
- [ ] Nexus running Prometheus and Alertmanager
- [ ] Discord server with #homelab-alerts channel configured
- [ ] SSH access from Skynet to Nexus, Outpost, Home Assistant
- [ ] Anthropic API account with active API key

### Access & Credentials
- [ ] SSH keys in `/home/t1/.ssh/keys/homelab_ed25519`
- [ ] SSH config aliases working (`ssh nexus`, `ssh outpost`, `ssh homeassistant`)
- [ ] Discord webhook URL for #homelab-alerts
- [ ] Anthropic API key from https://console.anthropic.com/
- [ ] PostgreSQL credentials for finance_db on Outpost
- [ ] n8n admin access at https://n8n.theburrow.casa

### Knowledge Check
- [ ] Reviewed `/home/t1/homelab/documentation/ai-remediation-system.md`
- [ ] Reviewed `/home/t1/homelab/documentation/ai-remediation-quickstart.md`
- [ ] Understand the workflow architecture
- [ ] Know how to access logs (PostgreSQL, n8n, Discord)

---

## Phase 1: Database Setup (15 minutes)

### 1.1 Deploy PostgreSQL Schema
```bash
cd /home/t1/homelab/scripts/ai-remediation
./setup_ai_remediation.sh
```

**Verification:**
- [ ] Script completed without errors
- [ ] Webhook password displayed and saved to Vaultwarden
- [ ] Alertmanager restarted successfully

**Manual Verification:**
```bash
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "\dt"'
```
Expected output: remediation_log, maintenance_windows, command_whitelist

- [ ] All 3 tables exist
- [ ] Command whitelist has seed data (>10 patterns)

**Check Functions:**
```bash
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT get_attempt_count('\''test'\'', '\''test:9090'\'');"'
```
Expected: Returns `0`

- [ ] Helper functions working

**Rollback Plan:**
If schema fails, manually execute:
```bash
ssh outpost
docker cp /home/t1/homelab/configs/postgres/ai-remediation-schema.sql n8n-db:/tmp/
docker exec -it n8n-db psql -U n8n -d finance_db -f /tmp/schema.sql
```

---

## Phase 2: Alertmanager Configuration (10 minutes)

### 2.1 Verify Configuration Applied

**Check Alertmanager config on Nexus:**
```bash
ssh nexus 'cat /home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml | grep n8n-remediation'
```

- [ ] n8n-remediation receiver exists
- [ ] Webhook URL points to https://n8n.theburrow.casa/webhook/alert-remediation
- [ ] Basic auth configured

**Check .env file:**
```bash
ssh nexus 'grep ALERTMANAGER_WEBHOOK_PASSWORD /home/jordan/docker/home-stack/.env'
```

- [ ] ALERTMANAGER_WEBHOOK_PASSWORD present

**Verify Alertmanager running:**
```bash
ssh nexus 'docker ps | grep alertmanager'
ssh nexus 'docker logs alertmanager --tail 20'
```

- [ ] Container running
- [ ] No config errors in logs

**Rollback Plan:**
Restore backup:
```bash
ssh nexus 'cd /home/jordan/docker/home-stack/alertmanager/config && cp alertmanager.yml.backup.* alertmanager.yml && docker compose restart alertmanager'
```

---

## Phase 3: n8n Credentials (15 minutes)

Navigate to: https://n8n.theburrow.casa → Settings → Credentials

### 3.1 SSH Credentials

**ssh_nexus:**
- [ ] Name: `ssh_nexus`
- [ ] Type: SSH
- [ ] Host: `192.168.0.11`
- [ ] Port: `22`
- [ ] Username: `jordan`
- [ ] Private Key: Paste from `/home/t1/.ssh/keys/homelab_ed25519`
- [ ] Test connection successful

**ssh_homeassistant:**
- [ ] Name: `ssh_homeassistant`
- [ ] Type: SSH
- [ ] Host: `192.168.0.10`
- [ ] Port: `22`
- [ ] Username: `root`
- [ ] Private Key: Same as above
- [ ] Test connection successful

**ssh_outpost:**
- [ ] Name: `ssh_outpost`
- [ ] Type: SSH
- [ ] Host: `localhost` (or `127.0.0.1`)
- [ ] Port: `22`
- [ ] Username: `root`
- [ ] Private Key: Same as above
- [ ] Test connection successful

### 3.2 PostgreSQL Credential

**postgres_finance_db:**
- [ ] Name: `postgres_finance_db`
- [ ] Type: PostgreSQL
- [ ] Host: `n8n-db`
- [ ] Port: `5432`
- [ ] Database: `finance_db`
- [ ] User: `n8n`
- [ ] Password: From `/opt/burrow/.env` (N8N_DB_PASSWORD)
- [ ] SSL: Disabled
- [ ] Test connection successful

**Test Query:**
```sql
SELECT COUNT(*) FROM remediation_log;
```
Expected: 0 (or small number if tests run)

### 3.3 Discord Webhook

**discord_homelab_alerts:**
- [ ] Name: `discord_homelab_alerts`
- [ ] Type: Discord Webhook
- [ ] Webhook URL: From Discord Server Settings → Integrations
- [ ] Test by sending message

### 3.4 Anthropic API

**anthropic_claude:**
- [ ] Name: `anthropic_claude`
- [ ] Type: HTTP Request (Generic Credential)
- [ ] Authentication: Header Auth
- [ ] Header Name: `x-api-key`
- [ ] Header Value: API key from https://console.anthropic.com/
- [ ] Test with simple request

**Test Command:**
```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model": "claude-sonnet-4-5-20250929", "max_tokens": 50, "messages": [{"role": "user", "content": "Hi"}]}'
```

Expected: JSON response with Claude's message

---

## Phase 4: Build n8n Workflows (45 minutes)

Follow: `/home/t1/homelab/configs/n8n-workflows/README.md`

### 4.1 Workflow 1: Alert Remediation

- [ ] Create new workflow named "Alert Remediation"
- [ ] Add Webhook trigger (path: `alert-remediation`)
- [ ] Configure basic auth (alertmanager / webhook_password)
- [ ] Add Parse Alerts (Code node)
- [ ] Add Check Maintenance Window (Postgres node)
- [ ] Add IF node (skip during maintenance)
- [ ] Add Get Attempt Count (Postgres node)
- [ ] Add IF node (attempts < 3)
- [ ] Add Determine Target System (Code node)
- [ ] Add Gather System Logs (SSH node)
- [ ] Add Build AI Prompt (Code node)
- [ ] Add Claude AI Request (HTTP Request node)
- [ ] Add Parse AI Response (Code node)
- [ ] Add Validate Commands (Code node)
- [ ] Add Risk & Safety Check (IF node)
- [ ] Add Execute Commands (SSH node)
- [ ] Add Calculate Results (Code node)
- [ ] Add Log to PostgreSQL (Postgres node)
- [ ] Add Post to Discord (Discord node)
- [ ] Test workflow with manual execution
- [ ] Activate workflow

**Verification Test:**
```bash
cd /home/t1/homelab/scripts/ai-remediation
./test_ai_remediation.sh webhook
```

- [ ] Test returns HTTP 200
- [ ] Execution appears in n8n
- [ ] No node errors

### 4.2 Workflow 2: Escalation (Optional for MVP)

- [ ] Create new workflow named "Alert Escalation"
- [ ] Add Webhook or Execute Workflow trigger
- [ ] Add Get Last 3 Attempts (Postgres node)
- [ ] Add Claude Summary Request (HTTP Request node)
- [ ] Add Post Discord Escalation (Discord node)
- [ ] Test workflow manually
- [ ] Activate workflow

**Note:** Can be built after Workflow 1 is proven in production

### 4.3 Workflow 3: Maintenance Toggle (Optional)

- [ ] Create new workflow named "Maintenance Mode Toggle"
- [ ] Add Webhook trigger (path: `maintenance-toggle`)
- [ ] Add Insert Maintenance Window (Postgres node)
- [ ] Add Post Confirmation (Discord node)
- [ ] Test workflow manually
- [ ] Activate workflow

**Test:**
```bash
./test_ai_remediation.sh maintenance
```

- [ ] Maintenance window created in database
- [ ] Discord confirmation posted

---

## Phase 5: Initial Testing (20 minutes)

### 5.1 Webhook Connectivity Test

```bash
cd /home/t1/homelab/scripts/ai-remediation
./test_ai_remediation.sh webhook
```

- [ ] HTTP 200 response
- [ ] n8n execution logged
- [ ] No errors in workflow

### 5.2 PostgreSQL Verification

```bash
./test_ai_remediation.sh postgres
```

- [ ] All tables exist
- [ ] Functions work correctly
- [ ] Seed data present

### 5.3 Command Validation Test

```bash
./test_ai_remediation.sh validation
```

- [ ] Safe commands pass validation
- [ ] Dangerous commands rejected

### 5.4 Simulated Alert Test

```bash
./test_ai_remediation.sh wireguard
```

- [ ] Alert received by n8n
- [ ] AI analysis generated
- [ ] Commands validated
- [ ] PostgreSQL log created
- [ ] Discord notification posted

**Check Results:**
```bash
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM remediation_log ORDER BY timestamp DESC LIMIT 1;"'
```

Expected fields:
- [ ] alert_name populated
- [ ] ai_analysis present
- [ ] commands_executed array populated
- [ ] success boolean set
- [ ] Discord message posted

---

## Phase 6: Production Validation (30 minutes)

### 6.1 Safe Real Alert Test

**Choose a non-critical service for testing:**

Option A: Temporary container (safest)
```bash
# Deploy test container on Nexus
ssh nexus 'docker run -d --name test-remediation nginx'
# Stop it
ssh nexus 'docker stop test-remediation'
# Wait for alert, check if auto-restarted
```

Option B: AdGuard (use caution, affects DNS)
```bash
# Only during low-usage period
ssh nexus 'docker stop adguard'
# Wait 2-3 minutes
# Verify auto-restart
ssh nexus 'docker ps | grep adguard'
```

- [ ] Alert fired by Alertmanager
- [ ] n8n workflow executed
- [ ] Service auto-restarted
- [ ] Alert resolved in Prometheus
- [ ] Discord shows success notification
- [ ] PostgreSQL log entry created

**Review Execution:**
- [ ] Go to n8n executions
- [ ] Click most recent execution
- [ ] Verify all nodes green
- [ ] Check AI analysis makes sense
- [ ] Verify commands executed correctly

### 6.2 Three-Attempt Escalation Test (Optional)

**Simulate persistent failure:**
```bash
# Remove a container to cause restart failures
ssh nexus 'docker rm -f test-remediation'
# Create alert that references removed container
# Wait for 3 failed attempts (may take 15-30 minutes)
```

- [ ] After 3 attempts, escalation workflow triggered
- [ ] Discord escalation message posted
- [ ] Remediation_log shows escalated=true

**Restore:**
```bash
ssh nexus 'docker run -d --name test-remediation nginx'
```

---

## Phase 7: Monitoring Setup (15 minutes)

### 7.1 Create Grafana Dashboard (Optional)

Import queries from `/home/t1/homelab/documentation/ai-remediation-system.md`

Panels to add:
- [ ] Success rate (last 24 hours)
- [ ] Most common alerts
- [ ] Average remediation time
- [ ] Recent activity table

### 7.2 Set Up Daily Review

Add to daily routine:
```bash
# Check overnight activity
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
    SELECT alert_name, COUNT(*), SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful
    FROM remediation_log
    WHERE timestamp > NOW() - INTERVAL '\''24 hours'\''
    GROUP BY alert_name;"'
```

- [ ] Bookmark this command or create alias

### 7.3 Weekly Audit Script (Optional)

Create `/home/t1/homelab/scripts/ai-remediation/weekly_audit.sh`:
```bash
#!/bin/bash
echo "=== AI Remediation Weekly Report ==="
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db' << EOF
SELECT
    DATE_TRUNC('week', timestamp) as week,
    COUNT(*) as total_attempts,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN escalated THEN 1 ELSE 0 END) as escalated
FROM remediation_log
WHERE timestamp > NOW() - INTERVAL '4 weeks'
GROUP BY week
ORDER BY week DESC;
EOF
```

- [ ] Create weekly audit script
- [ ] Add to calendar reminder

---

## Phase 8: Documentation & Handoff (10 minutes)

### 8.1 Update Main README

Add to `/home/t1/homelab/documentation/README.md`:
```markdown
## AI Remediation System
- **Status:** ACTIVE
- **Deployed:** 2025-11-09
- **Quick Start:** /home/t1/homelab/documentation/ai-remediation-quickstart.md
- **Full Docs:** /home/t1/homelab/documentation/ai-remediation-system.md
```

- [ ] README.md updated

### 8.2 Save Credentials to Vaultwarden

Store in https://vault.theburrow.casa:
- [ ] Alertmanager webhook password
- [ ] Anthropic API key
- [ ] Discord webhook URL
- [ ] Note: n8n URL for reference

### 8.3 Create Backup

```bash
# Backup n8n workflows
ssh outpost 'cd /opt/burrow/n8n-data && tar czf ~/n8n-workflows-backup-$(date +%Y%m%d).tar.gz workflows/'

# Backup PostgreSQL
ssh outpost 'docker exec n8n-db pg_dump -U n8n finance_db > ~/finance_db_backup_$(date +%Y%m%d).sql'
```

- [ ] n8n workflows backed up
- [ ] PostgreSQL backed up
- [ ] Backups copied to Google Drive

---

## Phase 9: Go-Live (5 minutes)

### 9.1 Enable Production Monitoring

- [ ] Verify Discord notifications working
- [ ] Check Grafana dashboard (if created)
- [ ] Verify Prometheus recording rules active

### 9.2 Announce to Team (Optional)

Post in Discord #homelab-alerts:
```
🤖 AI Remediation System is now LIVE!

- Automatic incident response enabled for common alerts
- Safe commands executed via SSH after AI analysis
- Escalation to humans after 3 failed attempts
- Full audit trail in PostgreSQL

Dashboard: https://n8n.theburrow.casa/executions
Docs: /home/t1/homelab/documentation/ai-remediation-quickstart.md

Monitoring closely for first week. 🚀
```

- [ ] Announcement posted

### 9.3 Set Calendar Reminders

- [ ] Daily: Check remediation logs (first week)
- [ ] Weekly: Review statistics and update whitelist
- [ ] Monthly: Audit logs and costs
- [ ] Quarterly: Rotate webhook password

---

## Post-Deployment Checklist (Week 1)

### Daily Checks
- [ ] Day 1: Review all executions, verify no false positives
- [ ] Day 2: Check AI analysis quality
- [ ] Day 3: Verify command safety (no unexpected executions)
- [ ] Day 4: Review costs (Anthropic API usage)
- [ ] Day 5: Check escalation workflow (if triggered)
- [ ] Day 6: Review PostgreSQL growth
- [ ] Day 7: Generate weekly report

### Success Criteria
- [ ] 0 dangerous commands executed
- [ ] >70% success rate for attempted remediations
- [ ] <5 minutes average remediation time
- [ ] Discord notifications timely and accurate
- [ ] No system instability from auto-remediation
- [ ] Costs within expected range ($5-15/month)

---

## Rollback Plan

### Emergency Disable (Immediate)

**Disable n8n workflows:**
```bash
# Access n8n UI
# Deactivate "Alert Remediation" workflow (toggle to OFF)
```

**Or remove Alertmanager receiver:**
```bash
ssh nexus
cd /home/jordan/docker/home-stack/alertmanager/config
# Restore backup
cp alertmanager.yml.backup.YYYYMMDD_HHMMSS alertmanager.yml
docker compose restart alertmanager
```

- [ ] Alert remediation disabled
- [ ] Alerts still go to Discord

### Partial Rollback (Keep Logs)

**Disable automation but keep database:**
```bash
# Deactivate n8n workflows only
# Keep PostgreSQL tables for audit trail
```

### Full Rollback

```bash
# 1. Deactivate n8n workflows
# 2. Restore Alertmanager config
ssh nexus 'cd /home/jordan/docker/home-stack/alertmanager/config && cp alertmanager.yml.backup.* alertmanager.yml && docker compose restart alertmanager'

# 3. Drop PostgreSQL tables (optional)
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "DROP TABLE IF EXISTS remediation_log, maintenance_windows, command_whitelist CASCADE;"'
```

---

## Deployment Summary

**Total Time:** ~2.5 hours
- Phase 1-2: 25 minutes (automated)
- Phase 3: 15 minutes (credentials)
- Phase 4: 45 minutes (workflow build)
- Phase 5-6: 50 minutes (testing)
- Phase 7-9: 30 minutes (monitoring, docs, go-live)

**Key Success Metrics:**
- System deployed without errors
- All tests passing
- At least 1 successful real alert remediation
- No false positives or dangerous commands
- Team understands how to monitor and maintain

**Next Steps After Deployment:**
1. Monitor closely for first week
2. Tune AI prompts based on actual performance
3. Add more alert types as confidence grows
4. Build Grafana dashboard for visibility
5. Expand to more systems (Skynet, Wall Tablet)

---

**Deployment Date:** _________
**Deployed By:** _________
**Sign-off:** _________

**Status:** □ Not Started | □ In Progress | □ Complete | □ Rolled Back
