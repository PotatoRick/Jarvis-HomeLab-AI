# AI Remediation System - Quick Start Guide

## 5-Minute Overview

The AI Remediation System automatically receives Prometheus/Alertmanager alerts, uses Claude AI to analyze root causes, and executes safe SSH commands to fix issues. After 3 failed attempts, it escalates to you via Discord.

**Architecture:** Alertmanager → n8n → Claude AI → SSH to systems → PostgreSQL logging → Discord notifications

**Status:** Ready to deploy to The Burrow homelab

## What You Get

- **Automatic incident response** for common homelab issues
- **AI-powered root cause analysis** via Claude Sonnet 4.5
- **Safe command execution** with comprehensive whitelist validation
- **Escalation workflow** when automation fails
- **Full audit trail** in PostgreSQL
- **Discord notifications** for all actions
- **Maintenance mode** to disable automation when needed

## Files Created

All files are ready in `/home/t1/homelab/`:

```
homelab/
├── documentation/
│   ├── ai-remediation-system.md           # Complete technical documentation
│   └── ai-remediation-quickstart.md       # This file
├── configs/
│   ├── postgres/
│   │   └── ai-remediation-schema.sql      # Database schema (3 tables, functions)
│   ├── n8n-workflows/
│   │   └── README.md                      # Workflow build guide with node configs
│   └── docker/
│       └── alertmanager/
│           └── alertmanager-ai-remediation.yml  # Updated Alertmanager config
└── scripts/
    └── ai-remediation/
        ├── setup_ai_remediation.sh        # Automated setup script
        └── test_ai_remediation.sh         # Comprehensive test suite
```

## Installation (30 minutes)

### Step 1: Run Setup Script (5 min)

```bash
cd /home/t1/homelab/scripts/ai-remediation
./setup_ai_remediation.sh
```

This will:
1. Deploy PostgreSQL schema to Outpost
2. Generate secure webhook password
3. Update Alertmanager configuration on Nexus
4. Restart Alertmanager

**Save the webhook password** displayed at the end - you'll need it for n8n.

### Step 2: Configure n8n Credentials (10 min)

Navigate to https://n8n.theburrow.casa → Settings → Credentials

Add these credentials:

**SSH Connections (3 credentials):**
- Name: `ssh_nexus`
  - Type: SSH
  - Host: `192.168.0.11`
  - Port: `22`
  - Username: `jordan`
  - Private Key: Paste contents of `/home/t1/.ssh/keys/homelab_ed25519`

- Name: `ssh_homeassistant`
  - Type: SSH
  - Host: `192.168.0.10`
  - Port: `22`
  - Username: `root`
  - Private Key: Same as above

- Name: `ssh_outpost`
  - Type: SSH
  - Host: `localhost`
  - Port: `22`
  - Username: `root`
  - Private Key: Same as above

**PostgreSQL:**
- Name: `postgres_finance_db`
  - Type: PostgreSQL
  - Host: `n8n-db`
  - Port: `5432`
  - Database: `finance_db`
  - User: `n8n`
  - Password: From `/opt/burrow/.env` on Outpost (N8N_DB_PASSWORD)
  - SSL: Disabled

**Discord:**
- Name: `discord_homelab_alerts`
  - Type: Discord Webhook
  - Webhook URL: From Discord Server Settings → Integrations → Webhooks → #homelab-alerts

**Anthropic Claude:**
- Name: `anthropic_claude`
  - Type: HTTP Request (Generic Credential)
  - Authentication: Header Auth
  - Header Name: `x-api-key`
  - Header Value: Your API key from https://console.anthropic.com/

**Test each credential** before saving (use the "Test" button).

### Step 3: Build n8n Workflows (15 min)

Open the workflow guide:
```bash
cat /home/t1/homelab/configs/n8n-workflows/README.md
```

Follow the detailed node-by-node configuration for:
1. **Workflow 1:** Alert Remediation (17 nodes)
2. **Workflow 2:** Escalation (5-7 nodes)
3. **Workflow 3:** Maintenance Mode (3 nodes)

Each node configuration is provided in the README with exact settings.

**Tip:** Build Workflow 1 first and test before building 2 and 3.

### Step 4: Test the System

Run the automated test suite:
```bash
cd /home/t1/homelab/scripts/ai-remediation
./test_ai_remediation.sh
```

Interactive menu lets you run:
1. Webhook connectivity test
2. PostgreSQL schema verification
3. Simulated WireGuard alert
4. Maintenance mode toggle
5. Real alert with AdGuard (optional, requires caution)
6. Command validation logic
7. View statistics
8. Cleanup test data
9. Run all tests (except #5)

**Start with option 9** to run all safe tests.

## How It Works

### Normal Flow (Alert Resolved Automatically)

```
1. Prometheus detects issue (e.g., container down)
2. Alertmanager fires webhook to n8n
3. n8n receives alert, checks maintenance mode
4. Queries PostgreSQL: "How many attempts for this alert in last 24hrs?"
5. If < 3 attempts:
   a. SSH to affected system, gather logs
   b. Send to Claude AI with alert context
   c. Claude returns: root cause + remediation commands + risk level
   d. Validate commands against whitelist
   e. If safe: Execute via SSH
   f. Log results to PostgreSQL
   g. Post success/failure to Discord
6. If successful, alert resolves - DONE
7. If failed and < 3 attempts, wait for next alert firing (Prometheus re-evaluates)
```

**Total time:** 15-45 seconds from alert to fix

### Escalation Flow (After 3 Failed Attempts)

```
1. n8n detects 3rd failed attempt
2. Queries last 3 attempts from PostgreSQL
3. Sends summary to Claude AI
4. Posts to Discord:
   - Summary of what failed
   - AI's suggested next action
   - Buttons: [Approve] [Show Logs] [Disable 1hr] [Manual]
5. User clicks button:
   - Approve → Executes AI's suggestion, logs result
   - Show Logs → Displays full error logs from database
   - Disable 1hr → Sets maintenance window
   - Manual → Marks as escalated, stops auto-remediation
```

## Common Alerts Handled

| Alert | Typical Cause | Auto-Remediation |
|-------|---------------|------------------|
| WireGuardVPNDown | Service crashed | `systemctl restart wg-quick@wg0` |
| ContainerUnhealthy | App crash | `docker restart <container>` |
| PostgreSQLDown | Database crash | `docker restart n8n-db` |
| HighMemoryUsage (container) | Memory leak | `docker restart <container>` |
| AdGuardDown | DNS server crash | `docker restart adguard` (CRITICAL) |
| ContainerRestartingFrequently | Boot loop | Escalates (no restart) |

## Safety Features

### Command Whitelist (Automated Approval)
- `systemctl restart <service>`
- `docker restart <container>`
- `ha core restart`
- `docker system prune -f`
- Read-only commands (logs, status)

### Command Blacklist (Requires Approval)
- Any `rm -rf` commands
- System reboots/shutdowns
- Firewall changes (ufw, iptables)
- Configuration file edits (sed -i, echo >)
- Data deletion (docker volume rm)

### Additional Protections
- Max 3 auto-attempts per alert per 24 hours
- 60-second timeout per SSH execution
- Risk assessment by AI (low/medium/high)
- Full audit trail in PostgreSQL
- Maintenance mode to disable automation

## Monitoring

### View Recent Activity

**PostgreSQL:**
```bash
ssh outpost 'docker exec -it n8n-db psql -U n8n -d finance_db -c "SELECT timestamp, alert_name, attempt_number, success, execution_duration_seconds FROM remediation_log ORDER BY timestamp DESC LIMIT 10;"'
```

**n8n Executions:**
https://n8n.theburrow.casa/executions

**Discord:**
Check #homelab-alerts channel for real-time notifications

**Grafana Dashboard:**
Import queries from `/home/t1/homelab/documentation/ai-remediation-system.md` section "Monitoring Dashboard"

### Check System Health

```bash
# Maintenance windows
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM v_maintenance_status;"'

# Active escalations
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM v_active_escalations;"'

# Success rate (last 7 days)
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
        ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate_pct
    FROM remediation_log
    WHERE timestamp > NOW() - INTERVAL '\''7 days'\'';"'
```

## Daily Operations

### Enable Maintenance Mode (Before System Work)

```bash
curl -X POST https://n8n.theburrow.casa/webhook/maintenance-toggle \
  -H "Content-Type: application/json" \
  -d '{
    "duration_minutes": 60,
    "reason": "Planned maintenance",
    "created_by": "jordan"
  }'
```

Or use the test script:
```bash
./test_ai_remediation.sh maintenance
```

### Review Overnight Activity

```bash
# Check what auto-fixed overnight
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "
    SELECT
        alert_name,
        COUNT(*) as attempts,
        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful
    FROM remediation_log
    WHERE timestamp > NOW() - INTERVAL '\''24 hours'\''
    GROUP BY alert_name
    ORDER BY attempts DESC;"'
```

### Update Command Whitelist

```bash
# Add new safe pattern
ssh outpost 'docker exec -it n8n-db psql -U n8n -d finance_db'

INSERT INTO command_whitelist (pattern, description, risk_level)
VALUES ('^your-regex-pattern$', 'Description', 'low');
```

## Troubleshooting

### Workflow Not Triggering

**Check Alertmanager:**
```bash
ssh nexus 'docker logs alertmanager --tail 50'
# Look for "Notify success" or "Notify failure"
```

**Test Webhook Manually:**
```bash
./test_ai_remediation.sh webhook
```

**Verify n8n Workflow Active:**
Check in n8n UI that workflow status is "Active" (toggle in top-right)

### Commands Not Executing

**Check SSH Credentials:**
```bash
# Test from Outpost
ssh outpost
ssh -i /home/t1/.ssh/keys/homelab_ed25519 jordan@192.168.0.11 'whoami'
```

**Check n8n Execution Logs:**
Go to n8n → Executions → Click failed execution → View each node output

**Verify Command in Whitelist:**
```bash
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM command_whitelist WHERE '\''your-command'\'' ~ pattern;"'
```

### AI API Errors

**Check API Key:**
Test manually:
```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model": "claude-sonnet-4-5-20250929", "max_tokens": 100, "messages": [{"role": "user", "content": "test"}]}'
```

**Check n8n Credential:**
Settings → Credentials → anthropic_claude → Test

**Check API Quota:**
https://console.anthropic.com/ → Usage

## Cost Estimation

**Claude API Usage:**
- Per alert: ~2,000-4,000 tokens input, 500-1,000 tokens output
- Cost: ~$0.02-0.04 per alert remediation
- Estimated monthly: $5-15 (assuming 10-30 alerts/month)

**Storage:**
- PostgreSQL: ~1-2 KB per log entry
- 90-day retention: ~10-20 MB total

**n8n Execution:**
- Included in self-hosted deployment (no additional cost)

## Security Best Practices

1. **Rotate webhook password quarterly**
   - Generate new: `openssl rand -base64 32`
   - Update in Alertmanager .env and n8n webhook
   - Restart Alertmanager

2. **Review audit logs weekly**
   ```bash
   ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT * FROM remediation_log WHERE timestamp > NOW() - INTERVAL '\''7 days'\'' ORDER BY timestamp DESC;"'
   ```

3. **Keep command whitelist minimal**
   - Only add patterns you trust
   - Document each pattern's purpose
   - Review quarterly

4. **Monitor escalations**
   - Review why automation failed
   - Update AI prompts if needed
   - Add new patterns if safe

5. **Backup PostgreSQL database**
   - Already included in Outpost daily backups
   - Verify: `/opt/burrow/backups/backup_outpost.sh`

## Advanced Configuration

### Customize AI Prompts

Edit the "Build AI Prompt" node in n8n Workflow 1 to:
- Add homelab-specific context
- Include documentation links
- Adjust risk thresholds
- Change command suggestions

### Add New Alert Types

1. Create Prometheus alert rule
2. Configure Alertmanager routing (optional)
3. Test with simulated alert
4. Review AI's suggested remediation
5. Add to command whitelist if needed

### Integrate with PagerDuty/Slack

Add new receiver in Alertmanager config for critical escalations:
```yaml
- name: 'pagerduty-critical'
  pagerduty_configs:
    - service_key: 'YOUR_KEY'
```

### Create Grafana Dashboard

Use queries from `/home/t1/homelab/documentation/ai-remediation-system.md` section "Monitoring Dashboard"

Panels to include:
- Success rate over time
- Most common alerts
- Average remediation time
- Escalation trends
- Recent activity table

## Next Steps After Installation

1. **Week 1:** Monitor closely, let it handle low-risk alerts
2. **Week 2:** Review logs, tune command whitelist
3. **Week 3:** Add more alert types as you gain confidence
4. **Month 1:** Review costs, success rate, adjust AI prompts

## Support Resources

- **Complete Documentation:** `/home/t1/homelab/documentation/ai-remediation-system.md`
- **Workflow Build Guide:** `/home/t1/homelab/configs/n8n-workflows/README.md`
- **Test Suite:** `/home/t1/homelab/scripts/ai-remediation/test_ai_remediation.sh`
- **Setup Script:** `/home/t1/homelab/scripts/ai-remediation/setup_ai_remediation.sh`

- **n8n Docs:** https://docs.n8n.io/
- **Anthropic API:** https://docs.anthropic.com/
- **Prometheus Alerting:** https://prometheus.io/docs/alerting/

## FAQ

**Q: What if AI suggests a dangerous command?**
A: Command validation rejects it and escalates to you via Discord. No dangerous commands execute automatically.

**Q: Can I disable auto-remediation temporarily?**
A: Yes, enable maintenance mode for any duration. Use test script or webhook.

**Q: What's the max cost per month?**
A: Estimated $5-15 for Claude API with typical homelab alert volume (10-30 alerts/month).

**Q: What happens if n8n is down?**
A: Alerts still go to Discord (separate receiver). Auto-remediation pauses until n8n returns.

**Q: Can I approve commands manually before execution?**
A: Not in current design, but you can modify Workflow 1 to always escalate (set risk=high in AI prompt).

**Q: How do I add a new safe command?**
A: Add regex pattern to command_whitelist table, or update the validation function in n8n.

**Q: What if SSH fails?**
A: Logged as failed attempt, retries on next alert firing (up to 3 times), then escalates.

**Q: Can multiple alerts remediate simultaneously?**
A: n8n workflows run concurrently by default. Set concurrency limit in workflow settings if needed.

---

**Status:** Production Ready
**Version:** 1.0
**Last Updated:** 2025-11-09
**Estimated Setup Time:** 30 minutes
**Maintenance:** ~15 min/week

**Ready to deploy!** Start with `./setup_ai_remediation.sh`
