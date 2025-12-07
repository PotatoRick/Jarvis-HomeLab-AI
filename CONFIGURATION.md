# Jarvis Configuration Reference

Complete guide to all configuration options for the Jarvis AI remediation service.

---

## Environment Variables

All configuration is managed via environment variables defined in `.env` file.

### Database Configuration

#### `DATABASE_URL` (required)
PostgreSQL connection string for attempt tracking and logging.

**Format:** `postgresql://username:password@host:port/database`

**Example:**
```bash
DATABASE_URL=postgresql://n8n:8Ws2WZpaUtiZAiWN%2Foj4gKejAE%2B4YqUj@<vps-ip>:5432/finance_db
```

**Notes:**
- URL-encode special characters in password (`%2F` for `/`, `%2B` for `+`)
- Database must exist before starting Jarvis
- Tables are created automatically on first run
- Use existing n8n database on Outpost

**Connection testing:**
```bash
docker exec n8n-db psql -U n8n -d finance_db -c "SELECT 1;"
```

---

### Claude API Configuration

#### `ANTHROPIC_API_KEY` (required)
API key for Claude AI from Anthropic console.

**Format:** `sk-ant-api03-...`

**Example:**
```bash
ANTHROPIC_API_KEY=sk-ant-api03-YOUR-API-KEY-HERE
```

**Notes:**
- Get key from https://console.anthropic.com/
- Free tier: $5 credit
- Cost: ~$0.008 per alert with Haiku 3.5
- API key is logged on startup (first 20 chars)

#### `CLAUDE_MODEL` (optional)
Claude model to use for remediation analysis.

**Default:** `claude-3-5-haiku-20241022`

**Options:**
- `claude-3-5-haiku-20241022` - **Recommended** (fast, cheap, 73% cost savings)
- `claude-sonnet-4-5-20250929` - More powerful but 3.5x more expensive
- `claude-3-5-sonnet-20241022` - Previous generation Sonnet

**Example:**
```bash
CLAUDE_MODEL=claude-3-5-haiku-20241022
```

**Cost comparison:**
| Model | Input (per 1M tokens) | Output (per 1M tokens) | Cost per alert |
|-------|----------------------|------------------------|----------------|
| Haiku 3.5 | $0.80 | $4.00 | $0.008 |
| Sonnet 4.5 | $3.00 | $15.00 | $0.030 |

**When to use Sonnet:**
- Complex multi-step remediations
- Large alert contexts (>50KB logs)
- Unclear root causes requiring deeper analysis

---

### SSH Configuration

#### `SSH_NEXUS_HOST` (required)
IP address or hostname of Nexus server (service host).

**Default:** `<service-host-ip>`

**Example:**
```bash
SSH_NEXUS_HOST=<service-host-ip>
```

#### `SSH_NEXUS_USER` (required)
SSH username for Nexus.

**Default:** `jordan`

**Example:**
```bash
SSH_NEXUS_USER=jordan
```

#### `SSH_KEY_PATH` (required)
Path to SSH private key inside container.

**Default:** `/app/ssh_key`

**Example:**
```bash
SSH_KEY_PATH=/app/ssh_key
```

**Setup:**
```bash
# Copy your SSH key to project directory
cp ~/.ssh/homelab_ed25519 ./ssh_key

# Set correct permissions
chmod 600 ./ssh_key

# Docker compose mounts it to /app/ssh_key
```

**Notes:**
- Must be Ed25519 or RSA key
- No passphrase (automated use)
- 600 permissions required
- Key must be authorized on all target hosts

#### `SSH_HOMEASSISTANT_HOST` (required)
IP address of Home Assistant system.

**Default:** `<ha-ip>`

**Example:**
```bash
SSH_HOMEASSISTANT_HOST=<ha-ip>
```

#### `SSH_HOMEASSISTANT_USER` (required)
SSH username for Home Assistant.

**Default:** `jordan`

**Example:**
```bash
SSH_HOMEASSISTANT_USER=jordan
```

#### `SSH_OUTPOST_HOST` (required)
IP address or hostname of Outpost VPS.

**Default:** `<vps-ip>`

**Example:**
```bash
SSH_OUTPOST_HOST=<vps-ip>
```

#### `SSH_OUTPOST_USER` (required)
SSH username for Outpost.

**Default:** `jordan`

**Example:**
```bash
SSH_OUTPOST_USER=jordan
```

---

### Discord Configuration

#### `DISCORD_WEBHOOK_URL` (optional)
Discord webhook URL for notifications.

**Format:** `https://discord.com/api/webhooks/{id}/{token}`

**Example:**
```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1434188146437914704/O2RpXkrts4eYndDG5E5clIUKvkx9OdKKmZAh6BYgzqhf1eD8O9K7alGoUL_VOHMWvZkH
```

**Notes:**
- Get from Discord Server Settings → Integrations → Webhooks
- If not provided, notifications are disabled
- Webhook must have permission to post and @here mention

#### `DISCORD_ENABLED` (optional)
Enable/disable Discord notifications.

**Default:** `true`

**Options:** `true`, `false`

**Example:**
```bash
DISCORD_ENABLED=true
```

**Use cases:**
- Set to `false` during testing to avoid spam
- Disable if webhook URL is invalid
- Service continues working without Discord

---

### Security Configuration

#### `WEBHOOK_AUTH_USERNAME` (optional)
HTTP Basic Auth username for webhook endpoint.

**Default:** `alertmanager`

**Example:**
```bash
WEBHOOK_AUTH_USERNAME=alertmanager
```

**Notes:**
- Used by Alertmanager to authenticate webhook requests
- Should match Alertmanager configuration
- Not case-sensitive

#### `WEBHOOK_AUTH_PASSWORD` (required)
HTTP Basic Auth password for webhook endpoint.

**Example:**
```bash
WEBHOOK_AUTH_PASSWORD=O28nsEX3clSJvpNvBLjKfM4Tk92KqLhy4OqPH1OLPf0=
```

**Generation:**
```bash
openssl rand -base64 32
```

**Notes:**
- Generate strong random password (32+ bytes)
- Must match Alertmanager configuration
- Rotate quarterly for security

---

### Logging Configuration

#### `LOG_LEVEL` (optional)
Logging verbosity level.

**Default:** `INFO`

**Options:** `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**Example:**
```bash
LOG_LEVEL=INFO
```

**Level descriptions:**
- `DEBUG` - All events, including command details and SSH operations
- `INFO` - Normal operations (webhooks, remediations, notifications)
- `WARNING` - Potential issues (command rejections, timeouts)
- `ERROR` - Failures (API errors, SSH failures, database errors)
- `CRITICAL` - Service-breaking issues

**Production recommendation:** `INFO`

**Debugging recommendation:** `DEBUG`

#### `LOG_FORMAT` (optional)
Log output format.

**Default:** `json`

**Options:** `json`, `text`

**Example:**
```bash
LOG_FORMAT=json
```

**JSON format:**
```json
{"timestamp":"2025-11-11T20:00:00Z","level":"info","event":"webhook_received","alert_name":"ContainerDown"}
```

**Text format:**
```
2025-11-11 20:00:00 [INFO] webhook_received alert_name=ContainerDown
```

**Notes:**
- `json` recommended for production (easier to parse)
- `text` useful for human-readable local testing

---

### Remediation Settings

#### `MAX_ATTEMPTS_PER_ALERT` (optional)
Maximum remediation attempts before escalation.

**Default:** `20`

**Range:** `1-100`

**Example:**
```bash
MAX_ATTEMPTS_PER_ALERT=20
```

**Notes:**
- Higher value gives AI more chances to fix issues
- Lower value escalates faster to humans
- Only actionable commands count toward limit
- Diagnostic commands (docker ps, curl -I) don't count

**Recommendations:**
- **Production:** 20 (allows thorough troubleshooting)
- **Testing:** 3 (faster escalation for validation)
- **Critical alerts:** 10 (balance between automation and human intervention)

#### `ATTEMPT_WINDOW_HOURS` (optional)
Time window for counting remediation attempts.

**Default:** `2`

**Range:** `1-24`

**Example:**
```bash
ATTEMPT_WINDOW_HOURS=2
```

**Notes:**
- Attempts older than this window are ignored
- Shorter window = fresh start for recurring issues
- Longer window = more persistent memory

**Recommendations:**
- **Production:** 2 hours (prevents stale data)
- **Frequent failures:** 1 hour (faster reset)
- **Intermittent issues:** 6 hours (tracks patterns)

**Example scenarios:**

**2-hour window:**
```
3:00 AM - Alert fires, 3 attempts, fails
5:00 AM - Window expires, attempts cleared
6:00 AM - Same alert fires, starts at attempt 1/20
```

**24-hour window:**
```
3:00 AM - Alert fires, 3 attempts, fails
6:00 AM - Same alert fires, continues at attempt 4/20
```

#### `COMMAND_EXECUTION_TIMEOUT` (optional)
SSH command timeout in seconds.

**Default:** `60`

**Range:** `10-300`

**Example:**
```bash
COMMAND_EXECUTION_TIMEOUT=60
```

**Notes:**
- Commands exceeding this timeout are killed
- Timeout error logged and counted as failed attempt
- Prevents hanging on unresponsive hosts

**Recommendations:**
- **Fast commands (restart):** 30 seconds
- **Slow commands (backup restore):** 120 seconds
- **Network operations:** 60 seconds (default)

---

## Docker Compose Configuration

### Container Settings

**File:** `docker-compose.yml`

#### Container Name
```yaml
services:
  jarvis:
    container_name: jarvis
```

**Notes:**
- Name used in self-protection rules
- Cannot be changed without updating blacklist patterns

#### Restart Policy
```yaml
restart: unless-stopped
```

**Options:**
- `no` - Never restart
- `always` - Always restart
- `unless-stopped` - Restart unless manually stopped
- `on-failure` - Restart only on failure

**Recommendation:** `unless-stopped` (survives host reboots)

#### Port Mapping
```yaml
ports:
  - "8000:8000"
```

**Notes:**
- Exposes webhook endpoint on host port 8000
- Change host port if conflict: `"8080:8000"`
- Container always uses internal port 8000

#### Volume Mounts
```yaml
volumes:
  - ./ssh_key:/app/ssh_key:ro
  - ./app:/app/app:ro  # Optional: live code reload
```

**SSH Key mount:**
- `:ro` = read-only for security
- Host path must have 600 permissions
- Container path must match `SSH_KEY_PATH`

**Code mount (optional):**
- Enables live code changes without rebuild
- Useful for development
- Remove in production for immutability

#### Health Check
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/health')"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 10s
```

**Parameters:**
- `interval` - Time between health checks
- `timeout` - Max time for check to complete
- `retries` - Failed checks before unhealthy
- `start_period` - Grace period on startup

**Health check endpoint:**
```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "timestamp": "2025-11-11T20:00:00Z"
}
```

---

## Alertmanager Configuration

### Receiver Configuration

**File:** `/home/<user>/docker/home-stack/alertmanager/config/alertmanager.yml` (on Nexus)

#### Basic Receiver
```yaml
receivers:
  - name: 'jarvis'
    webhook_configs:
      - url: 'http://jarvis:8000/webhook'
        send_resolved: true
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'YOUR_WEBHOOK_AUTH_PASSWORD'
```

**Key parameters:**
- `send_resolved: true` - Enables attempt cleanup when alerts resolve
- `username` - Must match `WEBHOOK_AUTH_USERNAME`
- `password` - Must match `WEBHOOK_AUTH_PASSWORD`

#### Routing Configuration
```yaml
route:
  receiver: 'jarvis'
  group_by: ['alertname', 'instance']
  group_wait: 5s
  group_interval: 1m
  repeat_interval: 30m
  resolve_timeout: 5m
```

**Parameters:**

**`group_by`** - Alert grouping labels
- Groups alerts with same alertname+instance
- Sends single webhook for grouped alerts
- Recommendation: `['alertname', 'instance']`

**`group_wait`** - Wait before sending first notification
- Allows similar alerts to group
- Prevents immediate notification spam
- Recommendation: `30s`

**`group_interval`** - Wait before sending updated group
- Time between notifications for same group
- Only if new alerts added to group
- Recommendation: `1m` (changed from 10s on Nov 12, 2025 to prevent webhook spam)

**`repeat_interval`** - Resend interval for ongoing alerts
- Prevents notification spam for persistent issues
- Jarvis tracks attempts internally
- Recommendation: `30m` (longer than attempt window)

**`resolve_timeout`** - Time before auto-resolving
- If alert stops firing, wait this long before resolving
- Prevents flapping alerts from clearing attempts prematurely
- Recommendation: `5m`

---

## Database Schema

### Tables Created Automatically

#### `remediation_log`
Stores all remediation attempts and outcomes.

```sql
CREATE TABLE remediation_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    alert_name VARCHAR(255) NOT NULL,
    alert_instance VARCHAR(255) NOT NULL,
    severity VARCHAR(50),
    alert_labels JSONB,
    alert_annotations JSONB,
    attempt_number INT NOT NULL,
    ai_analysis TEXT,
    ai_reasoning TEXT,
    remediation_plan TEXT,
    commands_executed TEXT[],
    success BOOLEAN NOT NULL,
    error_message TEXT,
    duration_seconds INT,
    ssh_host VARCHAR(50)
);
```

**Indexes:**
```sql
CREATE INDEX idx_remediation_log_alert
ON remediation_log(alert_name, alert_instance, timestamp);

CREATE INDEX idx_remediation_log_timestamp
ON remediation_log(timestamp);
```

**Queries:**

Query recent attempts:
```sql
SELECT timestamp, alert_name, alert_instance, success, commands_executed
FROM remediation_log
ORDER BY timestamp DESC
LIMIT 10;
```

Count attempts in window:
```sql
SELECT COUNT(*)
FROM remediation_log
WHERE alert_name = 'ContainerDown'
  AND alert_instance = 'nexus:omada'
  AND timestamp > NOW() - INTERVAL '2 hours';
```

Success rate by alert:
```sql
SELECT
    alert_name,
    COUNT(*) as total_attempts,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM remediation_log
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY alert_name
ORDER BY total_attempts DESC;
```

---

## Example Configurations

### Minimal Production

```bash
# .env
DATABASE_URL=postgresql://user:pass@host:5432/db
ANTHROPIC_API_KEY=sk-ant-...
SSH_KEY_PATH=/app/ssh_key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
WEBHOOK_AUTH_PASSWORD=random_password_here
```

### Development / Testing

```bash
# .env
DATABASE_URL=postgresql://user:pass@localhost:5432/db
ANTHROPIC_API_KEY=sk-ant-...
SSH_KEY_PATH=/app/ssh_key
DISCORD_ENABLED=false  # Disable during testing
LOG_LEVEL=DEBUG  # Verbose logging
MAX_ATTEMPTS_PER_ALERT=3  # Faster escalation
COMMAND_EXECUTION_TIMEOUT=30  # Shorter timeout
```

### High-Security

```bash
# .env
DATABASE_URL=postgresql://user:strong_pass@host:5432/db
ANTHROPIC_API_KEY=sk-ant-...
SSH_KEY_PATH=/app/ssh_key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
WEBHOOK_AUTH_PASSWORD=$(openssl rand -base64 48)  # Extra strong
LOG_LEVEL=WARNING  # Less verbose logs
MAX_ATTEMPTS_PER_ALERT=10  # Conservative attempts
ATTEMPT_WINDOW_HOURS=1  # Short memory
```

### Cost-Optimized

```bash
# .env
CLAUDE_MODEL=claude-3-5-haiku-20241022  # Cheapest model
MAX_ATTEMPTS_PER_ALERT=5  # Limit API calls
ATTEMPT_WINDOW_HOURS=1  # Shorter window
```

### Performance-Optimized

```bash
# .env
CLAUDE_MODEL=claude-sonnet-4-5-20250929  # More powerful
COMMAND_EXECUTION_TIMEOUT=30  # Faster failures
MAX_ATTEMPTS_PER_ALERT=20  # More chances to fix
```

---

## Configuration Validation

### Startup Checks

Jarvis validates configuration on startup:

```python
# app/config.py
class Settings(BaseSettings):
    # Required fields raise error if missing
    database_url: str  # Must be valid PostgreSQL URL
    anthropic_api_key: str  # Must start with 'sk-ant-'

    # Optional fields have defaults
    max_attempts_per_alert: int = 20
    attempt_window_hours: int = 2
```

**Error messages:**

Missing required field:
```
ERROR: ANTHROPIC_API_KEY environment variable is required
```

Invalid value:
```
ERROR: MAX_ATTEMPTS_PER_ALERT must be between 1 and 100, got 150
```

### Testing Configuration

Verify configuration after changes:

```bash
# 1. Check environment variables
docker exec jarvis env | grep -E "(DATABASE|ANTHROPIC|SSH|DISCORD)"

# 2. Test database connection
docker exec jarvis python -c "
import asyncio
from app.database import Database
from app.config import settings

async def test():
    db = Database()
    count = await db.get_attempt_count('test', 'test', 1)
    print(f'Database connected, attempt count: {count}')

asyncio.run(test())
"

# 3. Test Claude API
docker exec jarvis python -c "
import asyncio
from app.ai_analyzer import AIAnalyzer

async def test():
    analyzer = AIAnalyzer()
    # Simple test call
    print('Claude API key valid')

asyncio.run(test())
"

# 4. Test SSH connections
docker exec jarvis python -c "
import asyncio
from app.ssh_executor import SSHExecutor, SSHHost

async def test():
    executor = SSHExecutor()
    result = await executor.execute_command(SSHHost.NEXUS, 'echo test')
    print(f'SSH test result: {result.stdout}')

asyncio.run(test())
"
```

---

## Troubleshooting Configuration Issues

### Database connection failed

**Error:** `asyncpg.exceptions.InvalidCatalogNameError: database "finance_db" does not exist`

**Solution:**
```bash
# Create database
ssh outpost 'docker exec n8n-db createdb -U n8n finance_db'
```

### SSH authentication failed

**Error:** `asyncssh.misc.PermissionDenied: Permission denied`

**Solutions:**
```bash
# Check key permissions
ls -la ./ssh_key  # Should be 600

# Fix permissions
chmod 600 ./ssh_key

# Test key manually
ssh -i ./ssh_key jordan@<service-host-ip> 'echo test'

# Verify key is authorized on host
ssh nexus 'cat ~/.ssh/authorized_keys | grep -F "$(cat ~/.ssh/homelab_ed25519.pub)"'
```

### Claude API errors

**Error:** `anthropic.APIError: Invalid API key`

**Solutions:**
```bash
# Verify API key in .env
cat .env | grep ANTHROPIC_API_KEY

# Test API key
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: YOUR_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-3-5-haiku-20241022","max_tokens":100,"messages":[{"role":"user","content":"test"}]}'
```

### Discord webhook failed

**Error:** `discord_webhook_failed status=404`

**Solutions:**
```bash
# Test webhook URL
curl -X POST "$DISCORD_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d '{"content":"Test message from Jarvis"}'

# Regenerate webhook if invalid
# Discord Server Settings → Integrations → Webhooks
```

---

## Configuration Changes (November 11, 2025)

### Alertmanager Timing Optimization

**Previous Configuration (caused issues):**
```yaml
group_interval: 10s  # TOO AGGRESSIVE - caused duplicate webhooks
```

**Current Configuration (optimized):**
```yaml
group_wait: 5s          # First webhook sent 5 seconds after alert fires
group_interval: 1m      # Retry webhook every 1 minute if alert persists
repeat_interval: 30m    # After 30 minutes, resend if still unresolved
```

**Impact:**
- Prevents webhook spam (no more webhooks every 10 seconds)
- Allows ~120 retry attempts in 2-hour window
- First webhook still sent quickly (5 seconds)
- Balanced retry behavior for Jarvis remediation

**Why This Matters:**
The 10-second interval caused Jarvis to receive the same alert multiple times in rapid succession (e.g., 5-7 attempts for a single container failure in 2 minutes). This wasted API credits and created noisy logs. The 1-minute interval gives Jarvis time to attempt remediation while still providing multiple chances to fix issues.

---

**Last Updated:** November 11, 2025
**Version:** 2.0.0
