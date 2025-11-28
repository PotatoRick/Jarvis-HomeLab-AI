# AI Remediation Service - Skynet Migration Complete

**Date:** November 11, 2025
**Migration:** Outpost (72.60.163.242) → Skynet (192.168.0.13)
**Status:** ✅ Complete and Verified

---

## Executive Summary

The AI Remediation Service has been successfully migrated from Outpost VPS to Skynet (Raspberry Pi 5) and is now fully operational. All configuration references have been updated, old files removed, and the service is receiving alerts from Prometheus Alertmanager.

---

## Current Configuration

### Service Location
- **Host:** Skynet (192.168.0.13)
- **Container:** ai-remediation
- **Port:** 8000
- **Endpoint:** http://192.168.0.13:8000/webhook/alertmanager
- **Status:** Running (healthy)

### Database Configuration
- **Database:** PostgreSQL on Outpost (72.60.163.242:5432)
- **Database Name:** finance_db
- **Connection:** Via public IP (Skynet → Outpost port 5432)
- **Tables:** command_whitelist, maintenance_windows, remediation_log

### SSH Access
The service has SSH key authentication to:
- **Nexus:** jordan@192.168.0.11
- **Home Assistant:** root@192.168.0.10
- **Outpost:** root@72.60.163.242
- **SSH Key:** `/home/t1/.ssh/keys/homelab_ed25519` (mounted as `/app/ssh_key`)

---

## Configuration Files Verified

### 1. Alertmanager (Nexus)
**File:** `/home/jordan/docker/home-stack/alertmanager/alertmanager.yml`

```yaml
receivers:
  - name: 'ai-remediation'
    webhook_configs:
      - url: 'http://192.168.0.13:8000/webhook/alertmanager'
        send_resolved: true
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'O28nsEX3clSJvpNvBLjKfM4Tk92KqLhy4OqPH1OLPf0='
```

✅ **Correct:** Points to Skynet IP (192.168.0.13:8000)

### 2. Docker Compose (Skynet)
**File:** `/home/t1/homelab/projects/ai-remediation-service/docker-compose.yml`

**Key Changes from Outpost Version:**
- ❌ Removed: `networks: burrow_web` (doesn't exist on Skynet)
- ✅ Updated: DATABASE_URL uses Outpost public IP (72.60.163.242:5432)
- ✅ Updated: SSH key correctly mounted as file (not directory)
- ✅ Uses: Default bridge network (sufficient for standalone service)

### 3. Environment File
**File:** `/home/t1/homelab/projects/ai-remediation-service/.env`

```env
DATABASE_URL=postgresql://n8n:password@72.60.163.242:5432/finance_db
ANTHROPIC_API_KEY=sk-ant-api03-...
CLAUDE_MODEL=claude-sonnet-4-5-20250929

SSH_NEXUS_HOST=192.168.0.11
SSH_NEXUS_USER=jordan

SSH_HOMEASSISTANT_HOST=192.168.0.10
SSH_HOMEASSISTANT_USER=root

SSH_OUTPOST_HOST=72.60.163.242
SSH_OUTPOST_USER=root
```

✅ **All IPs and hostnames correct for Skynet operation**

### 4. System Prompt Context
**File:** `/home/t1/homelab/projects/ai-remediation-service/app/main.py:239-255`

```python
system_context = f"""
# Homelab System: {target_host.value.upper()}
# Alert Type: {alert_name}
# Service: {service_name or 'unknown'} ({service_type})
# Instance: {alert_instance}

This is part of The Burrow homelab infrastructure. Systems available:
- nexus (192.168.0.11): Docker host with most services
- homeassistant (192.168.0.10): Home automation hub
- outpost (VPS): Cloud gateway with n8n, RustDesk

Common issues and fixes:
- Container crashes: docker restart <container>
- Systemd service down: systemctl restart <service>
- WireGuard VPN down: systemctl restart wg-quick@wg0
- Home Assistant unresponsive: ha core restart
"""
```

✅ **Infrastructure context accurate** - Correctly describes all three target systems

---

## Claude Agent Tools

The AI agent has access to these tools for remediation:

1. **gather_logs**
   - Gather recent logs from docker containers, systemd services, or system logs
   - Supports: nexus, homeassistant, outpost
   - Parameters: host, service_type, service_name, lines

2. **check_service_status**
   - Check if a docker container or systemd service is running
   - Supports: nexus, homeassistant, outpost
   - Parameters: host, service_name, service_type

3. **restart_service**
   - Restart a docker container, systemd service, or Home Assistant
   - Supports: nexus, homeassistant, outpost
   - Parameters: host, service_type, service_name

4. **execute_safe_command**
   - Execute whitelisted safe commands
   - Validates against PostgreSQL command_whitelist table
   - Parameters: host, command

All tools use SSH execution via the mounted SSH key.

---

## Command Whitelist

**Total Commands:** 33
- **Low Risk:** 30 (diagnostic, read-only, safe restarts)
- **Medium Risk:** 3 (docker prune, ha core restart, ha supervisor restart)

**Recently Updated (Nov 11, 2025):**
- `docker ps` - Now allows `--filter` and `--format` options
- `curl` - Now allows common flags: `-s`, `-k`, `-I`, `-L`, `-f`, `-v`, `--connect-timeout`
- Added: `docker inspect`, `docker stats`, `docker compose ps/logs`
- Added: `netstat`, `ss`, `ps aux`, `ls`, `date`, `lsblk`

See `/home/t1/homelab/projects/ai-remediation-service/COMMAND_WHITELIST_UPDATE_20251111.md` for full details.

---

## Cleanup Performed

### Removed from Outpost (72.60.163.242)
✅ **Deleted:** `/opt/burrow/ai-remediation/` directory and all contents
- app/main.py
- docker-compose.yml
- Dockerfile
- .env
- requirements.txt
- ssh_key

✅ **Verified:** No references to ai-remediation in Outpost docker-compose.yml

✅ **Verified:** No running ai-remediation containers on Outpost

---

## Network Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Alert Flow                                │
└─────────────────────────────────────────────────────────────┘

Prometheus (Nexus)
  ↓ Alerts
Alertmanager (Nexus)
  ↓ Webhooks (2 destinations)
  ├─→ Discord (#homelab-alerts)
  └─→ AI Remediation (Skynet:8000)
        ↓
      Claude Analysis
        ↓
      SSH Commands to:
        ├─→ Nexus (192.168.0.11)
        ├─→ Home Assistant (192.168.0.10)
        └─→ Outpost (72.60.163.242)
        ↓
      Database Logging (Outpost PostgreSQL:5432)
```

### Why Skynet?
1. **Management Role:** Skynet is the homelab management system (Claude Code, Ansible, Git)
2. **Always-On:** Raspberry Pi 5 with low power consumption
3. **Local Access:** Direct LAN access to Nexus and Home Assistant
4. **Proximity:** Co-located with main infrastructure vs. remote VPS

### Database on Outpost?
- Shared finance_db database allows coordination between n8n workflows and AI remediation
- PostgreSQL already configured and accessible via port 5432
- Future option: Migrate to local SQLite on Skynet if desired

---

## Verification Checklist

- [x] Service running on Skynet (192.168.0.13:8000)
- [x] Health endpoint responding: `curl http://192.168.0.13:8000/health`
- [x] Database connection successful (finance_db on Outpost)
- [x] SSH key mounted correctly (file, not directory)
- [x] Alertmanager webhook pointing to Skynet IP
- [x] No old containers on Outpost
- [x] No old files in /opt/burrow/ai-remediation
- [x] System prompt context accurate
- [x] Command whitelist updated (33 commands)
- [x] Tools configuration correct (3 target hosts)
- [x] Documentation updated

---

## Testing Performed

### 1. Health Check
```bash
curl -s http://localhost:8000/health | jq
```
**Result:** ✅ Status: healthy, database_connected: true

### 2. Webhook Authentication
```bash
curl -u alertmanager:password http://localhost:8000/webhook/alertmanager \
  -X POST -H "Content-Type: application/json" -d '{"status":"test"}'
```
**Result:** ✅ Accepted and processed

### 3. Alert Processing
- **Alert:** HTTPSProbeFailed - n8n.theburrow.casa
- **Action:** AI gathered logs, diagnosed issue, attempted remediation
- **Outcome:** ✅ n8n container started, alert resolved

### 4. Command Whitelist
- **Test:** All previously rejected commands now validated
- **Result:** ✅ `docker ps -a --filter name=n8n` - Allowed
- **Result:** ✅ `curl -I -k https://localhost --connect-timeout 5` - Allowed

---

## Documentation Updated

1. **MONITORING_AUDIT_REPORT_20251111.md** - Monitoring infrastructure audit
2. **COMMAND_WHITELIST_UPDATE_20251111.md** - Command whitelist expansion
3. **AI_REMEDIATION_SKYNET_MIGRATION_COMPLETE.md** - This file

---

## Future Considerations

### Potential Enhancements
1. **Add Prometheus Monitoring** - Create alert if ai-remediation container goes down
2. **Add Skynet to WireGuard VPN** - Direct access to Outpost via 10.99.0.x
3. **Local Database Option** - SQLite on Skynet for better isolation
4. **Expanded Tool Set** - Add docker exec, file inspection tools
5. **Metrics Export** - Expose /metrics endpoint for Prometheus

### Known Limitations
1. **No VPN Access** - Skynet can't reach Outpost via 10.99.0.2 (VPN only between Nexus↔Outpost)
2. **Public DB Access** - Uses Outpost public IP for database (port 5432 exposed)
3. **Single Instance** - No redundancy if Skynet goes down

---

## Rollback Procedure

If rollback to Outpost is needed:

1. Copy project directory to Outpost:
   ```bash
   scp -r /home/t1/homelab/projects/ai-remediation-service outpost:/opt/burrow/
   ```

2. Update Alertmanager on Nexus:
   ```yaml
   url: 'http://10.99.0.2:8000/webhook/alertmanager'  # Via VPN
   ```

3. Update .env database URL:
   ```env
   DATABASE_URL=postgresql://n8n:password@n8n-db:5432/finance_db
   ```

4. Add to Outpost docker-compose.yml and deploy

5. Stop service on Skynet

---

## Conclusion

The AI Remediation Service migration from Outpost to Skynet is **complete and operational**. All configuration references have been verified and updated. The service is:

✅ **Receiving alerts** from Prometheus Alertmanager
✅ **Processing alerts** with Claude AI analysis
✅ **Executing commands** via SSH to all three target systems
✅ **Logging remediation attempts** to PostgreSQL database
✅ **Validated against command whitelist** (33 safe commands)

**No further action required.** The service is ready for production alert remediation.
