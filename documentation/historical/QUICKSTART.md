# AI Remediation Service - Quick Start

Get the service running in 15 minutes.

## Prerequisites

```bash
# 1. Claude API key
export ANTHROPIC_API_KEY="sk-ant-YOUR-KEY"

# 2. Discord webhook URL
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/YOUR_WEBHOOK"

# 3. Database password (get from Outpost)
ssh outpost 'grep POSTGRES_PASSWORD /opt/burrow/.env'
export DB_PASSWORD="the_password_here"

# 4. Generate webhook password
export WEBHOOK_PASSWORD=$(openssl rand -base64 32)
echo "Save this: $WEBHOOK_PASSWORD"
```

## Deploy

```bash
# 1. Copy to Outpost
cd /home/t1/homelab/projects/ai-remediation-service
tar czf /tmp/ai-remediation.tar.gz .
scp /tmp/ai-remediation.tar.gz outpost:/tmp/

# 2. Extract and configure
ssh outpost 'cd /opt/burrow && mkdir -p ai-remediation && cd ai-remediation && tar xzf /tmp/ai-remediation.tar.gz'

# 3. Create .env
ssh outpost 'cat > /opt/burrow/ai-remediation/.env << EOF
DATABASE_URL=postgresql://n8n:'"$DB_PASSWORD"'@n8n-db:5432/finance_db
ANTHROPIC_API_KEY='"$ANTHROPIC_API_KEY"'
DISCORD_WEBHOOK_URL='"$DISCORD_WEBHOOK_URL"'
SSH_KEY_PATH=/root/.ssh/homelab_ed25519
WEBHOOK_AUTH_USERNAME=alertmanager
WEBHOOK_AUTH_PASSWORD='"$WEBHOOK_PASSWORD"'
LOG_LEVEL=INFO
LOG_FORMAT=json
EOF'

# 4. Ensure SSH key exists
scp /home/t1/.ssh/keys/homelab_ed25519 outpost:/root/.ssh/
ssh outpost 'chmod 600 /root/.ssh/homelab_ed25519'

# 5. Deploy
ssh outpost 'cd /opt/burrow/ai-remediation && docker-compose build && docker-compose up -d'

# 6. Check health
ssh outpost 'curl -s http://localhost:8000/health | jq'
```

## Configure Alertmanager

```bash
# 1. Backup current config
ssh nexus 'cp /home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml{,.backup}'

# 2. Edit config
ssh nexus 'nano /home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml'

# Add this receiver:
```

```yaml
receivers:
  - name: 'ai-remediation'
    webhook_configs:
      - url: 'http://ai-remediation:8000/webhook/alertmanager'
        send_resolved: false
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'YOUR_WEBHOOK_PASSWORD'  # From step above
```

Note: If ai-remediation container is not on same Docker network, use VPN IP or public URL.

```bash
# 3. Reload Alertmanager
ssh nexus 'docker exec alertmanager kill -HUP 1'
```

## Test

```bash
# 1. Test webhook
ssh outpost 'cd /opt/burrow/ai-remediation && PASSWORD='"$WEBHOOK_PASSWORD"' ./test_alert.sh'

# 2. Check logs
ssh outpost 'docker logs ai-remediation --tail 50'

# 3. Check Discord
# Should see test alert notifications

# 4. Check database
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT COUNT(*) FROM remediation_log;"'
```

## Common Issues

### Can't connect to database

```bash
# Check n8n-db is running
ssh outpost 'docker ps | grep n8n-db'

# Test connection
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT 1;"'

# Verify network
ssh outpost 'docker network inspect burrow_default | grep ai-remediation'
```

### SSH commands fail

```bash
# Test SSH manually
ssh outpost 'ssh -i /root/.ssh/homelab_ed25519 jordan@192.168.0.11 "echo test"'

# Check key permissions
ssh outpost 'ls -la /root/.ssh/homelab_ed25519'
# Should be -rw------- (600)
```

### Alertmanager can't reach service

```bash
# Check if on same network
ssh nexus 'docker network ls'
ssh outpost 'docker network ls'

# If different hosts, use VPN or public URL
# Option 1: VPN (Outpost is on 10.99.0.2)
# In alertmanager.yml:
#   url: 'http://10.99.0.2:8000/webhook/alertmanager'

# Option 2: Public URL via Caddy
# Set up reverse proxy on Outpost, then use:
#   url: 'https://alerts.theburrow.casa/webhook/alertmanager'
```

## Quick Commands

```bash
# View logs
ssh outpost 'docker logs -f ai-remediation'

# Restart service
ssh outpost 'cd /opt/burrow/ai-remediation && docker-compose restart'

# View recent attempts
ssh outpost 'docker exec n8n-db psql -U n8n -d finance_db -c "SELECT timestamp, alert_name, success FROM remediation_log ORDER BY timestamp DESC LIMIT 10;"'

# Check statistics
ssh outpost 'curl -s http://localhost:8000/statistics?days=7 | jq'

# Enable maintenance mode (disable auto-remediation for 1 hour)
curl -X POST http://outpost:8000/maintenance/enable \
  -u "alertmanager:$WEBHOOK_PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"end_time":"'$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)'","reason":"Planned maintenance","created_by":"admin"}'
```

## Success Checklist

- [ ] Service health check returns "healthy"
- [ ] Test alert processes successfully
- [ ] Discord notification received
- [ ] Database log created
- [ ] Alertmanager sends webhooks (check logs)
- [ ] Real alert triggers remediation

## Next Steps

1. Monitor Discord #homelab-alerts for notifications
2. Review database logs weekly: `SELECT * FROM remediation_log WHERE timestamp > NOW() - INTERVAL '7 days'`
3. Check success rate: `curl http://localhost:8000/statistics?days=7 | jq .statistics.success_rate`
4. Add Grafana dashboard for metrics visualization
5. Fine-tune command whitelist based on your alert patterns

## Documentation

- **Full README**: ./README.md (architecture, API reference, troubleshooting)
- **Deployment Guide**: ./DEPLOYMENT.md (detailed step-by-step)
- **Test Script**: ./test_alert.sh (automated testing)

## Support

Questions? Check:
1. Container logs: `docker logs ai-remediation`
2. Database logs: `SELECT * FROM remediation_log ORDER BY timestamp DESC LIMIT 5`
3. README troubleshooting section
4. Discord #homelab-alerts for live issues
