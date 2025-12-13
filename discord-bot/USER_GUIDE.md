# Jarvis Discord Bot - User Guide

Quick reference for using Jarvis in Discord to interact with Claude Code AI for homelab management.

## Getting Started

Jarvis is an AI assistant that can help you manage and troubleshoot The Burrow homelab infrastructure. Ask questions, get status reports, and have multi-turn conversations with context retention.

**Access Requirements:**
- Member of the "Fucking Nerds" Discord server
- `homelab-admin` role assigned
- Access to the `#jarvis-requests` channel

**Rate Limits:**
- 10 requests per 5 minutes per user
- Exceeding the limit shows a cooldown timer

## Basic Usage

### Simple Questions

Ask Jarvis anything by mentioning the bot:

```
@Jarvis what services are running on Service-Host?
```

Jarvis will respond with the answer directly in the channel.

### Specify an Expert Agent

For specialized tasks, you can request a specific expert:

```
@Jarvis ask homelab-architect "how should I deploy a new monitoring service?"
```

**Available Agents:**
- `homelab-architect` - Infrastructure design, system planning
- `home-assistant-expert` - Home automation, sensors, integrations
- `n8n-workflow-architect` - Workflow automation design
- `homelab-security-auditor` - Security reviews and audits
- `financial-automation-guru` - Budget tracking, financial automation
- `omada-network-engineer` - Network configuration, VLANs
- `python-claude-code-expert` - Python development help
- `technical-documenter` - Documentation creation

If you don't specify an agent, Claude will automatically select the best one for your question.

## Multi-Turn Conversations

Jarvis remembers context within a session. You can ask follow-up questions without repeating information:

**Example:**
```
You: @Jarvis list all Docker containers on Service-Host
Jarvis: [Lists containers: caddy, frigate, adguard, prometheus, grafana...]

You: @Jarvis show me the logs for the Frigate container
Jarvis: [Shows Frigate logs]

You: @Jarvis restart it if there are errors
Jarvis: [Checks logs, restarts Frigate if needed]
```

**Session Behavior:**
- Sessions last for 30 minutes of inactivity
- Same user + same channel = same session (context preserved)
- After 30 minutes of silence, the next message starts a new session

## Session Control

### End a Session

When you're done with a task:

```
@Jarvis done
```

or

```
@Jarvis cancel
```

Your next message will start a fresh session with no prior context.

### Force a New Session

To start over without waiting 30 minutes:

```
@Jarvis new session
```

## What Jarvis Can Do

**System Status:**
- Check service health across all 4 homelab systems
- View Docker container status
- Monitor system resources (CPU, memory, disk)
- Check active Prometheus alerts

**Service Management:**
- Restart containers
- View logs
- Check configurations
- Verify backups

**Information Lookup:**
- Find documentation
- Explain system architecture
- Locate configuration files
- Review deployment procedures

**Infrastructure Tasks:**
- Design new services
- Plan deployments
- Review security configurations
- Create documentation

**What Jarvis Cannot Do:**
- Destructive operations without explicit confirmation
- Modify production databases directly
- Change firewall rules without review
- Delete backups or critical data

Jarvis operates with the same permissions as the primary Claude Code instance, with built-in safety checks for dangerous commands.

## Response Format

Jarvis responses include:

```
@YourUsername Response from Claude Code:

[Claude's answer here]

Session: 6db70575... | Requests remaining: 9
```

- **Session ID**: Short identifier for tracking (first 8 characters)
- **Requests remaining**: Your remaining requests in the current 5-minute window

**Long Responses:**
If Claude's response is very long (over 2000 characters), it will be split into multiple messages:

```
(continued 2/3)
[More content...]
```

## Rate Limiting

**Limit:** 10 requests per 5 minutes

**When you exceed the limit:**
```
⏱️ @YourUsername Rate limit exceeded! Try again in 4m 32s.
```

Wait for the timer to expire, then ask again.

**Why rate limiting?**
- Prevents accidental spam
- Ensures fair access for all users
- Protects Claude Code API costs

## Common Use Cases

### Check if a Service is Down

```
@Jarvis is Frigate running on Service-Host?
```

### Find Out Why Alerts are Firing

```
@Jarvis what Prometheus alerts are currently active?
@Jarvis why is the PostgreSQL alert firing?
```

### Get Deployment Instructions

```
@Jarvis ask homelab-architect "how do I deploy a new Docker service on Service-Host?"
```

### Troubleshoot Home Assistant

```
@Jarvis ask home-assistant-expert "why isn't my Zigbee sensor responding?"
```

### Create n8n Workflows

```
@Jarvis ask n8n-workflow-architect "design a workflow to send Discord alerts when backups fail"
```

### Review Security Configurations

```
@Jarvis ask homelab-security-auditor "review the Caddy configuration for security issues"
```

## Tips for Better Results

**Be Specific:**
- Good: "Show me Frigate's error logs from the last hour"
- Less good: "Check Frigate"

**Provide Context:**
- Good: "The Frigate container keeps restarting on Service-Host, check the logs and tell me why"
- Less good: "Container issue"

**Use Follow-ups:**
Instead of repeating yourself:
```
@Jarvis list containers on Service-Host
@Jarvis restart the first one  ← Jarvis remembers which was first
```

**Request Agent Expertise:**
For specialized tasks, ask the right expert:
```
@Jarvis ask omada-network-engineer "create a guest network VLAN"
```

## Troubleshooting

### Jarvis Doesn't Respond

**Check:**
1. Did you @mention Jarvis?
2. Are you in the `#jarvis-requests` channel?
3. Do you have the `homelab-admin` role?
4. Did you exceed the rate limit? (Wait for the timer)

### Response Says "Error"

```
❌ @YourUsername Error: [error message]
```

Common errors:
- **Empty message**: You mentioned Jarvis but didn't ask anything
- **Message too short**: Add more context to your question
- **Service unavailable**: Jarvis may be restarting (wait 30 seconds and try again)

### Session Not Remembering Context

If Jarvis doesn't remember your previous message:
- Check if 30 minutes passed since your last message
- Try asking in the same channel
- Use `@Jarvis new session` to start fresh, then continue

### Response is Incomplete

Long responses are split into chunks. Scroll up to see earlier parts marked:
```
(continued 2/3)
```

## Privacy & Security

**What Jarvis Sees:**
- Your Discord username and user ID
- Your messages in `#jarvis-requests` when you @mention Jarvis
- Your conversation history for the current session

**What Gets Stored:**
- Session metadata (user ID, timestamps, session ID)
- Your messages and Jarvis's responses (stored in PostgreSQL for 90 days)
- Conversation context (stored in Claude Code session files)

**Access Control:**
- Only users with `homelab-admin` role can use Jarvis
- All commands are logged and auditable
- Jarvis operates with the same safety checks as the primary Claude Code instance

**Data Retention:**
- Active sessions: 30 minutes of inactivity
- Session history: 90 days in PostgreSQL
- Cleanup: Automatic (old sessions deleted after 90 days)

## Getting Help

**For technical issues:**
Ask in `#homelab` or contact Jordan directly.

**For access issues:**
Request the `homelab-admin` role from a server administrator.

**For general questions:**
Just ask Jarvis:
```
@Jarvis how do I use this bot?
```

## Quick Reference

| Command | Description |
|---------|-------------|
| `@Jarvis [question]` | Ask a question |
| `@Jarvis ask [agent] "[question]"` | Use specific expert agent |
| `@Jarvis done` | End current session |
| `@Jarvis cancel` | Cancel current session |
| `@Jarvis new session` | Force new session |

**Rate Limit:** 10 requests per 5 minutes
**Session Timeout:** 30 minutes of inactivity
**Response Limit:** 2000 characters per message (splits if longer)
