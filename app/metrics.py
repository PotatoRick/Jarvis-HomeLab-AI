"""
Prometheus metrics export for Jarvis self-monitoring.

Phase 4: Exposes /metrics endpoint for Prometheus scraping.
Provides visibility into Jarvis performance, patterns, and API usage.
"""

import structlog
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

logger = structlog.get_logger()


# =============================================================================
# Counters - Cumulative metrics that only increase
# =============================================================================

remediation_total = Counter(
    'jarvis_remediation_total',
    'Total remediation attempts by alert name and outcome',
    ['alert_name', 'status']  # status: success, failure, escalated, skipped, suppressed
)

pattern_matches = Counter(
    'jarvis_pattern_matches_total',
    'Pattern matching results (hit = pattern used, miss = Claude API called)',
    ['result']  # hit, miss
)

api_calls = Counter(
    'jarvis_claude_api_calls_total',
    'Claude API calls by model and result',
    ['model', 'status']  # status: success, error, timeout
)

command_executions = Counter(
    'jarvis_command_executions_total',
    'SSH command executions by host and result',
    ['host', 'status']  # status: success, failure
)

alerts_received = Counter(
    'jarvis_alerts_received_total',
    'Total alerts received from Alertmanager',
    ['alert_name', 'severity']
)

verification_results = Counter(
    'jarvis_verification_total',
    'Remediation verification results',
    ['result']  # verified, failed, skipped, error
)

proactive_checks = Counter(
    'jarvis_proactive_checks_total',
    'Proactive monitoring check results',
    ['check_type', 'result']  # result: ok, warning, action_taken
)

rollback_operations = Counter(
    'jarvis_rollback_total',
    'Rollback operations performed',
    ['target_type', 'result']  # result: success, failure
)

n8n_workflow_executions = Counter(
    'jarvis_n8n_executions_total',
    'n8n workflow executions',
    ['workflow_name', 'status']  # status: success, failure, timeout
)


# =============================================================================
# Histograms - Distribution of values (duration, latency)
# =============================================================================

remediation_duration = Histogram(
    'jarvis_remediation_duration_seconds',
    'Time taken to complete remediation',
    ['alert_name'],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600]
)

api_call_duration = Histogram(
    'jarvis_claude_api_duration_seconds',
    'Claude API call duration',
    ['model'],
    buckets=[0.5, 1, 2, 5, 10, 30, 60]
)

ssh_execution_duration = Histogram(
    'jarvis_ssh_execution_duration_seconds',
    'SSH command execution duration',
    ['host'],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60]
)

verification_duration = Histogram(
    'jarvis_verification_duration_seconds',
    'Alert verification polling duration',
    buckets=[10, 20, 30, 60, 90, 120]
)


# =============================================================================
# Gauges - Point-in-time values that can go up or down
# =============================================================================

active_remediations = Gauge(
    'jarvis_active_remediations',
    'Currently active remediation operations'
)

database_connected = Gauge(
    'jarvis_database_connected',
    'Database connection status (1 = connected, 0 = disconnected)'
)

pattern_count = Gauge(
    'jarvis_patterns_total',
    'Total number of learned patterns',
    ['confidence_level']  # high, medium, low
)

queue_depth = Gauge(
    'jarvis_queue_depth',
    'Number of alerts queued for processing (degraded mode)'
)

maintenance_mode = Gauge(
    'jarvis_maintenance_mode',
    'Maintenance mode status (1 = active, 0 = inactive)'
)

proactive_monitor_running = Gauge(
    'jarvis_proactive_monitor_running',
    'Proactive monitoring status (1 = running, 0 = stopped)'
)

host_status = Gauge(
    'jarvis_host_status',
    'Target host status (1 = online, 0 = offline)',
    ['host']
)

ssh_pool_connections = Gauge(
    'jarvis_ssh_pool_connections',
    'Active SSH connections in pool',
    ['host']
)


# =============================================================================
# Info - Static labels for version/config info
# =============================================================================

build_info = Info(
    'jarvis_build',
    'Jarvis build information'
)


# =============================================================================
# Helper functions for recording metrics
# =============================================================================

def record_remediation_attempt(alert_name: str, status: str, duration_seconds: float = None):
    """
    Record a remediation attempt.

    Args:
        alert_name: Name of the alert
        status: Outcome (success, failure, escalated, skipped, suppressed)
        duration_seconds: Time taken for remediation
    """
    remediation_total.labels(alert_name=alert_name, status=status).inc()

    if duration_seconds is not None:
        remediation_duration.labels(alert_name=alert_name).observe(duration_seconds)


def record_pattern_match(hit: bool):
    """Record pattern matching result."""
    pattern_matches.labels(result='hit' if hit else 'miss').inc()


def record_api_call(model: str, status: str, duration_seconds: float = None):
    """
    Record a Claude API call.

    Args:
        model: Model used (e.g., claude-sonnet-4-5-20250929)
        status: Result (success, error, timeout)
        duration_seconds: API call duration
    """
    api_calls.labels(model=model, status=status).inc()

    if duration_seconds is not None:
        api_call_duration.labels(model=model).observe(duration_seconds)


def record_command_execution(host: str, status: str, duration_seconds: float = None):
    """Record SSH command execution."""
    command_executions.labels(host=host, status=status).inc()

    if duration_seconds is not None:
        ssh_execution_duration.labels(host=host).observe(duration_seconds)


def record_alert_received(alert_name: str, severity: str):
    """Record alert received from Alertmanager."""
    alerts_received.labels(alert_name=alert_name, severity=severity).inc()


def record_verification(result: str, duration_seconds: float = None):
    """
    Record verification result.

    Args:
        result: verified, failed, skipped, error
        duration_seconds: Verification polling duration
    """
    verification_results.labels(result=result).inc()

    if duration_seconds is not None:
        verification_duration.observe(duration_seconds)


def record_proactive_check(check_type: str, result: str):
    """Record proactive monitoring check."""
    proactive_checks.labels(check_type=check_type, result=result).inc()


def record_rollback(target_type: str, success: bool):
    """Record rollback operation."""
    rollback_operations.labels(
        target_type=target_type,
        result='success' if success else 'failure'
    ).inc()


def record_n8n_execution(workflow_name: str, status: str):
    """Record n8n workflow execution."""
    n8n_workflow_executions.labels(workflow_name=workflow_name, status=status).inc()


def update_active_remediations(delta: int):
    """Update active remediation count (+1 for start, -1 for end)."""
    if delta > 0:
        active_remediations.inc(delta)
    else:
        active_remediations.dec(abs(delta))


def set_database_status(connected: bool):
    """Set database connection status."""
    database_connected.set(1 if connected else 0)


def update_pattern_counts(high: int, medium: int, low: int):
    """Update learned pattern counts by confidence level."""
    pattern_count.labels(confidence_level='high').set(high)
    pattern_count.labels(confidence_level='medium').set(medium)
    pattern_count.labels(confidence_level='low').set(low)


def set_queue_depth(depth: int):
    """Set current queue depth."""
    queue_depth.set(depth)


def set_maintenance_mode(active: bool):
    """Set maintenance mode status."""
    maintenance_mode.set(1 if active else 0)


def set_proactive_monitor_status(running: bool):
    """Set proactive monitor running status."""
    proactive_monitor_running.set(1 if running else 0)


def set_host_status(host: str, online: bool):
    """Set target host status."""
    host_status.labels(host=host).set(1 if online else 0)


def set_ssh_pool_connections(host: str, count: int):
    """Set SSH connection pool size for host."""
    ssh_pool_connections.labels(host=host).set(count)


def set_build_info(version: str, python_version: str = "3.11"):
    """Set build information."""
    build_info.info({
        'version': version,
        'python_version': python_version,
        'app_name': 'Jarvis AI Remediation Service'
    })


def get_metrics_response() -> Response:
    """
    Generate Prometheus metrics response.

    Returns:
        FastAPI Response with Prometheus text format
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


# =============================================================================
# Initialization
# =============================================================================

def init_metrics(version: str):
    """
    Initialize metrics with startup values.

    Args:
        version: Application version string
    """
    set_build_info(version)
    set_database_status(False)
    set_maintenance_mode(False)
    set_proactive_monitor_status(False)
    active_remediations.set(0)
    queue_depth.set(0)

    # Initialize host status gauges
    for host in ['nexus', 'homeassistant', 'outpost', 'skynet']:
        set_host_status(host, False)
        set_ssh_pool_connections(host, 0)

    logger.info("prometheus_metrics_initialized", version=version)
