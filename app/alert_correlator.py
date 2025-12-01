"""
Alert correlation engine for root cause analysis.
Correlates multiple alerts to find root cause and avoid duplicate work.
"""

import structlog
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from .database import Database

logger = structlog.get_logger()


@dataclass
class Incident:
    """A correlated group of alerts."""
    id: str
    root_cause_alert: str
    related_alerts: List[str]
    correlation_type: str  # "cascade", "dependency", "temporal", "host"
    created_at: datetime
    root_cause_instance: Optional[str] = None


class AlertCorrelator:
    """Correlate multiple alerts to find root cause."""

    # Service dependency map: service -> [depends on...]
    DEPENDENCIES: Dict[str, List[str]] = {
        # Core infrastructure
        "grafana": ["prometheus", "loki", "docker"],
        "prometheus": ["docker"],
        "loki": ["docker"],
        "alertmanager": ["prometheus", "docker"],

        # Media/Security
        "frigate": ["docker", "coral-tpu", "mosquitto"],
        "scrypted": ["docker"],

        # Automation
        "n8n": ["n8n-db", "docker"],
        "home-assistant": ["mosquitto", "zigbee2mqtt"],
        "zigbee2mqtt": ["mosquitto"],

        # Network
        "caddy": ["docker"],
        "adguard": ["docker", "unbound"],
        "unbound": ["docker"],

        # Database
        "vaultwarden": ["docker"],
        "actual-budget": ["docker"],
    }

    # Cascading alert patterns: if these alerts fire together, first tuple element is root cause
    # Format: (root_cause_alert, dependent_alert) -> root_cause_alert
    CASCADE_PATTERNS: Dict[tuple, str] = {
        # VPN issues cascade to remote services
        ("WireGuardVPNDown", "OutpostDown"): "WireGuardVPNDown",
        ("WireGuardVPNDown", "OutpostServiceDown"): "WireGuardVPNDown",
        ("WireGuardVPNDown", "N8NDown"): "WireGuardVPNDown",
        ("WireGuardVPNDown", "ActualBudgetDown"): "WireGuardVPNDown",

        # Docker daemon issues cascade to all containers
        ("DockerDaemonUnresponsive", "ContainerDown"): "DockerDaemonUnresponsive",
        ("DockerDaemonUnresponsive", "ContainerUnhealthy"): "DockerDaemonUnresponsive",

        # Resource exhaustion cascades
        ("HighMemoryUsage", "ContainerOOMKilled"): "HighMemoryUsage",
        ("DiskSpaceCritical", "ContainerDown"): "DiskSpaceCritical",
        ("DiskSpaceLow", "ContainerUnhealthy"): "DiskSpaceLow",

        # Database dependencies
        ("PostgreSQLDown", "N8NDown"): "PostgreSQLDown",
        ("PostgreSQLDown", "GrafanaDown"): "PostgreSQLDown",

        # MQTT cascade
        ("MQTTBrokerDown", "Zigbee2MQTTDown"): "MQTTBrokerDown",
        ("MQTTBrokerDown", "HomeAssistantMQTTUnavailable"): "MQTTBrokerDown",

        # DNS cascade
        ("AdGuardDown", "DNSResolutionFailed"): "AdGuardDown",
        ("UnboundDown", "DNSResolutionSlow"): "UnboundDown",

        # Home Assistant addons
        ("HomeAssistantDown", "Zigbee2MQTTDown"): "HomeAssistantDown",
    }

    # Time window for temporal correlation (seconds)
    CORRELATION_WINDOW = 120

    def __init__(self, db: Database):
        """
        Initialize correlator with database connection.

        Args:
            db: Database instance for querying recent alerts
        """
        self.db = db
        self.active_incidents: Dict[str, Incident] = {}
        self.logger = logger.bind(component="alert_correlator")

    async def correlate_alert(self, alert: Dict[str, Any]) -> Optional[Incident]:
        """
        Check if alert correlates with existing incident or recent alerts.

        Args:
            alert: Alert data with labels and annotations

        Returns:
            Incident if correlated, None if standalone alert
        """
        alert_name = alert.get("labels", {}).get("alertname", "Unknown")
        alert_instance = alert.get("labels", {}).get("instance", "")
        alert_host = self._extract_host_from_instance(alert_instance)

        self.logger.info(
            "correlating_alert",
            alert_name=alert_name,
            alert_instance=alert_instance
        )

        # Get recent alerts for correlation
        recent_alerts = await self._get_recent_alerts(self.CORRELATION_WINDOW)
        recent_alert_names = [a["alert_name"] for a in recent_alerts]

        # 1. Check for cascade patterns (highest priority)
        cascade_incident = self._check_cascade_patterns(
            alert_name, recent_alert_names, recent_alerts
        )
        if cascade_incident:
            self.logger.info(
                "cascade_correlation_found",
                alert=alert_name,
                root_cause=cascade_incident.root_cause_alert,
                type="cascade"
            )
            return cascade_incident

        # 2. Check dependency correlation
        dependency_incident = await self._check_dependency_correlation(
            alert_name, recent_alerts
        )
        if dependency_incident:
            self.logger.info(
                "dependency_correlation_found",
                alert=alert_name,
                root_cause=dependency_incident.root_cause_alert,
                type="dependency"
            )
            return dependency_incident

        # 3. Check host-based correlation (same host, multiple alerts)
        if alert_host:
            host_incident = self._check_host_correlation(
                alert_name, alert_host, recent_alerts
            )
            if host_incident:
                self.logger.info(
                    "host_correlation_found",
                    alert=alert_name,
                    root_cause=host_incident.root_cause_alert,
                    type="host"
                )
                return host_incident

        # No correlation found
        self.logger.debug("no_correlation_found", alert=alert_name)
        return None

    def _check_cascade_patterns(
        self,
        alert_name: str,
        recent_alert_names: List[str],
        recent_alerts: List[Dict]
    ) -> Optional[Incident]:
        """Check if alert matches known cascade patterns."""
        for (alert_a, alert_b), root in self.CASCADE_PATTERNS.items():
            if alert_name == alert_a and alert_b in recent_alert_names:
                return Incident(
                    id=f"incident-{datetime.now().timestamp()}",
                    root_cause_alert=root,
                    related_alerts=[alert_a, alert_b],
                    correlation_type="cascade",
                    created_at=datetime.now()
                )
            elif alert_name == alert_b and alert_a in recent_alert_names:
                # Find instance of root cause alert
                root_instance = None
                for a in recent_alerts:
                    if a["alert_name"] == alert_a:
                        root_instance = a.get("alert_instance")
                        break

                return Incident(
                    id=f"incident-{datetime.now().timestamp()}",
                    root_cause_alert=root,
                    related_alerts=[alert_a, alert_b],
                    correlation_type="cascade",
                    created_at=datetime.now(),
                    root_cause_instance=root_instance
                )
        return None

    async def _check_dependency_correlation(
        self,
        alert_name: str,
        recent_alerts: List[Dict]
    ) -> Optional[Incident]:
        """Check if alert's dependencies are also alerting."""
        # Extract service name from alert (e.g., "GrafanaDown" -> "grafana")
        service_name = self._extract_service_name(alert_name)

        if service_name and service_name in self.DEPENDENCIES:
            deps = self.DEPENDENCIES[service_name]

            for dep in deps:
                # Check if any dependency is alerting
                for recent in recent_alerts:
                    recent_service = self._extract_service_name(recent["alert_name"])
                    if recent_service and dep.lower() in recent_service.lower():
                        return Incident(
                            id=f"incident-{datetime.now().timestamp()}",
                            root_cause_alert=recent["alert_name"],
                            related_alerts=[alert_name],
                            correlation_type="dependency",
                            created_at=datetime.now(),
                            root_cause_instance=recent.get("alert_instance")
                        )

        return None

    def _check_host_correlation(
        self,
        alert_name: str,
        alert_host: str,
        recent_alerts: List[Dict]
    ) -> Optional[Incident]:
        """Check for multiple alerts on the same host."""
        same_host_alerts = []

        for recent in recent_alerts:
            recent_instance = recent.get("alert_instance", "")
            recent_host = self._extract_host_from_instance(recent_instance)

            if recent_host == alert_host and recent["alert_name"] != alert_name:
                same_host_alerts.append(recent)

        # If multiple alerts on same host, look for resource-related root cause
        if same_host_alerts:
            # Prioritize resource alerts as root cause
            resource_alerts = ["HighMemoryUsage", "DiskSpaceLow", "DiskSpaceCritical",
                            "HighCPUUsage", "DockerDaemonUnresponsive"]

            for resource_alert in resource_alerts:
                for recent in same_host_alerts:
                    if resource_alert in recent["alert_name"]:
                        return Incident(
                            id=f"incident-{datetime.now().timestamp()}",
                            root_cause_alert=recent["alert_name"],
                            related_alerts=[alert_name] + [a["alert_name"] for a in same_host_alerts],
                            correlation_type="host",
                            created_at=datetime.now(),
                            root_cause_instance=recent.get("alert_instance")
                        )

        return None

    def _extract_service_name(self, alert_name: str) -> Optional[str]:
        """Extract service name from alert name."""
        # Common patterns: ServiceDown, ServiceUnhealthy, ServiceError
        suffixes = ["Down", "Unhealthy", "Error", "Unreachable", "Failed",
                   "Unavailable", "OOMKilled", "CrashLooping"]

        lower_alert = alert_name.lower()
        for suffix in suffixes:
            if lower_alert.endswith(suffix.lower()):
                service = alert_name[:-len(suffix)]
                return service.lower()

        return None

    def _extract_host_from_instance(self, instance: str) -> Optional[str]:
        """Extract host IP from instance label."""
        if not instance:
            return None

        # Instance format is usually "ip:port" or just "hostname"
        if ":" in instance:
            return instance.split(":")[0]
        return instance

    async def _get_recent_alerts(self, seconds: int) -> List[Dict]:
        """Get alerts from the last N seconds."""
        query = """
            SELECT alert_name, alert_instance, timestamp
            FROM remediation_log
            WHERE timestamp > NOW() - INTERVAL '%s seconds'
            ORDER BY timestamp DESC
        """

        try:
            rows = await self.db.fetch(query, seconds)
            return [
                {
                    "alert_name": row["alert_name"],
                    "alert_instance": row["alert_instance"],
                    "timestamp": row["timestamp"]
                }
                for row in rows
            ]
        except Exception as e:
            self.logger.error("failed_to_get_recent_alerts", error=str(e))
            return []

    def get_remediation_priority(self, incident: Incident) -> List[str]:
        """
        Return alerts in order they should be remediated.
        Root cause first, then dependents.

        Args:
            incident: Correlated incident

        Returns:
            List of alert names in remediation priority order
        """
        priority = [incident.root_cause_alert]
        priority.extend([a for a in incident.related_alerts
                        if a != incident.root_cause_alert])
        return priority

    def should_skip_alert(self, alert_name: str, incident: Optional[Incident]) -> bool:
        """
        Determine if an alert should be skipped because root cause is being handled.

        Args:
            alert_name: Name of the current alert
            incident: Correlated incident (if any)

        Returns:
            True if alert should be skipped
        """
        if not incident:
            return False

        # Skip if this alert is not the root cause
        return alert_name != incident.root_cause_alert

    async def get_correlation_context(self, alert: Dict[str, Any]) -> str:
        """
        Generate context string for Claude about correlated alerts.

        Args:
            alert: Current alert being processed

        Returns:
            Context string to include in Claude prompt
        """
        incident = await self.correlate_alert(alert)

        if not incident:
            return ""

        context_lines = [
            "\n## Alert Correlation Context",
            f"This alert appears to be part of a larger incident.",
            f"Correlation type: {incident.correlation_type}",
            f"Likely root cause: {incident.root_cause_alert}"
        ]

        if incident.root_cause_instance:
            context_lines.append(f"Root cause instance: {incident.root_cause_instance}")

        if len(incident.related_alerts) > 1:
            context_lines.append(f"Related alerts: {', '.join(incident.related_alerts)}")

        context_lines.append("")
        context_lines.append("**Recommendation:** Focus on the root cause alert first.")

        if incident.correlation_type == "cascade":
            context_lines.append("This is a cascade failure - fixing the root cause should resolve dependent alerts.")
        elif incident.correlation_type == "dependency":
            context_lines.append("This alert depends on another service that is also alerting.")
        elif incident.correlation_type == "host":
            context_lines.append("Multiple alerts on the same host - may indicate resource exhaustion.")

        return "\n".join(context_lines)


# Global correlator instance (initialized in main.py with db)
alert_correlator: Optional[AlertCorrelator] = None


def init_correlator(db: Database) -> AlertCorrelator:
    """Initialize global correlator with database."""
    global alert_correlator
    alert_correlator = AlertCorrelator(db)
    return alert_correlator
