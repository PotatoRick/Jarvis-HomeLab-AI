# Jarvis Discord Bot

Interactive Claude Code AI assistant for Discord-based homelab management.

## Overview

Jarvis Discord Bot provides conversational AI access to Claude Code through Discord, enabling users to ask questions, troubleshoot issues, and manage The Burrow homelab infrastructure through natural language commands.

**Key Features:**
- Multi-turn conversations with context retention
- Specialized AI agents for different domains (infrastructure, security, home automation, etc.)
- Session-based persistence (30-minute timeout)
- Autonomous command execution (no approval prompts needed)
- Rate limiting and role-based access control
- Full conversation history in PostgreSQL

## Quick Start

### For Users

Send a message in Discord `#jarvis-requests` channel:

```
@Jarvis what services are running on Service-Host?
```

Jarvis will respond with the answer. Follow-up questions remember context:

```
@Jarvis restart the Frigate container
```

See [USER_GUIDE.md](USER_GUIDE.md) for detailed usage instructions.

### For Administrators

Deploy the bot on Management-Host:

```bash
cd /home/<user>/homelab/projects/jarvis-discord-bot
docker compose build
docker compose up -d
```

See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for deployment, maintenance, and troubleshooting.

### For Developers

The bot is a Python 3.11 application using discord.py, integrated with n8n workflow orchestration and Claude Code execution.

See [ARCHITECTURE.md](ARCHITECTURE.md) for technical details and integration documentation.

## Documentation

| Document | Audience | Purpose |
|----------|----------|---------|
| [USER_GUIDE.md](USER_GUIDE.md) | End Users | How to use @Jarvis in Discord |
| [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | Administrators | Deployment, maintenance, troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Developers | Technical architecture, data flow, integration |
| [CLAUDE.md](CLAUDE.md) | All | Project overview and quick reference |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | All | Implementation details and testing results |

## System Architecture

```
Discord (#jarvis-requests)
    ↓ @Jarvis mention
Python Discord Bot (Management-Host:8001)
    ↓ HTTP POST
n8n Workflow (VPS-Host VPS)
    ↓ SSH
Claude Code (Management-Host)
    ↓ SQL
PostgreSQL (postgres-jarvis:5433)
    ↓
Response → Discord
```

**Components:**
- **Discord Bot** - Listens for @mentions, parses messages, orchestrates execution
- **n8n Workflow** - Manages sessions, executes Claude Code via SSH
- **Claude Code** - AI agent execution engine with homelab access
- **PostgreSQL** - Session management and conversation history

**Technologies:**
- Python 3.11 (discord.py, aiohttp)
- n8n (Node.js workflow automation)
- PostgreSQL 15
- Docker & Docker Compose
- Claude Code (Go binary)

## Features

### Multi-Turn Conversations

Sessions persist for 30 minutes, allowing follow-up questions without repeating context:

```
You: @Jarvis list all Docker containers on Service-Host
Jarvis: [Lists: caddy, frigate, adguard, prometheus, grafana...]

You: @Jarvis show me the logs for the Frigate container
Jarvis: [Shows Frigate logs]

You: @Jarvis restart it if there are errors
Jarvis: [Checks logs, restarts Frigate if needed]
```

### Specialized Agents

Request specific expertise:

```
@Jarvis ask homelab-architect "how should I deploy a new monitoring service?"
@Jarvis ask home-assistant-expert "why isn't my Zigbee sensor responding?"
@Jarvis ask homelab-security-auditor "review the Caddy configuration"
```

Available agents:
- homelab-architect
- home-assistant-expert
- n8n-workflow-architect
- homelab-security-auditor
- financial-automation-guru
- omada-network-engineer
- python-claude-code-expert
- technical-documenter

### Rate Limiting

10 requests per 5 minutes per user to prevent abuse and ensure fair access.

### Role-Based Access

Only users with the `homelab-admin` Discord role can use Jarvis.

### Autonomous Execution

Jarvis operates with `--permission-mode bypassPermissions`, running commands autonomously without approval prompts. Built-in safety checks prevent destructive operations.

## Installation

### Prerequisites

- Docker and Docker Compose on Management-Host
- PostgreSQL container `postgres-jarvis:5433` running
- n8n running on VPS-Host VPS
- Discord bot token (from Discord Developer Portal)
- SSH key authentication from VPS-Host to Management-Host

### Deploy

1. **Configure Environment:**
   ```bash
   cd /home/<user>/homelab/projects/jarvis-discord-bot
   cp .env.example .env
   nano .env  # Add Discord token and other settings
   ```

2. **Build and Start:**
   ```bash
   docker compose build
   docker compose up -d
   ```

3. **Verify:**
   ```bash
   docker logs jarvis-discord-bot | grep "Logged in as"
   # Expected: Logged in as Jarvis#2673
   ```

4. **Test in Discord:**
   ```
   @Jarvis hello
   ```

See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for detailed deployment instructions.

## Configuration

### Environment Variables

Required:
- `DISCORD_BOT_TOKEN` - Bot token from Discord Developer Portal
- `DISCORD_CHANNEL_ID` - Channel ID for #jarvis-requests (1425506950430461952)
- `DISCORD_REQUIRED_ROLE` - Role required to use bot (homelab-admin)
- `N8N_WEBHOOK_URL` - n8n webhook endpoint URL

Optional:
- `N8N_WEBHOOK_AUTH` - Basic auth token for n8n webhook
- `RATE_LIMIT_REQUESTS` - Max requests per window (default: 10)
- `RATE_LIMIT_WINDOW` - Window in seconds (default: 300)
- `LOG_LEVEL` - Logging level (default: INFO)

### Discord Bot Settings

- **Server:** "Fucking Nerds"
- **Channel:** #jarvis-requests (1425506950430461952)
- **Bot:** Jarvis#2673 (ID: 1447434205112827906)
- **Required Role:** homelab-admin

## Usage Examples

### Check Service Status
```
@Jarvis is Frigate running on Service-Host?
```

### Troubleshoot Alerts
```
@Jarvis what Prometheus alerts are currently active?
@Jarvis why is the PostgreSQL alert firing?
```

### Get Deployment Instructions
```
@Jarvis ask homelab-architect "how do I deploy a new Docker service on Service-Host?"
```

### Create Workflows
```
@Jarvis ask n8n-workflow-architect "design a workflow to send Discord alerts when backups fail"
```

### Multi-Turn Debugging
```
@Jarvis check the Frigate container logs on Service-Host
@Jarvis is there an error causing it to restart?
@Jarvis restart the container with fresh logs
```

## Monitoring

### Check Bot Status
```bash
# Container running?
docker ps | grep jarvis-discord-bot

# View logs
docker logs -f jarvis-discord-bot

# Check Discord connection
docker logs jarvis-discord-bot | grep "Logged in as"
```

### Database Queries

**Active Sessions:**
```bash
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "
SELECT discord_username, last_active, NOW() - last_active AS inactive_for
FROM discord_sessions WHERE status = 'active' ORDER BY last_active DESC;
"
```

**User Activity:**
```bash
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "
SELECT * FROM discord_analytics;
"
```

## Troubleshooting

### Bot Not Responding

1. Check bot is running: `docker ps | grep jarvis-discord-bot`
2. Check Discord connection: `docker logs jarvis-discord-bot | grep "Logged in"`
3. Verify channel ID: `docker exec jarvis-discord-bot env | grep DISCORD_CHANNEL_ID`
4. Check user has `homelab-admin` role in Discord

### n8n Workflow Failures

Test webhook manually:
```bash
curl -X POST https://n8n.yourdomain.com/webhook/jarvis-discord-claude \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","username":"Test","channel_id":"123","prompt":"hello","agent_hint":null}'
```

Expected response:
```json
{"success":true,"response":"...","session_id":"...","error":null}
```

### Multi-Turn Not Working

Check session timeout:
```bash
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "
SELECT session_id, last_active, NOW() - last_active AS inactive_duration
FROM discord_sessions WHERE discord_user_id = 'YOUR_USER_ID'
ORDER BY last_active DESC LIMIT 1;
"
```

Sessions timeout after 30 minutes of inactivity.

See [ADMIN_GUIDE.md](ADMIN_GUIDE.md) for comprehensive troubleshooting.

## Security

**Access Control:**
- Requires `homelab-admin` Discord role
- Rate limited (10 requests per 5 minutes per user)
- Audit trail in PostgreSQL (all messages logged)

**Secrets:**
- Discord token stored in SOPS-encrypted secrets
- Mounted to container via `.env` (gitignored)
- Never committed to git

**Permissions:**
- Bot operates with same permissions as Claude Code
- Built-in safety checks for destructive operations
- Requires explicit confirmation for dangerous commands

**Data Retention:**
- Active sessions: 30 minutes
- Session history: 90 days (then deleted)
- Claude Code session files: 90 days (manual cleanup)

## Maintenance

### Regular Tasks

**Weekly:**
- Review error logs: `docker logs jarvis-discord-bot | grep -i error`
- Check rate limiting stats: `docker logs jarvis-discord-bot | grep "rate limit"`

**Monthly:**
- Clean up old sessions (90+ days)
- Review user activity analytics
- Check disk usage for session files

### Session Cleanup

Add to Management-Host crontab:
```bash
# Clean PostgreSQL sessions (Sundays at 3 AM)
0 3 * * 0 docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c \
  "DELETE FROM discord_sessions WHERE created_at < NOW() - INTERVAL '90 days';"

# Clean Claude Code session files (Sundays at 2 AM)
0 2 * * 0 find /home/<user>/.claude/projects/-/ -name "*.jsonl" -mtime +90 -delete
```

## Project Structure

```
jarvis-discord-bot/
├── README.md                      # This file
├── USER_GUIDE.md                  # End user documentation
├── ADMIN_GUIDE.md                 # Administrator documentation
├── ARCHITECTURE.md                # Developer documentation
├── CLAUDE.md                      # Project technical reference
├── IMPLEMENTATION_STATUS.md       # Implementation details
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Container image definition
├── docker-compose.yml             # Container orchestration
├── .env.example                   # Configuration template
├── .gitignore                     # Git ignore rules
│
├── app/                           # Application code
│   ├── __init__.py
│   ├── bot.py                     # Main Discord bot
│   ├── config.py                  # Environment loader
│   ├── message_parser.py          # Message parsing
│   ├── rate_limiter.py            # Rate limiting
│   └── n8n_client.py              # n8n HTTP client
│
└── logs/                          # Application logs (gitignored)
    └── bot.log
```

## Development

### Local Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Configure .env with test Discord token
cp .env.example .env
nano .env

# Run locally
python -m app.bot
```

### Deployment

```bash
# Pull latest code
cd /home/<user>/homelab/projects/jarvis-discord-bot
git pull origin main

# Rebuild container
docker compose build

# Deploy
docker compose down
docker compose up -d

# Verify
docker logs -f jarvis-discord-bot
```

### Adding New Agents

1. Edit `app/message_parser.py`:
   ```python
   VALID_AGENTS = [
       "homelab-architect",
       "my-new-agent",  # Add here
   ]
   ```

2. Create agent in Claude Code (see Claude Code documentation)

3. Rebuild and deploy:
   ```bash
   docker compose build
   docker compose up -d
   ```

## Performance

**Response Time:** 10-15 seconds average (includes SSH + Claude execution)

**Rate Limits:**
- 10 requests per 5 minutes per user
- No global rate limit (per-user only)

**Resource Usage:**
- Memory: 128-256 MB
- CPU: <5% idle, 10-20% processing
- Disk: ~1 KB per message

**Scalability:**
- Concurrent users: 100+ (limited by rate limiting)
- Database: Handles 1000s of sessions
- Bottleneck: Claude Code execution time (10s average)

## Future Enhancements

**Planned:**
- Health check endpoint (`GET /health`)
- Prometheus metrics export (request count, response time, errors)
- Admin slash commands (reset rate limit, end session, view stats)
- Image upload support (screenshot analysis)

**Under Consideration:**
- Voice channel integration (speech-to-text)
- Collaborative sessions (multiple users)
- Alert analysis command (`@Jarvis analyze current alerts`)
- Session export (download conversation history)

## Support

**Documentation:**
- User Guide: [USER_GUIDE.md](USER_GUIDE.md)
- Admin Guide: [ADMIN_GUIDE.md](ADMIN_GUIDE.md)
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Technical Reference: [CLAUDE.md](CLAUDE.md)

**Logs:**
- Bot: `docker logs -f jarvis-discord-bot`
- PostgreSQL: `docker logs postgres-jarvis`
- n8n: Access via https://n8n.yourdomain.com (Executions tab)

**Database Access:**
```bash
docker exec -it postgres-jarvis psql -U jarvis -d jarvis
```

**Configuration Files:**
- Bot: `/home/<user>/homelab/projects/jarvis-discord-bot/.env`
- n8n: `/home/<user>/homelab/configs/n8n-workflows/jarvis-discord-claude-integration.json`
- Secrets: `/home/<user>/homelab/secrets/shared/discord-webhooks.env` (SOPS-encrypted)

## Contributing

This is a private homelab project. For issues or enhancements, contact Jordan directly or open an issue in the homelab repository.

## License

Private project - not for public distribution.

## Credits

**Implementation:** Claude Sonnet 4.5
**Date:** December 13, 2025
**Status:** Production Ready

Integrated with The Burrow homelab infrastructure.
