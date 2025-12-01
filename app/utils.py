"""
Utility functions and helpers.
"""

import structlog
from typing import Dict, Any, Optional
from .models import HostType, Alert


logger = structlog.get_logger()


def determine_target_host(alert: Alert, hints: Optional[Dict[str, Any]] = None) -> HostType:
    """
    Determine which host an alert is targeting based on instance label and hints.

    v3.0: Now accepts hints parameter which can override instance-based detection.
    The remediation_host label takes precedence over instance detection.

    Args:
        alert: Alert instance
        hints: Optional dict of hints extracted from alert (may contain target_host)

    Returns:
        HostType enum value
    """
    # v3.0: Check for explicit host hint first (highest priority)
    if hints and hints.get("target_host"):
        hint_host = hints["target_host"].lower()
        if hint_host == "skynet":
            return HostType.SKYNET
        elif hint_host == "nexus":
            return HostType.NEXUS
        elif hint_host in ("outpost", "vps"):
            return HostType.OUTPOST
        elif hint_host in ("homeassistant", "ha"):
            return HostType.HOMEASSISTANT

    instance = alert.labels.instance.lower()

    # Check for explicit host indicators
    if "outpost" in instance or "72.60.163.242" in instance or "vps" in instance:
        return HostType.OUTPOST
    elif "homeassistant" in instance or "192.168.0.10" in instance or "ha" in instance:
        return HostType.HOMEASSISTANT
    elif "skynet" in instance or "192.168.0.13" in instance:
        return HostType.SKYNET
    elif "nexus" in instance or "192.168.0.11" in instance:
        return HostType.NEXUS

    # Default based on common service patterns
    alert_name = alert.labels.alertname.lower()

    if "wireguard" in alert_name or "vpn" in alert_name:
        return HostType.OUTPOST
    elif "frigate" in alert_name or "adguard" in alert_name or "caddy" in alert_name:
        return HostType.NEXUS
    elif "zigbee" in alert_name or "automation" in alert_name:
        return HostType.HOMEASSISTANT

    # Default to Nexus (most services run there)
    logger.warning(
        "host_determination_defaulted",
        instance=instance,
        alert_name=alert.labels.alertname,
        default="nexus"
    )
    return HostType.NEXUS


def extract_service_name(alert: Alert) -> Optional[str]:
    """
    Extract service/container name from alert labels.

    Args:
        alert: Alert instance

    Returns:
        Service name or None
    """
    # Check common label patterns
    labels = alert.labels

    # Docker container name
    if hasattr(labels, "container_name"):
        return labels.container_name
    elif hasattr(labels, "container"):
        return labels.container

    # Systemd service name
    if hasattr(labels, "service_name"):
        return labels.service_name
    elif hasattr(labels, "systemd_unit"):
        return labels.systemd_unit

    # Extract from instance label (format: "service:port")
    instance = labels.instance
    if ":" in instance:
        parts = instance.split(":")
        return parts[0]

    # Try to infer from alert name
    alert_name = labels.alertname.lower()
    if "container" in alert_name:
        # Try to extract container name from description
        if hasattr(alert.annotations, "description"):
            desc = alert.annotations.description.lower()
            # Look for patterns like "container X is down"
            import re
            match = re.search(r'container\s+([a-z0-9_-]+)\s+is', desc)
            if match:
                return match.group(1)

    return None


def determine_service_type(alert: Alert, service_name: Optional[str]) -> str:
    """
    Determine if a service is a Docker container or systemd service.

    Args:
        alert: Alert instance
        service_name: Service name

    Returns:
        Service type ('docker', 'systemd', or 'system')
    """
    alert_name = alert.labels.alertname.lower()

    # Explicit indicators
    if "container" in alert_name or "docker" in alert_name:
        return "docker"
    elif "systemd" in alert_name or "service" in alert_name:
        return "systemd"
    elif "system" in alert_name or "node" in alert_name:
        return "system"

    # Common Docker containers in the homelab
    docker_services = [
        "caddy", "frigate", "adguard", "vaultwarden", "prometheus",
        "grafana", "loki", "alertmanager", "n8n", "n8n-db",
        "actual-budget", "rustdesk", "blackbox-exporter"
    ]

    if service_name and service_name.lower() in docker_services:
        return "docker"

    # Common systemd services
    systemd_services = [
        "wg-quick", "wireguard", "ssh", "docker", "postgresql",
        "home-assistant", "zigbee2mqtt"
    ]

    if service_name:
        for svc in systemd_services:
            if svc in service_name.lower():
                return "systemd"

    # Default to docker (most services are containerized)
    return "docker"


def format_alert_for_context(alert: Alert) -> Dict[str, Any]:
    """
    Format alert data for Claude context.

    Args:
        alert: Alert instance

    Returns:
        Dictionary with formatted alert data
    """
    return {
        "alert_name": alert.labels.alertname,
        "alert_instance": alert.labels.instance,
        "severity": alert.labels.severity,
        "description": alert.annotations.description or alert.annotations.summary or "No description",
        "labels": dict(alert.labels),
        "annotations": dict(alert.annotations),
        "fired_at": alert.startsAt
    }


def truncate_logs(logs: str, max_length: int = 2000) -> str:
    """
    Truncate logs to a maximum length for Claude context.

    Args:
        logs: Log text
        max_length: Maximum length

    Returns:
        Truncated logs
    """
    if len(logs) <= max_length:
        return logs

    # Take last N characters (most recent logs)
    truncated = logs[-max_length:]

    # Try to start at a newline for cleaner output
    newline_pos = truncated.find("\n")
    if newline_pos > 0 and newline_pos < 100:
        truncated = truncated[newline_pos + 1:]

    return f"[... truncated to last {max_length} chars ...]\n{truncated}"


def is_cross_system_alert(alert: Alert) -> bool:
    """
    Determine if an alert involves multiple systems (e.g., VPN, network connectivity).

    Cross-system alerts may require checking/fixing multiple hosts.

    Args:
        alert: Alert instance

    Returns:
        True if alert spans multiple systems
    """
    alert_name = alert.labels.alertname.lower()
    description = ""
    if hasattr(alert.annotations, "description") and alert.annotations.description:
        description = alert.annotations.description.lower()

    # VPN/network alerts typically span systems
    cross_system_keywords = [
        "wireguard", "vpn", "tunnel", "site-to-site",
        "connectivity", "unreachable", "network"
    ]

    for keyword in cross_system_keywords:
        if keyword in alert_name or keyword in description:
            return True

    return False


def get_related_hosts(alert: Alert) -> list:
    """
    Get list of hosts that may be related to this alert.

    For cross-system alerts, returns all potentially affected hosts.

    Args:
        alert: Alert instance

    Returns:
        List of HostType values
    """
    if not is_cross_system_alert(alert):
        return [determine_target_host(alert)]

    # For cross-system alerts, check primary hosts
    alert_name = alert.labels.alertname.lower()

    if "wireguard" in alert_name or "vpn" in alert_name:
        # VPN alerts: check both endpoints
        return [HostType.NEXUS, HostType.OUTPOST]
    elif "network" in alert_name or "connectivity" in alert_name:
        # General network issues: check all main hosts
        return [HostType.NEXUS, HostType.HOMEASSISTANT, HostType.OUTPOST]

    # Default: just the target host
    return [determine_target_host(alert)]


def _sanitize_hint_value(value: Any) -> str:
    """
    Sanitize hint value, handling Unicode and encoding issues.

    MEDIUM-010 FIX: Properly handles Unicode characters in hint values.

    Args:
        value: Raw value from alert label/annotation

    Returns:
        Sanitized string value
    """
    if value is None:
        return ""

    try:
        # Convert to string if needed
        if not isinstance(value, str):
            value = str(value)

        # Normalize Unicode characters
        import unicodedata
        normalized = unicodedata.normalize('NFKC', value)

        # Remove control characters but keep valid Unicode
        cleaned = ''.join(
            char for char in normalized
            if not unicodedata.category(char).startswith('C') or char in '\n\t'
        )

        return cleaned.strip()
    except Exception as e:
        logger.warning(
            "hint_sanitization_failed",
            value_type=type(value).__name__,
            error=str(e)
        )
        # Fallback: try ASCII encoding
        try:
            return str(value).encode('ascii', 'replace').decode('ascii')
        except Exception:
            return ""


def extract_hints_from_alert(alert: Alert) -> Dict[str, Any]:
    """
    Extract hints from alert labels/annotations that can help with remediation.

    v3.0: Enhanced hint extraction for better AI analysis.
    MEDIUM-010 FIX: Now sanitizes Unicode characters in hint values.

    Args:
        alert: Alert instance

    Returns:
        Dictionary of hints
    """
    hints = {}

    # Check for remediation hints in labels
    labels = alert.labels
    if hasattr(labels, "remediation_hint"):
        hints["remediation_hint"] = _sanitize_hint_value(labels.remediation_hint)
    if hasattr(labels, "remediation_host"):
        hints["target_host"] = _sanitize_hint_value(labels.remediation_host)
    if hasattr(labels, "service"):
        hints["service"] = _sanitize_hint_value(labels.service)
    if hasattr(labels, "container"):
        hints["container"] = _sanitize_hint_value(labels.container)
    if hasattr(labels, "job"):
        hints["job"] = _sanitize_hint_value(labels.job)

    # Check for hints in annotations
    annotations = alert.annotations
    if hasattr(annotations, "runbook_url"):
        hints["runbook_url"] = _sanitize_hint_value(annotations.runbook_url)
    if hasattr(annotations, "remediation"):
        hints["suggested_remediation"] = _sanitize_hint_value(annotations.remediation)

    # MEDIUM-010 FIX: Remove empty string values
    hints = {k: v for k, v in hints.items() if v}

    return hints


def get_confidence_level(confidence_score: float) -> str:
    """
    Convert numeric confidence score to human-readable level.

    v3.0: Helper for pattern confidence reporting.

    Args:
        confidence_score: Float between 0 and 1

    Returns:
        String level: 'high', 'medium', or 'low'
    """
    if confidence_score >= 0.80:
        return "high"
    elif confidence_score >= 0.60:
        return "medium"
    else:
        return "low"
