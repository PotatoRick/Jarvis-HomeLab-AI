# FrigateDatabaseError Remediation Runbook

<!-- risk_level: medium -->
<!-- estimated_duration: 2-5 minutes -->
<!-- target_host: nexus -->

## Overview

This alert fires when Frigate's SQLite database becomes corrupted, inaccessible, or when the events API fails to respond. Database corruption is a common issue with Frigate, especially after power outages or disk I/O errors.

## Alert Variants

This runbook covers these related alerts:
- **FrigateDatabaseError**: Database health check fails
- **FrigateEventsAPIDown**: Events API fails but main API responds (database corruption)
- **FrigateEventsStale**: No events recorded for 1+ hour despite cameras online
- **FrigateCamerasNotReceivingFrames**: All cameras report 0 FPS

## Investigation Steps

1. Check if Frigate API responds: `curl -s http://localhost:5000/api/version`
2. Check if events API responds: `curl -s http://localhost:5000/api/events?limit=1`
3. Check recent Frigate logs for errors: `docker logs frigate --tail 200 | grep -i error`
4. Check database file exists and size: `ls -la /media/frigate/frigate.db`
5. Check disk space on Frigate media mount: `df -h /media/frigate`

## Common Causes

- SQLite database corruption (power loss, disk errors)
- Database file locked by crashed process
- Disk space exhaustion preventing writes
- I/O errors on the storage device
- Database schema migration failure after update

## Remediation Steps

1. **First**: Check the database file exists and has non-zero size
2. **If database missing/empty**: Frigate will recreate on restart
3. **If disk full**: Clear old recordings first, then restart
4. **Default**: Restart Frigate container - this resolves most corruption issues
5. **If restart fails**: Check logs for specific SQLite error messages
6. **If persistent**: Delete corrupted database and let Frigate recreate

## Commands

```bash
# Check Frigate container status
docker ps | grep frigate

# Check database file
ls -la /media/frigate/frigate.db

# Check disk space
df -h /media/frigate

# View recent logs
docker logs frigate --tail 200

# Check for specific database errors
docker logs frigate --tail 500 2>&1 | grep -iE "database|sqlite|peewee|corrupt"

# Restart Frigate (usually fixes corruption)
docker restart frigate

# If restart fails, check if database needs deletion
# WARNING: This loses all event history
# docker stop frigate
# rm /media/frigate/frigate.db
# docker start frigate
```

## Verification

After restart, verify:
1. API responds: `curl -s http://localhost:5000/api/version`
2. Events API works: `curl -s http://localhost:5000/api/events?limit=5 | jq length`
3. Cameras show FPS > 0: `curl -s http://localhost:5000/api/stats | jq '.cameras | to_entries[] | {name: .key, fps: .value.camera_fps}'`

## Notes

- Database corruption is common after power outages - always verify after outage
- Events history is lost if database must be deleted, but recordings remain on disk
- Consider setting up UPS protection to prevent power-related corruption
- Frigate stores recordings on disk independently; only metadata/events are in SQLite
- The `frigate_events_recent` metric tracks if events are being recorded (staleness detection)
