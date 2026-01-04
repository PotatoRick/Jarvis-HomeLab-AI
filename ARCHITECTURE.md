# Jarvis Architecture

This document provides an in-depth look at the system design, component interactions, and key implementation details of the Jarvis AI remediation service.

---

## System Overview

```
┌─────────────────────┐
│   Alertmanager      │
│   (Prometheus)      │
└──────────┬──────────┘
           │ Webhook (HTTP POST)
           │ /webhook endpoint
           ▼
┌──────────────────────────────────────────────────────────┐
│                    Jarvis (FastAPI)                      │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Webhook    │──│   Database   │──│   Discord    │  │
│  │   Handler    │  │   Query      │  │   Notifier   │  │
│  └──────┬───────┘  └──────────────┘  └──────────────┘  │
│         │                                                │
│         ▼                                                │
│  ┌──────────────┐                                       │
│  │   Claude AI  │                                       │
│  │   Analyzer   │                                       │
│  └──────┬───────┘                                       │
│         │                                                │
│         ▼                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Command    │──│   Command    │──│     SSH      │  │
│  │   Validator  │  │   Executor   │  │   Executor   │  │
│  └──────────────┘  └──────────────┘  └──────┬───────┘  │
│                                              │           │
└──────────────────────────────────────────────┼───────────┘
                                               │
                                               ▼
                 ┌─────────────────────────────────────────┐
                 │   Target Hosts (SSH)                   │
                 │                                         │
                 │  ┌────────┐  ┌────────┐  ┌────────┐   │
                 │  │ Nexus  │  │  Home  │  │Outpost │   │
                 │  │  Host  │  │  Asst  │  │  VPS   │   │
                 │  └────────┘  └────────┘  └────────┘   │
                 └─────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Webhook Handler (`main.py`)

**Purpose:** Receive and process Prometheus/Alertmanager webhooks

**Key Responsibilities:**
- HTTP Basic Auth validation
- Alert filtering (status=firing)
- Container-specific instance formatting
- Resolved alert handling (clears attempts)
- Maintenance mode checks
- Orchestration of remediation flow

**Alert Processing Logic:**
```python
# app/main.py:268-296
# Build container-specific instance for ContainerDown alerts
# First check if Prometheus already formatted instance as "host:container"
if ":" in alert.labels.instance and alert_name == "ContainerDown":
    # Instance already formatted as "host:container" by Prometheus
    alert_instance = alert.labels.instance
elif alert_name == "ContainerDown" and hasattr(alert.labels, "container") and hasattr(alert.labels, "host"):
    # Build container-specific instance from separate labels
    alert_instance = f"{alert.labels.host}:{alert.labels.container}"
else:
    # Use default instance for non-container alerts
    alert_instance = alert.labels.instance
```

**Resolved Alert Handling:**
```python
# app/main.py:144-163
# When alert resolves, clear attempt history
if webhook.status.value == "resolved":
    cleared_count = await db.clear_attempts(alert_name, alert_instance)
    logger.info("attempts_cleared_on_resolution", cleared_count=cleared_count)
```

### 2. Database Manager (`database.py`)

**Purpose:** PostgreSQL operations for attempt tracking and history

**Schema:**
```sql
CREATE TABLE remediation_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
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

CREATE INDEX idx_remediation_log_alert ON remediation_log(alert_name, alert_instance, timestamp);
CREATE INDEX idx_remediation_log_timestamp ON remediation_log(timestamp);
```

**Key Methods:**
- `log_attempt()` - Record remediation attempt
- `get_attempts()` - Query attempts within window (2 hours)
- `clear_attempts()` - Delete attempts when alert resolves
- `get_previous_attempts()` - Fetch history for escalation notifications

**Attempt Window Logic:**
```python
# app/database.py:156-170
# Only count attempts within the configured window
query = """
    SELECT COUNT(*)
    FROM remediation_log
    WHERE alert_name = $1
      AND alert_instance = $2
      AND timestamp > NOW() - INTERVAL '1 hour' * $3
"""
count = await conn.fetchval(query, alert_name, alert_instance, window_hours)
```

### 3. Claude AI Analyzer (`ai_analyzer.py`)

**Purpose:** Interface with Claude API for alert analysis and command generation

**Model:** Claude 3.5 Haiku (`claude-3-5-haiku-20241022`)

**Prompt Structure:**
```python
You are an experienced SRE managing The Burrow homelab infrastructure.

# System Context
- Nexus (192.168.0.11): Service host (Docker containers)
- Home Assistant (192.168.0.10): Automation hub
- Outpost (72.60.163.242): Cloud gateway (VPS)

# Your Task
Analyze the alert and provide remediation commands.

# Alert Details
{alert_name}: {description}
Instance: {instance}
Severity: {severity}

# Previous Attempts
{attempt_history}

# Requirements
1. Analyze root cause
2. Suggest safe commands
3. Explain expected outcome
4. Consider previous failures
```

**Response Format:**
```json
{
  "analysis": "Container crashed due to OOM",
  "commands": ["docker restart container_name"],
  "reasoning": "Restarting will clear memory and restore service",
  "expected_outcome": "Container healthy within 30 seconds"
}
```

### 3b. Claude CLI Mode (`claude_cli.py`)

**Purpose:** Alternative AI backend using Claude Code subscription instead of API

**Architecture:**
```
Docker Container                    Skynet Host
┌─────────────────┐                ┌─────────────────────────────────┐
│  Jarvis Core    │   SSH/SFTP    │  Claude CLI                     │
│  ┌───────────┐  │ ──────────────▶│  ┌───────────┐  ┌───────────┐ │
│  │claude_cli │──┘                │  │ /home/t1/ │──│    MCP    │ │
│  │   .py     │                   │  │ .claude/  │  │  Servers  │ │
│  └───────────┘                   │  │ local/    │  └─────┬─────┘ │
│                                  │  │ claude    │        │       │
└─────────────────┘                │  └───────────┘        ▼       │
                                   │                 Infrastructure │
                                   │  (diagnostics, logs, status)  │
                                   └─────────────────────────────────┘
```

**Execution Flow:**
1. Docker container SSHs to Skynet host
2. Writes prompt to temp file via SFTP (avoids shell escaping issues)
3. Pipes prompt to Claude CLI via stdin
4. Claude CLI invokes MCP diagnostic tools
5. Returns structured JSON with remediation commands
6. Jarvis Core parses response and executes commands

**Key Implementation:**
```python
# app/claude_cli.py:270-291
async with asyncssh.connect(...) as conn:
    # Write prompt to temp file using SFTP
    async with conn.start_sftp_client() as sftp:
        async with sftp.open(temp_file, 'w') as f:
            await f.write(prompt)

    # Run CLI with prompt piped via stdin
    cmd = (
        f'cd /home/t1/homelab && '
        f'cat {temp_file} | '
        f'{settings.claude_cli_path} '
        f'--print '
        f'--permission-mode bypassPermissions '
        f'{model_flag}'
        f'; rm -f {temp_file}'
    )
    result = await conn.run(cmd, check=False)
```

**MCP Tools Available:**
- `get_container_diagnostics` - Container health, logs, state
- `get_system_state` - Disk, memory, CPU, Docker status
- `gather_logs` - Docker or systemd logs
- `check_service_status` - Service running status
- `run_diagnostic_command` - Safe read-only commands

**Configuration:**
```bash
USE_CLAUDE_CLI=true
CLAUDE_CLI_PATH=/home/t1/.claude/local/claude
SSH_SKYNET_HOST=host.docker.internal
SSH_SKYNET_USER=t1
```

**Trade-offs vs API Mode:**

| Aspect | API Mode | CLI Mode |
|--------|----------|----------|
| Cost | Pay-per-token | Flat subscription |
| Latency | ~10-30s | ~60-90s |
| MCP Tools | Not available | Full diagnostic access |
| Prompt Size | Limited by API | Larger context window |
| Best For | High volume | Complex diagnosis |

### 4. Command Validator (`command_validator.py`)

**Purpose:** Safety checks to prevent destructive operations

**Validation Approach:** Blacklist-only (default allow)

**Dangerous Patterns (68 patterns):**
```python
DANGEROUS_PATTERNS = [
    (r'rm\s+-rf', "Recursive deletion detected"),
    (r'\breboot\b', "System reboot detected"),
    (r'\biptables\b', "Firewall modification detected"),
    (r'docker\s+stop\s+.*jarvis', "Cannot stop Jarvis"),
    (r'docker\s+stop\s+.*n8n-db', "Cannot stop database"),
    (r'systemctl\s+stop\s+.*skynet', "Cannot stop Skynet"),
    # ... 62 more patterns
]
```

**Self-Protection Rules:**
- Cannot stop/restart `jarvis` container
- Cannot stop/restart `n8n-db` (database dependency)
- Cannot stop/restart `skynet` services (host system)

**Risk Levels:**
- `RiskLevel.LOW` - Safe diagnostic/restart operations
- `RiskLevel.MEDIUM` - State-changing but reversible
- `RiskLevel.HIGH` - Dangerous, triggers escalation

### 4b. Claude Code Escalation (`claude_cli.py`)

**Purpose:** When the command validator rejects proposed commands, escalate to Claude Code CLI with full permissions to fix the issue directly.

**Architecture:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Jarvis Core Container                              │
│                                                                              │
│  ┌────────────────┐   rejected   ┌─────────────────┐                        │
│  │    Command     │ ───────────▶ │    Escalation   │                        │
│  │   Validator    │              │     Handler     │                        │
│  └────────────────┘              └────────┬────────┘                        │
│                                           │ SSH + SFTP                       │
└───────────────────────────────────────────┼─────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Skynet Host                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        Claude Code CLI                               │    │
│  │                                                                      │    │
│  │  --dangerously-skip-permissions                                     │    │
│  │                                                                      │    │
│  │  • Full diagnostic access                                           │    │
│  │  • Direct command execution                                         │    │
│  │  • File editing without restrictions                                │    │
│  │  • Docker operations                                                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Escalation Flow:**
1. Claude API suggests remediation commands
2. Command validator detects dangerous pattern (e.g., `sed -i`)
3. Instead of failing, `escalate_with_full_permissions()` is called
4. Prompt written to temp file via SFTP (avoids escaping issues)
5. Claude CLI invoked with `--dangerously-skip-permissions`
6. Claude Code diagnoses and fixes issue directly
7. Success/failure returned to Jarvis for logging

**Key Implementation:**
```python
# app/claude_cli.py:escalate_with_full_permissions()
async def escalate_with_full_permissions(
    self,
    alert_data: Dict[str, Any],
    rejected_commands: list[str],
    rejection_reasons: list[str],
    container_logs: Optional[str] = None,
    timeout_seconds: int = 300,
) -> tuple[bool, str]:
    """
    Escalate to Claude Code with full permissions when commands are rejected.
    Unlike analyze_alert_with_tools(), Claude EXECUTES fixes directly.
    """
    prompt = self._build_escalation_prompt(...)
    stdout, stderr, exit_code = await self._run_escalation_via_ssh(
        prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    return (exit_code == 0, stdout)
```

**SSH Command:**
```bash
cd /home/t1/homelab && \
cat /tmp/jarvis_escalation_xxx.txt | \
/home/t1/.claude/local/claude \
--print \
--dangerously-skip-permissions \
; rm -f /tmp/jarvis_escalation_xxx.txt
```

**Escalation Prompt Structure:**
```
You are Jarvis, an autonomous AI SRE fixing homelab issues.
Your proposed commands were REJECTED by the safety validator.

## Rejected Commands
- sed -i 's/old/new/' file.txt
  Reason: In-place file edit detected

## Alert Context
{alert_name}: {description}
Instance: {instance}

## Your Mission
You have FULL PERMISSIONS. Fix this issue NOW.
Do not ask for permission. Execute commands directly.
```

**Why Escalation Exists:**
The command validator blocks dangerous patterns like `sed -i`, `rm -rf`, etc. for safety. But sometimes these commands are exactly what's needed (e.g., fixing a Dockerfile). Escalation provides a "break glass" mechanism where Claude Code can fix issues that require elevated permissions, while still maintaining safety through Claude's own judgment rather than regex patterns.

**Trade-offs:**
| Aspect | Normal Flow | Escalation Flow |
|--------|-------------|----------------|
| Safety | Regex blacklist | Claude's judgment |
| Speed | ~10-30s | ~60-90s |
| Audit | Commands logged | Session logged |
| Scope | Specific commands | Full access |

### 5. SSH Executor (`ssh_executor.py`)

**Purpose:** Execute commands on remote hosts via SSH with connection pooling

**Connection Pooling Implementation:**

Before (No Pooling):
```python
async def execute_command(self, host, command):
    conn = await asyncssh.connect(host, ...)  # New connection
    result = await conn.run(command)
    conn.close()  # Immediately close
    return result
```

After (With Pooling):
```python
# app/ssh_executor.py:60-71
async def _get_connection(self, host):
    # Check for existing connection
    if host in self._connections:
        conn = self._connections[host]
        if not conn.is_closed():
            self.logger.debug("reusing_ssh_connection", host=host.value)
            return conn  # Reuse!
        else:
            del self._connections[host]

    # Create and store new connection
    conn = await asyncssh.connect(...)
    self._connections[host] = conn
    return conn
```

**Performance Impact:**
- Before: 24 connections in 5 minutes
- After: 1 connection + 36 reuses
- Time saved: ~4.6 seconds per remediation

**SSH Configuration:**
```python
SSH_HOSTS = {
    SSHHost.NEXUS: {
        "host": "192.168.0.11",
        "username": "jordan",
        "known_hosts": None,  # Disable strict host checking
        "client_keys": ["/app/ssh_key"]
    },
    SSHHost.HOMEASSISTANT: {...},
    SSHHost.OUTPOST: {...}
}
```

### 6. Discord Notifier (`discord_notifier.py`)

**Purpose:** Send rich Discord embeds for remediation events

**Notification Types:**

1. **Success (Green)**
   - Alert auto-remediated
   - Commands executed
   - AI analysis
   - Duration and attempt count

2. **Failure (Orange)**
   - Auto-remediation failed
   - Error message
   - Attempts remaining
   - Commands attempted

3. **Escalation (Red, @here ping)**
   - Max attempts reached
   - Summary of previous attempts
   - Manual intervention required
   - AI's suggested next action

4. **Dangerous Command Rejected (Red)**
   - Commands blocked by validator
   - Rejection reasons
   - Escalated for manual review

**Embed Structure:**
```python
{
    "title": "✅ Alert Auto-Remediated",
    "description": "**ContainerDown** on nexus:omada has been automatically fixed.",
    "color": 0x00ff00,
    "fields": [
        {"name": "Severity", "value": "CRITICAL", "inline": True},
        {"name": "Attempt", "value": "2/20", "inline": True},
        {"name": "Duration", "value": "15 seconds", "inline": True},
        {"name": "AI Analysis", "value": "...", "inline": False},
        {"name": "Commands Executed", "value": "```bash\n...\n```", "inline": False}
    ],
    "timestamp": "2025-11-11T20:00:00Z",
    "footer": {"text": "Jarvis"},
    "author": {"name": "Jarvis"}
}
```

**Username Display:**
- All notifications use "Jarvis" as the webhook username
- Changed from "Homelab SRE" on November 11, 2025 for consistent branding
- Set in `discord_notifier.py` lines 69, 123, 184, 261, 358

---

## Data Flow

### Typical Remediation Flow

1. **Alert Fires**
   - Prometheus detects issue (e.g., container down)
   - Alertmanager sends webhook to Jarvis

2. **Webhook Reception**
   - FastAPI receives POST at `/webhook`
   - Validates HTTP Basic Auth
   - Filters for `status=firing`

3. **Instance Formatting**
   - For ContainerDown: builds `host:container` instance
   - For others: uses default instance label

4. **Database Query**
   - Checks attempts in last 2 hours for this alert+instance
   - If ≥20 attempts: escalate immediately

5. **Claude Analysis**
   - Sends alert context + attempt history to Claude
   - Claude suggests commands with reasoning

6. **Command Validation**
   - Validates each command against blacklist
   - Rejects dangerous patterns
   - Escalates if high risk

7. **Diagnostic Filtering**
   - Checks if commands are actionable (state-changing)
   - Read-only diagnostics don't count toward attempt limit

8. **SSH Execution**
   - Gets/creates SSH connection (pooled)
   - Executes commands on target host
   - Captures output and return codes

9. **Database Logging**
   - Records attempt (if actionable commands were run)
   - Logs success/failure + duration

10. **Discord Notification**
    - Sends success/failure embed
    - Includes commands, output, AI analysis

### Resolution Flow

1. **Alert Resolves**
   - Prometheus confirms issue is fixed
   - Alertmanager sends webhook with `status=resolved`

2. **Webhook Reception**
   - Jarvis receives resolved webhook
   - Identifies alert_name + alert_instance

3. **Attempt Cleanup**
   - Calls `database.clear_attempts()`
   - Deletes all logged attempts for this alert+instance
   - Returns count of cleared attempts

4. **Next Occurrence**
   - If alert fires again, starts fresh
   - No stale attempt history
   - Full 20 attempts available

---

## Key Design Decisions

### 1. Container-Specific Instance Tracking

**Problem:** Multiple containers on same host shared attempt counters

**Solution:** Detect if Prometheus already formatted instance, then build if needed
```python
# Check if already formatted as "host:container"
if ":" in alert.labels.instance and alert_name == "ContainerDown":
    alert_instance = alert.labels.instance
elif alert_name == "ContainerDown":
    alert_instance = f"{host}:{container}"  # e.g., "nexus:omada"
```

**Benefit:** Independent attempt tracking per container, compatible with Prometheus pre-formatted instances

**Fix History:** Improved detection logic on November 11, 2025 to handle cases where Prometheus alert rules already set instance as "host:container"

### 2. Blacklist-Only Validation

**Problem:** Whitelist rejected valid commands, limited AI flexibility

**Solution:** Allow all commands except explicitly dangerous ones

**Benefit:** AI has full troubleshooting freedom while staying safe

### 3. Diagnostic Command Filtering

**Problem:** Read-only diagnostics wasted attempt quota

**Solution:** Only count state-changing commands as attempts
```python
def is_actionable_command(cmd):
    # docker ps, curl -I, systemctl status → not actionable
    # docker restart, systemctl restart → actionable
```

**Benefit:** More attempts available for actual fixes

### 4. SSH Connection Pooling

**Problem:** 24 new connections in 5 minutes caused timeouts

**Solution:** Reuse persistent SSH connections
```python
if host in self._connections and not conn.is_closed():
    return conn  # Reuse existing
```

**Benefit:** 96% fewer connection overhead, no timeouts

### 5. 2-Hour Attempt Window

**Problem:** 24-hour window meant old failures affected new alerts

**Solution:** Reduced window to 2 hours

**Benefit:** Fresh start for recurring issues, stale data expires quickly

### 6. Resolved Alert Cleanup

**Problem:** Attempt history persisted after resolution

**Solution:** Clear attempts when alert resolves

**Benefit:** Clean slate for next occurrence, no false escalations

### 7. Self-Protection Rules

**Problem:** AI could suggest stopping itself or dependencies

**Solution:** Blacklist commands that would break Jarvis
```python
(r'docker\s+stop\s+.*jarvis', "Cannot stop Jarvis"),
(r'docker\s+stop\s+.*n8n-db', "Cannot stop database"),
```

**Benefit:** Service remains available even with aggressive AI suggestions

---

## Performance Characteristics

### Request Latency

**Typical webhook processing time:**
- Auth validation: <1ms
- Database query (attempts): 5-10ms
- Claude API call: 2-5 seconds
- Command validation: <1ms
- SSH execution: 100-500ms per command
- Database logging: 10-20ms
- Discord notification: 100-200ms

**Total:** ~3-7 seconds per remediation

### SSH Connection Pooling Impact

**Before (no pooling):**
- Connection overhead: 200ms per command
- 12 commands = 2,400ms overhead

**After (pooling):**
- First connection: 200ms
- Reuse connection: ~0ms
- 12 commands = 200ms overhead

**Savings:** 2,200ms (91% reduction in SSH overhead)

### Database Performance

**Indexes:**
```sql
CREATE INDEX idx_remediation_log_alert ON remediation_log(alert_name, alert_instance, timestamp);
```

**Query performance:**
- Get attempts (2-hour window): <5ms
- Log attempt: <10ms
- Get previous attempts: <20ms

### Claude API Costs

**Haiku 3.5 pricing:**
- Input: $0.80 per 1M tokens
- Output: $4 per 1M tokens

**Typical request:**
- Input: ~10,000 tokens (system prompt + alert context)
- Output: ~500 tokens (analysis + commands)

**Cost per remediation:** ~$0.008

**Monthly estimate (100 alerts):**
- 100 alerts × $0.008 = $0.80/month

---

## Security Considerations

### Authentication & Authorization

1. **Webhook Endpoint**
   - HTTP Basic Auth required
   - Username: `alertmanager`
   - Password: Strong random (32 bytes)
   - No anonymous access

2. **SSH Keys**
   - Dedicated key for Jarvis
   - Ed25519 algorithm (modern, secure)
   - 600 permissions (read-only by owner)
   - Private key never leaves container

3. **Database Credentials**
   - Stored in environment variables
   - URL-encoded special characters
   - Not logged or exposed in API responses

### Command Safety

1. **Blacklist Patterns**
   - 68 dangerous patterns blocked
   - Regex-based detection
   - Case-insensitive matching
   - All commands logged for audit

2. **Self-Protection**
   - Cannot stop itself
   - Cannot stop database
   - Cannot reboot host
   - Prevents accidental suicide

3. **Risk-Based Escalation**
   - High-risk commands trigger escalation
   - Human approval required
   - Discord notification sent

### Network Security

1. **SSH Access**
   - Key-based auth only (no passwords)
   - Known_hosts disabled (homelab trust)
   - Timeouts prevent hung connections

2. **API Exposure**
   - Only webhook endpoint exposed
   - No public API for command execution
   - Health check is read-only

---

## Scalability

### Current Limitations

1. **Single Container**
   - No horizontal scaling
   - Webhook handling is serial
   - Max ~10-20 concurrent alerts

2. **SSH Connection Pool**
   - 1 connection per host
   - Concurrent commands blocked
   - Could bottleneck under heavy load

3. **Database**
   - Single PostgreSQL instance
   - No connection pooling
   - Sufficient for homelab scale

### Future Scalability Options

1. **Multiple Workers**
   - FastAPI with Gunicorn
   - Multiple uvicorn workers
   - Webhook queue (Redis/RabbitMQ)

2. **SSH Connection Pooling**
   - Multiple connections per host
   - Semaphore-based concurrency control
   - Connection pool size configurable

3. **Database Scaling**
   - Connection pooling (asyncpg pool)
   - Read replicas for analytics
   - Partitioning by timestamp

---

## Monitoring & Observability

### Structured Logging

All logs use JSON format with structured fields:

```json
{
  "timestamp": "2025-11-11T20:00:00Z",
  "level": "info",
  "event": "webhook_received",
  "alert_name": "ContainerDown",
  "alert_instance": "nexus:omada",
  "severity": "critical"
}
```

**Key log events:**
- `webhook_received` - Alert webhook received
- `processing_alert` - Starting remediation
- `claude_api_call` - Calling Claude
- `command_validated` - Command passed safety checks
- `ssh_connection_established` - New SSH connection
- `reusing_ssh_connection` - Reused existing connection
- `command_executed` - SSH command completed
- `remediation_success` - Alert fixed successfully
- `remediation_failed` - Remediation failed
- `escalation_required` - Max attempts reached

### Metrics (Future)

Planned Prometheus metrics:

```python
# Counters
remediation_attempts_total{status="success|failure|escalated"}
commands_executed_total{host="nexus|homeassistant|outpost"}
claude_api_requests_total{status="success|error"}

# Histograms
remediation_duration_seconds
claude_api_duration_seconds
ssh_command_duration_seconds

# Gauges
ssh_connections_active
database_connections_active
```

---

## Failure Modes

### 1. Database Unavailable

**Symptoms:** Service starts but cannot log attempts

**Impact:** No attempt tracking, escalations won't work

**Mitigation:**
- Health check fails (`/health` returns error)
- Jarvis continues processing alerts
- Logs contain database errors

**Recovery:** Restart n8n-db container

### 2. Claude API Down

**Symptoms:** All remediations fail with API errors

**Impact:** No AI analysis, alerts escalate immediately

**Mitigation:**
- Rate limiting respected (429 errors)
- Retries with exponential backoff
- Discord notification sent

**Recovery:** Wait for Anthropic service restoration

### 3. SSH Connection Failure

**Symptoms:** Cannot execute commands on host

**Impact:** Remediation fails for that host

**Mitigation:**
- Connection timeout (10 seconds)
- Detailed error logged
- Discord notification explains SSH failure

**Recovery:**
- Check SSH key permissions (600)
- Verify host is reachable
- Check SSH daemon on target host

### 4. Alert Storm (>20 concurrent)

**Symptoms:** Webhook endpoint slow/unresponsive

**Impact:** Some webhooks timeout

**Mitigation:**
- Alertmanager will retry (repeat_interval)
- Jarvis processes serially (no concurrency issues)

**Recovery:** Wait for alert storm to subside

---

## Testing Strategy

### Unit Tests

- Command validator patterns
- Database query logic
- Diagnostic command detection
- SSH connection pooling

### Integration Tests

- Webhook processing end-to-end
- Database operations (create, read, clear)
- Discord notification formatting

### Manual Tests

1. **Simulated Alert**
   ```bash
   curl -X POST http://localhost:8000/webhook \
     -u alertmanager:password \
     -d @test_alert.json
   ```

2. **Container Stop Test**
   ```bash
   ssh nexus 'docker stop omada'
   # Watch logs: docker logs -f jarvis
   ```

3. **SSH Pooling Test**
   ```bash
   # Trigger alert, check logs for:
   # - ssh_connection_established (should be 1)
   # - reusing_ssh_connection (should be many)
   ```

---

## Future Enhancements

### Planned Features

1. **Rollback Capability**
   - Store pre-remediation state
   - Automatic rollback on failure
   - Manual rollback via API

2. **Learning from Success**
   - Track success patterns
   - Prioritize historically successful commands
   - Build remediation templates

3. **Multi-Step Workflows**
   - Complex remediations with dependencies
   - Wait/verify between steps
   - Conditional execution

4. **Web UI**
   - Manual approval interface
   - Remediation history viewer
   - Real-time log streaming

5. **Cost Tracking**
   - Claude API usage dashboard
   - Cost per alert type
   - Budget alerts

---

## Glossary

- **Alert Instance:** Unique identifier for alert occurrence (e.g., `nexus:omada`)
- **Attempt Window:** Time period for counting remediation attempts (2 hours)
- **Actionable Command:** State-changing command that counts toward attempt limit
- **Diagnostic Command:** Read-only command that doesn't count toward attempts
- **Escalation:** Alert sent to Discord after max attempts reached
- **Resolution:** Alert state change from firing → resolved
- **SSH Host:** Target system for command execution (Nexus, HA, Outpost)
- **Risk Level:** Safety classification of command (low, medium, high)
- **Connection Pooling:** Reusing persistent SSH connections instead of creating new ones

---

## Recent Bug Fixes (November 11, 2025)

### Discord Notification Improvements

**Issue:** Username displayed as "Homelab SRE" instead of "Jarvis"
**Fix:** Updated all webhook calls in `discord_notifier.py` to use `username="Jarvis"`
**Impact:** Consistent branding across all notification types

**Issue:** `NameError: name 'max_attempts' is not defined` in success notifications
**Fix:** Added `max_attempts: int` parameter to `notify_success()` method and passed `settings.max_attempts_per_alert` from caller
**Impact:** Attempt count now displays correctly (e.g., "2/20" instead of causing errors)

### Container Instance Detection

**Issue:** Container instances showing as just hostname (e.g., "nexus" instead of "nexus:container")
**Root Cause:** Prometheus alert rules already formatted instance as "host:container", but Jarvis tried to rebuild it from separate labels
**Fix:** Check if instance contains ":" before attempting to build container-specific format
**Impact:** Proper per-container attempt tracking, no more shared counters between different containers on same host

### Alertmanager Webhook Timing

**Issue:** `group_interval: 10s` caused duplicate webhooks every 10 seconds, leading to excessive remediation attempts
**Fix:** Changed to `group_interval: 1m` for balanced retry behavior
**Configuration:**
```yaml
routes:
  - match_re:
      alertname: '.+'
    receiver: 'ai-remediation'
    group_wait: 5s          # First webhook after 5s
    group_interval: 1m      # Retry every 1 minute if alert persists
    repeat_interval: 30m    # After 30 min, resend if still unresolved
```
**Impact:** ~120 retry attempts available in 2-hour window (well above 20-attempt limit), prevents webhook spam while giving multiple remediation chances

---

**Last Updated:** January 4, 2026
**Version:** 4.2.0
