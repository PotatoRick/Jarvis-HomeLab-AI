"""
Proactive issue detection and prevention.
Monitors for predictable issues before they trigger alerts.
"""

import asyncio
import structlog
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum

from .config import settings
from .prometheus_client import prometheus_client
from .discord_notifier import discord_notifier
from .database import db

logger = structlog.get_logger()


class CheckType(str, Enum):
    """Types of proactive checks."""
    DISK_FILL_RATE = "disk_fill_rate"
    CERTIFICATE_EXPIRY = "certificate_expiry"
    MEMORY_TREND = "memory_trend"
    CONTAINER_RESTARTS = "container_restarts"
    BACKUP_FRESHNESS = "backup_freshness"


class ProactiveMonitor:
    """Detect and fix issues before they become alerts."""

    # Host mapping for SSH targets
    HOST_MAP = {
        "192.168.0.11": "nexus",
        "192.168.0.10": "homeassistant",
        "192.168.0.13": "skynet"
    }

    # Node exporter instances to monitor
    NODE_INSTANCES = [
        "192.168.0.11:9100",  # Nexus
        "192.168.0.10:9100",  # Home Assistant
        "192.168.0.13:9100",  # Skynet
    ]

    def __init__(
        self,
        ssh_executor=None,
        check_interval: int = None
    ):
        """
        Initialize proactive monitor.

        Args:
            ssh_executor: SSH executor for remediation commands
            check_interval: Seconds between check cycles (default from config)
        """
        self.ssh_executor = ssh_executor
        self.check_interval = check_interval or settings.proactive_check_interval
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.logger = logger.bind(component="proactive_monitor")

        # Track what we've already notified about to avoid spam
        self._notified_issues: Dict[str, datetime] = {}
        self._notification_cooldown = timedelta(hours=4)

    async def start(self):
        """Start the proactive monitoring loop."""
        if self.running:
            return

        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        self.logger.info(
            "proactive_monitor_started",
            check_interval=self.check_interval
        )

    async def stop(self):
        """Stop the proactive monitoring loop."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("proactive_monitor_stopped")

    async def _run_loop(self):
        """Main proactive monitoring loop."""
        while self.running:
            try:
                await self._run_all_checks()
            except Exception as e:
                self.logger.error("proactive_monitor_error", error=str(e))

            await asyncio.sleep(self.check_interval)

    async def _run_all_checks(self):
        """Run all proactive checks."""
        self.logger.debug("running_proactive_checks")

        checks = [
            self.check_disk_fill_rates(),
            self.check_certificate_expiry(),
            self.check_memory_trends(),
            self.check_container_restarts(),
            self.check_backup_freshness(),
        ]

        await asyncio.gather(*checks, return_exceptions=True)

    def _should_notify(self, issue_key: str) -> bool:
        """Check if we should send a notification for this issue."""
        last_notified = self._notified_issues.get(issue_key)
        if last_notified:
            if datetime.now() - last_notified < self._notification_cooldown:
                return False

        self._notified_issues[issue_key] = datetime.now()
        return True

    async def _log_check(
        self,
        check_type: CheckType,
        target: str,
        finding: str,
        action_taken: Optional[str] = None
    ):
        """Log a proactive check result to the database."""
        try:
            await db.execute(
                """
                INSERT INTO proactive_checks (
                    check_type, target, finding, action_taken, created_at
                ) VALUES ($1, $2, $3, $4, NOW())
                """,
                check_type.value,
                target,
                finding,
                action_taken
            )
        except Exception as e:
            self.logger.warning(
                "proactive_check_log_failed",
                error=str(e),
                check_type=check_type.value
            )

    async def check_disk_fill_rates(self):
        """Check if any disk will be full within warning threshold."""
        self.logger.debug("checking_disk_fill_rates")

        for instance in self.NODE_INSTANCES:
            try:
                # Query disk space for root filesystem
                prediction = await prometheus_client.predict_exhaustion(
                    metric="node_filesystem_avail_bytes",
                    instance=instance,
                    threshold=1073741824  # 1GB threshold
                )

                if prediction.get("prediction") == "will_exhaust":
                    hours_remaining = prediction.get("hours_remaining", 999)

                    if hours_remaining < settings.disk_exhaustion_warning_hours:
                        hostname = instance.split(":")[0]
                        target = self.HOST_MAP.get(hostname, hostname)
                        issue_key = f"disk_fill_{target}"

                        await self._log_check(
                            CheckType.DISK_FILL_RATE,
                            target,
                            f"Disk predicted to fill in {hours_remaining:.1f}h"
                        )

                        if self._should_notify(issue_key):
                            await self._handle_disk_warning(
                                target, hours_remaining, prediction
                            )

            except Exception as e:
                self.logger.warning(
                    "disk_check_failed",
                    instance=instance,
                    error=str(e)
                )

    async def _handle_disk_warning(
        self,
        target: str,
        hours_remaining: float,
        prediction: Dict[str, Any]
    ):
        """Handle a disk space warning."""
        current_bytes = prediction.get("current", 0)
        current_gb = current_bytes / (1024 ** 3)

        self.logger.warning(
            "disk_exhaustion_predicted",
            target=target,
            hours_remaining=hours_remaining,
            current_gb=current_gb
        )

        # Send notification
        if discord_notifier and settings.discord_enabled:
            embed = {
                "title": "Proactive Alert: Disk Space Warning",
                "description": f"**{target.upper()}** disk space is depleting",
                "color": 0xFFA500,  # Orange
                "fields": [
                    {"name": "Hours Remaining", "value": f"{hours_remaining:.1f}h", "inline": True},
                    {"name": "Current Free", "value": f"{current_gb:.1f} GB", "inline": True},
                    {"name": "Action", "value": "Consider running `docker system prune` or clearing logs", "inline": False}
                ],
                "timestamp": datetime.utcnow().isoformat()
            }

            await discord_notifier.send_webhook({
                "username": "Jarvis - Proactive",
                "embeds": [embed]
            })

        # Optionally run automatic cleanup for critical situations
        if hours_remaining < 6 and self.ssh_executor:
            self.logger.info(
                "triggering_preemptive_cleanup",
                target=target,
                hours_remaining=hours_remaining
            )
            await self._run_disk_cleanup(target)

    async def _run_disk_cleanup(self, target: str):
        """Run disk cleanup commands on target host."""
        if not self.ssh_executor:
            return

        from .models import HostType
        try:
            host = HostType(target)
        except ValueError:
            self.logger.warning("invalid_cleanup_target", target=target)
            return

        cleanup_commands = [
            "docker system prune -f --volumes",
            "journalctl --vacuum-time=3d",
        ]

        for cmd in cleanup_commands:
            try:
                result = await self.ssh_executor.execute_commands(
                    host=host,
                    commands=[cmd],
                    timeout=120
                )

                await self._log_check(
                    CheckType.DISK_FILL_RATE,
                    target,
                    "Preemptive cleanup triggered",
                    cmd
                )

                self.logger.info(
                    "cleanup_command_executed",
                    target=target,
                    command=cmd,
                    success=result.success
                )
            except Exception as e:
                self.logger.warning(
                    "cleanup_command_failed",
                    target=target,
                    command=cmd,
                    error=str(e)
                )

    async def check_certificate_expiry(self):
        """Check for certificates expiring soon."""
        self.logger.debug("checking_certificate_expiry")

        try:
            # Query certificate expiry from blackbox exporter
            results = await prometheus_client.query_instant(
                'probe_ssl_earliest_cert_expiry - time()'
            )

            for result in results:
                seconds_remaining = float(result["value"][1])
                days_remaining = seconds_remaining / 86400

                if days_remaining < settings.cert_expiry_warning_days:
                    instance = result["metric"].get("instance", "unknown")
                    issue_key = f"cert_expiry_{instance}"

                    await self._log_check(
                        CheckType.CERTIFICATE_EXPIRY,
                        instance,
                        f"Certificate expires in {days_remaining:.0f} days"
                    )

                    if self._should_notify(issue_key):
                        self.logger.warning(
                            "certificate_expiry_warning",
                            instance=instance,
                            days_remaining=days_remaining
                        )

                        if discord_notifier and settings.discord_enabled:
                            embed = {
                                "title": "Proactive Alert: Certificate Expiry",
                                "description": f"Certificate for **{instance}** expiring soon",
                                "color": 0xFFA500,
                                "fields": [
                                    {"name": "Days Remaining", "value": f"{days_remaining:.0f}", "inline": True},
                                    {"name": "Action", "value": "Certificate renewal may be needed", "inline": False}
                                ],
                                "timestamp": datetime.utcnow().isoformat()
                            }

                            await discord_notifier.send_webhook({
                                "username": "Jarvis - Proactive",
                                "embeds": [embed]
                            })

        except Exception as e:
            self.logger.warning("certificate_check_failed", error=str(e))

    async def check_memory_trends(self):
        """Detect containers with memory leaks."""
        self.logger.debug("checking_memory_trends")

        try:
            # Query containers with steadily growing memory
            threshold_bytes = settings.memory_leak_threshold_mb_per_hour * 1048576 / 3600

            results = await prometheus_client.query_instant(
                f'rate(container_memory_working_set_bytes[6h]) > {threshold_bytes}'
            )

            for result in results:
                container = result["metric"].get("name", "unknown")

                # Skip system containers
                if container in ("POD", "unknown", ""):
                    continue

                growth_rate = float(result["value"][1]) * 3600 / 1048576  # MB/hour
                issue_key = f"memory_leak_{container}"

                await self._log_check(
                    CheckType.MEMORY_TREND,
                    container,
                    f"Memory growing {growth_rate:.1f}MB/hour"
                )

                if self._should_notify(issue_key):
                    self.logger.warning(
                        "memory_leak_detected",
                        container=container,
                        growth_mb_per_hour=growth_rate
                    )

                    if discord_notifier and settings.discord_enabled:
                        embed = {
                            "title": "Proactive Alert: Memory Leak Detected",
                            "description": f"Container **{container}** has potential memory leak",
                            "color": 0xFFA500,
                            "fields": [
                                {"name": "Growth Rate", "value": f"{growth_rate:.1f} MB/hour", "inline": True},
                                {"name": "Action", "value": "Monitor and consider restart if OOM risk", "inline": False}
                            ],
                            "timestamp": datetime.utcnow().isoformat()
                        }

                        await discord_notifier.send_webhook({
                            "username": "Jarvis - Proactive",
                            "embeds": [embed]
                        })

        except Exception as e:
            self.logger.warning("memory_trend_check_failed", error=str(e))

    async def check_container_restarts(self):
        """Detect containers restarting frequently."""
        self.logger.debug("checking_container_restarts")

        try:
            # Query containers with >3 restarts in the last hour
            results = await prometheus_client.query_instant(
                'increase(container_restart_count[1h]) > 3'
            )

            for result in results:
                container = result["metric"].get("name", "unknown")

                if container in ("POD", "unknown", ""):
                    continue

                restarts = int(float(result["value"][1]))
                issue_key = f"restart_loop_{container}"

                await self._log_check(
                    CheckType.CONTAINER_RESTARTS,
                    container,
                    f"Container restarted {restarts} times in last hour"
                )

                if self._should_notify(issue_key):
                    self.logger.warning(
                        "container_restart_loop",
                        container=container,
                        restarts_1h=restarts
                    )

                    if discord_notifier and settings.discord_enabled:
                        embed = {
                            "title": "Proactive Alert: Container Restart Loop",
                            "description": f"Container **{container}** is restarting frequently",
                            "color": 0xFF0000,  # Red
                            "fields": [
                                {"name": "Restarts (1h)", "value": str(restarts), "inline": True},
                                {"name": "Action", "value": "Check container logs for root cause", "inline": False}
                            ],
                            "timestamp": datetime.utcnow().isoformat()
                        }

                        await discord_notifier.send_webhook({
                            "username": "Jarvis - Proactive",
                            "embeds": [embed]
                        })

        except Exception as e:
            self.logger.warning("container_restart_check_failed", error=str(e))

    async def check_backup_freshness(self):
        """Verify backups are recent enough."""
        self.logger.debug("checking_backup_freshness")

        try:
            # Query backup age (>36 hours is stale)
            results = await prometheus_client.query_instant(
                '(time() - backup_last_success_timestamp) > 129600'
            )

            for result in results:
                system = result["metric"].get("system", result["metric"].get("job", "unknown"))
                age_seconds = float(result["value"][1])
                hours_old = age_seconds / 3600
                issue_key = f"backup_stale_{system}"

                await self._log_check(
                    CheckType.BACKUP_FRESHNESS,
                    system,
                    f"Backup is {hours_old:.1f} hours old"
                )

                if self._should_notify(issue_key):
                    self.logger.warning(
                        "backup_stale",
                        system=system,
                        hours_old=hours_old
                    )

                    if discord_notifier and settings.discord_enabled:
                        embed = {
                            "title": "Proactive Alert: Stale Backup",
                            "description": f"Backup for **{system}** may be stale",
                            "color": 0xFFA500,
                            "fields": [
                                {"name": "Last Backup", "value": f"{hours_old:.1f} hours ago", "inline": True},
                                {"name": "Action", "value": "Verify backup system is running", "inline": False}
                            ],
                            "timestamp": datetime.utcnow().isoformat()
                        }

                        await discord_notifier.send_webhook({
                            "username": "Jarvis - Proactive",
                            "embeds": [embed]
                        })

        except Exception as e:
            self.logger.warning("backup_freshness_check_failed", error=str(e))


# Global proactive monitor instance
proactive_monitor: Optional[ProactiveMonitor] = None


def init_proactive_monitor(ssh_executor=None) -> Optional[ProactiveMonitor]:
    """
    Initialize global proactive monitor.

    Args:
        ssh_executor: SSH executor for remediation commands

    Returns:
        ProactiveMonitor instance or None if disabled
    """
    global proactive_monitor

    if not settings.proactive_monitoring_enabled:
        logger.info("proactive_monitoring_disabled")
        return None

    proactive_monitor = ProactiveMonitor(ssh_executor=ssh_executor)
    logger.info("proactive_monitor_initialized")
    return proactive_monitor
