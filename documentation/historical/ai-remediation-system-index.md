# AI Remediation System - Complete File Index

## Quick Navigation

### Start Here
- **Quick Start Guide:** `/home/t1/homelab/documentation/ai-remediation-quickstart.md`
- **Deployment Checklist:** `/home/t1/homelab/documentation/ai-remediation-deployment-checklist.md`
- **Setup Script:** `/home/t1/homelab/scripts/ai-remediation/setup_ai_remediation.sh`

### Documentation Files

| Document | Location | Purpose | Pages |
|----------|----------|---------|-------|
| **Complete Technical Documentation** | `/home/t1/homelab/documentation/ai-remediation-system.md` | Full system design, architecture, workflows, troubleshooting | ~50 |
| **Quick Start Guide** | `/home/t1/homelab/documentation/ai-remediation-quickstart.md` | 30-minute setup guide with FAQ | ~15 |
| **Deployment Checklist** | `/home/t1/homelab/documentation/ai-remediation-deployment-checklist.md` | Phase-by-phase deployment steps with verification | ~20 |
| **This Index** | `/home/t1/homelab/documentation/ai-remediation-system-index.md` | File locations and navigation | 3 |

### Configuration Files

| File | Location | Purpose | Format |
|------|----------|---------|--------|
| **PostgreSQL Schema** | `/home/t1/homelab/configs/postgres/ai-remediation-schema.sql` | Database tables, functions, seed data | SQL |
| **Alertmanager Config** | `/home/t1/homelab/configs/docker/alertmanager/alertmanager-ai-remediation.yml` | Updated routing with n8n receiver | YAML |
| **n8n Workflow Guide** | `/home/t1/homelab/configs/n8n-workflows/README.md` | Node-by-node workflow build instructions | Markdown |

### Scripts

| Script | Location | Purpose | Usage |
|--------|----------|---------|-------|
| **Setup Script** | `/home/t1/homelab/scripts/ai-remediation/setup_ai_remediation.sh` | Automated deployment (PostgreSQL + Alertmanager) | `./setup_ai_remediation.sh` |
| **Test Suite** | `/home/t1/homelab/scripts/ai-remediation/test_ai_remediation.sh` | Interactive testing (9 test scenarios) | `./test_ai_remediation.sh` |
| **Scripts README** | `/home/t1/homelab/scripts/ai-remediation/README.md` | Script documentation and troubleshooting | - |

## System Components

### 1. PostgreSQL Database (Outpost)
- **Container:** `n8n-db`
- **Database:** `finance_db`
- **Tables:**
  - `remediation_log` - Audit trail of all remediation attempts
  - `maintenance_windows` - Scheduled maintenance periods
  - `command_whitelist` - Safe command patterns
- **Views:**
  - `v_recent_failures` - Last 7 days of failed attempts
  - `v_active_escalations` - Alerts awaiting user decision
  - `v_maintenance_status` - Current/upcoming maintenance
- **Functions:**
  - `get_attempt_count(alert_name, instance)` - Count attempts in 24hrs
  - `is_maintenance_active()` - Check if in maintenance window
  - `get_next_attempt_number(alert_name, instance)` - Sequential attempt #

**Schema File:** `/home/t1/homelab/configs/postgres/ai-remediation-schema.sql`

**Deploy:**
```bash
./setup_ai_remediation.sh
# Or manually:
ssh outpost 'docker cp /path/to/schema.sql n8n-db:/tmp/ && docker exec n8n-db psql -U n8n -d finance_db -f /tmp/schema.sql'
```

### 2. n8n Workflows (Outpost)
- **Instance:** https://n8n.theburrow.casa
- **Workflow 1:** Alert Remediation (17 nodes)
  - Webhook trigger: `/webhook/alert-remediation`
  - Core remediation engine
- **Workflow 2:** Escalation (5-7 nodes)
  - Webhook/Execute trigger
  - Human approval workflow
- **Workflow 3:** Maintenance Toggle (3 nodes)
  - Webhook trigger: `/webhook/maintenance-toggle`
  - Enable/disable automation

**Build Guide:** `/home/t1/homelab/configs/n8n-workflows/README.md`

**Credentials Needed:**
- `ssh_nexus`, `ssh_homeassistant`, `ssh_outpost`
- `postgres_finance_db`
- `discord_homelab_alerts`
- `anthropic_claude`

### 3. Alertmanager (Nexus)
- **Location:** `/home/jordan/docker/home-stack/alertmanager/`
- **Config:** `config/alertmanager.yml`
- **Receivers:**
  - `discord-homelab` - Discord notifications
  - `n8n-remediation` - Webhook to n8n
- **Authentication:** Basic auth (alertmanager / webhook_password)

**Config File:** `/home/t1/homelab/configs/docker/alertmanager/alertmanager-ai-remediation.yml`

**Deploy:**
```bash
./setup_ai_remediation.sh
# Or manually:
scp alertmanager-ai-remediation.yml nexus:/home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml
ssh nexus 'cd /home/jordan/docker/home-stack && docker compose restart alertmanager'
```

### 4. Claude AI Integration
- **API:** Anthropic Claude API (https://api.anthropic.com/v1/messages)
- **Model:** claude-sonnet-4-5-20250929
- **Usage:** ~2,000-4,000 tokens per alert
- **Cost:** ~$0.02-0.04 per remediation
- **Estimated Monthly:** $5-15 (10-30 alerts/month)

**Prompt Templates:** See `/home/t1/homelab/documentation/ai-remediation-system.md` section "AI Prompt Templates"

### 5. Discord Integration
- **Channel:** #homelab-alerts
- **Webhook:** Configured in n8n credentials
- **Message Types:**
  - Success: "✅ Alert Auto-Remediated"
  - Failure: "⚠️ Auto-remediation failed (attempt X/3)"
  - Escalation: "🚨 Alert Escalation Required"

## Workflow Execution Flow

### Standard Remediation (Success)
```
1. Prometheus detects issue
2. Alertmanager fires webhook → n8n
3. n8n Workflow 1:
   a. Parse alert JSON
   b. Check maintenance mode (skip if active)
   c. Query attempt count (must be < 3)
   d. SSH to system, gather logs
   e. Send to Claude AI with context
   f. AI returns: analysis + commands + risk
   g. Validate commands (whitelist/blacklist)
   h. If safe: Execute via SSH
   i. Log to PostgreSQL
   j. Post result to Discord
4. Service restored, alert resolves
```

**Time:** 15-45 seconds

### Escalation Flow (After 3 Failures)
```
1. Attempt #3 fails
2. n8n Workflow 2 triggered:
   a. Fetch last 3 attempts from database
   b. Send to Claude for summary
   c. Post to Discord with:
      - What failed (summary)
      - AI's suggested next action
      - Interactive buttons (if using Discord Bot)
3. User reviews and decides:
   - Approve → Execute suggestion
   - Manual → Stop auto-remediation
   - Disable 1hr → Set maintenance window
```

## Testing Procedures

### Quick Test (5 minutes)
```bash
cd /home/t1/homelab/scripts/ai-remediation
./test_ai_remediation.sh all
```

Runs:
1. Webhook connectivity
2. PostgreSQL schema verification
3. Command validation
4. Simulated alert
5. Maintenance mode
6. Statistics view

### Individual Tests
```bash
./test_ai_remediation.sh webhook      # Test webhook endpoint
./test_ai_remediation.sh postgres     # Verify database
./test_ai_remediation.sh wireguard    # Simulated VPN alert
./test_ai_remediation.sh maintenance  # Test maintenance mode
./test_ai_remediation.sh validation   # Command whitelist test
./test_ai_remediation.sh stats        # View metrics
./test_ai_remediation.sh cleanup      # Remove test data
```

### Real Alert Test (Use Caution)
```bash
# Temporarily stop AdGuard (affects DNS)
./test_ai_remediation.sh adguard

# Or safer: use temporary test container
ssh nexus 'docker run -d --name test-ai nginx'
ssh nexus 'docker stop test-ai'
# Wait for alert, verify auto-restart
```

## Monitoring Commands

### Check Recent Activity
```bash
# Last 10 remediations
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT timestamp, alert_name, attempt_number, success, execution_duration_seconds FROM remediation_log ORDER BY timestamp DESC LIMIT 10;"'

# Success rate (last 24 hours)
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT COUNT(*) as total, SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful, ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1) as pct FROM remediation_log WHERE timestamp > NOW() - INTERVAL '\''24 hours'\'';"'

# Active escalations
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM v_active_escalations;"'

# Maintenance status
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM v_maintenance_status;"'
```

### n8n Executions
- **URL:** https://n8n.theburrow.casa/executions
- **Filter:** "Alert Remediation" workflow
- **View:** Click execution → See each node's output

### Discord
- **Channel:** #homelab-alerts
- **Filter:** Messages from webhook (AI remediation notifications)

### Prometheus/Alertmanager
```bash
# View active alerts
curl http://192.168.0.11:9090/api/v1/alerts | jq

# Alertmanager status
ssh nexus 'docker logs alertmanager --tail 50'
```

## Troubleshooting Guide

### Issue: Workflow Not Triggering

**Symptoms:** Alert fires but n8n execution doesn't appear

**Check:**
```bash
# 1. Verify Alertmanager sending webhooks
ssh nexus 'docker logs alertmanager --tail 50 | grep n8n'

# 2. Test webhook manually
curl -X POST https://n8n.theburrow.casa/webhook/alert-remediation \
  -u "alertmanager:PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"alerts": [{"status": "firing", "labels": {"alertname": "Test"}}]}'

# 3. Check n8n workflow active
# Open n8n UI → Check workflow toggle is ON
```

**Solution:** See troubleshooting section in quick-start guide

### Issue: Commands Not Executing

**Symptoms:** Workflow runs but SSH commands fail

**Check:**
```bash
# 1. Test SSH from Outpost
ssh outpost
ssh -i /path/to/key jordan@192.168.0.11 'whoami'

# 2. Check n8n credentials
# n8n UI → Settings → Credentials → Test each SSH credential

# 3. View execution logs
# n8n UI → Executions → Click failed execution → Check SSH node output
```

### Issue: AI Not Responding

**Symptoms:** Claude API requests fail

**Check:**
```bash
# 1. Test API key
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model": "claude-sonnet-4-5-20250929", "max_tokens": 50, "messages": [{"role": "user", "content": "test"}]}'

# 2. Check API quota
# Visit https://console.anthropic.com/ → Usage

# 3. Review prompt length
# Prompts >200K tokens may fail
```

## Maintenance Tasks

### Daily (First Week)
- [ ] Review n8n executions
- [ ] Check PostgreSQL logs
- [ ] Verify no unexpected commands executed
- [ ] Monitor Discord notifications

### Weekly
```bash
# Generate weekly report
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db' << 'EOF'
SELECT
    alert_name,
    COUNT(*) as attempts,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    ROUND(AVG(execution_duration_seconds)) as avg_duration_sec
FROM remediation_log
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY alert_name
ORDER BY attempts DESC;
EOF

# Review escalations
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM v_recent_failures LIMIT 10;"'

# Check command whitelist usage
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT pattern, match_count, last_matched_at FROM command_whitelist WHERE match_count > 0 ORDER BY match_count DESC;"'
```

### Monthly
- [ ] Review AI API costs
- [ ] Audit command whitelist
- [ ] Check PostgreSQL disk usage
- [ ] Update AI prompts if needed
- [ ] Review and remove stale data (>90 days)

### Quarterly
- [ ] Rotate webhook password
- [ ] Review system architecture
- [ ] Update documentation
- [ ] Disaster recovery drill

## File Permissions

All scripts are executable:
```bash
chmod +x /home/t1/homelab/scripts/ai-remediation/*.sh
```

Configuration files are read-only:
```bash
chmod 644 /home/t1/homelab/configs/postgres/*.sql
chmod 644 /home/t1/homelab/configs/docker/alertmanager/*.yml
```

## Backup Locations

**Git Repository:**
- All documentation in `/home/t1/homelab/documentation/`
- All configs in `/home/t1/homelab/configs/`
- All scripts in `/home/t1/homelab/scripts/`
- Committed to: https://github.com/YOUR_REPO (via Skynet daily backup)

**PostgreSQL:**
- Included in Outpost daily backup: `/opt/burrow/backups/`
- Retention: 7 days local, 30 days Google Drive

**n8n Workflows:**
- Stored in: `/opt/burrow/n8n-data/workflows/`
- Included in Outpost daily backup

## Security Notes

**Credentials Storage:**
- Webhook password: Vaultwarden + Nexus .env
- API keys: n8n credentials (encrypted)
- SSH keys: `/home/t1/.ssh/keys/homelab_ed25519`
- PostgreSQL passwords: `/opt/burrow/.env` (Outpost)

**Command Safety:**
- All commands validated against whitelist regex
- Dangerous patterns blacklisted (rm -rf, reboot, etc.)
- Max 3 auto-attempts per alert
- Full audit trail in database
- Human approval required for high-risk operations

**Network Security:**
- Webhook uses HTTPS + basic auth
- n8n credentials encrypted at rest
- SSH key-based authentication only
- PostgreSQL on internal Docker network

## Support & Resources

**Internal Documentation:**
- Full system design: `/home/t1/homelab/documentation/ai-remediation-system.md`
- Quick start: `/home/t1/homelab/documentation/ai-remediation-quickstart.md`
- Deployment checklist: `/home/t1/homelab/documentation/ai-remediation-deployment-checklist.md`

**External Resources:**
- n8n Documentation: https://docs.n8n.io/
- Anthropic API: https://docs.anthropic.com/
- Prometheus Alerting: https://prometheus.io/docs/alerting/
- PostgreSQL: https://www.postgresql.org/docs/

**Contact:**
- Owner: Jordan Hoelscher (hoelscher.jordan@gmail.com)
- Repository: /home/t1/homelab/ on Skynet (192.168.0.13)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-09
**Status:** Production Ready
**Total Files:** 11 (4 docs, 3 configs, 3 scripts, 1 index)
**Total Lines of Code:** ~3,500+ (SQL + Bash + Markdown)
