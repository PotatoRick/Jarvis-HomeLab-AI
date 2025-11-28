# AI-Powered Alert Remediation System

## Overview

An automated incident response system that receives Prometheus/Alertmanager alerts, uses Claude AI to analyze and suggest remediation steps, executes safe commands via SSH, and escalates to humans when automatic resolution fails.

## Architecture

```
┌─────────────────────┐
│   Prometheus        │
│   (Nexus)           │
└──────────┬──────────┘
           │ Alert Triggers
           ▼
┌─────────────────────┐
│   Alertmanager      │
│   (Nexus)           │
└──────────┬──────────┘
           │ Webhook (JSON)
           ▼
┌─────────────────────────────────────────────────────────────┐
│                   n8n Workflows (Outpost)                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Workflow 1: Alert Ingestion & Remediation         │     │
│  ├────────────────────────────────────────────────────┤     │
│  │  1. Webhook Trigger                                │     │
│  │  2. Parse Alert JSON                               │     │
│  │  3. Query PostgreSQL (attempt count)               │     │
│  │  4. IF attempts < 3                                │     │
│  │     ├─ YES: Continue to AI analysis                │     │
│  │     └─ NO:  Trigger Workflow 2 (Escalation)        │     │
│  │  5. Fetch System Logs (SSH)                        │     │
│  │  6. Claude AI Analysis (HTTP Request)              │     │
│  │  7. Validate Commands (Whitelist)                  │     │
│  │  8. IF risk = low/medium                           │     │
│  │     ├─ Execute SSH Commands                        │     │
│  │     └─ Log to PostgreSQL                           │     │
│  │  9. IF risk = high → Escalate (Workflow 2)         │     │
│  │  10. Post Result to Discord                        │     │
│  └────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Workflow 2: Escalation & User Approval            │     │
│  ├────────────────────────────────────────────────────┤     │
│  │  1. Triggered by Workflow 1 or manual              │     │
│  │  2. Fetch last 3 attempts from PostgreSQL          │     │
│  │  3. Claude AI Summary + Next Suggestion            │     │
│  │  4. Discord Message with Interactive Buttons:      │     │
│  │     • Approve Suggested Fix                        │     │
│  │     • Show Logs                                    │     │
│  │     • Disable Auto-Fix (1hr)                       │     │
│  │     • Manual Intervention Required                 │     │
│  │  5. Wait for Discord Webhook (button click)        │     │
│  │  6. Switch on button action:                       │     │
│  │     ├─ Approve → Execute → Log                     │     │
│  │     ├─ Show Logs → Query PostgreSQL → Post         │     │
│  │     ├─ Disable → Set maintenance flag              │     │
│  │     └─ Manual → Mark escalated, stop               │     │
│  └────────────────────────────────────────────────────┘     │
│                                                               │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Workflow 3: Maintenance Mode Toggle               │     │
│  ├────────────────────────────────────────────────────┤     │
│  │  1. Webhook Trigger (Discord or API)               │     │
│  │  2. Parse duration parameter                       │     │
│  │  3. Insert maintenance window to PostgreSQL        │     │
│  │  4. Post confirmation to Discord                   │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
           │                    │                    │
           ▼                    ▼                    ▼
     ┌──────────┐        ┌──────────┐        ┌──────────┐
     │ PostgreSQL│        │ SSH to   │        │ Discord  │
     │ (Outpost) │        │ Systems  │        │ Webhooks │
     └──────────┘        └──────────┘        └──────────┘
```

## System Components

### 1. Data Storage (PostgreSQL)
- **Database:** `finance_db` (existing on Outpost)
- **Table:** `remediation_log` - Tracks all remediation attempts
- **Table:** `maintenance_windows` - Stores maintenance mode periods
- **Table:** `command_whitelist` - Safe command patterns

### 2. n8n Workflows
- **Workflow 1:** Core remediation engine (webhook → AI → execute → notify)
- **Workflow 2:** Human escalation and approval workflow
- **Workflow 3:** Maintenance mode management

### 3. External Integrations
- **Claude API:** AI analysis and remediation suggestions
- **Alertmanager:** Alert source (webhook sender)
- **Discord:** User notifications and approvals
- **SSH:** Remote command execution on homelab systems

## Alert Processing Flow

### Phase 1: Alert Reception
1. Alertmanager fires alert (JSON webhook)
2. n8n receives webhook, extracts:
   - `alert_name` (e.g., "WireGuardVPNDown")
   - `instance` (e.g., "outpost:51820")
   - `severity` (critical/warning/info)
   - `description` (human-readable summary)
   - `labels` (all Prometheus labels)
   - `annotations` (additional metadata)

### Phase 2: Attempt Tracking
1. Query PostgreSQL for attempts in last 24 hours:
   ```sql
   SELECT COUNT(*) FROM remediation_log
   WHERE alert_name = $alertName
   AND alert_instance = $instance
   AND timestamp > NOW() - INTERVAL '24 hours';
   ```
2. If count >= 3 → Escalate to Workflow 2
3. If count < 3 → Continue to Phase 3

### Phase 3: Context Gathering
1. SSH to affected system, gather logs:
   - For containers: `docker logs --tail 100 <container>`
   - For systemd: `journalctl -u <service> -n 100 --no-pager`
   - For system: `dmesg | tail -100`
2. Fetch relevant documentation from `/home/t1/homelab/documentation/`
3. Compile context package for AI

### Phase 4: AI Analysis
1. Send to Claude API with structured prompt (see templates below)
2. Receive JSON response:
   ```json
   {
     "analysis": "Root cause description",
     "commands": [
       "systemctl restart wg-quick@wg0",
       "sleep 5",
       "systemctl status wg-quick@wg0"
     ],
     "risk": "low",
     "expected_outcome": "VPN should reconnect within 10 seconds",
     "reasoning": "Service likely crashed, restart is safe operation"
   }
   ```
3. Validate risk level and commands

### Phase 5: Command Validation
1. Check each command against whitelist patterns
2. Reject if any command matches dangerous patterns
3. If risk = "high" or dangerous command detected → Escalate
4. If safe → Proceed to Phase 6

### Phase 6: Execution
1. Start timer (for duration tracking)
2. Execute commands via SSH with 60-second timeout
3. Capture stdout, stderr, exit codes
4. Stop timer
5. Determine success/failure based on exit codes

### Phase 7: Logging & Notification
1. Insert record to `remediation_log`:
   - Timestamp, alert details, attempt number
   - AI analysis, commands executed
   - Success boolean, error messages
   - Execution duration
2. Post to Discord #homelab-alerts:
   - If success: "✅ Auto-remediation successful"
   - If failure: "⚠️ Auto-remediation failed (attempt X/3)"
3. If success and alert is resolved → Done
4. If failure and attempts < 3 → Wait for next alert firing
5. If failure and attempts >= 3 → Trigger Workflow 2

## Command Safety Framework

### Safe Commands (Auto-approved)
```regex
# Service restarts
^systemctl restart [a-zA-Z0-9_-]+$
^systemctl restart wg-quick@wg[0-9]+$

# Docker operations (specific containers)
^docker restart [a-zA-Z0-9_-]+$
^docker exec [a-zA-Z0-9_-]+ kill -HUP 1$
^docker system prune -f$

# Home Assistant
^ha core restart$
^ha core check$

# Low-risk system commands
^sync$
^sleep [0-9]+$
^systemctl status [a-zA-Z0-9_-]+$
```

### Dangerous Commands (Require Approval)
```regex
# Data deletion
.*rm -rf.*
.*docker volume rm.*
.*docker rm.*

# System power
.*reboot.*
.*shutdown.*
.*poweroff.*

# Firewall changes
.*ufw.*
.*iptables.*
.*nft.*

# Configuration edits
.*sed -i.*
.*echo.*>.*
.*tee.*

# Package management
.*apt.*
.*dpkg.*
.*systemctl disable.*
```

### Validation Logic
```javascript
function validateCommand(command) {
  const dangerousPatterns = [
    /rm\s+-rf/,
    /reboot/,
    /shutdown/,
    /iptables/,
    /ufw/,
    /docker\s+rm/,
    /systemctl\s+disable/
  ];

  const safePatterns = [
    /^systemctl restart [a-zA-Z0-9_-]+$/,
    /^docker restart [a-zA-Z0-9_-]+$/,
    /^ha core restart$/,
    /^docker system prune -f$/
  ];

  // Check dangerous first (blacklist)
  for (const pattern of dangerousPatterns) {
    if (pattern.test(command)) {
      return { safe: false, reason: 'Dangerous command detected' };
    }
  }

  // Check whitelist
  for (const pattern of safePatterns) {
    if (pattern.test(command)) {
      return { safe: true };
    }
  }

  // Default deny
  return { safe: false, reason: 'Command not in whitelist' };
}
```

## AI Prompt Templates

### Template 1: Initial Analysis
```markdown
You are an AI SRE managing The Burrow homelab infrastructure. You receive alerts from Prometheus/Alertmanager and must analyze them to suggest remediation steps.

# Alert Details
- **Alert Name:** {alertname}
- **Instance:** {instance}
- **Severity:** {severity}
- **Description:** {description}
- **Labels:** {labels_json}
- **Fired At:** {startsAt}

# System Context
{system_documentation}

# Recent Logs (Last 100 lines)
{recent_logs}

# Your Task
Analyze this alert and provide a remediation plan. Return your response as JSON with this structure:

{
  "analysis": "Brief root cause analysis (2-3 sentences)",
  "commands": ["command1", "command2", "command3"],
  "risk": "low|medium|high",
  "expected_outcome": "What should happen after executing these commands",
  "reasoning": "Why these commands will resolve the issue",
  "estimated_duration": "How long resolution should take (e.g., '30 seconds')"
}

# Constraints
- Only suggest commands that are safe to run automatically
- Use systemctl restart, docker restart, basic service management
- DO NOT suggest: reboots, data deletion, firewall changes, file edits
- If the issue requires human intervention, set risk="high"
- Commands must be idempotent (safe to run multiple times)

# Known Alert Patterns
- WireGuardVPNDown → `systemctl restart wg-quick@wg0`
- ContainerUnhealthy → `docker restart <container>`
- PostgreSQLDown → `docker restart n8n-db` or `systemctl restart postgresql`
- HighMemoryUsage (container) → `docker restart <container>`
- ContainerRestartingFrequently → DO NOT restart again, set risk=high
```

### Template 2: Escalation Summary
```markdown
You are an AI SRE managing The Burrow homelab. An alert has failed automatic remediation 3 times. Summarize what was attempted and suggest the next action for a human operator.

# Alert Details
- **Alert Name:** {alertname}
- **Instance:** {instance}
- **Severity:** {severity}

# Previous Attempts
{attempts_json}

# Your Task
Provide a summary and next steps. Return JSON:

{
  "summary": "Concise summary of what failed and why",
  "attempted_commands": ["cmd1", "cmd2"],
  "failure_pattern": "Common thread in failures",
  "suggested_next_action": "What a human should try next",
  "urgency": "low|medium|high",
  "potential_impact": "What happens if this isn't fixed soon"
}

Be concise. The user is receiving this as a Discord notification.
```

## Discord Integration

### Message Format: Auto-Remediation Success
```
✅ **Alert Auto-Remediated**
**Alert:** WireGuardVPNDown
**Instance:** outpost:51820
**Action Taken:** Restarted WireGuard service
**Duration:** 12 seconds
**Outcome:** VPN reconnected successfully

Commands executed:
```bash
systemctl restart wg-quick@wg0
systemctl status wg-quick@wg0
```

**AI Analysis:** Service crashed due to network timeout. Restart restored connectivity.
```

### Message Format: Escalation (After 3 Failures)
```
🚨 **Alert Escalation Required**
**Alert:** PostgreSQLDown
**Instance:** outpost:5432
**Severity:** critical
**Attempts:** 3 failed auto-remediations

**Summary:** Container repeatedly crashes on startup. Log shows "database files are incompatible with server" error. Automated restarts did not resolve.

**Attempted:**
1. docker restart n8n-db (failed - container exited)
2. docker system prune + restart (failed - same error)
3. Waited 5 minutes + restart (failed - same error)

**Suggested Next Action:** Database may need manual recovery. Check PostgreSQL version compatibility or restore from backup.

**Urgency:** HIGH - n8n workflows are offline

[Approve Suggested Fix] [Show Full Logs] [Disable Auto-Fix 1hr] [Manual Intervention]
```

### Discord Webhook Setup
1. Create webhook in Discord server settings
2. Store webhook URL in n8n credentials: `discord_homelab_alerts`
3. Configure threaded replies to original Alertmanager message

## PostgreSQL Schema

### Table: remediation_log
```sql
CREATE TABLE IF NOT EXISTS remediation_log (
  id SERIAL PRIMARY KEY,
  timestamp TIMESTAMPTZ DEFAULT NOW(),
  alert_name VARCHAR(255) NOT NULL,
  alert_instance VARCHAR(255) NOT NULL,
  alert_fingerprint VARCHAR(64), -- Alertmanager fingerprint for deduplication
  severity VARCHAR(50),
  attempt_number INT DEFAULT 1,
  ai_analysis TEXT,
  ai_reasoning TEXT,
  remediation_plan TEXT,
  commands_executed TEXT[], -- PostgreSQL array of strings
  command_outputs TEXT[], -- stdout/stderr for each command
  exit_codes INT[], -- Exit code for each command
  success BOOLEAN,
  error_message TEXT,
  execution_duration_seconds INT,
  risk_level VARCHAR(20),
  escalated BOOLEAN DEFAULT FALSE,
  user_approved BOOLEAN DEFAULT NULL,
  discord_message_id VARCHAR(100) -- For threading replies
);

CREATE INDEX idx_alert_tracking ON remediation_log(alert_name, alert_instance, timestamp DESC);
CREATE INDEX idx_fingerprint ON remediation_log(alert_fingerprint);
CREATE INDEX idx_escalated ON remediation_log(escalated) WHERE escalated = TRUE;
```

### Table: maintenance_windows
```sql
CREATE TABLE IF NOT EXISTS maintenance_windows (
  id SERIAL PRIMARY KEY,
  start_time TIMESTAMPTZ DEFAULT NOW(),
  end_time TIMESTAMPTZ NOT NULL,
  reason TEXT,
  created_by VARCHAR(100), -- Discord username
  active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_active_maintenance ON maintenance_windows(active, end_time) WHERE active = TRUE;
```

### Table: command_whitelist
```sql
CREATE TABLE IF NOT EXISTS command_whitelist (
  id SERIAL PRIMARY KEY,
  pattern TEXT NOT NULL, -- Regex pattern
  description TEXT,
  risk_level VARCHAR(20) DEFAULT 'medium', -- low, medium, high
  enabled BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed with safe patterns
INSERT INTO command_whitelist (pattern, description, risk_level) VALUES
  ('^systemctl restart [a-zA-Z0-9_-]+$', 'Restart systemd service', 'low'),
  ('^systemctl restart wg-quick@wg[0-9]+$', 'Restart WireGuard VPN', 'low'),
  ('^docker restart [a-zA-Z0-9_-]+$', 'Restart Docker container', 'low'),
  ('^docker exec [a-zA-Z0-9_-]+ kill -HUP 1$', 'Reload container process', 'low'),
  ('^docker system prune -f$', 'Clean up Docker resources', 'medium'),
  ('^ha core restart$', 'Restart Home Assistant', 'medium'),
  ('^sleep [0-9]+$', 'Wait N seconds', 'low'),
  ('^systemctl status [a-zA-Z0-9_-]+$', 'Check service status', 'low');
```

## Setup Instructions

### Step 1: PostgreSQL Setup
```bash
# SSH to Outpost
ssh outpost

# Connect to PostgreSQL
docker exec -it n8n-db psql -U n8n -d finance_db

# Run schema creation (paste SQL from above)
\i /path/to/schema.sql

# Verify tables
\dt
\d remediation_log

# Exit
\q
```

### Step 2: n8n Credentials Configuration
1. Navigate to https://n8n.theburrow.casa
2. Go to Settings → Credentials
3. Add credentials:
   - **SSH (Nexus):** Name: `ssh_nexus`, Host: 192.168.0.11, User: jordan, Private Key: (homelab_ed25519)
   - **SSH (Home Assistant):** Name: `ssh_homeassistant`, Host: 192.168.0.10, User: root, Private Key: (homelab_ed25519)
   - **SSH (Outpost):** Name: `ssh_outpost`, Host: localhost, User: root (for local commands)
   - **PostgreSQL:** Name: `postgres_finance_db`, Host: n8n-db, Port: 5432, Database: finance_db, User: n8n, Password: (from .env)
   - **Discord Webhook:** Name: `discord_homelab_alerts`, Webhook URL: (from Discord server settings)
   - **Anthropic API:** Name: `anthropic_claude`, API Key: (from Anthropic console)

### Step 3: Import n8n Workflows
1. Download workflow JSON files (provided below)
2. In n8n, go to Workflows → Import from File
3. Import in order:
   - `workflow_1_alert_remediation.json`
   - `workflow_2_escalation.json`
   - `workflow_3_maintenance.json`
4. Activate each workflow

### Step 4: Configure Alertmanager
Edit `/home/jordan/docker/home-stack/alertmanager/config/alertmanager.yml` on Nexus:

```yaml
receivers:
  - name: 'discord-homelab'
    webhook_configs:
      - url: 'https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN'
        send_resolved: true

  # Add new receiver for n8n
  - name: 'n8n-remediation'
    webhook_configs:
      - url: 'https://n8n.theburrow.casa/webhook/alert-remediation'
        send_resolved: true
        http_config:
          basic_auth:
            username: 'alertmanager'
            password: 'SECURE_PASSWORD_HERE' # Generate and store in n8n webhook auth

route:
  receiver: 'discord-homelab'
  group_wait: 10s
  group_interval: 5m
  repeat_interval: 3h
  routes:
    # Send ALL alerts to both Discord and n8n
    - matchers:
        - alertname =~ ".+"
      receiver: 'discord-homelab'
      continue: true # Important: continue to next route

    - matchers:
        - alertname =~ ".+"
      receiver: 'n8n-remediation'
```

Reload Alertmanager:
```bash
ssh nexus 'docker exec alertmanager kill -HUP 1'
```

### Step 5: Test the System
See Testing Procedures section below.

## Workflow Execution Flows

### Workflow 1 Detailed Steps

**Node 1: Webhook Trigger**
- Path: `/webhook/alert-remediation`
- Method: POST
- Authentication: Basic Auth (alertmanager:PASSWORD)
- Response: 200 OK immediately (async processing)

**Node 2: Parse Alert Data (Function)**
```javascript
// Extract alert details from Alertmanager JSON
const alerts = $input.item.json.alerts || [];
const outputItems = [];

for (const alert of alerts) {
  outputItems.push({
    json: {
      alert_name: alert.labels.alertname,
      alert_instance: alert.labels.instance || 'unknown',
      alert_fingerprint: alert.fingerprint,
      severity: alert.labels.severity || 'warning',
      description: alert.annotations.description || alert.annotations.summary,
      fired_at: alert.startsAt,
      labels: alert.labels,
      annotations: alert.annotations,
      status: alert.status
    }
  });
}

return outputItems;
```

**Node 3: Check Maintenance Window (PostgreSQL Query)**
```sql
SELECT COUNT(*) as in_maintenance
FROM maintenance_windows
WHERE active = TRUE
  AND NOW() BETWEEN start_time AND end_time;
```
Output: If in_maintenance > 0, route to "Skip (Maintenance)" branch

**Node 4: Query Attempt Count (PostgreSQL)**
```sql
SELECT
  COUNT(*) as attempt_count,
  MAX(timestamp) as last_attempt
FROM remediation_log
WHERE alert_name = $1
  AND alert_instance = $2
  AND timestamp > NOW() - INTERVAL '24 hours';
```
Params: `{{ $json.alert_name }}`, `{{ $json.alert_instance }}`

**Node 5: IF Attempts < 3**
- Condition: `{{ $json.attempt_count < 3 }}`
- True → Continue to Node 6
- False → Execute Workflow 2 (Escalation)

**Node 6: Gather System Logs (SSH)**
Logic to determine which system and command:
```javascript
const instance = $json.alert_instance;
const alertName = $json.alert_name;

let sshHost = 'nexus';
let command = '';

// Determine target system from instance label
if (instance.includes('outpost') || instance.includes('72.60.163.242')) {
  sshHost = 'outpost';
} else if (instance.includes('homeassistant') || instance.includes('192.168.0.10')) {
  sshHost = 'homeassistant';
} else if (instance.includes('nexus') || instance.includes('192.168.0.11')) {
  sshHost = 'nexus';
}

// Determine log command based on alert type
if (alertName.includes('Container')) {
  const containerName = instance.split(':')[0];
  command = `docker logs --tail 100 ${containerName} 2>&1`;
} else if (alertName.includes('WireGuard')) {
  command = `journalctl -u wg-quick@wg0 -n 100 --no-pager`;
} else if (alertName.includes('PostgreSQL')) {
  command = `docker logs --tail 100 n8n-db 2>&1`;
} else {
  command = `dmesg | tail -100`;
}

return [{
  json: {
    ...($json),
    ssh_host: sshHost,
    log_command: command
  }
}];
```

**Node 7: Execute SSH for Logs**
- Credential: `ssh_{{ $json.ssh_host }}`
- Command: `{{ $json.log_command }}`
- Timeout: 30 seconds
- Output stored in `$json.system_logs`

**Node 8: Fetch Documentation (Read File - via Code)**
```javascript
const fs = require('fs');
const alertName = $json.alert_name;

// Map alert types to relevant docs
const docMap = {
  'WireGuardVPNDown': '/home/t1/homelab/documentation/vps.md',
  'Container': '/home/t1/homelab/documentation/nexus.md',
  'PostgreSQL': '/home/t1/homelab/documentation/vps.md',
  'HomeAssistant': '/home/t1/homelab/documentation/home-assistant.md'
};

let docPath = '/home/t1/homelab/documentation/README.md'; // default
for (const [key, path] of Object.entries(docMap)) {
  if (alertName.includes(key)) {
    docPath = path;
    break;
  }
}

const documentation = fs.readFileSync(docPath, 'utf8');

return [{
  json: {
    ...($json),
    system_documentation: documentation.substring(0, 4000) // Limit size
  }
}];
```

**Node 9: Claude AI Analysis (HTTP Request)**
- Method: POST
- URL: `https://api.anthropic.com/v1/messages`
- Authentication: Bearer Token (from Anthropic credential)
- Headers:
  - `anthropic-version: 2023-06-01`
  - `Content-Type: application/json`
- Body:
```json
{
  "model": "claude-sonnet-4-5-20250929",
  "max_tokens": 2000,
  "messages": [
    {
      "role": "user",
      "content": "{{ $json.ai_prompt }}"
    }
  ]
}
```

Where `$json.ai_prompt` is constructed in previous Function node:
```javascript
const prompt = `You are an AI SRE managing The Burrow homelab infrastructure.

# Alert Details
- **Alert Name:** ${$json.alert_name}
- **Instance:** ${$json.alert_instance}
- **Severity:** ${$json.severity}
- **Description:** ${$json.description}
- **Fired At:** ${$json.fired_at}

# System Context
${$json.system_documentation}

# Recent Logs (Last 100 lines)
${$json.system_logs}

# Your Task
Analyze this alert and provide a remediation plan. Return ONLY valid JSON (no markdown, no extra text):

{
  "analysis": "Brief root cause analysis (2-3 sentences)",
  "commands": ["command1", "command2"],
  "risk": "low|medium|high",
  "expected_outcome": "What should happen after executing these commands",
  "reasoning": "Why these commands will resolve the issue",
  "estimated_duration": "30 seconds"
}

# Constraints
- Only suggest commands safe to run automatically
- Use systemctl restart, docker restart, basic service management
- DO NOT suggest: reboots, data deletion, firewall changes, file edits
- If requires human intervention, set risk="high"
- Commands must be idempotent

# Known Patterns
- WireGuardVPNDown → systemctl restart wg-quick@wg0
- ContainerUnhealthy → docker restart <container>
- PostgreSQLDown → docker restart n8n-db
- HighMemoryUsage (container) → docker restart <container>`;

return [{ json: { ...($json), ai_prompt: prompt } }];
```

**Node 10: Parse AI Response (Function)**
```javascript
const response = $json.choices[0].message.content;

// Extract JSON from response (Claude may wrap in markdown)
let aiResponse;
try {
  const jsonMatch = response.match(/\{[\s\S]*\}/);
  aiResponse = JSON.parse(jsonMatch[0]);
} catch (error) {
  return [{
    json: {
      ...($json),
      ai_analysis: 'Failed to parse AI response',
      commands: [],
      risk: 'high',
      error: response
    }
  }];
}

return [{
  json: {
    ...($json),
    ai_analysis: aiResponse.analysis,
    ai_reasoning: aiResponse.reasoning,
    commands: aiResponse.commands,
    risk: aiResponse.risk,
    expected_outcome: aiResponse.expected_outcome,
    estimated_duration: aiResponse.estimated_duration
  }
}];
```

**Node 11: Validate Commands (Function)**
```javascript
const commands = $json.commands;
const dangerousPatterns = [
  /rm\s+-rf/,
  /reboot/,
  /shutdown/,
  /iptables/,
  /ufw/,
  /docker\s+rm(?!\s+--help)/,
  /systemctl\s+disable/,
  /sed\s+-i/,
  />\s*\//
];

const safePatterns = [
  /^systemctl restart [a-zA-Z0-9_-]+$/,
  /^systemctl restart wg-quick@wg[0-9]+$/,
  /^docker restart [a-zA-Z0-9_-]+$/,
  /^docker exec [a-zA-Z0-9_-]+ kill -HUP 1$/,
  /^docker system prune -f$/,
  /^ha core restart$/,
  /^sleep [0-9]+$/,
  /^systemctl status [a-zA-Z0-9_-]+$/,
  /^journalctl/
];

const validatedCommands = [];
let allSafe = true;
let rejectionReason = '';

for (const cmd of commands) {
  // Check dangerous patterns first
  let isDangerous = false;
  for (const pattern of dangerousPatterns) {
    if (pattern.test(cmd)) {
      isDangerous = true;
      allSafe = false;
      rejectionReason = `Command "${cmd}" matches dangerous pattern: ${pattern}`;
      break;
    }
  }

  if (isDangerous) continue;

  // Check whitelist
  let isWhitelisted = false;
  for (const pattern of safePatterns) {
    if (pattern.test(cmd)) {
      isWhitelisted = true;
      validatedCommands.push(cmd);
      break;
    }
  }

  if (!isWhitelisted) {
    allSafe = false;
    rejectionReason = `Command "${cmd}" not in whitelist`;
  }
}

return [{
  json: {
    ...($json),
    validated_commands: validatedCommands,
    commands_safe: allSafe,
    validation_reason: rejectionReason
  }
}];
```

**Node 12: Risk & Safety Check (IF)**
- Condition: `{{ $json.risk === 'high' || !$json.commands_safe }}`
- True → Escalate (Workflow 2)
- False → Continue to execution

**Node 13: Execute Remediation Commands (SSH)**
```javascript
// Construct bash script with all commands
const commands = $json.validated_commands;
const sshHost = $json.ssh_host;

const bashScript = commands.join(' && ');

return [{
  json: {
    ...($json),
    execution_script: bashScript,
    target_host: sshHost
  }
}];
```

SSH Node:
- Credential: `ssh_{{ $json.target_host }}`
- Command: `{{ $json.execution_script }}`
- Timeout: 60 seconds

**Node 14: Capture Execution Results (Function)**
```javascript
const startTime = new Date($json.execution_start_time);
const endTime = new Date();
const duration = Math.floor((endTime - startTime) / 1000);

const exitCode = $json.exit_code || 0;
const success = exitCode === 0;

return [{
  json: {
    ...($json),
    execution_duration: duration,
    success: success,
    stdout: $json.stdout || '',
    stderr: $json.stderr || '',
    exit_code: exitCode
  }
}];
```

**Node 15: Log to PostgreSQL**
```sql
INSERT INTO remediation_log (
  alert_name,
  alert_instance,
  alert_fingerprint,
  severity,
  attempt_number,
  ai_analysis,
  ai_reasoning,
  remediation_plan,
  commands_executed,
  command_outputs,
  exit_codes,
  success,
  error_message,
  execution_duration_seconds,
  risk_level,
  escalated
) VALUES (
  $1, $2, $3, $4,
  (SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM remediation_log WHERE alert_name = $1 AND alert_instance = $2 AND timestamp > NOW() - INTERVAL '24 hours'),
  $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, FALSE
) RETURNING id;
```

**Node 16: Post to Discord**
Success message:
```javascript
const emoji = $json.success ? '✅' : '⚠️';
const status = $json.success ? 'Auto-Remediated' : `Failed (Attempt ${$json.attempt_number}/3)`;

const message = `${emoji} **Alert ${status}**
**Alert:** ${$json.alert_name}
**Instance:** ${$json.alert_instance}
**Action Taken:** ${$json.ai_analysis}
**Duration:** ${$json.execution_duration} seconds

**Commands Executed:**
\`\`\`bash
${$json.validated_commands.join('\n')}
\`\`\`

**Outcome:** ${$json.expected_outcome}

${!$json.success ? `**Error:** ${$json.stderr}` : ''}
`;

return [{
  json: {
    content: message
  }
}];
```

## Testing Procedures

### Test 1: Simulated Alert (Manual Webhook)
```bash
# From Skynet or Outpost
curl -X POST https://n8n.theburrow.casa/webhook/alert-remediation \
  -u "alertmanager:PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "WireGuardVPNDown",
        "instance": "outpost:51820",
        "severity": "critical"
      },
      "annotations": {
        "description": "WireGuard VPN tunnel is down",
        "summary": "VPN connectivity lost"
      },
      "startsAt": "2025-11-09T12:00:00Z",
      "fingerprint": "test123456"
    }]
  }'
```

Expected:
1. n8n receives webhook
2. Queries PostgreSQL (0 attempts)
3. SSHes to Outpost, gathers logs
4. Sends to Claude AI
5. Receives remediation plan
6. Executes `systemctl restart wg-quick@wg0`
7. Logs to database
8. Posts success to Discord

Verify:
```sql
SELECT * FROM remediation_log ORDER BY timestamp DESC LIMIT 1;
```

### Test 2: Dangerous Command Rejection
Modify AI response to return dangerous command:
```javascript
// In Node 10 (Parse AI Response), temporarily override:
aiResponse.commands = ['rm -rf /tmp/test'];
```

Expected:
- Command validation fails
- Alert escalates to Workflow 2
- Discord shows "Escalation Required"

### Test 3: Three Failed Attempts
1. Disconnect WireGuard on Outpost: `ssh outpost 'sudo systemctl stop wg-quick@wg0'`
2. Trigger alert 3 times (wait 5 minutes between each)
3. After 3rd attempt, escalation workflow should fire
4. Discord shows escalation message with buttons

### Test 4: Maintenance Mode
```bash
curl -X POST https://n8n.theburrow.casa/webhook/maintenance-toggle \
  -H "Content-Type: application/json" \
  -d '{
    "duration_minutes": 60,
    "reason": "Testing maintenance mode",
    "created_by": "jordan"
  }'
```

Expected:
- Maintenance window created in PostgreSQL
- All alerts skip remediation for 1 hour
- Discord confirmation posted

### Test 5: Full Integration (Real Alert)
1. On Nexus, temporarily break AdGuard: `ssh nexus 'docker stop adguard'`
2. Wait for Prometheus to detect (30s scrape interval + 1m evaluation)
3. Alertmanager fires alert
4. n8n receives, remediates (restarts AdGuard)
5. Alert resolves

Monitor:
```bash
# Watch Alertmanager
curl http://192.168.0.11:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname == "SystemDown")'

# Watch n8n execution
# Via n8n UI: Executions tab

# Watch PostgreSQL
ssh outpost 'docker exec -it n8n-db psql -U n8n -d finance_db -c "SELECT * FROM remediation_log ORDER BY timestamp DESC LIMIT 5;"'
```

## Monitoring Dashboard

### Grafana Dashboard: AI Remediation Metrics

**Panel 1: Auto-Remediation Success Rate**
```promql
sum(rate(remediation_log{success="true"}[1h])) / sum(rate(remediation_log[1h])) * 100
```

**Panel 2: Most Common Alerts**
Query PostgreSQL data source:
```sql
SELECT
  alert_name,
  COUNT(*) as count,
  SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
  AVG(execution_duration_seconds) as avg_duration
FROM remediation_log
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY alert_name
ORDER BY count DESC
LIMIT 10;
```

**Panel 3: Escalation Rate**
```sql
SELECT
  DATE_TRUNC('hour', timestamp) as hour,
  COUNT(*) as total_attempts,
  SUM(CASE WHEN escalated THEN 1 ELSE 0 END) as escalations
FROM remediation_log
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour;
```

**Panel 4: Average Remediation Time**
```sql
SELECT
  alert_name,
  AVG(execution_duration_seconds) as avg_seconds,
  MAX(execution_duration_seconds) as max_seconds
FROM remediation_log
WHERE success = TRUE
  AND timestamp > NOW() - INTERVAL '7 days'
GROUP BY alert_name;
```

**Panel 5: Recent Activity (Table)**
```sql
SELECT
  timestamp,
  alert_name,
  alert_instance,
  attempt_number,
  success,
  execution_duration_seconds,
  ai_analysis
FROM remediation_log
ORDER BY timestamp DESC
LIMIT 20;
```

## Security Considerations

### 1. SSH Key Management
- Use dedicated SSH key for n8n: `/opt/burrow/.ssh/n8n_remediation_key`
- Restrict key to specific commands via `authorized_keys`:
  ```
  command="/usr/local/bin/remediation-wrapper.sh",no-pty,no-port-forwarding ssh-ed25519 AAAA...
  ```

### 2. API Key Protection
- Store Claude API key in n8n credentials (encrypted at rest)
- Rotate key quarterly
- Monitor API usage for anomalies

### 3. Webhook Authentication
- Use strong password for Alertmanager → n8n webhook
- Consider IP whitelisting (Nexus IP only)
- Enable HTTPS with valid certificate

### 4. Command Injection Prevention
- NEVER use user input directly in commands
- All commands validated against whitelist regex
- No string interpolation in SSH commands

### 5. Audit Logging
- All commands logged to PostgreSQL before execution
- Logs retained for 90 days
- Weekly audit report generated

### 6. Rate Limiting
- Max 1 remediation execution at a time (n8n concurrency limit)
- Max 3 attempts per alert per 24 hours
- Maintenance mode for planned work

## Operational Procedures

### Daily Operations
- Check Discord #homelab-alerts for overnight activity
- Review Grafana dashboard for trends
- Verify PostgreSQL log retention

### Weekly
- Review escalation logs (what required human intervention?)
- Update command whitelist based on new alert types
- Check AI API usage and costs

### Monthly
- Audit successful remediations (were they correct?)
- Test escalation workflow
- Review and update documentation patterns

### Quarterly
- Rotate API keys
- Review and update SSH keys
- Disaster recovery drill

## Troubleshooting

### Issue: n8n Workflow Not Triggering
**Check:**
1. Webhook URL correct in Alertmanager config?
2. Alertmanager can reach n8n (network/firewall)?
3. Webhook authentication credentials correct?
4. n8n workflow activated?

**Debug:**
```bash
# Test webhook manually
curl -X POST https://n8n.theburrow.casa/webhook/alert-remediation \
  -u "alertmanager:PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"alerts": [{"status": "firing", "labels": {"alertname": "TestAlert"}}]}'

# Check n8n logs
ssh outpost 'docker logs n8n --tail 100'

# Check Alertmanager logs
ssh nexus 'docker logs alertmanager --tail 100'
```

### Issue: SSH Commands Failing
**Check:**
1. SSH credentials configured in n8n?
2. Private key correct and accessible?
3. Target system reachable from Outpost?
4. User has permissions for command?

**Debug:**
```bash
# Test SSH manually from Outpost
ssh outpost
ssh -i /path/to/key jordan@192.168.0.11 'docker ps'

# Check SSH logs on target
ssh nexus 'sudo journalctl -u ssh -n 50'
```

### Issue: Claude API Errors
**Check:**
1. API key valid and active?
2. Sufficient API credits?
3. Request format correct?
4. Rate limits hit?

**Debug:**
```bash
# Test API manually
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model": "claude-sonnet-4-5-20250929", "max_tokens": 100, "messages": [{"role": "user", "content": "test"}]}'
```

### Issue: PostgreSQL Connection Failures
**Check:**
1. n8n-db container running?
2. Credentials correct in n8n?
3. Database `finance_db` exists?
4. Tables created?

**Debug:**
```bash
ssh outpost 'docker ps | grep n8n-db'
ssh outpost 'docker exec -it n8n-db psql -U n8n -d finance_db -c "\dt"'
```

## Future Enhancements

### Phase 2 Features
1. **ML-Based Pattern Recognition**
   - Learn from successful remediations
   - Predict alert patterns
   - Suggest preventive actions

2. **Multi-Step Remediation Workflows**
   - Complex recovery procedures
   - Rollback capabilities
   - State machine tracking

3. **Proactive Health Checks**
   - Periodic system scans
   - Drift detection
   - Capacity planning

4. **Cost Tracking**
   - Claude API costs per remediation
   - ROI analysis (time saved vs. cost)
   - Budget alerts

5. **Remediation Templates**
   - User-definable workflows
   - Alert-type to template mapping
   - Version control for templates

## References

- [n8n Documentation](https://docs.n8n.io/)
- [Anthropic Claude API](https://docs.anthropic.com/en/api/)
- [Alertmanager Webhook](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)
- [PostgreSQL Arrays](https://www.postgresql.org/docs/current/arrays.html)
- [Discord Webhooks](https://discord.com/developers/docs/resources/webhook)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-09
**Author:** Claude Code
**Status:** Design Complete, Ready for Implementation
