"""
Alert Suppression Engine

Prevents alert storms by suppressing cascading alerts when root cause is identified.
Reduces Discord noise and focuses attention on actual problems.
"""

import structlog
from typing import Dict, Set, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from app.host_monitor import HostMonitor, HostStatus
from app.discord_notifier import DiscordNotifier


@dataclass
class SuppressionSummary:
    """Summary of suppressed alerts for a host"""
    host: str
    suppressed_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    alert_names: Set[str] = field(default_factory=set)
    first_suppressed: Optional[datetime] = None
    last_suppressed: Optional[datetime] = None


class AlertSuppressor:
    """
    Manages alert suppression logic to prevent cascading notifications.

    Suppresses alerts from offline hosts and during maintenance windows.
    Consolidates notifications to reduce noise.
    """

    # Known cascading relationships (child alerts triggered by parent)
    CASCADING_RULES = {
        "WireGuardVPNDown": [
            "OutpostDown",
            "PostgreSQLDown",
            "SystemDown",
            "TargetDown",
        ],
        "OutpostDown": [
            "ContainerUnhealthy",
            "ContainerDown",
            "ServiceUnreachable",
        ],
        "NexusDown": [
            "ContainerUnhealthy",
            "ContainerDown",
            "ServiceUnreachable",
            "TargetDown",
        ],
    }

    def __init__(self, host_monitor: HostMonitor, discord: DiscordNotifier):
        self.host_monitor = host_monitor
        self.discord = discord
        self.logger = structlog.get_logger(__name__)

        # Track suppressed alerts per host
        self.suppression_summaries: Dict[str, SuppressionSummary] = {}

        # Track active root cause alerts
        self.active_root_causes: Set[str] = set()

    def should_suppress(
        self,
        alert_name: str,
        instance: str,
        severity: str,
        target_host: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Determine if an alert should be suppressed.

        Args:
            alert_name: Name of the alert
            instance: Alert instance
            severity: Alert severity (critical, warning)
            target_host: Target host for the alert

        Returns:
            Tuple of (should_suppress: bool, reason: Optional[str])
        """

        # Check 1: Host is offline
        if target_host:
            host_state = self.host_monitor.get_host_status(target_host)
            if host_state and host_state.status == HostStatus.OFFLINE:
                self._record_suppression(target_host, alert_name, severity)
                return True, f"Host {target_host} is offline"

        # Check 2: Cascading alert from known root cause
        for root_cause, cascading_alerts in self.CASCADING_RULES.items():
            if alert_name in cascading_alerts and root_cause in self.active_root_causes:
                reason = f"Cascading from {root_cause}"
                self.logger.info(
                    "suppressing_cascading_alert",
                    alert=alert_name,
                    root_cause=root_cause
                )
                return True, reason

        # Check 3: Check maintenance windows (TODO: integrate when implemented)
        # if self._is_in_maintenance(target_host):
        #     return True, "Maintenance window active"

        return False, None

    def register_root_cause(self, alert_name: str):
        """Register an alert as an active root cause"""
        if alert_name in self.CASCADING_RULES:
            self.active_root_causes.add(alert_name)
            self.logger.info(
                "root_cause_registered",
                alert=alert_name,
                will_suppress=self.CASCADING_RULES[alert_name]
            )

    def clear_root_cause(self, alert_name: str):
        """Clear a root cause when it's resolved"""
        if alert_name in self.active_root_causes:
            self.active_root_causes.remove(alert_name)
            self.logger.info(
                "root_cause_cleared",
                alert=alert_name
            )

    def _record_suppression(self, host: str, alert_name: str, severity: str):
        """Record a suppressed alert for summary reporting"""
        if host not in self.suppression_summaries:
            self.suppression_summaries[host] = SuppressionSummary(
                host=host,
                first_suppressed=datetime.utcnow()
            )

        summary = self.suppression_summaries[host]
        summary.suppressed_count += 1
        summary.alert_names.add(alert_name)
        summary.last_suppressed = datetime.utcnow()

        if severity == "critical":
            summary.critical_count += 1
        elif severity == "warning":
            summary.warning_count += 1

    async def send_suppression_summary(self, host: str):
        """
        Send consolidated Discord notification for suppressed alerts.

        Args:
            host: Host name to summarize
        """
        if host not in self.suppression_summaries:
            return

        summary = self.suppression_summaries[host]

        if summary.suppressed_count == 0:
            return

        # Format alert names
        alert_list = ", ".join(sorted(summary.alert_names))
        if len(alert_list) > 100:
            alert_list = alert_list[:97] + "..."

        # Calculate suppression duration
        duration = ""
        if summary.first_suppressed and summary.last_suppressed:
            delta = summary.last_suppressed - summary.first_suppressed
            if delta.total_seconds() > 60:
                minutes = int(delta.total_seconds() / 60)
                duration = f"\n**Duration:** {minutes} minutes"

        message = f"""🔕 **Alert Suppression Summary**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Host:** {host.title()}
**Total Suppressed:** {summary.suppressed_count} alerts
**Critical:** {summary.critical_count} | **Warning:** {summary.warning_count}{duration}

**Alert Types:** {alert_list}

**Reason:** Host offline - remediation skipped
Monitoring will resume when host recovers."""

        await self.discord.send_notification(message, username="Jarvis - Suppression")

        self.logger.info(
            "suppression_summary_sent",
            host=host,
            suppressed_count=summary.suppressed_count,
            critical=summary.critical_count,
            warning=summary.warning_count
        )

    async def send_host_recovery_summary(self, host: str):
        """
        Send summary when host recovers, clearing suppressed alerts.

        Args:
            host: Host that recovered
        """
        if host not in self.suppression_summaries:
            return

        summary = self.suppression_summaries[host]

        if summary.suppressed_count == 0:
            return

        message = f"""✅ **Host Recovered - Resuming Monitoring**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Host:** {host.title()}
**Status:** ONLINE

**Previously Suppressed:** {summary.suppressed_count} alerts
({summary.critical_count} critical, {summary.warning_count} warning)

Alert processing resumed. Jarvis will remediate any ongoing issues."""

        await self.discord.send_notification(message, username="Jarvis - Suppression")

        # Clear suppression summary
        del self.suppression_summaries[host]

        self.logger.info(
            "host_recovery_summary_sent",
            host=host,
            had_suppressed=summary.suppressed_count
        )

    def get_suppression_stats(self) -> Dict[str, SuppressionSummary]:
        """Get current suppression statistics"""
        return self.suppression_summaries.copy()

    async def periodic_summary_check(self):
        """
        Periodically send suppression summaries for hosts with many suppressed alerts.

        Should be called every 5-10 minutes to provide updates.
        """
        for host, summary in self.suppression_summaries.items():
            # Send summary if we've suppressed >10 alerts and haven't sent in 10+ minutes
            if summary.suppressed_count > 10:
                if summary.last_suppressed:
                    time_since_last = datetime.utcnow() - summary.last_suppressed
                    if time_since_last > timedelta(minutes=10):
                        await self.send_suppression_summary(host)
