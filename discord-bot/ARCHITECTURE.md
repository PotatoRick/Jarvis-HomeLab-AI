# Jarvis Discord Bot - Architecture Documentation

Technical architecture and integration details for developers working on the Discord bot integration.

## System Architecture

The Jarvis Discord bot enables conversational AI access to Claude Code through Discord. The system spans four hosts and integrates five major components.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Discord API                              │
│                    (discord.com servers)                         │
└────────────────────────┬────────────────────────────────────────┘
                         │ WebSocket + REST
                         │
         ┌───────────────▼──────────────────┐
         │   Discord Bot (Python 3.11)      │
         │   Management-Host: <management-host-ip>:8001      │
         │   - discord.py library           │
         │   - Rate limiter (in-memory)     │
         │   - Message parser               │
         └────────────┬─────────────────────┘
                      │ HTTP POST
                      │ (JSON payload)
         ┌────────────▼─────────────────────┐
         │   n8n Workflow (Node.js)         │
         │   VPS-Host: <vps-ip>         │
         │   - Webhook trigger              │
         │   - Session management           │
         │   - SSH orchestration            │
         └────────────┬─────────────────────┘
                      │ SSH
                      │ (WireGuard VPN tunnel)
         ┌────────────▼─────────────────────┐
         │   Claude Code (Go binary)        │
         │   Management-Host: <management-host-ip>           │
         │   - Agent execution              │
         │   - Session persistence          │
         │   - Permission handling          │
         └────────────┬─────────────────────┘
                      │ SQL (via SSH)
                      │
         ┌────────────▼─────────────────────┐
         │   PostgreSQL 15                  │
         │   Management-Host: postgres-jarvis:5433   │
         │   - Session metadata             │
         │   - Conversation history         │
         │   - Analytics views              │
         └──────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Language | Location |
|-----------|---------------|----------|----------|
| Discord Bot | Listen for @mentions, parse messages, orchestrate execution | Python 3.11 | Management-Host (container) |
| n8n Workflow | Session management, SSH to Management-Host, execute Claude Code | Node.js | VPS-Host VPS |
| Claude Code | AI agent execution, read/write filesystem, run commands | Go | Management-Host (binary) |
| PostgreSQL | Store sessions, messages, analytics | SQL | Management-Host (container) |

## Data Flow

### Request Processing Flow

```
1. User posts in Discord: "@Jarvis ask homelab-architect 'how to deploy X'"
   ↓
2. Discord API sends event to bot via WebSocket
   ↓
3. Bot receives on_message event
   ↓
4. Bot checks:
   - Is user in correct channel? (#jarvis-requests)
   - Does user have required role? (homelab-admin)
   - Is user within rate limit? (10 req / 5 min)
   ↓
5. Bot parses message:
   - Extract prompt: "how to deploy X"
   - Extract agent hint: "homelab-architect"
   ↓
6. Bot POSTs to n8n webhook:
   {
     "user_id": "98554078157615104",
     "username": "DeadEye360",
     "channel_id": "1425506950430461952",
     "prompt": "how to deploy X",
     "agent_hint": "homelab-architect"
   }
   ↓
7. n8n workflow receives webhook
   ↓
8. n8n calls PostgreSQL function via SSH:
   SELECT get_or_create_discord_session(
     'user_id', 'username', 'channel_id', 'agent_hint'
   );
   Returns: session_id (UUID)
   ↓
9. n8n inserts user message into discord_messages table
   ↓
10. n8n counts messages in session:
    - If count = 1: Use --session-id {UUID} (create new session)
    - If count > 1: Use --resume {UUID} (continue session)
    ↓
11. n8n executes Claude Code via SSH:
    /home/<user>/.claude/local/claude \
      --agent homelab-architect \
      --print \
      --permission-mode bypassPermissions \
      --resume {UUID} \
      "how to deploy X"
    ↓
12. Claude Code:
    - Loads session context from ~/.claude/projects/-/{UUID}.jsonl
    - Processes prompt with agent
    - Executes tools (ssh, docker, grep, etc.)
    - Returns response to stdout
    ↓
13. n8n parses Claude output, extracts response
    ↓
14. n8n inserts assistant message into discord_messages
    ↓
15. n8n updates session last_active timestamp
    ↓
16. n8n returns JSON to bot:
    {
      "success": true,
      "response": "To deploy X, you should...",
      "session_id": "6db70575-...",
      "error": null
    }
    ↓
17. Bot formats response and posts to Discord channel
    ↓
18. User sees response in Discord
```

### Multi-Turn Conversation Flow

```
User Message 1: "List containers on Service-Host"
  → Creates session: 6db70575-c50a-4006-8431-279c4d9b06ff
  → Claude executes: ssh service-host 'docker ps'
  → Response: [List of containers]
  → PostgreSQL: discord_messages has 2 rows (user + assistant)
  → Claude saves context to: ~/.claude/projects/-/6db70575-c50a-4006-8431-279c4d9b06ff.jsonl

User Message 2 (within 30 min): "Restart the first one"
  → Reuses session: 6db70575-c50a-4006-8431-279c4d9b06ff
  → n8n uses: --resume 6db70575-c50a-4006-8431-279c4d9b06ff
  → Claude loads prior context (knows which was "first")
  → Claude executes: ssh service-host 'docker restart caddy'
  → PostgreSQL: discord_messages now has 4 rows (2 user + 2 assistant)
  → Claude appends to session file
```

## Database Schema

### discord_sessions Table

```sql
CREATE TABLE discord_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    discord_user_id TEXT NOT NULL,
    discord_username TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'completed', 'timeout')),
    agent_hint TEXT
);

-- Indexes for performance
CREATE INDEX idx_discord_sessions_user_status ON discord_sessions(discord_user_id, status);
CREATE INDEX idx_discord_sessions_user_channel ON discord_sessions(discord_user_id, channel_id);
CREATE INDEX idx_discord_sessions_status ON discord_sessions(status);
CREATE INDEX idx_discord_sessions_last_active ON discord_sessions(last_active);
CREATE INDEX idx_discord_sessions_created_at ON discord_sessions(created_at);
```

**Session States:**
- `active` - Session in use or inactive < 30 minutes
- `completed` - User ended session with "done" or "cancel"
- `timeout` - Inactive > 30 minutes (cleanup task marks these)

**Session Reuse Logic:**
```sql
-- Function: get_or_create_discord_session()
-- Returns existing session if:
--   1. Same user + channel
--   2. Status = 'active'
--   3. last_active > NOW() - 30 minutes
-- Otherwise creates new session
```

### discord_messages Table

```sql
CREATE TABLE discord_messages (
    message_id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES discord_sessions(session_id) ON DELETE CASCADE,
    message_type TEXT NOT NULL CHECK (message_type IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    claude_model TEXT,
    execution_time_ms INTEGER
);

-- Indexes
CREATE INDEX idx_discord_messages_session ON discord_messages(session_id);
CREATE INDEX idx_discord_messages_timestamp ON discord_messages(timestamp);
```

**Message Types:**
- `user` - User's prompt to Jarvis
- `assistant` - Claude Code's response
- `system` - System messages (errors, notifications)

### discord_analytics View

```sql
CREATE VIEW discord_analytics AS
SELECT
    discord_user_id,
    discord_username,
    COUNT(DISTINCT session_id) AS total_sessions,
    MAX(last_active) AS last_seen,
    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_sessions
FROM discord_sessions
GROUP BY discord_user_id, discord_username;
```

## Discord Bot Implementation

### Technology Stack

- **Language:** Python 3.11
- **Framework:** discord.py 2.3+
- **HTTP Client:** aiohttp (for n8n webhook calls)
- **Container:** Docker (python:3.11-slim base image)
- **Runtime:** Management-Host (<management-host-ip>:8001)

### Module Structure

```
app/
├── __init__.py           # Package init
├── bot.py                # Main bot class (JarvisBot)
├── config.py             # Environment variable loader
├── message_parser.py     # Agent hint extraction, session commands
├── rate_limiter.py       # Sliding window rate limiting
└── n8n_client.py         # HTTP client for n8n webhook
```

### Key Classes

**JarvisBot (bot.py):**
```python
class JarvisBot(commands.Bot):
    """Main bot class, extends discord.py Bot."""

    def __init__(self):
        # Load config from environment
        # Initialize Discord intents (message_content, members)
        # Initialize RateLimiter
        # Initialize N8NClient

    async def on_ready(self):
        # Called when bot connects to Discord
        # Logs bot username, channel ID, required role

    async def on_message(self, message: discord.Message):
        # Main message handler
        # Flow:
        #   1. Ignore self messages
        #   2. Check channel match
        #   3. Check bot mentioned
        #   4. Check user role
        #   5. Extract prompt
        #   6. Validate prompt
        #   7. Check session commands
        #   8. Check rate limit
        #   9. Parse agent hint
        #   10. Call n8n webhook
        #   11. Send response to Discord

    def _check_user_role(self, user: discord.Member) -> bool:
        # Verify user has required role

    async def _handle_session_command(self, message, command):
        # Handle "done", "cancel", "new session" commands

    async def _send_response(self, message, result, requests_remaining):
        # Format and send Claude's response to Discord
        # Handles message splitting for >2000 chars
```

**RateLimiter (rate_limiter.py):**
```python
class RateLimiter:
    """Sliding window rate limiter using in-memory deque."""

    def __init__(self, max_requests: int, window_seconds: int):
        # max_requests: 10
        # window_seconds: 300 (5 minutes)
        # user_requests: Dict[user_id, Deque[timestamp]]

    def check_rate_limit(self, user_id: str) -> Tuple[bool, int]:
        # Returns: (allowed, requests_remaining)
        # Algorithm:
        #   1. Get current timestamp
        #   2. Remove timestamps outside window
        #   3. Check if under max_requests
        #   4. Append current timestamp if allowed
        #   5. Return (allowed, remaining)

    def get_reset_time(self, user_id: str) -> int:
        # Returns seconds until oldest request expires

    def cleanup_old_entries(self) -> int:
        # Remove users inactive > 2x window (memory cleanup)
```

**MessageParser (message_parser.py):**
```python
VALID_AGENTS = [
    "homelab-architect",
    "home-assistant-expert",
    "n8n-workflow-architect",
    # ... etc
]

def parse_agent_hint(message: str) -> Tuple[Optional[str], str]:
    # Parses: "ask homelab-architect how do VLANs work?"
    # Returns: ("homelab-architect", "how do VLANs work?")
    # Pattern: ^ask\s+[@']?([a-z-]+)['']?\s+(.+)$

def is_session_command(message: str) -> bool:
    # Returns True if message in ["done", "cancel", "new", "new session"]

def extract_prompt(message: str, bot_mention: str) -> str:
    # Removes bot mention from message

def validate_prompt(prompt: str) -> Tuple[bool, Optional[str]]:
    # Checks: not empty, >= 3 chars, <= 4000 chars
```

**N8NClient (n8n_client.py):**
```python
class N8NClient:
    """Async HTTP client for n8n webhook."""

    def __init__(self, webhook_url: str, auth_token: Optional[str]):
        # Creates aiohttp.ClientSession

    async def execute_claude_code(
        self, user_id, username, channel_id, prompt, agent_hint
    ) -> dict:
        # POST to n8n webhook
        # Payload: {user_id, username, channel_id, prompt, agent_hint, action: "execute"}
        # Returns: {success, response, session_id, error}

    async def end_session(self, user_id, username, channel_id) -> dict:
        # POST to n8n webhook
        # Payload: {user_id, username, channel_id, action: "end_session"}
```

### Configuration

**Environment Variables (.env):**
```bash
# Discord
DISCORD_BOT_TOKEN=          # Bot token from Discord Developer Portal
DISCORD_CHANNEL_ID=         # Channel ID for #jarvis-requests
DISCORD_REQUIRED_ROLE=      # Role name required (homelab-admin)

# n8n
N8N_WEBHOOK_URL=            # Webhook endpoint URL
N8N_WEBHOOK_AUTH=           # Optional: Basic auth token

# Rate Limiting
RATE_LIMIT_REQUESTS=10      # Max requests per window
RATE_LIMIT_WINDOW=300       # Window in seconds

# Logging
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR
```

**Docker Compose:**
```yaml
services:
  jarvis-discord-bot:
    build: .
    container_name: jarvis-discord-bot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./logs:/app/logs
    networks:
      - ai-remediation-service_default  # Shared with postgres-jarvis
```

## n8n Workflow Implementation

### Workflow Nodes (11 total)

```
1. Webhook Trigger
   ↓
2. Get or Create Session (SSH → psql)
   ↓
3. Parse Session ID (Extract UUID from psql output)
   ↓
4. Log User Message (SSH → INSERT into discord_messages)
   ↓
5. Count Messages in Session (SSH → SELECT COUNT)
   ↓
6. Determine Session Mode (IF count = 1: --session-id, ELSE: --resume)
   ↓
7. Execute Claude Code (SSH → /home/<user>/.claude/local/claude)
   ↓
8. Parse Claude Output (Extract response from stdout)
   ↓
9. Log Assistant Response (SSH → INSERT into discord_messages)
   ↓
10. Update Session Timestamp (SSH → UPDATE last_active)
    ↓
11. Respond to Webhook (Return JSON to Discord bot)
```

### Critical Node Details

**Webhook Trigger:**
- Method: POST
- Path: `/webhook/jarvis-discord-claude`
- Mode: **"Using 'Respond to Webhook' Node"** (synchronous)
- Authentication: None (public, but rate limited by bot)

**Get or Create Session (SSH):**
```bash
docker exec -i postgres-jarvis psql -U jarvis -d jarvis -c "
SELECT get_or_create_discord_session(
  '{{ $json.user_id }}',
  '{{ $json.username }}',
  '{{ $json.channel_id }}',
  '{{ $json.agent_hint }}'
);"
```

Output parsed by next node to extract UUID.

**Execute Claude Code (SSH):**
```bash
/home/<user>/.claude/local/claude \
  {{ $json.agent_hint ? '--agent ' + $json.agent_hint : '' }} \
  --print \
  --permission-mode bypassPermissions \
  {{ $json.session_flag }} {{ $json.session_id }} \
  "{{ $json.prompt }}"
```

Where:
- `session_flag` = `--session-id` (first message) or `--resume` (follow-up)
- `session_id` = UUID from PostgreSQL
- `agent_hint` = Optional agent name
- `prompt` = User's question

**Respond to Webhook:**
```json
{
  "success": {{ $json.success || false }},
  "response": "{{ $json.response }}",
  "session_id": "{{ $json.session_id }}",
  "error": {{ $json.error || null }}
}
```

### Session Mode Logic

**First Message (Create Session):**
```bash
--session-id 6db70575-c50a-4006-8431-279c4d9b06ff
```

Creates new session file: `~/.claude/projects/-/6db70575-c50a-4006-8431-279c4d9b06ff.jsonl`

**Follow-up Messages (Resume Session):**
```bash
--resume 6db70575-c50a-4006-8431-279c4d9b06ff
```

Loads existing session file, appends new messages.

**Error: Session ID Already in Use:**
If you use `--session-id` with an existing UUID, Claude returns error. Must use `--resume` for follow-ups.

## Claude Code Integration

### Command Structure

```bash
/home/<user>/.claude/local/claude \
  [--agent AGENT_NAME] \              # Optional: homelab-architect, etc.
  --print \                           # Print response to stdout (machine-readable)
  --permission-mode bypassPermissions \ # Run autonomously (no approval prompts)
  [--session-id UUID | --resume UUID] \ # Session management
  "PROMPT"                            # User's question
```

### Session Persistence

**Session File Location:**
```
/home/<user>/.claude/projects/-/{UUID}.jsonl
```

**File Format (JSONL):**
```json
{"role":"user","content":"What containers are running on Service-Host?"}
{"role":"assistant","content":"I'll check the containers on Service-Host...","tool_calls":[...]}
{"role":"tool","content":"caddy\nfrigate\nadguard..."}
{"role":"assistant","content":"Here are the containers: caddy, frigate, adguard..."}
{"role":"user","content":"Restart the first one"}
{"role":"assistant","content":"I'll restart caddy...","tool_calls":[...]}
```

Each line is a JSON object representing one message in the conversation.

### Permission Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| `acceptEdits` | Prompts for approval before executing commands | Interactive sessions |
| `bypassPermissions` | Runs commands autonomously | Discord bot (no human in loop) |

Discord bot uses `bypassPermissions` because there's no mechanism to prompt user for approval mid-execution.

### Agent Hints

Agents are specialized Claude instances with domain expertise:

```python
VALID_AGENTS = [
    "homelab-architect",        # Infrastructure design
    "homelab-security-auditor", # Security reviews
    "home-assistant-expert",    # HA automations
    "n8n-workflow-architect",   # n8n workflows
    "financial-automation-guru", # Finance tracking
    "omada-network-engineer",   # Networking
    "python-claude-code-expert", # Python dev
    "technical-documenter",     # Documentation
]
```

**Without agent hint:**
Claude auto-selects best agent based on prompt.

**With agent hint:**
Forces specific agent expertise.

## Security Considerations

### Authentication & Authorization

**Discord Layer:**
- Bot token authentication (OAuth2)
- Role-based access control (homelab-admin required)
- Rate limiting per user (10 req / 5 min)

**n8n Layer:**
- No authentication (internal-only webhook)
- Only accessible from Discord bot IP (could add IP whitelist)

**PostgreSQL Layer:**
- Password authentication (jarvis user)
- Only accessible from Management-Host Docker network
- No external access

**Claude Code Layer:**
- Filesystem permissions (runs as t1 user)
- Same safety checks as primary instance
- Logs all commands executed

### Data Privacy

**Stored Data:**
- Discord user IDs (snowflake format, not reversible to username)
- Discord usernames (display names, may change)
- Message content (prompts and responses)
- Session metadata (timestamps, channel IDs)

**Retention:**
- Active sessions: 30 minutes
- Session history: 90 days (then deleted)
- Claude Code session files: 90 days (manual cleanup)

**Access Control:**
- Database: Only accessible from Management-Host
- Session files: Readable by t1 user only
- Logs: Stored in container, rotated (10MB, 3 files)

### Secrets Management

**Encrypted Secrets (SOPS):**
```
/home/<user>/homelab/secrets/shared/discord-webhooks.env
```

Decrypted at deploy time, mounted to container as `.env` (gitignored).

**Never Committed:**
- `.env` (production config)
- `logs/` (application logs)
- Session files (ephemeral)

## Performance Characteristics

### Response Times

**Typical Request:**
```
User posts in Discord        @ T+0s
Bot receives event           @ T+0.1s
Bot validates & POSTs        @ T+0.2s
n8n receives webhook         @ T+0.3s
n8n calls PostgreSQL         @ T+0.5s
n8n executes Claude Code     @ T+1s
Claude processes & responds  @ T+10s
n8n returns to bot           @ T+10.5s
Bot posts to Discord         @ T+11s
```

**Total: ~10-15 seconds** (varies by Claude execution time)

### Resource Usage

**Discord Bot Container:**
- Memory: 128-256 MB
- CPU: <5% (idle), 10-20% (processing)
- Network: Minimal (WebSocket + HTTP)

**PostgreSQL:**
- Disk: ~1 KB per message (text content)
- Expected: 10,000 messages = ~10 MB
- Indexes add ~30% overhead

**Claude Code Session Files:**
- Disk: ~500 bytes per message (JSONL)
- Expected: 100 sessions × 10 messages × 500 bytes = 500 KB

### Scalability

**Current Limits:**
- Rate limit: 10 req / 5 min / user (60 req/hr/user)
- Concurrent users: Limited by Discord bot (can handle 100+)
- Database: PostgreSQL can handle 1000s of sessions
- n8n: Single workflow execution at a time (queues if busy)

**Bottlenecks:**
- Claude Code execution time (10s average)
- n8n synchronous workflow (blocks while executing)
- SSH latency (VPS-Host → Management-Host VPN tunnel)

**Future Scaling:**
- Move n8n to Management-Host (eliminate SSH hop)
- Async workflow mode (queue-based)
- Multiple n8n workers (parallel execution)

## Testing

### Unit Tests

**Rate Limiter:**
```python
# tests/test_rate_limiter.py
def test_rate_limit_basic():
    limiter = RateLimiter(max_requests=3, window_seconds=10)
    user_id = "test_user"

    # First 3 requests allowed
    for i in range(3):
        allowed, remaining = limiter.check_rate_limit(user_id)
        assert allowed is True
        assert remaining == 2 - i

    # 4th request blocked
    allowed, remaining = limiter.check_rate_limit(user_id)
    assert allowed is False
```

**Message Parser:**
```python
# tests/test_message_parser.py
def test_parse_agent_hint():
    agent, prompt = parse_agent_hint("ask homelab-architect how to deploy")
    assert agent == "homelab-architect"
    assert prompt == "how to deploy"

def test_no_agent_hint():
    agent, prompt = parse_agent_hint("how to deploy")
    assert agent is None
    assert prompt == "how to deploy"
```

### Integration Tests

**End-to-End Test (Manual):**
```
1. Start Discord bot: docker compose up -d
2. Post in #jarvis-requests: @Jarvis hello
3. Verify response within 15 seconds
4. Post follow-up: @Jarvis what is 2 + 2?
5. Verify Claude remembers context ("4")
6. Check PostgreSQL: SELECT * FROM discord_sessions ORDER BY created_at DESC LIMIT 1;
7. Verify session has 2 messages
```

**n8n Workflow Test:**
```bash
curl -X POST https://n8n.yourdomain.com/webhook/jarvis-discord-claude \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "username": "Test",
    "channel_id": "123",
    "prompt": "hello",
    "agent_hint": null
  }'
```

Expected response:
```json
{
  "success": true,
  "response": "Hello! How can I help you with The Burrow homelab today?",
  "session_id": "6db70575-...",
  "error": null
}
```

## Deployment Pipeline

### Development Workflow

```
1. Edit code locally in VSCode
   ↓
2. Test locally (optional: python -m app.bot with .env)
   ↓
3. Commit to git: git commit -m "feat: add feature"
   ↓
4. Push to GitHub: git push origin main
   ↓
5. SSH to Management-Host: ssh management-host
   ↓
6. Pull changes: cd /home/<user>/homelab && git pull
   ↓
7. Rebuild container: cd projects/jarvis-discord-bot && docker compose build
   ↓
8. Restart service: docker compose up -d
   ↓
9. Verify logs: docker logs -f jarvis-discord-bot
```

### Production Deployment

**Build:**
```bash
cd /home/<user>/homelab/projects/jarvis-discord-bot
docker compose build
```

**Deploy:**
```bash
docker compose down
docker compose up -d
```

**Verify:**
```bash
# Check container running
docker ps | grep jarvis-discord-bot

# Check Discord connection
docker logs jarvis-discord-bot | grep "Logged in as"

# Test in Discord
# @Jarvis hello
```

**Rollback:**
```bash
# If deployment fails, rollback code
git log --oneline -5               # Find previous commit
git checkout <commit_hash>

# Rebuild and redeploy
docker compose build
docker compose up -d
```

## Monitoring & Observability

### Logs

**Discord Bot Logs:**
```bash
# Container logs (stdout/stderr)
docker logs jarvis-discord-bot

# Application log file
tail -f /home/<user>/homelab/projects/jarvis-discord-bot/logs/bot.log
```

**Log Format:**
```
2025-12-13 10:23:45 [INFO] bot: Logged in as Jarvis#2673 (ID: 1447434205112827906)
2025-12-13 10:24:12 [INFO] bot: Received mention from DeadEye360 (98554078157615104): hello
2025-12-13 10:24:22 [INFO] bot: Response sent to DeadEye360, session 6db70575, 127 chars
```

**PostgreSQL Logs:**
```bash
docker logs postgres-jarvis --tail 50
```

**n8n Execution Logs:**
Access via n8n UI: https://n8n.yourdomain.com > Executions

### Metrics

**Future: Prometheus Metrics Endpoint:**

Planned metrics:
- `jarvis_discord_requests_total` - Total requests by user
- `jarvis_discord_response_time_seconds` - Response time histogram
- `jarvis_discord_rate_limits_total` - Rate limit hits by user
- `jarvis_discord_errors_total` - Errors by type
- `jarvis_discord_active_sessions` - Current active sessions

**Database Metrics (Manual):**
```sql
-- Total sessions
SELECT COUNT(*) FROM discord_sessions;

-- Active sessions
SELECT COUNT(*) FROM discord_sessions WHERE status = 'active';

-- Messages per session (average)
SELECT AVG(message_count) FROM (
  SELECT session_id, COUNT(*) AS message_count
  FROM discord_messages
  GROUP BY session_id
) sub;

-- User activity (last 7 days)
SELECT * FROM discord_analytics WHERE last_seen > NOW() - INTERVAL '7 days';
```

## Extension Points

### Adding New Agents

**1. Define agent in bot:**
```python
# app/message_parser.py
VALID_AGENTS = [
    "homelab-architect",
    "my-new-agent",  # Add here
]
```

**2. Create agent in Claude Code:**

Agents are defined in `~/.claude/agents/` (see Claude Code documentation).

**3. Redeploy bot:**
```bash
docker compose build
docker compose up -d
```

### Adding New Session Commands

**1. Update parser:**
```python
# app/message_parser.py
def is_session_command(message: str) -> bool:
    message_lower = message.strip().lower()
    return message_lower in ["done", "cancel", "new", "new session", "my_command"]
```

**2. Handle command:**
```python
# app/bot.py
async def _handle_session_command(self, message, command):
    if command_lower == "my_command":
        # Handle new command
        await message.channel.send("Command executed!")
```

### Adding Health Check Endpoint

**Future enhancement:**

```python
# app/bot.py
from aiohttp import web

async def health_check(request):
    return web.json_response({
        "status": "healthy",
        "discord_connected": bot.is_ready(),
        "sessions": {
            "total_users": len(bot.rate_limiter.user_requests),
        }
    })

# In JarvisBot.__init__:
self.web_app = web.Application()
self.web_app.router.add_get('/health', health_check)
web.run_app(self.web_app, host='0.0.0.0', port=8001)
```

## Troubleshooting & Debugging

### Enable Debug Logging

**Edit .env:**
```bash
LOG_LEVEL=DEBUG
```

**Restart:**
```bash
docker restart jarvis-discord-bot
```

**View logs:**
```bash
docker logs -f jarvis-discord-bot
```

Debug logs show:
- Full message content
- Rate limiter decisions
- n8n payload/response
- Detailed error traces

### Common Issues

**1. "Session ID already in use" Error:**

**Cause:** Using `--session-id` with existing UUID.

**Fix:** n8n workflow must use `--resume` for follow-up messages (count > 1).

**2. Webhook Returns HTML Instead of JSON:**

**Cause:** n8n webhook mode is "When Last Node Finishes" instead of "Using 'Respond to Webhook' Node".

**Fix:** In n8n workflow settings, change webhook mode to synchronous.

**3. Multi-Turn Not Working (Creates New Session Each Time):**

**Cause:** PostgreSQL function `get_or_create_discord_session()` not reusing sessions.

**Debug:**
```sql
SELECT session_id, last_active, NOW() - last_active AS inactive_duration
FROM discord_sessions
WHERE discord_user_id = 'USER_ID'
ORDER BY last_active DESC;
```

If `inactive_duration > 30 minutes`, new session is expected.

**4. Bot Not Receiving Messages:**

**Cause:** Missing `message_content` intent.

**Fix:** Verify intents in bot initialization:
```python
intents = discord.Intents.default()
intents.message_content = True  # Required!
intents.members = True          # Required for role checking
```

## References

**Discord.py Documentation:**
https://discordpy.readthedocs.io/en/stable/

**n8n Documentation:**
https://docs.n8n.io/

**Claude Code (internal):**
`/home/<user>/.claude/local/claude --help`

**Project Files:**
- User Guide: `USER_GUIDE.md`
- Admin Guide: `ADMIN_GUIDE.md`
- Implementation Status: `IMPLEMENTATION_STATUS.md`
- Technical Reference: `CLAUDE.md`
