"""
Host Availability Monitoring Module

Tracks the availability status of remote hosts (Service-Host, HomeAssistant, VPS-Host)
and provides intelligent routing to avoid futile connection attempts.
"""

import asyncio
import subprocess
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass
import structlog

from app.database import Database
from app.discord_notifier import DiscordNotifier
from app.config import Settings


class HostStatus(str, Enum):
    """Host connectivity status"""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    CHECKING = "CHECKING"


@dataclass
class HostState:
    """Current state of a monitored host"""
    name: str
    status: HostStatus
    failure_count: int = 0
    last_successful_connection: Optional[datetime] = None
    last_check_attempt: Optional[datetime] = None
    error_message: Optional[str] = None


class HostMonitor:
    """
    Monitors host availability and manages connectivity status.

    Prevents futile connection attempts to offline hosts and provides
    intelligent routing decisions for alert remediation.
    """

    # Configuration
    MAX_FAILURES_BEFORE_OFFLINE = 3
    OFFLINE_CHECK_INTERVAL = 300  # 5 minutes
    PING_TIMEOUT = 5  # seconds

    def __init__(self, db: Database, discord: DiscordNotifier, settings: Settings):
        self.db = db
        self.discord = discord
        self.settings = settings
        self.logger = structlog.get_logger(__name__)

        # In-memory state for quick lookups
        self.hosts: Dict[str, HostState] = {
            "service-host": HostState("service-host", HostStatus.ONLINE),
            "ha-host": HostState("ha-host", HostStatus.ONLINE),
            "vps-host": HostState("vps-host", HostStatus.ONLINE)
        }

        # Background tasks
        self._monitoring_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start background monitoring tasks"""
        self.logger.info("host_monitor_starting")
        self._monitoring_task = asyncio.create_task(self._periodic_check_loop())

    async def stop(self):
        """Stop background monitoring"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        self.logger.info("host_monitor_stopped")

    async def _periodic_check_loop(self):
        """Periodically check offline hosts for recovery"""
        while True:
            try:
                await asyncio.sleep(self.OFFLINE_CHECK_INTERVAL)

                for host_name, state in self.hosts.items():
                    if state.status == HostStatus.OFFLINE:
                        self.logger.info(
                            "checking_offline_host",
                            host=host_name,
                            offline_since=state.last_check_attempt
                        )
                        await self._check_host_recovery(host_name)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(
                    "periodic_check_error",
                    error=str(e),
                    exc_info=True
                )

    async def record_connection_attempt(
        self,
        host_name: str,
        success: bool,
        error_message: Optional[str] = None
    ):
        """
        Record the result of a connection attempt.

        Args:
            host_name: Name of the host (service-host, ha-host, vps-host)
            success: Whether the connection succeeded
            error_message: Error message if failed
        """
        if host_name not in self.hosts:
            self.logger.warning("unknown_host", host=host_name)
            return

        state = self.hosts[host_name]
        state.last_check_attempt = datetime.utcnow()

        if success:
            # Connection successful
            old_status = state.status
            state.status = HostStatus.ONLINE
            state.failure_count = 0
            state.last_successful_connection = datetime.utcnow()
            state.error_message = None

            # Notify if recovered from offline
            if old_status == HostStatus.OFFLINE:
                await self._notify_host_recovered(host_name, state)

            self.logger.info(
                "connection_successful",
                host=host_name,
                previous_status=old_status.value
            )
        else:
            # Connection failed
            state.failure_count += 1
            state.error_message = error_message

            self.logger.warning(
                "connection_failed",
                host=host_name,
                failure_count=state.failure_count,
                error=error_message
            )

            # Mark as offline after threshold
            if (state.failure_count >= self.MAX_FAILURES_BEFORE_OFFLINE and
                state.status != HostStatus.OFFLINE):
                await self._mark_host_offline(host_name, state)

        # Persist to database
        await self._save_host_status(host_name, state)

    async def _mark_host_offline(self, host_name: str, state: HostState):
        """Mark a host as offline and send notifications"""
        old_status = state.status
        state.status = HostStatus.OFFLINE

        self.logger.error(
            "host_marked_offline",
            host=host_name,
            failure_count=state.failure_count,
            error=state.error_message
        )

        # Send Discord notification
        await self._notify_host_offline(host_name, state)

    async def _check_host_recovery(self, host_name: str):
        """
        Check if an offline host has recovered.

        Attempts a simple ping test, then marks as CHECKING for SSH verification.
        """
        state = self.hosts[host_name]

        # Get host IP from settings
        host_map = {
            "service-host": self.settings.ssh_service-host_host,
            "ha-host": self.settings.ssh_ha-host_host,
            "vps-host": self.settings.ssh_vps-host_host
        }

        host_ip = host_map.get(host_name)
        if not host_ip:
            return

        # Attempt ping
        ping_success = await self._ping_host(host_ip)

        if ping_success:
            self.logger.info(
                "host_ping_successful",
                host=host_name,
                ip=host_ip
            )
            state.status = HostStatus.CHECKING
            state.error_message = None
            # Next SSH attempt will verify full connectivity
        else:
            self.logger.debug(
                "host_still_offline",
                host=host_name,
                ip=host_ip
            )

    async def _ping_host(self, host_ip: str) -> bool:
        """
        Ping a host to check basic connectivity.

        Returns:
            True if ping succeeds, False otherwise
        """
        try:
            # Run ping command (1 packet, timeout)
            process = await asyncio.create_subprocess_exec(
                'ping', '-c', '1', '-W', str(self.PING_TIMEOUT), host_ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.PING_TIMEOUT + 2
            )

            return process.returncode == 0

        except (asyncio.TimeoutError, Exception) as e:
            self.logger.debug("ping_failed", host=host_ip, error=str(e))
            return False

    async def is_host_available(self, host_name: str) -> bool:
        """
        Check if a host is currently available for connections.

        Args:
            host_name: Name of the host

        Returns:
            True if host is ONLINE or CHECKING, False if OFFLINE
        """
        if host_name not in self.hosts:
            # Unknown hosts are assumed available
            return True

        state = self.hosts[host_name]
        return state.status in (HostStatus.ONLINE, HostStatus.CHECKING)

    def get_host_status(self, host_name: str) -> Optional[HostState]:
        """Get the current status of a host"""
        return self.hosts.get(host_name)

    def get_all_statuses(self) -> Dict[str, HostState]:
        """Get status of all monitored hosts"""
        return self.hosts.copy()

    async def _save_host_status(self, host_name: str, state: HostState):
        """Persist host status to database"""
        try:
            query = """
                INSERT INTO host_status_log
                    (host_name, status, failure_count, last_successful_connection,
                     last_check_attempt, error_message)
                VALUES ($1, $2, $3, $4, $5, $6)
            """

            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    query,
                    host_name,
                    state.status.value,
                    state.failure_count,
                    state.last_successful_connection,
                    state.last_check_attempt,
                    state.error_message
                )

        except Exception as e:
            self.logger.error(
                "save_host_status_failed",
                host=host_name,
                error=str(e)
            )

    async def _notify_host_offline(self, host_name: str, state: HostState):
        """Send Discord notification when host goes offline"""
        message = f"""🔴 **Host Offline**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Host:** {host_name.title()}
**Failures:** {state.failure_count} consecutive attempts
**Error:** {state.error_message or 'Connection timeout'}

**Impact:**
• Alerts for this host will be suppressed
• Remediation attempts paused
• Automatic recovery check every 5 minutes

Will notify when connectivity is restored."""

        if self.settings.discord_enabled:
            await self.discord.send_notification(message, username="Jarvis - Host Monitor")

    async def _notify_host_recovered(self, host_name: str, state: HostState):
        """Send Discord notification when host comes back online"""
        downtime = None
        if state.last_check_attempt and state.last_successful_connection:
            downtime = state.last_successful_connection - state.last_check_attempt

        message = f"""✅ **Host Recovered**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Host:** {host_name.title()}
**Status:** ONLINE
**Downtime:** {self._format_timedelta(downtime) if downtime else 'Unknown'}

Resuming normal alert processing and remediation."""

        if self.settings.discord_enabled:
            await self.discord.send_notification(message, username="Jarvis - Host Monitor")

    @staticmethod
    def _format_timedelta(td: timedelta) -> str:
        """Format a timedelta as human-readable string"""
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0 or not parts:
            parts.append(f"{seconds}s")

        return " ".join(parts)
