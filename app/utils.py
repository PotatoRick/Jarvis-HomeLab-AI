"""
Utility functions and helpers for Jarvis AI Remediation Service.

v3.0: Added hint extraction, Skynet host detection, and investigation helpers.
"""

import re
import structlog
from typing import Dict, Any, Optional, List, Tuple
from .models import HostType, Alert


logger = structlog.get_logger()


# ============================================================================
# Alert Hint Extraction (v3.0)
# ============================================================================

def extract_hints_from_alert(alert: Alert) -> Dict[str, Any]:
    """
    Extract actionable hints from alert annotations before calling Claude.

    This parses the alert description/summary for:
    - Host mentions (e.g., "Check cron job on Skynet")
    - Suggested commands (e.g., "crontab -l")
    - File paths mentioned
    - Service names

    Args:
        alert: Alert instance

    Returns:
        Dictionary of extracted hints
    """
    hints = {
        "mentioned_hosts": [],
        "suggested_commands": [],
        "mentioned_paths": [],
        "mentioned_services": [],
        "remediation_host_hint": None,
    }

    # Combine description and summary for analysis
    text = ""
    if alert.annotations.description:
        text += alert.annotations.description + " "
    if alert.annotations.summary:
        text += alert.annotations.summary
    text = text.lower()

    # Detect host mentions
    host_patterns = {
        "skynet": ["skynet", "192.168.0.13"],
        "nexus": ["nexus", "192.168.0.11"],
        "homeassistant": ["homeassistant", "home assistant", "192.168.0.10", " ha "],
        "outpost": ["outpost", "72.60.163.242", "vps"],
    }

    for host, patterns in host_patterns.items():
        for pattern in patterns:
            if pattern in text:
                hints["mentioned_hosts"].append(host)
                # If description explicitly says "on <host>" or "check <host>", that's the remediation host
                if any(phrase in text for phrase in [f"on {pattern}", f"check {pattern}", f"{pattern}:", f"at {pattern}"]):
                    hints["remediation_host_hint"] = host
                break

    # Detect suggested commands
    command_patterns = [
        (r'`([^`]+)`', "backtick"),  # Commands in backticks
        (r'crontab\s*-l', "crontab"),
        (r'docker\s+(?:logs|restart|ps)\s+\w+', "docker"),
        (r'systemctl\s+(?:status|restart)\s+\S+', "systemctl"),
        (r'journalctl\s+[^\s]+', "journalctl"),
        (r'tail\s+-\d*f?\s+\S+', "tail"),
        (r'cat\s+\S+', "cat"),
    ]

    for pattern, cmd_type in command_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, str) and len(match) > 2:
                hints["suggested_commands"].append(match.strip())

    # Detect file paths
    path_pattern = r'(/[\w./-]+(?:\.(?:sh|log|conf|yml|yaml|json|env|prom))?)'
    paths = re.findall(path_pattern, alert.annotations.description or "")
    paths += re.findall(path_pattern, alert.annotations.summary or "")
    hints["mentioned_paths"] = list(set(paths))

    # Detect service names
    service_patterns = [
        r'(?:service|container|daemon)\s+["\']?(\w+)["\']?',
        r'(?:docker|systemctl)\s+\w+\s+(\w+)',
    ]

    for pattern in service_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        hints["mentioned_services"].extend(matches)
    hints["mentioned_services"] = list(set(hints["mentioned_services"]))

    logger.info(
        "hints_extracted_from_alert",
        alert_name=alert.labels.alertname,
        mentioned_hosts=hints["mentioned_hosts"],
        remediation_host_hint=hints["remediation_host_hint"],
        suggested_commands=hints["suggested_commands"][:3],  # Log first 3
    )

    return hints


def get_confidence_level(confidence: float) -> str:
    """
    Convert numeric confidence to level string.

    Args:
        confidence: Float 0.0-1.0

    Returns:
        Confidence level string
    """
    if confidence < 0.30:
        return "uncertain"
    elif confidence < 0.50:
        return "low"
    elif confidence < 0.70:
        return "medium"
    elif confidence < 0.90:
        return "high"
    else:
        return "very_high"


def can_execute_at_confidence(action_type: str, confidence: float) -> Tuple[bool, str]:
    """
    Check if an action is allowed at the current confidence level.

    Confidence-gated execution:
    - < 30%: Only read-only diagnostic commands
    - 30-50%: Safe investigative commands (logs, status checks)
    - 50-70%: Safe restarts with verification
    - 70-90%: Learned patterns
    - > 90%: Any validated command

    Args:
        action_type: Type of action (read_only, investigate, restart, pattern, any)
        confidence: Current confidence level 0.0-1.0

    Returns:
        Tuple of (allowed, reason)
    """
    thresholds = {
        "read_only": 0.0,      # Always allowed
        "investigate": 0.30,   # Need some confidence to run investigative commands
        "restart": 0.50,       # Need medium confidence for restarts
        "pattern": 0.70,       # Need high confidence for learned patterns
        "any": 0.90,           # Need very high confidence for arbitrary commands
    }

    required = thresholds.get(action_type, 0.90)

    if confidence >= required:
        return True, f"Confidence {confidence:.0%} >= {required:.0%} threshold for {action_type}"
    else:
        return False, f"Confidence {confidence:.0%} < {required:.0%} required for {action_type}"


def determine_target_host(alert: Alert, hints: Optional[Dict[str, Any]] = None) -> HostType:
    """
    Determine which host an alert is targeting based on instance label and hints.

    v3.0: Now uses hints from alert description to override instance label when appropriate.

    Args:
        alert: Alert instance
        hints: Optional hints extracted from alert description

    Returns:
        HostType enum value
    """
    # First, check if hints provide a remediation host override
    # This handles cases where instance != where the fix should happen
    if hints and hints.get("remediation_host_hint"):
        hint_host = hints["remediation_host_hint"].lower()
        if hint_host == "skynet":
            logger.info(
                "host_from_hint_override",
                hint=hint_host,
                original_instance=alert.labels.instance
            )
            return HostType.SKYNET
        elif hint_host == "nexus":
            return HostType.NEXUS
        elif hint_host in ["homeassistant", "ha"]:
            return HostType.HOMEASSISTANT
        elif hint_host == "outpost":
            return HostType.OUTPOST

    instance = alert.labels.instance.lower()

    # Check for explicit host indicators in instance label
    if "skynet" in instance or "192.168.0.13" in instance:
        return HostType.SKYNET
    elif "outpost" in instance or "72.60.163.242" in instance or "vps" in instance:
        return HostType.OUTPOST
    elif "homeassistant" in instance or "192.168.0.10" in instance or "ha" in instance:
        return HostType.HOMEASSISTANT
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
    elif "backup" in alert_name and "health" in alert_name:
        # Backup health checks run on Skynet
        return HostType.SKYNET

    # Default to Nexus (most services run there)
    logger.warning(
        "host_determination_defaulted",
        instance=instance,
        alert_name=alert.labels.alertname,
        default="nexus"
    )
    return HostType.NEXUS


def is_cross_system_alert(alert: Alert) -> bool:
    """
    Check if an alert requires cross-system investigation.

    Some issues (like VPN tunnels) involve multiple systems and
    the root cause might be on a different host than where the alert fired.

    Args:
        alert: Alert instance

    Returns:
        True if alert needs cross-system investigation
    """
    alert_name = alert.labels.alertname.lower()

    # VPN/WireGuard alerts need both endpoints checked
    cross_system_patterns = [
        "wireguard",
        "vpn",
        "wg-quick",
        "site-to-site",
    ]

    return any(pattern in alert_name for pattern in cross_system_patterns)


def get_related_hosts(alert: Alert) -> list:
    """
    Get list of hosts that should be investigated for this alert.

    For cross-system alerts (like VPN), returns multiple hosts.
    For normal alerts, returns just the primary target.

    Args:
        alert: Alert instance

    Returns:
        List of HostType values to investigate
    """
    primary_host = determine_target_host(alert)

    if is_cross_system_alert(alert):
        alert_name = alert.labels.alertname.lower()

        # WireGuard VPN connects Nexus <-> Outpost
        if "wireguard" in alert_name or "vpn" in alert_name:
            logger.info(
                "cross_system_alert_detected",
                alert_name=alert.labels.alertname,
                hosts=["outpost", "nexus"]
            )
            return [HostType.OUTPOST, HostType.NEXUS]

    return [primary_host]


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
