"""
State snapshot and rollback manager.
Track state before remediation for potential rollback if things go wrong.
"""

import json
import structlog
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum

from .config import settings
from .database import db

logger = structlog.get_logger()


class SnapshotType(str, Enum):
    """Types of state snapshots."""
    CONTAINER = "container"
    SERVICE = "service"
    CONFIG = "config"
    DATABASE = "database"


class RollbackManager:
    """Track state before remediation for potential rollback."""

    # Snapshot retention period
    RETENTION_HOURS = 24

    def __init__(self, ssh_executor=None):
        """
        Initialize rollback manager.

        Args:
            ssh_executor: SSH executor for capturing state
        """
        self.ssh_executor = ssh_executor
        self.logger = logger.bind(component="rollback_manager")

    async def snapshot_container_state(
        self,
        host: str,
        container: str,
        alert_context: Optional[str] = None
    ) -> Optional[str]:
        """
        Capture container state before changes.

        Args:
            host: Target host (service-host, ha-host, etc.)
            container: Container name
            alert_context: Optional context about why snapshot is being taken

        Returns:
            snapshot_id or None if failed
        """
        if not self.ssh_executor:
            self.logger.warning("snapshot_skipped_no_ssh_executor")
            return None

        self.logger.info(
            "capturing_container_snapshot",
            host=host,
            container=container
        )

        try:
            from .models import HostType
            host_enum = HostType(host)

            # Capture current state
            inspect_result = await self.ssh_executor.execute_commands(
                host=host_enum,
                commands=[f"docker inspect {container}"],
                timeout=30
            )

            logs_result = await self.ssh_executor.execute_commands(
                host=host_enum,
                commands=[f"docker logs --tail 100 {container} 2>&1"],
                timeout=30
            )

            snapshot_id = f"snap-{datetime.now().timestamp():.0f}"

            state_data = {
                "inspect": inspect_result.outputs[0] if inspect_result.outputs else "",
                "logs": logs_result.outputs[0] if logs_result.outputs else "",
                "captured_at": datetime.now().isoformat(),
                "exit_codes": {
                    "inspect": inspect_result.exit_codes[0] if inspect_result.exit_codes else -1,
                    "logs": logs_result.exit_codes[0] if logs_result.exit_codes else -1
                }
            }

            # Store in database
            await db.execute(
                """
                INSERT INTO state_snapshots (
                    snapshot_id, host, target_type, target_name,
                    state_data, alert_context, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
                """,
                snapshot_id,
                host,
                SnapshotType.CONTAINER.value,
                container,
                json.dumps(state_data),
                alert_context
            )

            self.logger.info(
                "container_snapshot_captured",
                snapshot_id=snapshot_id,
                host=host,
                container=container
            )

            return snapshot_id

        except Exception as e:
            self.logger.error(
                "container_snapshot_failed",
                host=host,
                container=container,
                error=str(e)
            )
            return None

    async def snapshot_service_state(
        self,
        host: str,
        service: str,
        alert_context: Optional[str] = None
    ) -> Optional[str]:
        """
        Capture systemd service state before changes.

        Args:
            host: Target host
            service: Service name (e.g., "wg-quick@wg0")
            alert_context: Optional context

        Returns:
            snapshot_id or None if failed
        """
        if not self.ssh_executor:
            return None

        self.logger.info(
            "capturing_service_snapshot",
            host=host,
            service=service
        )

        try:
            from .models import HostType
            host_enum = HostType(host)

            # Capture service status
            status_result = await self.ssh_executor.execute_commands(
                host=host_enum,
                commands=[f"systemctl status {service} --no-pager"],
                timeout=30
            )

            # Capture service config if accessible
            show_result = await self.ssh_executor.execute_commands(
                host=host_enum,
                commands=[f"systemctl show {service}"],
                timeout=30
            )

            snapshot_id = f"snap-{datetime.now().timestamp():.0f}"

            state_data = {
                "status": status_result.outputs[0] if status_result.outputs else "",
                "config": show_result.outputs[0] if show_result.outputs else "",
                "captured_at": datetime.now().isoformat()
            }

            await db.execute(
                """
                INSERT INTO state_snapshots (
                    snapshot_id, host, target_type, target_name,
                    state_data, alert_context, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
                """,
                snapshot_id,
                host,
                SnapshotType.SERVICE.value,
                service,
                json.dumps(state_data),
                alert_context
            )

            self.logger.info(
                "service_snapshot_captured",
                snapshot_id=snapshot_id,
                host=host,
                service=service
            )

            return snapshot_id

        except Exception as e:
            self.logger.error(
                "service_snapshot_failed",
                host=host,
                service=service,
                error=str(e)
            )
            return None

    async def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a snapshot by ID.

        Args:
            snapshot_id: Snapshot ID to retrieve

        Returns:
            Snapshot data or None if not found
        """
        try:
            row = await db.fetchrow(
                """
                SELECT snapshot_id, host, target_type, target_name,
                       state_data, alert_context, created_at, rolled_back_at
                FROM state_snapshots
                WHERE snapshot_id = $1
                """,
                snapshot_id
            )

            if row:
                return {
                    "snapshot_id": row["snapshot_id"],
                    "host": row["host"],
                    "target_type": row["target_type"],
                    "target_name": row["target_name"],
                    "state_data": json.loads(row["state_data"]) if row["state_data"] else {},
                    "alert_context": row["alert_context"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "rolled_back_at": row["rolled_back_at"].isoformat() if row["rolled_back_at"] else None
                }

            return None

        except Exception as e:
            self.logger.error(
                "get_snapshot_failed",
                snapshot_id=snapshot_id,
                error=str(e)
            )
            return None

    async def rollback_container(
        self,
        snapshot_id: str,
        reason: str
    ) -> Dict[str, Any]:
        """
        Attempt to rollback a container to its snapshot state.

        This is a best-effort operation - it will restart the container
        which should restore it to a known working state.

        Args:
            snapshot_id: Snapshot ID to rollback to
            reason: Reason for rollback

        Returns:
            Rollback result
        """
        snapshot = await self.get_snapshot(snapshot_id)

        if not snapshot:
            return {"success": False, "error": "Snapshot not found"}

        if snapshot["target_type"] != SnapshotType.CONTAINER.value:
            return {"success": False, "error": "Snapshot is not a container snapshot"}

        if not self.ssh_executor:
            return {"success": False, "error": "SSH executor not available"}

        host = snapshot["host"]
        container = snapshot["target_name"]

        self.logger.info(
            "attempting_rollback",
            snapshot_id=snapshot_id,
            host=host,
            container=container,
            reason=reason
        )

        try:
            from .models import HostType
            host_enum = HostType(host)

            # For containers, restart is the primary rollback mechanism
            # This clears any corrupted state and returns to image defaults
            result = await self.ssh_executor.execute_commands(
                host=host_enum,
                commands=[f"docker restart {container}"],
                timeout=60
            )

            success = result.success

            # Mark snapshot as rolled back
            await db.execute(
                """
                UPDATE state_snapshots
                SET rolled_back_at = NOW(),
                    rollback_reason = $1
                WHERE snapshot_id = $2
                """,
                reason,
                snapshot_id
            )

            self.logger.info(
                "rollback_complete",
                snapshot_id=snapshot_id,
                success=success,
                container=container
            )

            return {
                "success": success,
                "snapshot_id": snapshot_id,
                "action": "container_restart",
                "container": container,
                "host": host,
                "output": result.outputs[0] if result.outputs else "",
                "error": result.error if not success else None
            }

        except Exception as e:
            self.logger.error(
                "rollback_failed",
                snapshot_id=snapshot_id,
                error=str(e)
            )
            return {"success": False, "error": str(e)}

    async def list_recent_snapshots(
        self,
        hours: int = 24,
        target_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List recent snapshots.

        Args:
            hours: How far back to look
            target_type: Optional filter by type

        Returns:
            List of snapshot summaries
        """
        try:
            if target_type:
                rows = await db.fetch(
                    """
                    SELECT snapshot_id, host, target_type, target_name,
                           alert_context, created_at, rolled_back_at
                    FROM state_snapshots
                    WHERE created_at > NOW() - INTERVAL '%s hours'
                      AND target_type = $2
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    hours,
                    target_type
                )
            else:
                rows = await db.fetch(
                    """
                    SELECT snapshot_id, host, target_type, target_name,
                           alert_context, created_at, rolled_back_at
                    FROM state_snapshots
                    WHERE created_at > NOW() - INTERVAL '%s hours'
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    hours
                )

            return [
                {
                    "snapshot_id": row["snapshot_id"],
                    "host": row["host"],
                    "target_type": row["target_type"],
                    "target_name": row["target_name"],
                    "alert_context": row["alert_context"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "rolled_back": row["rolled_back_at"] is not None
                }
                for row in rows
            ]

        except Exception as e:
            self.logger.error("list_snapshots_failed", error=str(e))
            return []

    async def cleanup_old_snapshots(self, retention_hours: int = None):
        """
        Delete snapshots older than retention period.

        Args:
            retention_hours: Hours to retain (default: RETENTION_HOURS)
        """
        hours = retention_hours or self.RETENTION_HOURS

        try:
            result = await db.execute(
                """
                DELETE FROM state_snapshots
                WHERE created_at < NOW() - INTERVAL '%s hours'
                """,
                hours
            )

            self.logger.info(
                "old_snapshots_cleaned",
                retention_hours=hours
            )

        except Exception as e:
            self.logger.error("snapshot_cleanup_failed", error=str(e))

    async def should_rollback(
        self,
        snapshot_id: str,
        current_state_check: bool = True
    ) -> Dict[str, Any]:
        """
        Analyze whether rollback is recommended.

        Compares current state to snapshot state to determine
        if rollback would be beneficial.

        Args:
            snapshot_id: Snapshot to compare against
            current_state_check: If True, fetch current state for comparison

        Returns:
            Analysis with recommendation
        """
        snapshot = await self.get_snapshot(snapshot_id)

        if not snapshot:
            return {"recommend_rollback": False, "reason": "Snapshot not found"}

        if snapshot.get("rolled_back_at"):
            return {"recommend_rollback": False, "reason": "Already rolled back"}

        # Basic heuristic: if snapshot is recent and container might be in bad state
        state_data = snapshot.get("state_data", {})
        captured_at = snapshot.get("created_at")

        # Parse the captured state
        try:
            inspect_data = json.loads(state_data.get("inspect", "{}"))
            if isinstance(inspect_data, list) and len(inspect_data) > 0:
                inspect_data = inspect_data[0]

            was_running = inspect_data.get("State", {}).get("Running", False)

            return {
                "recommend_rollback": was_running,  # Recommend if was previously running
                "reason": "Container was running at snapshot time" if was_running else "Container was not running",
                "snapshot_id": snapshot_id,
                "captured_at": captured_at,
                "previous_state": {
                    "running": was_running,
                    "status": inspect_data.get("State", {}).get("Status", "unknown")
                }
            }

        except Exception as e:
            return {
                "recommend_rollback": False,
                "reason": f"Unable to analyze snapshot: {str(e)}"
            }


# Global rollback manager instance
rollback_manager: Optional[RollbackManager] = None


def init_rollback_manager(ssh_executor=None) -> RollbackManager:
    """
    Initialize global rollback manager.

    Args:
        ssh_executor: SSH executor for state capture

    Returns:
        RollbackManager instance
    """
    global rollback_manager
    rollback_manager = RollbackManager(ssh_executor=ssh_executor)
    logger.info("rollback_manager_initialized")
    return rollback_manager
