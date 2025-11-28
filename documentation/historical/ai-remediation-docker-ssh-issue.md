# AI Remediation System - Docker SSH Access Issue

**Date**: November 10, 2025
**Status**: System 95% Complete - One Critical Blocker Remaining
**Location**: Skynet (192.168.0.13) - Python FastAPI service in Docker

---

## Quick Resume Instructions

### System Status RIGHT NOW
```bash
# AI service is STOPPED (disabled to prevent overnight API usage)
docker ps -a | grep ai-remediation
# Should show: STATUS = Exited

# To restart when ready
docker start ai-remediation
docker logs -f ai-remediation
```

### The ONE Remaining Problem
**Docker commands fail when executed via SSH from the AI service to Outpost (72.60.163.242)**

**What works manually:**
```bash
ssh jordan@72.60.163.242 'docker ps'
# Returns: Container list ✓
```

**What fails from AI container:**
```python
# From inside ai-remediation container
stdout, stderr, exit_code = await ssh_executor.execute_command(
    HostType.OUTPOST,
    'docker ps',
    timeout=10
)
# Returns: Exit 127, "docker: not found" ✗
```

**BUT the PATH is correct!**
```python
# This works and shows /usr/bin in PATH:
await ssh_executor.execute_command(HostType.OUTPOST, 'echo $PATH', timeout=10)
# Output: /usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin ✓
```

### Resume Tomorrow With These Tests

#### Test 1: Check Docker Group Membership
```python
docker exec ai-remediation python3 -c "
import asyncio
from app.ssh_executor import ssh_executor
from app.models import HostType

async def test():
    stdout, stderr, exit_code = await ssh_executor.execute_command(
        HostType.OUTPOST,
        'groups',
        timeout=10
    )
    print(f'Groups: {stdout}')
    # Should show: jordan sudo users docker

asyncio.run(test())
"
```

#### Test 2: Check Docker Socket Permissions
```bash
ssh outpost 'ls -la /var/run/docker.sock'
# Expected: srw-rw---- 1 root docker
```

#### Test 3: Test with Absolute Path
```python
docker exec ai-remediation python3 -c "
import asyncio
from app.ssh_executor import ssh_executor
from app.models import HostType

async def test():
    stdout, stderr, exit_code = await ssh_executor.execute_command(
        HostType.OUTPOST,
        '/usr/bin/docker --version',
        timeout=10
    )
    print(f'Exit: {exit_code}, Output: {stdout}')

asyncio.run(test())
"
```

---

## Session Summary (November 10, 2025)

### What We Fixed Today ✅

1. **Escalation Limit**: Increased from 3 to 5 attempts
2. **Per-Container Tracking**: Each container now has independent attempt counter (e.g., `outpost:promtail`, `outpost:actual-budget`)
3. **Corrupted Metrics**: Fixed tab delimiter parsing issue in docker health exporter
4. **Prometheus TSDB**: Cleaned corrupted data
5. **SSH Configuration**: Fixed host/user settings for Outpost
6. **PATH in SSH**: Added bash wrapper to export full PATH
7. **Async Webhooks**: Returns HTTP 200 in <100ms (previously fixed)
8. **Attempt Logic**: Only counts failed attempts (previously fixed)

### Files Modified Today

| File | What Changed |
|------|--------------|
| `/opt/ai-remediation/.env` | `MAX_ATTEMPTS_PER_ALERT=5`, `SSH_OUTPOST_HOST=72.60.163.242`, `SSH_OUTPOST_USER=jordan` |
| `/opt/ai-remediation/app/main.py` | Lines 202-208: Per-container instance tracking |
| `/opt/ai-remediation/app/ssh_executor.py` | Lines 141-144: Bash wrapper with PATH export |
| `/opt/ai-remediation/app/database.py` | Line 77: `AND success = FALSE` filter |
| `/opt/burrow/scripts/docker_health_exporter.sh` | Clean metrics script (Outpost) |
| `/usr/local/bin/docker_health_exporter.sh` | Clean metrics script (Skynet) |
| `/home/jordan/.ssh/authorized_keys` (Outpost) | Added AI SSH key |

### System Architecture

```
┌─────────────┐   Scrapes    ┌────────────────┐   Webhooks   ┌─────────────────┐
│ Prometheus  │─────────────>│ Docker Health  │<─────────────│  Alertmanager   │
│  (Nexus)    │   every 30s  │   Exporters    │              │    (Nexus)      │
└─────────────┘              └────────────────┘              └─────────────────┘
                                                                      │
                                                                      │ HTTP POST
                                                                      ▼
                                                              ┌─────────────────┐
                                                              │ AI Remediation  │
                                                              │   (Skynet)      │
                                                              │   PORT 8000     │
                                                              └─────────────────┘
                                                                      │
                                                                      │ SSH Commands
                                                                      ▼
                                                              ┌─────────────────┐
                                                              │ Target Systems  │
                                                              │ (Nexus/Outpost/ │
                                                              │  HomeAssistant) │
                                                              └─────────────────┘
```

---

## The Docker SSH Problem (CRITICAL BLOCKER)

### Symptoms
```bash
# Manual SSH works
$ ssh jordan@72.60.163.242 'docker ps'
CONTAINER ID   NAMES
...containers listed... ✓

# From AI service fails
$ docker exec ai-remediation python3 -c "..."
Exit code: 127
Stderr: /bin/sh: 1: docker: not found ✗
```

### What We Know

#### Environment is Correct
- PATH includes `/usr/bin` ✓
- Jordan user exists ✓
- Jordan is in docker group: `jordan : jordan sudo users docker` ✓
- Docker binary exists at `/usr/bin/docker` ✓
- SSH authentication works ✓
- Bash wrapper executes ✓

#### But Docker Still Not Found
Tested these and all failed:
- `docker --version` → "not found"
- `/usr/bin/docker --version` → "not found"
- `which docker` → returns nothing
- `ls /usr/bin/docker` → "No such file" (exit 2)

### Root Cause Theories

#### Theory 1: Docker Socket Permissions
Docker requires access to `/var/run/docker.sock`. Non-interactive SSH might not have socket access even with correct group membership.

**Test:**
```bash
ssh outpost 'ls -la /var/run/docker.sock'
# Should show: srw-rw---- 1 root docker
```

#### Theory 2: Group Membership Not Effective
Jordan's docker group membership might not be active in non-interactive SSH sessions.

**Test:**
```python
# Check effective groups
await ssh_executor.execute_command(HostType.OUTPOST, 'groups', timeout=10)
# Should include 'docker'

# Check group ID
await ssh_executor.execute_command(HostType.OUTPOST, 'id', timeout=10)
# Should show docker group in list
```

#### Theory 3: AsyncSSH Execution Context
The `asyncssh` library might execute commands in a restricted context different from normal SSH.

**Test:**
```python
# Try with newgrp
command = "newgrp docker <<EOF\ndocker ps\nEOF"
await ssh_executor.execute_command(HostType.OUTPOST, command, timeout=10)
```

#### Theory 4: Docker Binary Not Actually There
Maybe `/usr/bin/docker` is a symlink that doesn't resolve in SSH context?

**Test:**
```bash
ssh outpost 'readlink -f /usr/bin/docker'
# Follow symlinks to find real binary
```

### Troubleshooting Plan for Tomorrow

#### Step 1: Gather Information
```python
docker start ai-remediation

# Run these tests
commands = [
    'groups',                    # Check group membership
    'id',                        # Check effective UID/GIDs
    'ls -la /usr/bin/docker',   # Check if binary exists
    'readlink -f /usr/bin/docker',  # Follow symlinks
    'ls -la /var/run/docker.sock',  # Check socket permissions
    'test -r /var/run/docker.sock && echo readable || echo not readable',  # Test socket read access
]

for cmd in commands:
    stdout, stderr, exit_code = await ssh_executor.execute_command(
        HostType.OUTPOST, cmd, timeout=10
    )
    print(f"{cmd}: {stdout} (exit {exit_code})")
```

#### Step 2: Try Alternative Approaches

**Option A: Use `sudo docker`**
```bash
# Check if jordan has passwordless sudo
ssh outpost 'sudo -n docker ps'

# If yes, modify bash wrapper in ssh_executor.py to prepend sudo to docker commands
```

**Option B: Try `newgrp docker`**
```python
# Modify ssh_executor.py line 144:
command_with_path = f"bash -c 'export PATH=/usr/bin:$PATH; newgrp docker <<EOF\n{escaped_command}\nEOF'"
```

**Option C: Switch to root user**
```bash
# In .env
SSH_OUTPOST_USER=root

# Then test if docker works as root
```

**Option D: Use `sg docker` (substitute group)**
```python
command_with_path = f"bash -c 'export PATH=/usr/bin:$PATH; sg docker \"{escaped_command}\"'"
```

#### Step 3: If None Work, Debug AsyncSSH
```python
# Try bypassing asyncssh and using subprocess.run with direct SSH
import subprocess
result = subprocess.run(
    ['ssh', '-i', '/app/ssh_key', 'jordan@72.60.163.242', 'docker ps'],
    capture_output=True, text=True
)
print(result.stdout)
```

---

## Complete Checklist for Working System

- [x] Docker health exporter on all systems
- [x] Clean metrics generated
- [x] Prometheus scraping correctly
- [x] Per-container attempt tracking
- [x] Async webhook processing
- [x] Escalation limit = 5
- [x] SSH authentication configured
- [x] PATH environment set correctly
- [ ] **Docker commands work via SSH** ← BLOCKER
- [ ] End-to-end test (stop container, AI restarts it)
- [ ] All 3 systems tested (Nexus, Outpost, HA)
- [ ] Escalation flow tested (5 failed attempts)
- [ ] Discord notifications working

**Status**: 8/12 complete (67%)

---

## Configuration Files

### AI Service Environment
```bash
# /opt/ai-remediation/.env

DATABASE_URL=postgresql://n8n:PASSWORD@72.60.163.242:5432/finance_db
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-5-20250929

SSH_NEXUS_HOST=192.168.0.11
SSH_NEXUS_USER=jordan

SSH_HOMEASSISTANT_HOST=192.168.0.10
SSH_HOMEASSISTANT_USER=root

SSH_OUTPOST_HOST=72.60.163.242
SSH_OUTPOST_USER=jordan

DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
WEBHOOK_AUTH_USERNAME=alertmanager
WEBHOOK_AUTH_PASSWORD=O28nsEX3clSJvpNvBLjKfM4Tk92KqLhy4OqPH1OLPf0=

MAX_ATTEMPTS_PER_ALERT=5
ATTEMPT_WINDOW_HOURS=24
COMMAND_EXECUTION_TIMEOUT=60
```

### SSH Key Info
```bash
# AI service key location (inside container)
/app/ssh_key

# Public key (added to jordan@outpost authorized_keys)
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOGmmdbCkURVvBt1xx0/ofWb/2TNt/lI2SG5RWyP7nrh homelab-ai-remediation
```

### Bash Wrapper Code
```python
# /opt/ai-remediation/app/ssh_executor.py lines 141-144

# Wrap command in bash with explicit PATH to ensure binaries are found in non-interactive SSH
# Escape single quotes in the command to avoid breaking the bash -c wrapper
escaped_command = command.replace("'", "'\\''")
command_with_path = f"bash -c 'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; {escaped_command}'"
```

---

## Testing Commands

### Service Management
```bash
# Start AI service
docker start ai-remediation

# View logs
docker logs -f ai-remediation

# Stop AI service (to prevent API usage)
docker stop ai-remediation

# Restart after config changes
docker restart ai-remediation
```

### Test Docker Access
```bash
# This should work (manual SSH)
ssh jordan@72.60.163.242 'docker ps'

# This should fail (from AI container)
docker exec ai-remediation python3 -c "
import asyncio
from app.ssh_executor import ssh_executor
from app.models import HostType

async def test():
    stdout, stderr, exit_code = await ssh_executor.execute_command(
        HostType.OUTPOST,
        'docker ps',
        timeout=10
    )
    print(f'Exit: {exit_code}')
    print(f'Stdout: {stdout}')
    print(f'Stderr: {stderr}')

asyncio.run(test())
"
```

### Trigger Real Test
```bash
# Once docker access is fixed:

# 1. Start AI service
docker start ai-remediation

# 2. Stop a container on Outpost
ssh outpost 'docker stop promtail'

# 3. Monitor AI logs
docker logs -f ai-remediation

# 4. Should see:
#  - Alert received
#  - Claude analysis
#  - SSH execution: docker start promtail
#  - Success notification
#  - Database logged

# 5. Verify container restarted
ssh outpost 'docker ps | grep promtail'
```

---

## Related Documentation

- **Main Docs**: `/home/t1/homelab/documentation/ai-remediation-system.md`
- **Setup Guide**: `/home/t1/homelab/documentation/ai-remediation-quickstart.md`
- **Old n8n Log**: `/home/t1/homelab/documentation/ai-remediation-troubleshooting-log.md`
- **System Index**: `/home/t1/homelab/documentation/ai-remediation-system-index.md`

---

## Key Code Locations

| Component | File | Lines |
|-----------|------|-------|
| Per-container tracking | `/opt/ai-remediation/app/main.py` | 202-208 |
| Bash wrapper / PATH fix | `/opt/ai-remediation/app/ssh_executor.py` | 141-144 |
| Attempt counting | `/opt/ai-remediation/app/database.py` | 71-91 |
| Async webhooks | `/opt/ai-remediation/app/main.py` | 131-172 |
| Config | `/opt/ai-remediation/.env` | All |

---

**TOMORROW: Start with Theory 2 (group membership test)**

```python
# FIRST TEST TOMORROW
docker start ai-remediation

docker exec ai-remediation python3 -c "
import asyncio
from app.ssh_executor import ssh_executor
from app.models import HostType

async def test():
    # Test 1: Check groups
    stdout1, _, _ = await ssh_executor.execute_command(HostType.OUTPOST, 'groups', timeout=10)
    print(f'Groups: {stdout1}')

    # Test 2: Check id
    stdout2, _, _ = await ssh_executor.execute_command(HostType.OUTPOST, 'id', timeout=10)
    print(f'ID: {stdout2}')

    # Test 3: Try with sg (substitute group)
    stdout3, stderr3, exit3 = await ssh_executor.execute_command(HostType.OUTPOST, 'sg docker \"docker ps\"', timeout=10)
    print(f'sg docker result: Exit={exit3}, Out={stdout3}, Err={stderr3}')

asyncio.run(test())
"
```

If `sg docker` works, update `/opt/ai-remediation/app/ssh_executor.py` line 144:
```python
command_with_path = f"bash -c 'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; sg docker \"{escaped_command}\"'"
```

---

**Last Updated**: November 10, 2025, 11:05 PM EST
**Next Session**: Test docker group membership and try `sg docker` wrapper
**AI Service Status**: STOPPED (intentionally, to prevent overnight API usage)
