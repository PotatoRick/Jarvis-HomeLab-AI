# Jarvis AI Remediation Service

> **Autonomous AI that fixes your homelab infrastructure problems - automatically.**

---

## What It Does

Jarvis connects to Prometheus/Alertmanager and **automatically fixes infrastructure problems** when alerts fire. No human intervention required.

**Example:** Container crashes at 3 AM → Jarvis analyzes it with AI, restarts the container, and sends you a "Fixed in 18 seconds" message. You sleep through it.

---

## Core Features

### 🧠 **AI-Powered Analysis**
- Receives alerts from Alertmanager in real-time
- Uses Claude AI to understand what went wrong
- Generates safe, specific remediation commands
- Executes via SSH, reports results on Discord

### 📚 **Machine Learning**
- **Learns from every successful fix**
- Builds a pattern database (currently 14 patterns)
- After seeing the same issue twice, remembers the solution
- **60-80% cost reduction** (skips AI calls for known patterns)
- Gets smarter over time with Bayesian confidence scoring

### 🔄 **Self-Healing**
Common issues Jarvis fixes automatically:
- Container crashes → Restart
- Service unhealthy → Restart service
- PostgreSQL down → Restart PostgreSQL
- Disk space critical → Docker prune
- WireGuard VPN disconnected → Restart WireGuard

**Fix time:** 10-45 seconds vs. 30+ minutes manual

### 💪 **Resilient Architecture**
Survives failures and keeps working:
- **Database outage** → Degraded mode, queues alerts in memory
- **Host offline** → Detects offline hosts, stops trying, pings every 5 min
- **Network blip** → Retries with exponential backoff
- **Alert storm** → Suppresses cascading alerts (20+ alerts → 1 root cause)

### 🔇 **Alert Suppression**
When VPS goes offline, you normally get 20+ alerts (VPN down, database down, n8n down, etc.)

**Jarvis:**
- Detects root cause (VPN down)
- Suppresses 19 cascading alerts (they're symptoms)
- Sends 1 Discord message instead of 20
- **80%+ noise reduction**

### 🔧 **Maintenance Windows**
Tell Jarvis you're doing upgrades so it doesn't "fix" intentional downtime:

```bash
maintenance-start nexus "Docker upgrade"
# Do your upgrade...
maintenance-end nexus
```

Jarvis suppresses alerts, counts them, and reports when done.

### 📡 **Host Monitoring**
- Tracks if hosts are reachable before trying to fix
- After 3 SSH failures → marks host OFFLINE
- Pings every 5 minutes to detect recovery
- Clear messages: "Cannot remediate - Nexus OFFLINE"

### 📊 **Complete Observability**
```bash
jarvis-status        # Health check
jarvis-patterns      # List learned patterns
jarvis-analytics     # View stats and cost savings
jarvis-logs          # View recent logs
maintenance-status   # Check active maintenance
```

---

## Real-World Example

### Before Jarvis:
**3:14 AM** - Alert: "Frigate container unhealthy"
- You wake up
- SSH into server
- Debug with logs
- Restart container
- Back to sleep **30+ minutes later** (now fully awake)

### With Jarvis:
**3:14 AM** - Alert fires
- Jarvis analyzes: "Frigate unhealthy"
- Executes: `docker restart frigate`
- **3:14:18 AM** - Fixed
- Discord: "✅ Remediated in 18 seconds"
- You sleep through it, read summary in morning

---

## Safety Features

- Command validation (whitelist of safe operations)
- Risk assessment (LOW/MEDIUM/HIGH)
- High-risk operations escalated to Discord
- SSH key authentication (no passwords)
- Execution logging (every command tracked)
- Attempt limits (max 20 per alert)

**Never executes:** `rm -rf`, `dd`, `mkfs`, firewall flushes, etc.

---

## Cost Efficiency

- **Without learning:** ~$12/month (400 AI calls)
- **With learning:** ~$5/month (80 AI calls, rest use patterns)
- **Savings:** ~$7/month (~$84/year)

Plus faster fixes (no API latency) and continuous improvement.

---

## Tech Stack

- **Backend:** Python 3.11 (FastAPI)
- **Database:** PostgreSQL 16 (Skynet)
- **AI:** Claude 3.5 Haiku
- **Execution:** AsyncSSH
- **Code:** ~2,600 lines production Python

---

## Quick Stats

- ✅ **14 pre-seeded patterns** (common issues)
- ✅ **80%+ alert noise reduction** (suppression)
- ✅ **60-80% cost reduction** (after learning)
- ✅ **10-45 second** fix times
- ✅ **24/7 operation** (no human intervention)
- ✅ **Production-ready** (resilient to failures)

---

## Bottom Line

**Jarvis = Your 24/7 AI SRE**

It detects problems, analyzes them with AI, fixes them automatically, learns from success, and gets better over time. Sleep better knowing Jarvis has your back.

**Built by:** Jordan Hoelscher + Claude Code
**Status:** ✅ Production-ready, actively learning
**Location:** `/home/t1/homelab/projects/ai-remediation-service/`
