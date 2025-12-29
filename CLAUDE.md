# Jarvis AI Remediation Service

AI-powered infrastructure alert remediation for homelabs. Automatically analyzes and fixes alerts from Prometheus/Alertmanager using Claude AI.

**Current Version:** 4.1.0 (Phase 8 + CLI Mode)

## Quick Reference

```bash
# Development
docker compose up -d
docker logs -f jarvis
curl http://localhost:8000/health

# Key endpoints
curl http://localhost:8000/patterns      # Learned patterns
curl http://localhost:8000/analytics     # Stats
curl http://localhost:8000/metrics       # Prometheus metrics
curl http://localhost:8000/runbooks      # Runbook list
```

## Architecture

```
Alertmanager -> Jarvis (FastAPI) -> Claude AI -> SSH Executor -> Target Hosts
                    |                                   |
                    v                                   v
               PostgreSQL                    Nexus/HA/Outpost/Skynet
                    |
                    v
            Discord Notifications
```

**Tech Stack:** Python 3.11, FastAPI, PostgreSQL 16, Claude API, asyncssh

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, webhook handler |
| `app/claude_agent.py` | Claude API, agentic tools |
| `app/claude_cli.py` | Claude CLI via SSH (subscription mode) |
| `app/tools/diagnostics.py` | Phase 8 diagnostic tools |
| `app/tools/safe_executor.py` | Phase 8 remediation execution |
| `app/learning_engine.py` | Tiered pattern learning |
| `app/ssh_executor.py` | SSH command execution |
| `app/self_preservation.py` | Self-restart via n8n |
| `app/brain_bridge.py` | Cross-satellite context to Brain |
| `runbooks/*.md` | Alert remediation guidance |

## Configuration

**Required in `.env`:**
- `ANTHROPIC_API_KEY` - Claude API key
- `DATABASE_URL` - PostgreSQL connection
- `DISCORD_WEBHOOK_URL` - Notifications
- `WEBHOOK_AUTH_PASSWORD` - Alertmanager auth
- `SSH_*_HOST/USER` - SSH config for Nexus, HA, Outpost, Skynet

## Phase 8: Reasoning-First Architecture (v4.0.0)

**Tiered Execution Model:**
| Tier | Criteria | API Cost |
|------|----------|----------|
| Cached | 90%+ confidence, 5+ successes | Zero |
| Hint-Assisted | 70-90% confidence | ~50% |
| Full Reasoning | Novel/low confidence | 100% |

Patterns come from Claude's successful reasoning, not hardcoded dictionaries.

## CLI Mode (Subscription-based)

Instead of using the Claude API (pay-per-token), Jarvis can use the Claude Code CLI with your subscription (flat-rate). When enabled, Core SSHs to Skynet and runs the CLI with MCP diagnostic tools.

**Configuration:**
```bash
USE_CLAUDE_CLI=true
CLAUDE_CLI_PATH=/home/t1/.claude/local/claude
SSH_SKYNET_HOST=192.168.0.13
SSH_SKYNET_USER=t1
```

**How it works:**
1. Core receives alert from Alertmanager
2. Core SSHs to Skynet (where Claude CLI is installed)
3. Writes prompt to temp file via SFTP (avoids escaping issues)
4. Pipes prompt to Claude CLI which uses MCP tools for diagnostics
5. Parses structured JSON response for remediation commands

**Requirements:**
- Claude Code CLI installed on Skynet (`/home/t1/.claude/local/claude`)
- SSH access from Docker container to Skynet
- MCP server configured in `~/.claude.json` on Skynet

**Key Files:**
- `app/claude_cli.py` - SSH/SFTP wrapper for CLI invocation
- `../mcp/remediation.py` - MCP server with diagnostic tools

## Self-Preservation

Jarvis can safely restart itself via n8n handoff:
```bash
curl -X POST "http://localhost:8000/self-restart?target=jarvis" -u "alertmanager:$PASS"
```
Targets: `jarvis`, `postgres-jarvis`, `docker-daemon`, `skynet-host`

## Brain Integration

Jarvis Core writes remediation conversations to the shared Brain database for cross-satellite context:

**Features:**
- Insight can query: "What alerts did you fix last month?"
- Voice can reference recent remediation patterns
- iOS app gets unified conversation history

**Configuration:**
```bash
BRAIN_DATABASE_URL=postgresql://jarvis:xxx@host.docker.internal:5435/jarvis_brain
BRAIN_ENABLED=true
```

**Key Files:**
- `app/brain_bridge.py` - Writes remediation summaries to Brain
- `app/config.py` - Brain settings

The bridge writes to Brain's `conversations` table with `satellite='core'` after each remediation attempt. If Brain is unavailable, remediation continues normally (graceful degradation).

## Distribution

| Component | URL |
|-----------|-----|
| GitHub | github.com/PotatoRick/Jarvis-HomeLab-AI |
| Jarvis Hub | jarvis.theburrow.casa |
| Registry | registry.theburrow.casa |

**Deploy:** Use `/jarvis-deployment` skill for full release process.

## Troubleshooting

See `runbooks/JarvisRestart.md` for self-preservation issues.
See `TROUBLESHOOTING.md` for general issues.
