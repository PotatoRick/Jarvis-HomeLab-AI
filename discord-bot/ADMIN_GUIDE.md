# Jarvis Discord Bot - Administrator Guide

Operations guide for deploying, maintaining, and troubleshooting the Jarvis Discord bot integration.

## System Overview

The Jarvis Discord bot provides interactive access to Claude Code AI through Discord. Users @mention Jarvis in `#jarvis-requests`, and the bot orchestrates Claude Code execution via n8n workflow.

**Components:**
- **Discord Bot** (Management-Host) - Python 3.11 application listening for @mentions
- **n8n Workflow** (VPS-Host) - Orchestrates Claude Code execution
- **PostgreSQL** (Management-Host) - Session management and conversation history
- **Claude Code** (Management-Host) - AI agent execution engine

**Data Flow:**
```
Discord → Bot (Management-Host:8001) → n8n (VPS-Host) → SSH → Claude Code (Management-Host) → PostgreSQL → Discord
```

## Deployment

### Prerequisites

- Docker and Docker Compose on Management-Host
- PostgreSQL container `postgres-jarvis:5433` running on Management-Host
- n8n running on VPS-Host VPS
- SSH key authentication from VPS-Host to Management-Host
- Discord bot token (stored in SOPS-encrypted secrets)

### Initial Setup

**1. Clone and Navigate:**
```bash
cd /home/<user>/homelab/projects/jarvis-discord-bot
```

**2. Configure Environment:**
```bash
# Copy example config
cp .env.example .env

# Edit .env with production values
nano .env
```

**Required Environment Variables:**
```bash
DISCORD_BOT_TOKEN=your_token_here          # From Discord Developer Portal
DISCORD_CHANNEL_ID=1425506950430461952     # #jarvis-requests channel ID
DISCORD_REQUIRED_ROLE=homelab-admin        # Role required to use bot
N8N_WEBHOOK_URL=https://n8n.yourdomain.com/webhook/jarvis-discord-claude
```

**3. Deploy Database Schema:**

The database schema is deployed as part of Jarvis AI migrations. If not already deployed:

```bash
# Check if tables exist
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "\dt discord_*"

# If not found, schema must be created (see Database Schema section)
```

**4. Build and Deploy:**
```bash
# Build container
docker compose build

# Start service
docker compose up -d

# Verify running
docker ps | grep jarvis-discord-bot
```

**5. Verify Discord Connection:**
```bash
# Check logs for successful login
docker logs jarvis-discord-bot | grep "Logged in as"

# Expected output:
# Logged in as Jarvis#2673 (ID: 1447434205112827906)
```

**6. Test Bot:**

In Discord `#jarvis-requests` channel:
```
@Jarvis hello
```

Expected response within 10-15 seconds.

### Updating

**Pull latest code and rebuild:**
```bash
cd /home/<user>/homelab/projects/jarvis-discord-bot
git pull origin main
docker compose down
docker compose build
docker compose up -d
```

**Check logs for errors:**
```bash
docker logs -f jarvis-discord-bot
```

## Configuration

### Discord Settings

**Bot Token:**
Stored in `/home/<user>/homelab/secrets/shared/discord-webhooks.env` (SOPS-encrypted)

**Channel Configuration:**
- **Channel:** `#jarvis-requests` (ID: 1425506950430461952)
- **Server:** "Fucking Nerds"
- **Bot:** Jarvis#2673 (ID: 1447434205112827906)

**Permissions Required:**
- Read Messages
- Send Messages
- Read Message History
- Mention Everyone (to check user roles)

**Role-Based Access:**
- Only users with `homelab-admin` role can use Jarvis
- Checked on every request before processing

### Rate Limiting

**Default Limits:**
- 10 requests per 5 minutes per user
- Sliding window algorithm (in-memory)

**Adjust Limits:**

Edit `.env`:
```bash
RATE_LIMIT_REQUESTS=10     # Max requests
RATE_LIMIT_WINDOW=300      # Time window in seconds (5 min)
```

Restart bot:
```bash
docker restart jarvis-discord-bot
```

### n8n Webhook Integration

**Webhook URL:**
```
https://n8n.yourdomain.com/webhook/jarvis-discord-claude
```

**Workflow Location:**
```
/home/<user>/homelab/configs/n8n-workflows/jarvis-discord-claude-integration.json
```

**Critical Settings:**
- **Webhook Mode:** "Using 'Respond to Webhook' Node" (synchronous)
- **SSH Credential:** "Management-Host's SSH Key" configured in n8n
- **Permission Mode:** `--permission-mode bypassPermissions`

**Update Workflow:**
1. Export from n8n UI (Settings > Export)
2. Save to `/home/<user>/homelab/configs/n8n-workflows/jarvis-discord-claude-integration.json`
3. Commit to git

## Database Schema

### Tables

**discord_sessions:**
```sql
session_id UUID PRIMARY KEY          -- Unique session identifier
discord_user_id TEXT NOT NULL        -- Discord user ID (snowflake)
discord_username TEXT NOT NULL       -- Display name
channel_id TEXT NOT NULL             -- Discord channel ID
created_at TIMESTAMP DEFAULT NOW()   -- Session creation
last_active TIMESTAMP DEFAULT NOW()  -- Last message timestamp
status TEXT DEFAULT 'active'         -- active/completed/timeout
agent_hint TEXT                      -- Requested agent (if any)
```

**discord_messages:**
```sql
message_id SERIAL PRIMARY KEY              -- Auto-increment ID
session_id UUID FK → discord_sessions      -- Session reference
message_type TEXT NOT NULL                 -- user/assistant/system
content TEXT NOT NULL                      -- Message content
timestamp TIMESTAMP DEFAULT NOW()          -- Message timestamp
claude_model TEXT                          -- Model used (e.g., claude-sonnet-4.5)
execution_time_ms INT                      -- Execution time (ms)
```

### Database Management

**Access Database:**
```bash
docker exec -it postgres-jarvis psql -U jarvis -d jarvis
```

**View Active Sessions:**
```sql
SELECT
  session_id,
  discord_username,
  status,
  created_at,
  last_active,
  NOW() - last_active AS inactive_for
FROM discord_sessions
WHERE status = 'active'
ORDER BY last_active DESC;
```

**View User Activity:**
```sql
SELECT
  discord_username,
  COUNT(DISTINCT session_id) AS sessions,
  COUNT(*) AS total_messages
FROM discord_sessions s
JOIN discord_messages m USING (session_id)
WHERE s.created_at > NOW() - INTERVAL '7 days'
GROUP BY discord_username
ORDER BY total_messages DESC;
```

**Check Session Message History:**
```sql
SELECT
  message_type,
  SUBSTRING(content, 1, 100) AS preview,
  timestamp
FROM discord_messages
WHERE session_id = 'SESSION_UUID_HERE'
ORDER BY timestamp ASC;
```

**Cleanup Old Sessions:**
```sql
-- Delete sessions older than 90 days
DELETE FROM discord_sessions
WHERE created_at < NOW() - INTERVAL '90 days';
```

**Session Analytics:**
```sql
-- Use built-in analytics view
SELECT * FROM discord_analytics;
```

## Monitoring

### Health Checks

**Check Bot Status:**
```bash
# Container running?
docker ps | grep jarvis-discord-bot

# Recent logs
docker logs jarvis-discord-bot --tail 50

# Follow logs in real-time
docker logs -f jarvis-discord-bot
```

**Check Discord Connection:**
```bash
# Look for login confirmation
docker logs jarvis-discord-bot | grep "Logged in as"

# Expected output:
# [INFO] Logged in as Jarvis#2673 (ID: 1447434205112827906)
# [INFO] Listening in channel ID: 1425506950430461952
```

**Check PostgreSQL:**
```bash
# Database reachable?
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "SELECT COUNT(*) FROM discord_sessions;"

# Expected: number of sessions (0 or more)
```

**Check n8n Workflow:**
```bash
# Test webhook manually
curl -X POST https://n8n.yourdomain.com/webhook/jarvis-discord-claude \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","username":"Test","channel_id":"123","prompt":"hello","agent_hint":null}'

# Expected: {"success":true,"response":"...","session_id":"...","error":null}
```

### Logs

**Bot Logs:**
```bash
# Last 100 lines
docker logs jarvis-discord-bot --tail 100

# Follow new logs
docker logs -f jarvis-discord-bot

# Search for errors
docker logs jarvis-discord-bot 2>&1 | grep -i error
```

**Log Locations:**
- **Container logs:** `docker logs jarvis-discord-bot`
- **Application logs:** `/home/<user>/homelab/projects/jarvis-discord-bot/logs/bot.log`
- **n8n executions:** n8n UI > Executions tab

**Key Log Messages:**
```
[INFO] Logged in as Jarvis#2673               # Bot connected
[INFO] Received mention from User (ID)        # Request received
[WARNING] Rate limit exceeded for user         # Rate limit hit
[ERROR] Execution failed: ...                  # Processing error
```

### Performance Metrics

**Current Metrics (Manual):**
```bash
# Active sessions count
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c \
  "SELECT COUNT(*) FROM discord_sessions WHERE status = 'active';"

# Messages in last 24 hours
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c \
  "SELECT COUNT(*) FROM discord_messages WHERE timestamp > NOW() - INTERVAL '24 hours';"

# Average response time (from discord_messages.execution_time_ms)
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c \
  "SELECT AVG(execution_time_ms) AS avg_response_ms FROM discord_messages
   WHERE execution_time_ms IS NOT NULL AND timestamp > NOW() - INTERVAL '7 days';"
```

**Typical Performance:**
- Response time: 10-15 seconds average
- Session creation: <1 second
- Database queries: <100ms

## Maintenance

### Regular Tasks

**Weekly:**
- Review error logs for anomalies
- Check rate limiting stats
- Verify n8n workflow executions

**Monthly:**
- Clean up old sessions (90+ days)
- Review user activity analytics
- Check disk usage for session files

**As Needed:**
- Update Discord bot token (if expired)
- Adjust rate limits (if abuse detected)
- Update agent list (when new agents added)

### Session Cleanup

**Automatic Cleanup:**

Add to Management-Host crontab:
```bash
# Clean PostgreSQL sessions older than 90 days (Sundays at 3 AM)
0 3 * * 0 docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c \
  "DELETE FROM discord_sessions WHERE created_at < NOW() - INTERVAL '90 days';"

# Clean Claude Code session files older than 90 days (Sundays at 2 AM)
0 2 * * 0 find /home/<user>/.claude/projects/-/ -name "*.jsonl" -mtime +90 -delete
```

**Manual Cleanup:**
```bash
# Clean PostgreSQL sessions
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c \
  "DELETE FROM discord_sessions WHERE created_at < NOW() - INTERVAL '90 days';"

# Clean Claude Code session files
find /home/<user>/.claude/projects/-/ -name "*.jsonl" -mtime +90 -delete

# Check disk usage before/after
du -sh /home/<user>/.claude/projects/-/
```

### Rate Limit Management

**View Rate Limit Stats:**

Rate limiter is in-memory, stats available via bot logs:
```bash
docker logs jarvis-discord-bot | grep -i "rate limit"
```

**Reset User Rate Limit:**

Currently requires bot restart (future enhancement: admin command):
```bash
docker restart jarvis-discord-bot
```

**Adjust Global Limits:**

Edit `.env`, restart bot:
```bash
nano .env
# Change RATE_LIMIT_REQUESTS or RATE_LIMIT_WINDOW
docker restart jarvis-discord-bot
```

## Troubleshooting

### Bot Not Responding to @Mentions

**1. Check Bot is Running:**
```bash
docker ps | grep jarvis-discord-bot
```

If not running:
```bash
docker compose up -d
docker logs jarvis-discord-bot
```

**2. Verify Discord Connection:**
```bash
docker logs jarvis-discord-bot | grep "Logged in as"
```

If not found, check Discord token:
```bash
docker exec jarvis-discord-bot env | grep DISCORD_BOT_TOKEN
```

**3. Check Channel Configuration:**
```bash
docker exec jarvis-discord-bot env | grep DISCORD_CHANNEL_ID
# Should be: 1425506950430461952
```

**4. Verify User Has Required Role:**

User must have `homelab-admin` role in Discord server.

**5. Check Logs for Errors:**
```bash
docker logs jarvis-discord-bot --tail 50 | grep -i error
```

### n8n Workflow Failures

**1. Test Webhook:**
```bash
curl -X POST https://n8n.yourdomain.com/webhook/jarvis-discord-claude \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","username":"Test","channel_id":"123","prompt":"test","agent_hint":null}'
```

Expected response:
```json
{"success":true,"response":"...","session_id":"...","error":null}
```

**2. Check n8n Logs:**
```bash
ssh vps-host 'docker logs n8n --tail 50'
```

**3. Verify SSH Access:**
```bash
# From VPS-Host to Management-Host
ssh vps-host 'ssh t1@<management-host-ip> "echo SSH works"'
```

**4. Check Workflow Mode:**

In n8n UI:
- Webhook node must be in "Using 'Respond to Webhook' Node" mode
- Verify "Respond to Webhook" node exists at end of workflow

### Claude Code Execution Errors

**1. Test Claude Code Manually:**
```bash
/home/<user>/.claude/local/claude --print \
  --permission-mode bypassPermissions \
  --session-id $(uuidgen) \
  -r "test prompt"
```

**2. Check Session Files:**
```bash
ls -la /home/<user>/.claude/projects/-/*.jsonl | tail -5
```

**3. Verify PostgreSQL Connection:**
```bash
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "SELECT 1;"
```

**4. Check Session Reuse Logic:**
```sql
-- Check recent sessions for user
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "
SELECT session_id, status, last_active,
       NOW() - last_active AS inactive_duration
FROM discord_sessions
WHERE discord_user_id = 'USER_ID_HERE'
ORDER BY last_active DESC
LIMIT 3;
"
```

### Multi-Turn Conversations Not Working

**1. Verify Session Persistence:**
```sql
-- Count messages per session
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "
SELECT session_id, COUNT(*) AS message_count
FROM discord_messages
GROUP BY session_id
ORDER BY MAX(timestamp) DESC
LIMIT 5;
"
```

Sessions with >1 message indicate multi-turn is working.

**2. Check Claude Code Session Files:**
```bash
# Find recent session files
find /home/<user>/.claude/projects/-/ -name "*.jsonl" -mmin -60 -ls
```

**3. Check Session Timeout:**
```sql
-- Sessions should reuse within 30 minutes
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "
SELECT session_id, last_active,
       CASE WHEN last_active > NOW() - INTERVAL '30 minutes'
            THEN 'Should reuse'
            ELSE 'Should create new'
       END AS status
FROM discord_sessions
WHERE discord_user_id = 'USER_ID_HERE'
ORDER BY last_active DESC
LIMIT 1;
"
```

**4. Review n8n Execution Logs:**

In n8n UI:
- Go to Executions tab
- Find recent execution for affected user
- Check "Determine Session Mode" node output
- Should be `--resume {UUID}` for follow-up messages

### Rate Limiting Issues

**1. Check User Request Count:**
```bash
docker logs jarvis-discord-bot | grep "Rate limit check for USER_ID"
```

**2. View Rate Limit Blocks:**
```bash
docker logs jarvis-discord-bot | grep "Rate limit exceeded"
```

**3. Reset Rate Limiter:**

Restart bot (clears in-memory rate limiter):
```bash
docker restart jarvis-discord-bot
```

**4. Adjust Limits:**

Edit `.env`:
```bash
RATE_LIMIT_REQUESTS=20    # Increase to 20
RATE_LIMIT_WINDOW=300     # Keep 5 minutes
```

Restart:
```bash
docker restart jarvis-discord-bot
```

### Database Connection Issues

**1. Check PostgreSQL Running:**
```bash
docker ps | grep postgres-jarvis
```

**2. Test Connection:**
```bash
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "SELECT NOW();"
```

**3. Verify Network:**

Bot and PostgreSQL must be on same Docker network:
```bash
docker network inspect ai-remediation-service_default
```

Both `jarvis-discord-bot` and `postgres-jarvis` should appear.

**4. Check Database Logs:**
```bash
docker logs postgres-jarvis --tail 50
```

## Security

### Access Control

**Discord Role Requirement:**
- Users must have `homelab-admin` role
- Checked on every request
- Configurable via `DISCORD_REQUIRED_ROLE` in `.env`

**Rate Limiting:**
- 10 requests per 5 minutes per user
- Prevents spam and abuse
- In-memory tracking (resets on bot restart)

**Audit Trail:**
- All messages logged in PostgreSQL
- Session metadata includes user ID and username
- Logs include timestamps and request details

### Secrets Management

**Discord Bot Token:**
- Stored in `/home/<user>/homelab/secrets/shared/discord-webhooks.env`
- Encrypted with SOPS (safe to commit to git)
- Mounted to container via `.env` file (gitignored)

**Decrypt Token:**
```bash
sops -d /home/<user>/homelab/secrets/shared/discord-webhooks.env | grep DISCORD_BOT_TOKEN
```

**Update Token:**
```bash
# Edit encrypted file
sops /home/<user>/homelab/secrets/shared/discord-webhooks.env

# Update .env
nano .env

# Restart bot
docker restart jarvis-discord-bot
```

### Claude Code Permissions

**Permission Mode:**
- Bot uses `--permission-mode bypassPermissions`
- Operates with same safety as primary Claude Code instance
- Built-in checks for destructive operations
- Requires explicit confirmation for dangerous commands

**Safety Features:**
- Cannot force-push to git main branch
- Cannot delete backups without confirmation
- Cannot modify critical configs without review
- Logs all executed commands

## Backup & Recovery

### What Gets Backed Up

**Code:**
- Git repository: `/home/<user>/homelab/projects/jarvis-discord-bot/`
- Included in daily Management-Host backups

**Database:**
- PostgreSQL `jarvis` database on `postgres-jarvis:5433`
- Backed up via Jarvis backup routine
- Includes `discord_sessions` and `discord_messages` tables

**Session Files:**
- Claude Code session files: `/home/<user>/.claude/projects/-/*.jsonl`
- Not backed up (ephemeral, 90-day retention)

### Restore Procedure

**1. Restore Code:**
```bash
cd /home/<user>/homelab/projects/jarvis-discord-bot
git pull origin main
```

**2. Restore Database:**

If database is lost, PostgreSQL backup includes schema and data:
```bash
# Restore from Jarvis backup (details in Jarvis CLAUDE.md)
```

**3. Redeploy:**
```bash
docker compose down
docker compose build
docker compose up -d
```

**4. Verify:**
```bash
docker logs jarvis-discord-bot | grep "Logged in as"
```

## Future Enhancements

**Planned:**
- Health check endpoint (`GET /health`)
- Prometheus metrics export (request count, response time, rate limits)
- Admin slash commands (reset rate limit, end session, view stats)
- Image upload support (screenshot analysis)

**Under Consideration:**
- Voice channel integration (speech-to-text)
- Collaborative sessions (multiple users)
- Alert analysis command (`@Jarvis analyze current alerts`)
- Session export (download conversation history)

## Support

**Logs:**
```bash
# Bot logs
docker logs -f jarvis-discord-bot

# PostgreSQL logs
docker logs postgres-jarvis --tail 50

# n8n workflow executions
# Access via n8n UI at https://n8n.yourdomain.com
```

**Database Access:**
```bash
docker exec -it postgres-jarvis psql -U jarvis -d jarvis
```

**Configuration Files:**
- Bot config: `/home/<user>/homelab/projects/jarvis-discord-bot/.env`
- n8n workflow: `/home/<user>/homelab/configs/n8n-workflows/jarvis-discord-claude-integration.json`
- Secrets: `/home/<user>/homelab/secrets/shared/discord-webhooks.env` (SOPS-encrypted)

**Documentation:**
- User guide: `USER_GUIDE.md` (this directory)
- Technical reference: `CLAUDE.md` (this directory)
- Implementation details: `IMPLEMENTATION_STATUS.md` (this directory)
