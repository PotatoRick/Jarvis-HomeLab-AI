"""
AI Remediation Service - Main FastAPI Application

Receives Alertmanager webhooks, uses Claude AI to analyze alerts,
executes safe remediation commands via SSH, and notifies via Discord.
"""

import structlog
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from datetime import datetime
import secrets

from .config import settings
from .models import (
    AlertmanagerWebhook,
    HealthCheckResponse,
    MaintenanceWindow,
    RemediationAttempt,
    RiskLevel,
)
from .database import db
from .claude_agent import claude_agent
from .command_validator import CommandValidator
from .discord_notifier import discord_notifier
from .ssh_executor import ssh_executor
from .host_monitor import HostMonitor
from .alert_suppressor import AlertSuppressor
from .alert_queue import AlertQueue
from .learning_engine import LearningEngine
from .external_service_monitor import ExternalServiceMonitor
from .prometheus_client import prometheus_client
from .alert_correlator import AlertCorrelator, init_correlator, alert_correlator
from .proactive_monitor import ProactiveMonitor, init_proactive_monitor, proactive_monitor
from .rollback_manager import RollbackManager, init_rollback_manager, rollback_manager
from .n8n_client import init_n8n_client
from .runbook_manager import init_runbook_manager, get_runbook_manager
from . import metrics
from .utils import (
    determine_target_host,
    extract_service_name,
    determine_service_type,
    format_alert_for_context,
    is_cross_system_alert,
    get_related_hosts,
    extract_hints_from_alert,  # v3.0: Alert hint extraction
    get_confidence_level,       # v3.0: Confidence level helpers
)

# Initialize components (will be set up in lifespan)
host_monitor = None
alert_suppressor = None
alert_queue = None
learning_engine = None
external_service_monitor = None
correlator = None
proactive_mon = None  # Phase 3: Proactive monitoring
rollback_mgr = None   # Phase 3: Rollback capability

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer() if settings.log_format == "json" else structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# HTTP Basic Auth
security = HTTPBasic()


async def log_attempt_with_fallback(attempt):
    """
    Log remediation attempt to database with queue fallback.

    If database is unavailable, queues the attempt for later insertion.
    """
    try:
        return await db.log_remediation_attempt(attempt)
    except Exception as e:
        logger.warning(
            "database_unavailable_queueing_attempt",
            error=str(e),
            alert=attempt.alert_name
        )
        if alert_queue:
            # Convert attempt to dict for queueing
            await alert_queue.enqueue({
                'alert_name': attempt.alert_name,
                'alert_instance': attempt.alert_instance,
                'severity': attempt.severity,
                'alert_labels': {},  # TODO: capture if needed
                'alert_annotations': {},
                'attempt_number': attempt.attempt_number,
                'ai_analysis': attempt.ai_analysis,
                'ai_reasoning': attempt.ai_reasoning,
                'remediation_plan': attempt.remediation_plan,
                'commands_executed': attempt.commands_executed,
                'command_outputs': attempt.command_outputs,
                'exit_codes': attempt.exit_codes,
                'success': attempt.success,
                'error_message': attempt.error_message,
                'execution_duration_seconds': attempt.execution_duration_seconds,
                'risk_level': attempt.risk_level.value if attempt.risk_level else 'low',
                'escalated': attempt.escalated,
                'user_approved': attempt.user_approved,
                'discord_message_id': attempt.discord_message_id,
                'discord_thread_id': attempt.discord_thread_id
            })
        return None  # No ID when queued


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    global host_monitor, alert_suppressor, alert_queue, learning_engine, external_service_monitor, correlator, proactive_mon, rollback_mgr

    logger.info(
        "application_starting",
        version=settings.app_version,
        debug=settings.debug
    )

    # Connect to database
    await db.connect()

    # Initialize alert queue for degraded mode
    alert_queue = AlertQueue(db)
    await alert_queue.start()

    # Initialize and start host monitoring
    host_monitor = HostMonitor(db, discord_notifier, settings)
    ssh_executor.host_monitor = host_monitor  # Inject host monitor
    await host_monitor.start()

    # Initialize external service monitoring
    external_service_monitor = ExternalServiceMonitor(cache_ttl_seconds=300)
    await external_service_monitor.start()
    logger.info("external_service_monitor_initialized")

    # Initialize alert suppression
    alert_suppressor = AlertSuppressor(host_monitor, discord_notifier)

    # Initialize learning engine
    learning_engine = LearningEngine(db)
    logger.info("learning_engine_initialized")

    # Initialize alert correlator for root cause analysis (Phase 2)
    correlator = init_correlator(db)
    logger.info("alert_correlator_initialized")

    # Phase 3: Initialize n8n client for workflow orchestration
    init_n8n_client()

    # Phase 3: Initialize rollback manager for state snapshots
    rollback_mgr = init_rollback_manager(ssh_executor=ssh_executor)
    logger.info("rollback_manager_initialized")

    # Phase 3: Initialize and start proactive monitoring
    proactive_mon = init_proactive_monitor(ssh_executor=ssh_executor)
    if proactive_mon:
        await proactive_mon.start()
        logger.info("proactive_monitor_started")

    # CRITICAL-003 FIX: Validate SSH keys on startup
    ssh_key_errors = ssh_executor.get_key_validation_errors()
    if ssh_key_errors:
        # Log warnings but don't fail startup - some hosts may be localhost
        for error in ssh_key_errors:
            logger.warning("ssh_key_validation_warning", error=error)
    else:
        logger.info("ssh_keys_validated", message="All SSH keys validated successfully")

    # Phase 4: Initialize runbook manager
    runbook_dir = "/app/runbooks"  # Default Docker path
    import os
    if not os.path.exists(runbook_dir):
        # Fallback for local development
        runbook_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "runbooks")
    init_runbook_manager(runbook_dir=runbook_dir)
    logger.info("runbook_manager_initialized", runbook_dir=runbook_dir)

    # Phase 4: Initialize Prometheus metrics
    metrics.init_metrics(settings.app_version)
    metrics.set_database_status(True)
    logger.info("prometheus_metrics_initialized")

    yield

    # Cleanup
    await host_monitor.stop()
    await alert_queue.stop()
    await external_service_monitor.stop()
    # Phase 3: Stop proactive monitoring
    if proactive_mon:
        await proactive_mon.stop()
    # HIGH-011 FIX: Close SSH connections on shutdown to prevent resource leaks
    await ssh_executor.close_all_connections()
    await db.disconnect()
    logger.info("application_shutdown")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify HTTP Basic Auth credentials."""
    correct_username = secrets.compare_digest(
        credentials.username,
        settings.webhook_auth_username
    )
    correct_password = secrets.compare_digest(
        credentials.password,
        settings.webhook_auth_password
    )

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


@app.get("/version")
async def get_version():
    """
    Get Jarvis version information.

    LOW-006: Dedicated version endpoint for quick version checks and monitoring.
    """
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "python_version": "3.11"
    }


@app.get("/metrics")
async def prometheus_metrics():
    """
    Prometheus metrics endpoint for self-monitoring.

    Phase 4: Exposes Jarvis performance metrics for Prometheus scraping.
    Add to Prometheus scrape config:
        - job_name: 'jarvis'
          static_configs:
            - targets: ['192.168.0.13:8000']
    """
    return metrics.get_metrics_response()


@app.get("/runbooks")
async def list_runbooks():
    """
    List all available runbooks.

    Phase 4: Returns runbook inventory for debugging and visibility.
    """
    runbook_mgr = get_runbook_manager()
    if not runbook_mgr:
        return {
            "status": "not_initialized",
            "runbooks": []
        }

    return {
        "status": "ok",
        "count": len(runbook_mgr.runbooks),
        "runbooks": runbook_mgr.list_runbooks()
    }


@app.get("/runbooks/{alert_name}")
async def get_runbook(alert_name: str):
    """
    Get runbook for a specific alert type.

    Phase 4: Returns structured runbook content for an alert.
    """
    runbook_mgr = get_runbook_manager()
    if not runbook_mgr:
        raise HTTPException(
            status_code=503,
            detail="Runbook manager not initialized"
        )

    runbook = runbook_mgr.get_runbook(alert_name)
    if not runbook:
        raise HTTPException(
            status_code=404,
            detail=f"No runbook found for alert: {alert_name}"
        )

    return {
        "alert_name": runbook.alert_name,
        "title": runbook.title,
        "overview": runbook.overview,
        "investigation_steps": runbook.investigation_steps,
        "common_causes": runbook.common_causes,
        "remediation_steps": runbook.remediation_steps,
        "commands": runbook.commands,
        "risk_level": runbook.risk_level,
        "estimated_duration": runbook.estimated_duration
    }


@app.post("/runbooks/reload")
async def reload_runbooks():
    """
    Reload runbooks from disk.

    Phase 4: Allows refreshing runbooks without restarting Jarvis.
    """
    runbook_mgr = get_runbook_manager()
    if not runbook_mgr:
        raise HTTPException(
            status_code=503,
            detail="Runbook manager not initialized"
        )

    count = runbook_mgr.reload()
    return {
        "status": "reloaded",
        "count": count
    }


@app.get("/health")
async def health_check():
    """Health check endpoint with degraded mode support."""
    db_connected = await db.health_check()

    # Determine status based on queue state and DB connection
    if alert_queue and alert_queue.is_degraded():
        status = "degraded"  # Queue has items, DB was unavailable
    elif db_connected:
        status = "healthy"
    else:
        status = "unhealthy"

    in_maintenance = await db.is_maintenance_mode() if db_connected else False

    response = {
        "status": status,
        "version": settings.app_version,
        "timestamp": datetime.utcnow().isoformat(),
        "database_connected": db_connected,
        "maintenance_mode": in_maintenance
    }

    # Add queue stats if available
    if alert_queue:
        queue_stats = alert_queue.get_stats()
        if queue_stats["queue_depth"] > 0:
            response["queue_stats"] = queue_stats

    return response


@app.get("/patterns")
async def get_patterns(
    min_confidence: float = 0.0,
    limit: int = 100
):
    """
    Get learned remediation patterns.

    Args:
        min_confidence: Minimum confidence score filter
        limit: Maximum number of patterns to return
    """
    if not learning_engine:
        raise HTTPException(
            status_code=503,
            detail="Learning engine not initialized"
        )

    # Refresh cache to get latest patterns
    await learning_engine._refresh_pattern_cache()

    # Filter patterns by confidence
    patterns = [
        p for p in learning_engine._pattern_cache
        if p['confidence_score'] >= min_confidence
    ]

    # Limit results
    patterns = patterns[:limit]

    # Format for API response
    response = {
        "count": len(patterns),
        "patterns": [
            {
                "id": p['id'],
                "alert_name": p['alert_name'],
                "category": p['alert_category'],
                "confidence": round(p['confidence_score'], 3),
                "success_count": p['success_count'],
                "failure_count": p['failure_count'],
                "usage_count": p['usage_count'],
                "risk_level": p['risk_level'],
                "target_host": p.get('target_host'),  # v3.2: Host override
                "solution": p['solution_commands'],
                "root_cause": p.get('root_cause'),
                "last_used": p['last_used_at'].isoformat() if p['last_used_at'] else None,
                "avg_execution_time": round(p['avg_execution_time'], 1) if p['avg_execution_time'] else None
            }
            for p in patterns
        ]
    }

    return response


@app.get("/patterns/{pattern_id}")
async def get_pattern(pattern_id: int):
    """Get details of a specific pattern."""
    if not learning_engine:
        raise HTTPException(
            status_code=503,
            detail="Learning engine not initialized"
        )

    query = """
        SELECT
            id, alert_name, alert_category, symptom_fingerprint,
            root_cause, solution_commands, success_count, failure_count,
            confidence_score, risk_level, usage_count, avg_execution_time,
            created_at, updated_at, last_used_at, enabled
        FROM remediation_patterns
        WHERE id = $1
    """

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(query, pattern_id)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Pattern {pattern_id} not found"
        )

    pattern = dict(row)

    # Format for API response
    response = {
        "id": pattern['id'],
        "alert_name": pattern['alert_name'],
        "category": pattern['alert_category'],
        "symptom_fingerprint": pattern['symptom_fingerprint'],
        "root_cause": pattern['root_cause'],
        "solution": pattern['solution_commands'],
        "statistics": {
            "confidence": round(pattern['confidence_score'], 3),
            "success_count": pattern['success_count'],
            "failure_count": pattern['failure_count'],
            "usage_count": pattern['usage_count'],
            "avg_execution_time": round(pattern['avg_execution_time'], 1) if pattern['avg_execution_time'] else None
        },
        "risk_level": pattern['risk_level'],
        "enabled": pattern['enabled'],
        "timestamps": {
            "created": pattern['created_at'].isoformat(),
            "updated": pattern['updated_at'].isoformat() if pattern['updated_at'] else None,
            "last_used": pattern['last_used_at'].isoformat() if pattern['last_used_at'] else None
        }
    }

    return response


@app.get("/analytics")
async def get_analytics():
    """Get learning engine analytics and statistics."""
    if not learning_engine:
        raise HTTPException(
            status_code=503,
            detail="Learning engine not initialized"
        )

    # Get pattern stats
    stats = await learning_engine.get_pattern_stats()

    # Get remediation stats from database
    remediation_stats = await db.get_statistics(days=30)

    response = {
        "learning_engine": {
            "total_patterns": stats['total_patterns'],
            "high_confidence_patterns": stats['high_confidence'],
            "medium_confidence_patterns": stats['medium_confidence'],
            "average_confidence": round(stats['avg_confidence'], 3) if stats['avg_confidence'] else 0,
            "total_pattern_usage": stats['total_usage'],
            "estimated_api_calls_saved": int(stats['estimated_api_calls_saved'])
        },
        "remediation_performance": {
            "total_attempts_30d": remediation_stats['total_attempts'],
            "successful": remediation_stats['successful'],
            "escalated": remediation_stats['escalated'],
            "success_rate": round(remediation_stats['success_rate'], 1),
            "avg_duration_seconds": round(remediation_stats['avg_duration'], 1) if remediation_stats['avg_duration'] else 0,
            "unique_alerts": remediation_stats['unique_alerts']
        },
        "cost_savings": {
            "api_calls_saved": int(stats['estimated_api_calls_saved']),
            "estimated_cost_savings_usd": round(stats['estimated_api_calls_saved'] * 0.003, 2)  # ~$0.003 per call
        }
    }

    return response


@app.get("/external-services")
async def get_external_service_health():
    """
    Get health status of all monitored external services.

    Useful for debugging DDNS alert suppression and verifying service availability.
    """
    if not external_service_monitor:
        raise HTTPException(
            status_code=503,
            detail="External service monitor not initialized"
        )

    # Get all service health
    service_health = await external_service_monitor.get_all_service_health()

    # Format for API response
    response = {
        "timestamp": datetime.utcnow().isoformat(),
        "services": {}
    }

    for service_key, health in service_health.items():
        response["services"][service_key] = {
            "name": health.service,
            "status": health.status.value,
            "last_checked": health.last_checked.isoformat(),
            "response_time_ms": round(health.response_time_ms, 2) if health.response_time_ms else None,
            "error": health.error_message,
            "status_page": health.status_page_url
        }

    # Add summary
    operational_count = sum(
        1 for h in service_health.values()
        if h.status.value == "operational"
    )
    response["summary"] = {
        "total_services": len(service_health),
        "operational": operational_count,
        "degraded": sum(1 for h in service_health.values() if h.status.value == "degraded"),
        "outage": sum(1 for h in service_health.values() if h.status.value == "outage"),
        "cloudflare_healthy": await external_service_monitor.is_cloudflare_healthy()
    }

    return response


@app.post("/maintenance/start")
async def start_maintenance(
    host: str = None,
    reason: str = "Manual maintenance",
    created_by: str = "manual"
):
    """
    Start a maintenance window.

    Args:
        host: Optional host to limit maintenance to (nexus, homeassistant, outpost)
              If not specified, applies to ALL hosts (global maintenance)
        reason: Reason for maintenance
        created_by: Who initiated the maintenance

    Returns:
        Maintenance window details

    Example:
        # Global maintenance (all hosts)
        POST /maintenance/start?reason=System+upgrades&created_by=jordan

        # Host-specific maintenance
        POST /maintenance/start?host=nexus&reason=Docker+upgrade&created_by=jordan
    """
    # Check if there's already an active maintenance window
    query_check = """
        SELECT id, host, started_at, reason
        FROM maintenance_windows
        WHERE is_active = TRUE
          AND ended_at IS NULL
          AND (host = $1 OR host IS NULL OR $1 IS NULL)
        LIMIT 1
    """

    async with db.pool.acquire() as conn:
        existing = await conn.fetchrow(query_check, host)

        if existing:
            return {
                "status": "already_active",
                "message": f"Maintenance window already active for {existing['host'] or 'all hosts'}",
                "maintenance_window": {
                    "id": existing['id'],
                    "host": existing['host'],
                    "started_at": existing['started_at'].isoformat(),
                    "reason": existing['reason']
                }
            }

        # Create new maintenance window
        query_insert = """
            INSERT INTO maintenance_windows (host, reason, created_by)
            VALUES ($1, $2, $3)
            RETURNING id, host, started_at, reason, created_by
        """

        row = await conn.fetchrow(query_insert, host, reason, created_by)

    logger.info(
        "maintenance_window_started",
        window_id=row['id'],
        host=host or "all",
        reason=reason,
        created_by=created_by
    )

    # Send Discord notification if enabled
    if discord_notifier and settings.discord_enabled:
        scope = f"**{host.upper()}**" if host else "**ALL HOSTS**"
        message = f"""🔧 **Maintenance Window Started**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Scope:** {scope}
**Reason:** {reason}
**Started By:** {created_by}
**Started At:** {row['started_at'].strftime('%Y-%m-%d %H:%M:%S')}

**Impact:**
• Alert remediation {"for " + host if host else ""} is **PAUSED**
• Alerts will be suppressed and logged
• Use `POST /maintenance/end` to resume normal operations

Jarvis will not attempt any remediations until maintenance ends."""

        await discord_notifier.send_webhook({
            "username": "Jarvis - Maintenance",
            "content": message
        })

    return {
        "status": "started",
        "maintenance_window": {
            "id": row['id'],
            "host": row['host'],
            "started_at": row['started_at'].isoformat(),
            "reason": row['reason'],
            "created_by": row['created_by']
        }
    }


@app.post("/maintenance/end")
async def end_maintenance(
    window_id: int = None,
    host: str = None
):
    """
    End a maintenance window.

    Args:
        window_id: Specific window ID to end (optional)
        host: Host to end maintenance for (optional)
              If neither specified, ends ALL active maintenance windows

    Returns:
        Ended maintenance window details

    Example:
        # End specific window
        POST /maintenance/end?window_id=5

        # End maintenance for specific host
        POST /maintenance/end?host=nexus

        # End all active maintenance
        POST /maintenance/end
    """
    # Build query based on parameters
    if window_id:
        query = """
            UPDATE maintenance_windows
            SET ended_at = NOW(),
                is_active = FALSE
            WHERE id = $1
              AND is_active = TRUE
              AND ended_at IS NULL
            RETURNING id, host, started_at, ended_at, reason, suppressed_alert_count
        """
        params = [window_id]
    elif host:
        query = """
            UPDATE maintenance_windows
            SET ended_at = NOW(),
                is_active = FALSE
            WHERE host = $1
              AND is_active = TRUE
              AND ended_at IS NULL
            RETURNING id, host, started_at, ended_at, reason, suppressed_alert_count
        """
        params = [host]
    else:
        # End all active maintenance windows
        query = """
            UPDATE maintenance_windows
            SET ended_at = NOW(),
                is_active = FALSE
            WHERE is_active = TRUE
              AND ended_at IS NULL
            RETURNING id, host, started_at, ended_at, reason, suppressed_alert_count
        """
        params = []

    async with db.pool.acquire() as conn:
        if params:
            rows = await conn.fetch(query, *params)
        else:
            rows = await conn.fetch(query)

    if not rows:
        return {
            "status": "not_found",
            "message": "No active maintenance window found"
        }

    ended_windows = []
    for row in rows:
        duration = (row['ended_at'] - row['started_at']).total_seconds() / 60  # minutes

        logger.info(
            "maintenance_window_ended",
            window_id=row['id'],
            host=row['host'] or "all",
            duration_minutes=duration,
            suppressed_alerts=row['suppressed_alert_count']
        )

        ended_windows.append({
            "id": row['id'],
            "host": row['host'],
            "started_at": row['started_at'].isoformat(),
            "ended_at": row['ended_at'].isoformat(),
            "duration_minutes": round(duration, 1),
            "reason": row['reason'],
            "suppressed_alerts": row['suppressed_alert_count']
        })

        # Send Discord notification
        if discord_notifier and settings.discord_enabled:
            scope = f"**{row['host'].upper()}**" if row['host'] else "**ALL HOSTS**"
            message = f"""✅ **Maintenance Window Ended**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Scope:** {scope}
**Duration:** {round(duration, 1)} minutes
**Alerts Suppressed:** {row['suppressed_alert_count']}
**Ended At:** {row['ended_at'].strftime('%Y-%m-%d %H:%M:%S')}

Normal alert processing and remediation has resumed."""

            await discord_notifier.send_webhook({
                "username": "Jarvis - Maintenance",
                "content": message
            })

    return {
        "status": "ended",
        "windows_ended": len(ended_windows),
        "maintenance_windows": ended_windows
    }


@app.get("/maintenance/status")
async def get_maintenance_status():
    """
    Get current maintenance window status.

    Returns:
        List of active maintenance windows and recent history
    """
    # Get active windows
    query_active = """
        SELECT id, host, started_at, reason, created_by, suppressed_alert_count
        FROM maintenance_windows
        WHERE is_active = TRUE
          AND ended_at IS NULL
        ORDER BY started_at DESC
    """

    # Get recent completed windows (last 24 hours)
    query_recent = """
        SELECT id, host, started_at, ended_at, reason, suppressed_alert_count
        FROM maintenance_windows
        WHERE is_active = FALSE
          AND ended_at IS NOT NULL
          AND ended_at > NOW() - INTERVAL '24 hours'
        ORDER BY ended_at DESC
        LIMIT 10
    """

    async with db.pool.acquire() as conn:
        active_rows = await conn.fetch(query_active)
        recent_rows = await conn.fetch(query_recent)

    active_windows = []
    for row in active_rows:
        duration = (datetime.utcnow() - row['started_at'].replace(tzinfo=None)).total_seconds() / 60

        active_windows.append({
            "id": row['id'],
            "host": row['host'],
            "started_at": row['started_at'].isoformat(),
            "duration_minutes": round(duration, 1),
            "reason": row['reason'],
            "created_by": row['created_by'],
            "suppressed_alerts": row['suppressed_alert_count']
        })

    recent_windows = []
    for row in recent_rows:
        duration = (row['ended_at'] - row['started_at']).total_seconds() / 60

        recent_windows.append({
            "id": row['id'],
            "host": row['host'],
            "started_at": row['started_at'].isoformat(),
            "ended_at": row['ended_at'].isoformat(),
            "duration_minutes": round(duration, 1),
            "reason": row['reason'],
            "suppressed_alerts": row['suppressed_alert_count']
        })

    return {
        "in_maintenance": len(active_windows) > 0,
        "active_windows": active_windows,
        "recent_windows": recent_windows
    }


@app.post("/webhook/alertmanager")
async def receive_alertmanager_webhook(
    webhook: AlertmanagerWebhook,
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    """
    Receive and process Alertmanager webhook.

    This is the main entry point for alert remediation.
    """
    logger.info(
        "webhook_received",
        alert_count=len(webhook.alerts),
        status=webhook.status.value,
        receiver=webhook.receiver
    )

    # Check maintenance mode
    if await db.is_maintenance_mode():
        logger.info("maintenance_mode_active", action="skipping_remediation")
        return {"status": "skipped", "reason": "maintenance_mode"}

    # Handle resolved alerts - clear attempt counters and escalation cooldowns
    if webhook.status.value == "resolved":
        for alert in webhook.alerts:
            alert_name = alert.labels.alertname

            # Build container-specific instance for ContainerDown alerts
            if alert_name == "ContainerDown" and hasattr(alert.labels, "container") and hasattr(alert.labels, "host"):
                alert_instance = f"{alert.labels.host}:{alert.labels.container}"
            else:
                alert_instance = alert.labels.instance

            cleared_count = await db.clear_attempts(alert_name, alert_instance)

            # v3.1.0: Clear escalation cooldown so fresh incidents get escalated
            cooldown_cleared = await db.clear_escalation_cooldown(alert_name, alert_instance)

            # Clear root cause from suppression
            if alert_suppressor:
                alert_suppressor.clear_root_cause(alert_name)

            logger.info(
                "attempts_cleared_on_resolution",
                alert_name=alert_name,
                alert_instance=alert_instance,
                cleared_count=cleared_count,
                escalation_cooldown_cleared=cooldown_cleared
            )

        return {
            "status": "resolved",
            "alerts_processed": len(webhook.alerts),
            "attempts_cleared": True
        }

    # Process each firing alert
    results = []
    for alert in webhook.alerts:
        # Only process firing alerts
        if alert.status.value != "firing":
            logger.info(
                "alert_not_firing",
                alert_name=alert.labels.alertname,
                status=alert.status.value
            )
            continue

        try:
            result = await process_alert(alert)
            results.append(result)
        except Exception as e:
            logger.error(
                "alert_processing_failed",
                alert_name=alert.labels.alertname,
                error=str(e)
            )
            results.append({
                "alert": alert.labels.alertname,
                "status": "error",
                "error": str(e)
            })

    return {
        "status": "processed",
        "alerts_processed": len(results),
        "results": results
    }


def is_actionable_command(command: str) -> bool:
    """
    Determine if a command is actionable (modifies state) vs diagnostic (read-only).

    Only actionable commands should count toward remediation attempts.

    MEDIUM-001 FIX: Added comprehensive list of diagnostic patterns.

    Args:
        command: Command string to evaluate

    Returns:
        True if command is actionable, False if diagnostic
    """
    import re

    # MEDIUM-001 FIX: Comprehensive diagnostic/read-only commands (do NOT count as attempts)
    diagnostic_patterns = [
        # Docker read-only commands
        r'^docker\s+ps',
        r'^docker\s+logs',
        r'^docker\s+inspect',
        r'^docker\s+stats',
        r'^docker\s+images',
        r'^docker\s+port',
        r'^docker\s+top',
        r'^docker\s+events',
        r'^docker\s+info',
        r'^docker\s+version',
        r'^docker\s+compose\s+ps',
        r'^docker\s+compose\s+logs',
        r'^docker\s+compose\s+config',
        r'^docker\s+compose\s+images',
        r'^docker\s+compose\s+ls',
        # Systemd read-only commands
        r'^systemctl\s+status',
        r'^systemctl\s+is-active',
        r'^systemctl\s+is-enabled',
        r'^systemctl\s+is-failed',
        r'^systemctl\s+show',
        r'^systemctl\s+list-',
        r'^journalctl',
        # Network diagnostics
        r'^curl\s+.*-[IfsSkLv]',  # GET requests with info/silent flags
        r'^curl\s+--head',
        r'^wget\s+--spider',
        r'^ping',
        r'^traceroute',
        r'^tracepath',
        r'^dig\s',
        r'^nslookup',
        r'^host\s',
        r'^netstat',
        r'^ss\s+-',
        r'^ip\s+(addr|link|route|neigh)\s+(show|list)?',
        # System information
        r'^uptime',
        r'^free',
        r'^df',
        r'^du\s',
        r'^top\s+-b',
        r'^vmstat',
        r'^iostat',
        r'^mpstat',
        r'^sar\s',
        r'^w$',
        r'^who$',
        r'^whoami',
        r'^hostname',
        r'^uname',
        r'^lscpu',
        r'^lsmem',
        # File system read-only
        r'^ls\s',
        r'^ls$',
        r'^cat\s',
        r'^head\s',
        r'^tail\s',
        r'^less\s',
        r'^more\s',
        r'^grep\s',
        r'^find\s',
        r'^stat\s',
        r'^file\s',
        r'^wc\s',
        r'^diff\s',
        r'^md5sum',
        r'^sha\d+sum',
        # Process/system lookup
        r'^which\s',
        r'^whereis\s',
        r'^type\s',
        r'^ps\s+aux',
        r'^ps\s+-ef',
        r'^pgrep',
        r'^pidof',
        r'^dmesg',
        r'^lsblk',
        r'^lsof',
        r'^lspci',
        r'^lsusb',
        r'^fdisk\s+-l',
        r'^blkid',
        # Home Assistant read-only
        r'^ha\s+core\s+info',
        r'^ha\s+core\s+check',
        r'^ha\s+core\s+stats',
        r'^ha\s+info',
        r'^ha\s+backups\s+list',
        r'^ha\s+addons\s+info',
        r'^ha\s+network\s+info',
        # Database read-only
        r'^psql\s+-c\s+["\']SELECT',  # SELECT queries only
        r'^sqlite3\s+.*\s+["\']SELECT',
        # Echo/print (diagnostic output)
        r'^echo\s',
        r'^printf\s',
    ]

    for pattern in diagnostic_patterns:
        if re.match(pattern, command, re.IGNORECASE):
            return False

    # Everything else is considered actionable
    return True


async def process_alert(alert):
    """
    Process a single alert through the remediation pipeline.

    Args:
        alert: Alert instance from Alertmanager

    Returns:
        Processing result dictionary
    """
    alert_name = alert.labels.alertname
    alert_fingerprint = alert.fingerprint
    severity = getattr(alert.labels, 'severity', 'warning')

    # Phase 4: Record alert received metric
    metrics.record_alert_received(alert_name, severity)
    metrics.update_active_remediations(1)  # Increment active count

    # HIGH-010 FIX: Validate alert fingerprint exists and is non-empty
    # Empty fingerprints could bypass deduplication entirely
    if not alert_fingerprint or not isinstance(alert_fingerprint, str) or len(alert_fingerprint.strip()) == 0:
        logger.error(
            "invalid_alert_fingerprint",
            alert_name=alert_name,
            fingerprint=alert_fingerprint,
            reason="Fingerprint is empty, None, or invalid"
        )
        return {
            "alert": alert_name,
            "status": "error",
            "reason": "Invalid or missing alert fingerprint"
        }

    # Normalize fingerprint (strip whitespace)
    alert_fingerprint = alert_fingerprint.strip()

    # Build container-specific alert instance for ContainerDown alerts
    # This prevents different containers on same host from sharing attempt counters
    # HIGH-001 FIX: Always prefer explicit container/host labels over instance format
    if alert_name == "ContainerDown":
        if hasattr(alert.labels, "container") and hasattr(alert.labels, "host"):
            # Always prefer explicit labels - they're more accurate
            alert_instance = f"{alert.labels.host}:{alert.labels.container}"
            logger.info(
                "container_specific_instance_built",
                original_instance=alert.labels.instance,
                container_instance=alert_instance
            )
        elif ":" in alert.labels.instance:
            # Instance already in host:container format (from Prometheus rule)
            alert_instance = alert.labels.instance
            logger.info(
                "container_specific_instance_from_label",
                alert_instance=alert_instance
            )
        else:
            # Fallback to instance label
            alert_instance = alert.labels.instance
            logger.warning(
                "container_specific_instance_fallback",
                alert_instance=alert_instance,
                reason="No container/host labels or colon in instance"
            )
    else:
        alert_instance = alert.labels.instance

    # =========================================================================
    # v3.1.0: Fingerprint-based deduplication
    # CRITICAL-002 FIX: Use atomic check-and-set to prevent race conditions
    # =========================================================================
    # Check if we recently processed this exact alert (same fingerprint)
    # This prevents spam when Alertmanager sends repeated webhooks for ongoing alerts
    # The atomic operation ensures that two simultaneous alerts with the same fingerprint
    # can't both pass the cooldown check
    in_cooldown, last_processed = await db.check_and_set_fingerprint_atomic(
        fingerprint=alert_fingerprint,
        alert_name=alert_name,
        alert_instance=alert_instance,
        cooldown_seconds=settings.fingerprint_cooldown_seconds
    )

    if in_cooldown:
        logger.info(
            "alert_deduplicated",
            alert_name=alert_name,
            alert_instance=alert_instance,
            fingerprint=alert_fingerprint[:16] + "...",
            last_processed=last_processed.isoformat() if last_processed else None,
            cooldown_seconds=settings.fingerprint_cooldown_seconds
        )
        # Phase 4: Record skipped metric (deduplicated)
        metrics.record_remediation_attempt(alert_name, 'skipped')
        metrics.update_active_remediations(-1)
        return {
            "alert": alert_name,
            "status": "deduplicated",
            "reason": f"Same fingerprint processed within {settings.fingerprint_cooldown_seconds}s"
        }

    # Fingerprint was atomically set above, no need for separate set call

    logger.info(
        "processing_alert",
        alert_name=alert_name,
        alert_instance=alert_instance
    )

    # Check attempt count
    attempt_count = await db.get_attempt_count(
        alert_name=alert_name,
        alert_instance=alert_instance,
        window_hours=settings.attempt_window_hours
    )

    if attempt_count >= settings.max_attempts_per_alert:
        logger.warning(
            "max_attempts_reached",
            alert_name=alert_name,
            attempts=attempt_count
        )

        # Escalate
        await escalate_alert(alert, attempt_count)

        # Phase 4: Record escalation metric
        metrics.record_remediation_attempt(alert_name, 'escalated')
        metrics.update_active_remediations(-1)

        return {
            "alert": alert_name,
            "status": "escalated",
            "attempts": attempt_count
        }

    # v3.0: Extract hints from alert description FIRST
    hints = extract_hints_from_alert(alert)

    # Determine target system (now uses hints to override instance if needed)
    target_host = determine_target_host(alert, hints)
    service_name = extract_service_name(alert)
    service_type = determine_service_type(alert, service_name)

    logger.info(
        "alert_context_determined",
        alert_name=alert_name,
        target_host=target_host.value,
        service_name=service_name,
        service_type=service_type,
        hint_host=hints.get("remediation_host_hint"),  # v3.0: Log hint if present
    )

    # Check for host-specific or global maintenance window
    maintenance_window = await db.get_active_maintenance_window(target_host.value)
    if maintenance_window:
        # Increment suppression counter
        await db.increment_maintenance_suppression_count(maintenance_window['id'])

        scope = maintenance_window['host'] or "all hosts"
        logger.info(
            "alert_suppressed_maintenance",
            alert_name=alert_name,
            instance=alert_instance,
            window_id=maintenance_window['id'],
            scope=scope,
            reason=maintenance_window['reason']
        )

        # Phase 4: Record suppressed metric
        metrics.record_remediation_attempt(alert_name, 'suppressed')
        metrics.update_active_remediations(-1)

        return {
            "alert": alert_name,
            "status": "suppressed",
            "reason": f"Maintenance mode ({scope})",
            "maintenance_window_id": maintenance_window['id'],
            "target_host": target_host.value
        }

    # Check if alert should be suppressed
    if alert_suppressor:
        should_suppress, suppress_reason = alert_suppressor.should_suppress(
            alert_name=alert_name,
            instance=alert_instance,
            severity=alert.labels.severity if hasattr(alert.labels, 'severity') else 'warning',
            target_host=target_host.value
        )

        if should_suppress:
            logger.info(
                "alert_suppressed",
                alert_name=alert_name,
                instance=alert_instance,
                reason=suppress_reason
            )

            # Phase 4: Record suppressed metric
            metrics.record_remediation_attempt(alert_name, 'suppressed')
            metrics.update_active_remediations(-1)

            return {
                "alert": alert_name,
                "status": "suppressed",
                "reason": suppress_reason,
                "target_host": target_host.value
            }

        # Register root cause alerts
        alert_suppressor.register_root_cause(alert_name)

    # Phase 2: Check for alert correlation (root cause analysis)
    correlation_context = ""
    if correlator:
        try:
            # Build alert dict for correlator
            alert_dict = {
                "labels": dict(alert.labels),
                "annotations": dict(alert.annotations) if hasattr(alert, 'annotations') else {},
                "startsAt": alert.startsAt.isoformat() if hasattr(alert, 'startsAt') and alert.startsAt else None
            }

            # Check if this alert correlates with others
            incident = await correlator.correlate_alert(alert_dict)

            if incident:
                logger.info(
                    "alert_correlated",
                    alert_name=alert_name,
                    root_cause=incident.root_cause_alert,
                    correlation_type=incident.correlation_type,
                    related_alerts=incident.related_alerts
                )

                # Check if we should skip this alert (not the root cause)
                if correlator.should_skip_alert(alert_name, incident):
                    logger.info(
                        "alert_skipped_not_root_cause",
                        alert_name=alert_name,
                        root_cause=incident.root_cause_alert,
                        reason="Root cause is being handled"
                    )
                    return {
                        "alert": alert_name,
                        "status": "skipped",
                        "reason": f"Correlated with {incident.root_cause_alert} (root cause)",
                        "correlation_type": incident.correlation_type
                    }

                # Get correlation context to pass to Claude
                correlation_context = await correlator.get_correlation_context(alert_dict)

        except Exception as e:
            logger.warning(
                "correlation_check_failed",
                alert_name=alert_name,
                error=str(e)
            )
            # Continue without correlation - non-critical feature

    # Check if we have a learned pattern for this alert
    use_pattern = False
    learned_pattern = None
    pattern_used_id = None

    if learning_engine:
        use_pattern, learned_pattern = await learning_engine.should_use_pattern(
            alert_name=alert_name,
            alert_labels=dict(alert.labels)
        )

        if use_pattern and learned_pattern:
            logger.info(
                "using_learned_pattern",
                pattern_id=learned_pattern['id'],
                confidence=learned_pattern['effective_confidence'],
                alert_name=alert_name
            )
            pattern_used_id = learned_pattern['id']

    # Gather context for Claude
    alert_context = format_alert_for_context(alert)

    # Check if this is a cross-system alert
    related_hosts = get_related_hosts(alert)
    is_cross_system = len(related_hosts) > 1

    # Build system context with learned pattern if available
    cross_system_note = ""
    if is_cross_system:
        host_names = [h.value for h in related_hosts]
        cross_system_note = f"""
## CROSS-SYSTEM ALERT - CHECK MULTIPLE HOSTS
This alert type often has root causes on MULTIPLE systems.
**You should investigate: {', '.join(host_names)}**
For VPN issues, check both endpoints - the problem might be routing, interface names, or config on either end.
"""

    system_context = f"""
# Homelab System: {target_host.value.upper()}
# Alert Type: {alert_name}
# Service: {service_name or 'unknown'} ({service_type})
# Instance: {alert_instance}
{cross_system_note}
This is part of The Burrow homelab infrastructure. Systems available:
- nexus (192.168.0.11): Docker host with most services, WireGuard endpoint
- homeassistant (192.168.0.10): Home automation hub
- outpost (VPS 72.60.163.242): Cloud gateway with n8n, Headscale, WireGuard endpoint

Common issues and fixes:
- Container crashes: docker restart <container>
- Systemd service down: sudo systemctl restart <service>
- WireGuard VPN down: sudo systemctl restart wg-quick@wg0 (check BOTH nexus AND outpost)
- Home Assistant unresponsive: ha core restart
"""

    # Add learned pattern context if available
    if learned_pattern and not use_pattern:
        # Medium confidence - pass to Claude as context
        system_context += f"""

## Historical Pattern (Confidence: {learned_pattern['confidence_score']:.0%})
Previous successful fixes for similar issues:
Root Cause: {learned_pattern.get('root_cause', 'Unknown')}
Solution: {', '.join(learned_pattern['solution_commands'])}
Success Rate: {learned_pattern['success_count']}/{learned_pattern['success_count'] + learned_pattern['failure_count']}

You may use this pattern if it applies, or suggest a different approach if needed.
"""

    # Phase 2: Add correlation context if available
    if correlation_context:
        system_context += correlation_context

    start_time = datetime.utcnow()

    # If high-confidence pattern, use it directly; otherwise analyze with Claude
    if use_pattern and learned_pattern:
        # Use learned pattern directly (skip Claude API call)
        analysis_obj = type('Analysis', (), {
            'analysis': f"Using learned pattern (confidence: {learned_pattern['effective_confidence']:.0%})",
            'reasoning': learned_pattern.get('root_cause', 'Historical pattern match'),
            'expected_outcome': 'Apply known solution',
            'commands': learned_pattern['solution_commands'],
            'risk': RiskLevel[learned_pattern.get('risk_level', 'MEDIUM').upper()]
        })()

        logger.info(
            "pattern_applied",
            pattern_id=learned_pattern['id'],
            commands=learned_pattern['solution_commands']
        )

        analysis = analysis_obj
    else:
        # Analyze with Claude (using function calling)
        # v3.0: Pass hints for investigation-first approach
        try:
            analysis = await claude_agent.analyze_alert_with_tools(
                alert_data=alert_context,
                system_context=system_context,
                hints=hints  # v3.0: Pass extracted hints
            )

            # v3.0: Log additional investigation details
            logger.info(
                "claude_analysis_completed",
                alert_name=alert_name,
                risk=analysis.risk.value,
                command_count=len(analysis.commands),
                confidence=getattr(analysis, 'confidence', None),
                investigation_steps=len(getattr(analysis, 'investigation_steps', [])),
                target_host_override=getattr(analysis, 'target_host', None),
                instance_misleading=getattr(analysis, 'instance_label_misleading', False),
            )

        except Exception as e:
            logger.error(
                "claude_analysis_failed",
                alert_name=alert_name,
                error=str(e)
            )

            # Log failure attempt
            attempt = RemediationAttempt(
                alert_name=alert_name,
                alert_instance=alert_instance,
                alert_fingerprint=alert_fingerprint,
                severity=alert.labels.severity,
                attempt_number=attempt_count + 1,
                success=False,
                error_message=f"Claude analysis failed: {str(e)}",
                risk_level=RiskLevel.HIGH,
                escalated=True
            )

            await log_attempt_with_fallback(attempt)
            await discord_notifier.notify_failure(
                attempt,
                execution_time=0,
                max_attempts=settings.max_attempts_per_alert
            )

            return {
                "alert": alert_name,
                "status": "failed",
                "error": "AI analysis failed"
            }

    # Validate commands
    validator = CommandValidator()
    validation_result = validator.validate_commands(analysis.commands)

    if not validation_result.safe:
        logger.warning(
            "unsafe_commands_detected",
            alert_name=alert_name,
            rejected=validation_result.rejected_commands
        )

        # Notify about dangerous commands
        await discord_notifier.notify_dangerous_command(
            alert_name=alert_name,
            alert_instance=alert_instance,
            rejected_commands=validation_result.rejected_commands,
            reasons=validation_result.rejection_reasons
        )

        # Log and escalate
        attempt = RemediationAttempt(
            alert_name=alert_name,
            alert_instance=alert_instance,
            alert_fingerprint=alert_fingerprint,
            severity=alert.labels.severity,
            attempt_number=attempt_count + 1,
            ai_analysis=analysis.analysis,
            ai_reasoning=analysis.reasoning,
            remediation_plan=analysis.expected_outcome,
            commands_executed=[],
            success=False,
            error_message="Unsafe commands rejected",
            risk_level=RiskLevel.HIGH,
            escalated=True
        )

        await log_attempt_with_fallback(attempt)

        return {
            "alert": alert_name,
            "status": "rejected",
            "reason": "unsafe_commands"
        }

    # Check risk level - but trust CommandValidator for safe commands
    # Only escalate HIGH risk if:
    # 1. No validated commands available (AI says human intervention needed)
    # 2. Commands include non-standard operations beyond restarts/status checks
    if analysis.risk == RiskLevel.HIGH:
        # Check if we have validated commands that are simple restarts/checks
        simple_restart_patterns = [
            r'^(sudo\s+)?systemctl\s+restart\s+',
            r'^(sudo\s+)?systemctl\s+status\s+',
            r'^docker\s+restart\s+',
            r'^docker\s+ps\b',
            r'^docker\s+logs\b',
            r'^ha\s+core\s+restart',
            r'^journalctl\s+',
        ]

        import re
        has_simple_commands = False
        if validation_result.validated_commands:
            for cmd in validation_result.validated_commands:
                for pattern in simple_restart_patterns:
                    if re.match(pattern, cmd.strip()):
                        has_simple_commands = True
                        break
                if has_simple_commands:
                    break

        if not validation_result.validated_commands or not has_simple_commands:
            # No commands or complex commands - escalate
            logger.warning(
                "high_risk_remediation_escalated",
                alert_name=alert_name,
                reasoning=analysis.reasoning,
                has_commands=bool(validation_result.validated_commands)
            )

            # Log and escalate
            attempt = RemediationAttempt(
                alert_name=alert_name,
                alert_instance=alert_instance,
                alert_fingerprint=alert_fingerprint,
                severity=alert.labels.severity,
                attempt_number=attempt_count + 1,
                ai_analysis=analysis.analysis,
                ai_reasoning=analysis.reasoning,
                remediation_plan=analysis.expected_outcome,
                commands_executed=validation_result.validated_commands,
                success=False,
                error_message="Risk level too high for auto-remediation",
                risk_level=RiskLevel.HIGH,
                escalated=True
            )

            await log_attempt_with_fallback(attempt)
            await escalate_alert(alert, attempt_count + 1)

            return {
                "alert": alert_name,
                "status": "escalated",
                "reason": "high_risk"
            }
        else:
            # Commands are simple restarts that passed validation - proceed with warning
            logger.info(
                "high_risk_override_simple_commands",
                alert_name=alert_name,
                reasoning=analysis.reasoning,
                commands=validation_result.validated_commands,
                note="Proceeding because commands are validated safe restarts"
            )

    # Execute validated commands
    if validation_result.validated_commands:
        # Classify commands as actionable vs diagnostic
        actionable_commands = [cmd for cmd in validation_result.validated_commands if is_actionable_command(cmd)]
        diagnostic_commands = [cmd for cmd in validation_result.validated_commands if not is_actionable_command(cmd)]

        logger.info(
            "executing_remediation",
            alert_name=alert_name,
            total_commands=len(validation_result.validated_commands),
            actionable_commands=len(actionable_commands),
            diagnostic_commands=len(diagnostic_commands)
        )

        execution_result = await ssh_executor.execute_commands(
            host=target_host,
            commands=validation_result.validated_commands,
            timeout=settings.command_execution_timeout
        )

        end_time = datetime.utcnow()
        duration = int((end_time - start_time).total_seconds())

        # Only log as remediation attempt if actionable commands were executed
        if actionable_commands:
            # Log attempt
            attempt = RemediationAttempt(
                alert_name=alert_name,
                alert_instance=alert_instance,
                alert_fingerprint=alert_fingerprint,
                severity=alert.labels.severity,
                attempt_number=attempt_count + 1,
                ai_analysis=analysis.analysis,
                ai_reasoning=analysis.reasoning,
                remediation_plan=analysis.expected_outcome,
                commands_executed=execution_result.commands,
                command_outputs=execution_result.outputs,
                exit_codes=execution_result.exit_codes,
                success=execution_result.success,
                error_message=execution_result.error,
                execution_duration_seconds=duration,
                risk_level=analysis.risk,
                escalated=False
            )

            await log_attempt_with_fallback(attempt)

            # Notify (only if actionable commands were executed)
            if execution_result.success:
                # Phase 1: Verify remediation via Prometheus if enabled
                verified_success = True
                verification_message = "Verification skipped"

                if settings.verification_enabled:
                    try:
                        # Build labels dict for matching
                        verification_labels = {}
                        if hasattr(alert.labels, 'system'):
                            verification_labels['system'] = alert.labels.system
                        if hasattr(alert.labels, 'container'):
                            verification_labels['container'] = alert.labels.container

                        verified_success, verification_message = await prometheus_client.verify_remediation(
                            alert_name=alert_name,
                            instance=alert_instance if ':' not in (alert_instance or '') else None,
                            labels=verification_labels if verification_labels else None,
                            max_wait_seconds=settings.verification_max_wait_seconds,
                            poll_interval=settings.verification_poll_interval,
                            initial_delay=settings.verification_initial_delay
                        )

                        logger.info(
                            "remediation_verification_result",
                            alert_name=alert_name,
                            verified=verified_success,
                            message=verification_message
                        )
                    except Exception as e:
                        logger.warning(
                            "verification_failed_fallback_to_exit_code",
                            alert_name=alert_name,
                            error=str(e)
                        )
                        # Fallback to exit code success if verification fails
                        verified_success = True
                        verification_message = f"Verification error ({str(e)}), using exit code"

                # Update attempt success based on verification
                if not verified_success:
                    attempt.success = False
                    attempt.error_message = f"Commands succeeded but alert not resolved: {verification_message}"
                    await log_attempt_with_fallback(attempt)

                    await discord_notifier.notify_failure(
                        attempt,
                        execution_time=duration,
                        max_attempts=settings.max_attempts_per_alert
                    )

                    # Record failure for learning
                    if learning_engine and pattern_used_id:
                        try:
                            await learning_engine.record_outcome(
                                pattern_id=pattern_used_id,
                                success=False,
                                execution_time=duration
                            )
                        except Exception as e:
                            logger.warning("pattern_outcome_recording_failed", error=str(e))

                    # Phase 1: Record failure pattern to avoid repeating
                    if learning_engine and actionable_commands:
                        try:
                            await learning_engine.record_failure_pattern(
                                alert_name=alert_name,
                                alert_instance=alert_instance,
                                commands_attempted=actionable_commands,
                                failure_reason=verification_message
                            )
                        except Exception as e:
                            logger.warning("failure_pattern_recording_failed", error=str(e))

                    # Check if we should escalate
                    if attempt_count + 1 >= settings.max_attempts_per_alert:
                        await escalate_alert(alert, attempt_count + 1)

                    return {
                        "alert": alert_name,
                        "status": "failed",
                        "reason": "verification_failed",
                        "verification_message": verification_message,
                        "attempt": attempt_count + 1,
                        "pattern_used": pattern_used_id is not None
                    }

                # Verified success - notify and learn
                await discord_notifier.notify_success(attempt, duration, settings.max_attempts_per_alert)

                # Extract pattern for learning (only from VERIFIED successful remediations)
                if learning_engine and not pattern_used_id:
                    # This was a Claude-generated solution that succeeded
                    try:
                        pattern_id = await learning_engine.extract_pattern(
                            attempt=attempt,
                            alert_labels=dict(alert.labels)
                        )
                        if pattern_id:
                            logger.info(
                                "pattern_learned",
                                pattern_id=pattern_id,
                                alert_name=alert_name,
                                verified=verified_success
                            )
                    except Exception as e:
                        logger.warning(
                            "pattern_extraction_failed",
                            error=str(e),
                            alert_name=alert_name
                        )

                # Record outcome for learned pattern if one was used
                if learning_engine and pattern_used_id:
                    try:
                        await learning_engine.record_outcome(
                            pattern_id=pattern_used_id,
                            success=True,
                            execution_time=duration
                        )
                        logger.info(
                            "pattern_outcome_recorded",
                            pattern_id=pattern_used_id,
                            success=True,
                            verified=verified_success
                        )
                    except Exception as e:
                        logger.warning(
                            "pattern_outcome_recording_failed",
                            error=str(e),
                            pattern_id=pattern_used_id
                        )

                # Phase 4: Record success metrics
                metrics.record_remediation_attempt(alert_name, 'success', duration)
                metrics.update_active_remediations(-1)
                if pattern_used_id:
                    metrics.record_pattern_match(True)

                return {
                    "alert": alert_name,
                    "status": "remediated",
                    "duration": duration,
                    "verified": verified_success,
                    "verification_message": verification_message,
                    "pattern_used": pattern_used_id is not None
                }
            else:
                await discord_notifier.notify_failure(
                    attempt,
                    execution_time=duration,
                    max_attempts=settings.max_attempts_per_alert
                )

                # Record failure for learned pattern if one was used
                if learning_engine and pattern_used_id:
                    try:
                        await learning_engine.record_outcome(
                            pattern_id=pattern_used_id,
                            success=False,
                            execution_time=duration
                        )
                        logger.warning(
                            "pattern_outcome_recorded",
                            pattern_id=pattern_used_id,
                            success=False
                        )
                    except Exception as e:
                        logger.warning(
                            "pattern_outcome_recording_failed",
                            error=str(e),
                            pattern_id=pattern_used_id
                        )

                # Check if we should escalate
                if attempt_count + 1 >= settings.max_attempts_per_alert:
                    await escalate_alert(alert, attempt_count + 1)

                # Phase 4: Record failure metrics
                metrics.record_remediation_attempt(alert_name, 'failure', duration)
                metrics.update_active_remediations(-1)

                return {
                    "alert": alert_name,
                    "status": "failed",
                    "attempt": attempt_count + 1,
                    "error": execution_result.error,
                    "pattern_used": pattern_used_id is not None
                }
        else:
            # Only diagnostic commands executed - don't count as attempt
            metrics.update_active_remediations(-1)
            logger.info(
                "diagnostic_only_no_attempt_logged",
                alert_name=alert_name,
                commands=validation_result.validated_commands
            )

            return {
                "alert": alert_name,
                "status": "diagnostic_only",
                "commands": diagnostic_commands
            }
    else:
        logger.info(
            "no_commands_to_execute",
            alert_name=alert_name,
            ai_analysis=analysis.analysis if analysis else None,
            ai_reasoning=analysis.reasoning if analysis else None
        )

        # Log this as a failed attempt so we have a record
        end_time = datetime.utcnow()
        duration = int((end_time - start_time).total_seconds())

        attempt = RemediationAttempt(
            alert_name=alert_name,
            alert_instance=alert_instance,
            alert_fingerprint=alert_fingerprint,
            severity=alert.labels.severity,
            attempt_number=attempt_count + 1,
            ai_analysis=analysis.analysis if analysis else "No analysis available",
            ai_reasoning=analysis.reasoning if analysis else "No reasoning available",
            remediation_plan=analysis.expected_outcome if analysis else None,
            commands_executed=[],
            success=False,
            error_message="No commands generated by AI",
            execution_duration_seconds=duration,
            risk_level=analysis.risk if analysis else RiskLevel.HIGH,
            escalated=False
        )

        await log_attempt_with_fallback(attempt)

        # Check if we should escalate after no commands
        if attempt_count + 1 >= settings.max_attempts_per_alert:
            await escalate_alert(alert, attempt_count + 1)

        return {
            "alert": alert_name,
            "status": "no_action",
            "reason": "No validated commands",
            "attempt": attempt_count + 1
        }


async def escalate_alert(alert, attempt_count: int):
    """
    Escalate an alert to Discord for manual intervention.

    v3.1.0: Checks escalation cooldown to prevent spam. If alert was already
    escalated within the cooldown period, logs silently without Discord notification.

    Args:
        alert: Alert instance
        attempt_count: Number of attempts made
    """
    alert_name = alert.labels.alertname
    alert_instance = alert.labels.instance

    # =========================================================================
    # v3.1.0: Check escalation cooldown
    # =========================================================================
    in_cooldown, escalated_at = await db.check_escalation_cooldown(
        alert_name=alert_name,
        alert_instance=alert_instance,
        cooldown_hours=settings.escalation_cooldown_hours
    )

    if in_cooldown:
        # Already escalated recently - log silently, don't spam Discord
        logger.info(
            "escalation_skipped_cooldown",
            alert_name=alert_name,
            alert_instance=alert_instance,
            escalated_at=escalated_at.isoformat() if escalated_at else None,
            cooldown_hours=settings.escalation_cooldown_hours
        )
        return  # Silent return - no Discord notification

    logger.info(
        "escalating_alert",
        alert_name=alert_name,
        attempts=attempt_count
    )

    # Get recent attempts
    previous_attempts = await db.get_recent_attempts(
        alert_name=alert_name,
        alert_instance=alert_instance,
        limit=3
    )

    # Create escalation attempt record
    attempt = RemediationAttempt(
        alert_name=alert_name,
        alert_instance=alert_instance,
        alert_fingerprint=alert.fingerprint,
        severity=alert.labels.severity,
        attempt_number=attempt_count,
        ai_analysis=f"Alert escalated after {attempt_count} failed attempts",
        success=False,
        escalated=True,
        risk_level=RiskLevel.HIGH
    )

    # Log escalation to database
    await log_attempt_with_fallback(attempt)

    # Set escalation cooldown to prevent spam
    await db.set_escalation_cooldown(alert_name, alert_instance)

    # Notify Discord
    await discord_notifier.notify_escalation(attempt, previous_attempts)


@app.post("/maintenance/enable")
async def enable_maintenance_mode(
    window: MaintenanceWindow,
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    """Enable maintenance mode to disable auto-remediation."""
    window_id = await db.create_maintenance_window(window)

    await discord_notifier.notify_maintenance_mode(
        enabled=True,
        duration_minutes=int((window.end_time - window.start_time).total_seconds() / 60),
        reason=window.reason
    )

    logger.info(
        "maintenance_mode_enabled",
        window_id=window_id,
        duration_minutes=(window.end_time - window.start_time).total_seconds() / 60
    )

    return {
        "status": "enabled",
        "window_id": window_id,
        "end_time": window.end_time.isoformat()
    }


@app.get("/statistics")
async def get_statistics(days: int = 7):
    """Get remediation statistics."""
    stats = await db.get_statistics(days=days)

    return {
        "period_days": days,
        "statistics": stats
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        error=str(exc),
        exc_info=True
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.debug else "An error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
