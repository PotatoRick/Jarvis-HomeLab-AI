# Remaining Implementation Tasks

## STATUS: 50% Complete (Phases 1-3 done, 4-8 remaining)

We've completed:
- ✅ Phase 1: Database migration to Skynet
- ✅ Phase 8.1: Knowledge base schema created
- ✅ Phase 2: Host monitoring fully integrated
- ✅ Phase 3: Alert suppression engine working

Created but not yet integrated:
- 📄 `app/alert_queue.py` - Needs integration into main.py and database.py

Still to implement:
- Phase 4 integration
- Phase 6: Database resilience
- Phase 7: SSH resilience
- Phase 8.2-8.7: Learning engine
- Phase 5: Maintenance windows
- Testing & docs

## Quick Integration Guide for Alert Queue (Phase 4)

### 1. Update main.py lifespan
```python
# Add to imports
from .alert_queue import AlertQueue

# Add to globals
alert_queue = None

# In lifespan function after db.connect():
alert_queue = AlertQueue(db)
await alert_queue.start()

# In cleanup:
await alert_queue.stop()
```

### 2. Update health endpoint
```python
@app.get("/health")
async def health_check():
    db_connected = await db.health_check()

    # Determine status
    if alert_queue and alert_queue.is_degraded():
        status = "degraded"
    elif db_connected:
        status = "healthy"
    else:
        status = "unhealthy"

    response = {
        "status": status,
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
        "database_connected": db_connected,
        "maintenance_mode": await db.is_maintenance_mode() if db_connected else False
    }

    if alert_queue:
        response["queue_stats"] = alert_queue.get_stats()

    return response
```

### 3. Update database log_remediation_attempt
In `database.py`, wrap database inserts with queue fallback:
```python
async def log_remediation_attempt(self, data: Dict):
    try:
        # Normal database insert
        async with self.pool.acquire() as conn:
            await conn.execute(INSERT_QUERY, ...)
    except Exception as e:
        # Fallback to queue if database unavailable
        if alert_queue:
            await alert_queue.enqueue(data)
            logger.warning("database_unavailable_using_queue")
        else:
            raise
```

## Phases 6 & 7: Connection Resilience (Simple)

### database.py - Add retry decorator
```python
import asyncio
from functools import wraps

def retry_with_backoff(max_retries=5, base_delay=1):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)  # Exponential
                    logger.warning(f"Retry {attempt+1}/{max_retries} after {delay}s")
                    await asyncio.sleep(delay)
        return wrapper
    return decorator

# Apply to connect() method
@retry_with_backoff(max_retries=10, base_delay=1)
async def connect(self):
    # existing code
```

### ssh_executor.py - Add retry to execute_command
```python
async def execute_command_with_retry(self, host, command, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await self.execute_command(host, command)
        except (ConnectionError, asyncio.TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            delay = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(f"SSH retry {attempt+1}/{max_retries}")
            await asyncio.sleep(delay)

            # Close stale connection
            if host in self._connections:
                del self._connections[host]
```

## Phase 8.2-8.7: Learning Engine (Core Implementation)

This is the most complex phase. Create these files:

### 1. `app/learning_engine.py` - Pattern extraction and matching
- `async def extract_pattern(remediation_log_id)` - Create pattern from successful fix
- `async def find_similar_patterns(alert_name, labels, annotations)` - Match existing
- `def calculate_confidence(pattern)` - Bayesian scoring
- `async def record_outcome(pattern_id, success)` - Update stats

### 2. Update `main.py` process_alert():
```python
# BEFORE Claude analysis:
patterns = await learning_engine.find_similar_patterns(alert_name, labels, annotations)

if patterns and patterns[0].confidence > 0.75:
    # Use learned solution, skip Claude
    commands = patterns[0].solution_commands
    logger.info("using_learned_pattern", confidence=patterns[0].confidence)
elif patterns:
    # Pass to Claude as context
    system_prompt += f"\\n\\nHistorical pattern: {patterns[0]}"

# AFTER successful remediation:
await learning_engine.extract_pattern(log_id)
```

### 3. `app/analytics.py` - Simple stats queries
```python
async def get_learning_stats():
    query = "SELECT COUNT(*), AVG(confidence_score) FROM remediation_patterns"
    # ... return stats dict
```

### 4. Add API endpoints to main.py:
```python
@app.get("/patterns")
async def list_patterns():
    return await learning_engine.get_all_patterns()

@app.get("/analytics")
async def get_analytics():
    return await analytics.get_learning_stats()
```

## Phase 5: Maintenance Windows (OPTIONAL - Can skip)

Simple REST endpoints:
```python
@app.post("/maintenance/start")
async def start_maintenance(host: str, reason: str):
    await db.execute(
        "INSERT INTO maintenance_windows (host, reason) VALUES ($1, $2)",
        host, reason
    )
    return {"status": "started"}

@app.post("/maintenance/end")
async def end_maintenance(host: str):
    await db.execute(
        "UPDATE maintenance_windows SET ended_at=NOW(), is_active=FALSE WHERE host=$1 AND is_active=TRUE",
        host
    )
    return {"status": "ended"}
```

## Testing Checklist

1. **Restart Jarvis**: `docker compose restart jarvis`
2. **Check health**: `curl http://localhost:8000/health`
3. **Trigger test alert** (if Alertmanager available)
4. **Verify logs**: `docker logs jarvis --tail 50`
5. **Check database**: `docker exec postgres-jarvis psql -U jarvis -d jarvis -c "SELECT COUNT(*) FROM remediation_patterns;"`

## Documentation Updates

1. Update `CLAUDE.md` with new Jarvis capabilities
2. Create `/documentation/jarvis-architecture.md`
3. Update `README.md` in projects/ai-remediation-service

## Estimated Time Remaining

- Phase 4 integration: 15 min
- Phase 6 & 7: 30 min
- Phase 8 (simplified): 60 min
- Phase 5 (if doing): 20 min
- Testing: 20 min
- Docs: 15 min

**Total: ~2.5 hours** (or 2 hours if skipping Phase 5)

## Priority Order

1. **Phase 4** - Critical for DB resilience
2. **Phase 6** - Database retry logic
3. **Phase 7** - SSH retry logic
4. **Test basic functionality**
5. **Phase 8** - Learning (can be added incrementally later)
6. **Phase 5** - Maintenance (nice-to-have)
7. **Documentation**
