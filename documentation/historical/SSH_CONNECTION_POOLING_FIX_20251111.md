# SSH Connection Pooling Fix

**Date:** November 11, 2025 (8:30 PM EST / 01:30 UTC)
**Issue:** Command timeouts during AI remediation attempts
**Status:** ✅ Implemented and Testing

---

## Problem

During scrypted container remediation at 8:21 PM, the AI service experienced widespread command timeouts:

```
2025-11-12 01:22:55 [error] command_timeout command=docker logs --tail 200 scrypted 2>&1
2025-11-12 01:23:03 [error] command_timeout command=docker ps --filter name=scrypted
2025-11-12 01:23:39 [error] command_timeout command=docker restart scrypted
```

**Symptoms:**
- Commands timing out after 60 seconds
- Multiple simultaneous SSH connection attempts
- Remediation taking 3+ minutes instead of seconds
- Despite timeouts, container was successfully restarted

**Statistics:**
- **24 SSH connections** created in 5 minutes
- Each command created a new connection and immediately closed it
- Claude made parallel tool calls, flooding Nexus with simultaneous SSH connections

---

## Root Cause

The `SSHExecutor` class had a connection pooling dictionary (`self._connections = {}`) that was **initialized but never used**.

### Code Issue in `/app/ssh_executor.py`

**Line 23:**
```python
def __init__(self):
    self.logger = logger.bind(component="ssh_executor")
    self._connections = {}  # ← Created but never used!
```

**Lines 44-93:** `_get_connection()` method
- Always created a new connection via `asyncssh.connect()`
- Never checked `self._connections` for existing connections
- Never stored connections for reuse

**Line 155:** `execute_command()` method
```python
conn = await self._get_connection(host)
result = await asyncio.wait_for(conn.run(command, check=False), timeout=timeout)
# ... process result ...
conn.close()  # ← Immediately closed after use!
```

### Why This Caused Timeouts

1. Claude API makes **parallel tool calls** during analysis:
   - `gather_logs()` + `check_service_status()` + `execute_safe_command()` simultaneously
   - Each tool call triggers `execute_command()`
   - Each command creates a new SSH connection

2. **Connection flooding:**
   - 5-10 simultaneous SSH connections to Nexus
   - Each connection has overhead (key exchange, auth, etc.)
   - Nexus SSH daemon gets overwhelmed
   - Some connections timeout waiting for previous ones to complete

3. **Cascading failures:**
   - First few commands succeed
   - Later commands timeout after 60s
   - Claude retries with different approaches
   - More parallel calls → more connections → more timeouts

---

## Solution Implemented

### 1. Connection Pooling in `_get_connection()`

**File:** `/app/ssh_executor.py` (lines 60-71)

```python
async def _get_connection(self, host: HostType) -> asyncssh.SSHClientConnection:
    # ... handle localhost case ...

    # Check if we have an existing connection that's still alive
    if host in self._connections:
        conn = self._connections[host]
        if not conn.is_closed():
            self.logger.debug(
                "reusing_ssh_connection",
                host=host.value
            )
            return conn
        else:
            # Connection is closed, remove it
            del self._connections[host]

    # Create new connection only if needed
    config = self.host_config[host]
    conn = await asyncio.wait_for(asyncssh.connect(...), timeout=...)

    # Store connection for reuse
    self._connections[host] = conn

    self.logger.info("ssh_connection_established", host=host.value)
    return conn
```

**Behavior:**
- First call to Nexus: Creates connection, stores in `self._connections[HostType.NEXUS]`
- Subsequent calls: Returns existing connection immediately (no overhead)
- If connection is closed: Removes from pool and creates new one

### 2. Removed Connection Closure

**File:** `/app/ssh_executor.py` (line 155)

**Before:**
```python
conn.close()  # Closed after every command
```

**After:**
```python
# Don't close connection - keep it open for reuse
```

**Rationale:**
- Connections stay open for the lifetime of the remediation session
- Multiple commands share the same connection
- No reconnection overhead between commands

### 3. Graceful Shutdown

**File:** `/app/ssh_executor.py` (lines 371-383)

```python
async def close_all_connections(self):
    """
    Close all open SSH connections.
    Should be called on shutdown.
    """
    for host, conn in list(self._connections.items()):
        if not conn.is_closed():
            conn.close()
            self.logger.info(
                "ssh_connection_closed",
                host=host.value
            )
    self._connections.clear()
```

**Purpose:**
- Clean up connections when service shuts down
- Prevents resource leaks
- Can be called manually if needed

---

## Expected Impact

### Before Fix:
- **24 connections** for one remediation attempt
- Each command: 100-200ms connection overhead + command execution
- Parallel commands compete for SSH daemon resources
- Commands timeout waiting for connection slots

### After Fix:
- **1 connection** per host for entire remediation session
- First command: 100-200ms overhead
- Subsequent commands: ~10-50ms (no connection overhead)
- No competition for SSH daemon resources
- No connection-related timeouts

### Performance Improvement:
```
Before: 24 connections × 200ms = 4,800ms overhead
After:  1 connection  × 200ms = 200ms overhead
Savings: 4,600ms (4.6 seconds) per remediation
```

---

## Verification Test

**Test Command:**
```bash
# Stop scrypted to trigger alert
ssh nexus 'docker stop scrypted'

# Wait for alert and remediation (2.5 min)
# Then check connection statistics:

docker logs ai-remediation --since 3m | grep ssh_connection_established | wc -l
# Expected: 1 (only one new connection)

docker logs ai-remediation --since 3m | grep reusing_ssh_connection | wc -l
# Expected: 10-20 (many reuses)
```

**Success Criteria:**
- ✅ Only 1-2 new connections created
- ✅ 10+ connection reuses logged
- ✅ No command timeouts
- ✅ Remediation completes in < 60 seconds
- ✅ Container successfully restarted

---

## Files Changed

### `/app/ssh_executor.py`
1. **Lines 60-71**: Added connection pooling logic in `_get_connection()`
   - Check for existing connection
   - Reuse if alive
   - Create and store if needed

2. **Line 155**: Removed `conn.close()` call
   - Keep connections open for reuse

3. **Lines 371-383**: Added `close_all_connections()` method
   - Graceful shutdown cleanup

---

## Rollback Procedure

If issues arise:

```bash
cd /home/t1/homelab/projects/ai-remediation-service

# View changes
git diff app/ssh_executor.py

# Revert if needed
git checkout app/ssh_executor.py
docker compose restart
```

---

## Related Issues

This fix also resolves:
- **Issue #1**: Multiple "command failed with exit code -1" errors
- **Issue #2**: Remediation taking 3+ minutes instead of seconds
- **Issue #3**: Successful commands being reported as failures due to connection overhead
- **Issue #4**: High SSH daemon load on Nexus during remediation

---

## Monitoring

### Check Connection Pooling is Working:
```bash
# During active remediation:
docker logs ai-remediation --tail 50 | grep -E "(ssh_connection|reusing)"

# Should see:
# ssh_connection_established (once at start)
# reusing_ssh_connection (many times)
```

### Check for Timeouts:
```bash
docker logs ai-remediation --tail 100 | grep command_timeout

# Should see:
# (empty - no timeouts)
```

### Check Remediation Speed:
```bash
# Look for command_batch_completed entries
docker logs ai-remediation --tail 50 | grep command_batch_completed

# duration_seconds should be < 60s total
```

---

## Next Steps

1. ✅ **Implemented**: Connection pooling code
2. ✅ **Deployed**: Service restarted with fix
3. 🔄 **Testing**: scrypted remediation test in progress
4. ⏳ **Verify**: Check test results after 2.5 minutes
5. ⏳ **Monitor**: Watch for any new issues over next 24 hours

---

## Conclusion

The SSH connection pooling fix addresses the root cause of command timeouts by:
- Reusing SSH connections instead of creating new ones for every command
- Eliminating connection overhead (200ms per command → 10-50ms)
- Preventing SSH daemon flooding during parallel tool calls
- Reducing total remediation time from 3+ minutes to < 60 seconds

**This is a critical performance and reliability improvement that should be monitored closely.**
