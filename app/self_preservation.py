"""
Self-Preservation Module for Jarvis AI Remediation Service.

Enables Jarvis to safely restart itself and its dependencies by:
1. Serializing current remediation state
2. Handing off to n8n workflow for restart orchestration
3. Resuming from saved state after restart

This is the ONLY mechanism that can restart Jarvis or its critical dependencies.
"""

import asyncio
import json
import uuid
import structlog
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum

from .config import settings
from . import metrics

logger = structlog.get_logger()


class SelfRestartTarget(str, Enum):
    """Valid targets for self-restart operations."""
    JARVIS = "jarvis"                    # Jarvis container itself
    POSTGRES_JARVIS = "postgres-jarvis"  # Jarvis database
    SKYNET_HOST = "management-host-host"          # Full host restart
    DOCKER_DAEMON = "docker-daemon"      # Docker service on Management-Host


class HandoffStatus(str, Enum):
    """Status of a self-preservation handoff."""
    PENDING = "pending"          # Handoff initiated, awaiting n8n pickup
    IN_PROGRESS = "in_progress"  # n8n is processing (restart in progress)
    COMPLETED = "completed"      # Restart complete, Jarvis resumed
    FAILED = "failed"            # Something went wrong
    TIMEOUT = "timeout"          # n8n did not complete in time
    CANCELLED = "cancelled"      # Handoff was cancelled


@dataclass
class RemediationContext:
    """
    Serializable context of an in-progress remediation.

    This is everything Jarvis needs to resume after a restart.
    """
    # HIGH-002 FIX: Size limits to prevent database issues
    MAX_COMMANDS = 50  # Max commands to store
    MAX_OUTPUT_LENGTH = 10000  # 10KB per output
    MAX_ANALYSIS_LENGTH = 20000  # 20KB for AI analysis

    # Alert identification
    alert_name: str
    alert_instance: str
    alert_fingerprint: str
    severity: str

    # Current progress
    attempt_number: int
    commands_executed: List[str]
    command_outputs: List[str]
    diagnostic_info: Dict[str, Any]

    # AI context
    ai_analysis: Optional[str] = None
    ai_reasoning: Optional[str] = None
    planned_commands: List[str] = None

    # Target information
    target_host: str = "unknown"
    service_name: Optional[str] = None
    service_type: Optional[str] = None

    # Timestamps
    started_at: Optional[str] = None

    # MEDIUM-008 FIX: Track restart count to prevent infinite loops
    restart_count: int = 0
    max_restarts: int = 2

    def __post_init__(self):
        if self.planned_commands is None:
            self.planned_commands = []
        if self.started_at is None:
            self.started_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.

        HIGH-002 FIX: Applies size limits to prevent database overflow.
        """
        # Truncate commands list
        commands = self.commands_executed[:self.MAX_COMMANDS]
        outputs = self.command_outputs[:self.MAX_COMMANDS]

        # Truncate individual outputs
        truncated_outputs = []
        for output in outputs:
            if output and len(output) > self.MAX_OUTPUT_LENGTH:
                truncated_outputs.append(
                    output[:self.MAX_OUTPUT_LENGTH] + "\n...(truncated)"
                )
            else:
                truncated_outputs.append(output or "")

        # Truncate AI analysis
        ai_analysis = self.ai_analysis
        if ai_analysis and len(ai_analysis) > self.MAX_ANALYSIS_LENGTH:
            ai_analysis = ai_analysis[:self.MAX_ANALYSIS_LENGTH] + "\n...(truncated)"

        ai_reasoning = self.ai_reasoning
        if ai_reasoning and len(ai_reasoning) > self.MAX_ANALYSIS_LENGTH:
            ai_reasoning = ai_reasoning[:self.MAX_ANALYSIS_LENGTH] + "\n...(truncated)"

        # Build result dict
        result = {
            "alert_name": self.alert_name,
            "alert_instance": self.alert_instance,
            "alert_fingerprint": self.alert_fingerprint,
            "severity": self.severity,
            "attempt_number": self.attempt_number,
            "commands_executed": commands,
            "command_outputs": truncated_outputs,
            "diagnostic_info": self.diagnostic_info,
            "ai_analysis": ai_analysis,
            "ai_reasoning": ai_reasoning,
            "planned_commands": (self.planned_commands or [])[:20],  # Limit planned too
            "target_host": self.target_host,
            "service_name": self.service_name,
            "service_type": self.service_type,
            "started_at": self.started_at,
            "restart_count": self.restart_count,
            "max_restarts": self.max_restarts,
        }

        # Validate serialization works
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            # Return minimal safe context if serialization fails
            logger.warning(
                "context_serialization_fallback",
                error=str(e),
                alert_name=self.alert_name
            )
            return {
                "alert_name": self.alert_name,
                "alert_instance": self.alert_instance,
                "alert_fingerprint": self.alert_fingerprint,
                "severity": self.severity,
                "attempt_number": self.attempt_number,
                "target_host": self.target_host,
                "restart_count": self.restart_count,
                "max_restarts": self.max_restarts,
                "error": f"Context too large or complex to serialize: {str(e)}"
            }

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemediationContext":
        """Create from dictionary."""
        # Handle both old format (without restart_count) and new format
        return cls(
            alert_name=data.get("alert_name", "unknown"),
            alert_instance=data.get("alert_instance", "unknown"),
            alert_fingerprint=data.get("alert_fingerprint", "unknown"),
            severity=data.get("severity", "warning"),
            attempt_number=data.get("attempt_number", 1),
            commands_executed=data.get("commands_executed", []),
            command_outputs=data.get("command_outputs", []),
            diagnostic_info=data.get("diagnostic_info", {}),
            ai_analysis=data.get("ai_analysis"),
            ai_reasoning=data.get("ai_reasoning"),
            planned_commands=data.get("planned_commands", []),
            target_host=data.get("target_host", "unknown"),
            service_name=data.get("service_name"),
            service_type=data.get("service_type"),
            started_at=data.get("started_at"),
            restart_count=data.get("restart_count", 0),
            max_restarts=data.get("max_restarts", 2),
        )


@dataclass
class SelfPreservationHandoff:
    """
    A handoff record for self-restart operations.

    This is stored in the database so it survives restarts.
    """
    handoff_id: str
    restart_target: SelfRestartTarget
    restart_reason: str
    remediation_context: Optional[RemediationContext]
    status: HandoffStatus
    created_at: str
    callback_url: str
    n8n_execution_id: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "handoff_id": self.handoff_id,
            "restart_target": self.restart_target.value,
            "restart_reason": self.restart_reason,
            "remediation_context": self.remediation_context.to_dict() if self.remediation_context else None,
            "status": self.status.value,
            "created_at": self.created_at,
            "callback_url": self.callback_url,
            "n8n_execution_id": self.n8n_execution_id,
            "completed_at": self.completed_at,
            "error_message": self.error_message
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SelfPreservationHandoff":
        """Create from dictionary."""
        return cls(
            handoff_id=data["handoff_id"],
            restart_target=SelfRestartTarget(data["restart_target"]),
            restart_reason=data["restart_reason"],
            remediation_context=RemediationContext.from_dict(data["remediation_context"]) if data.get("remediation_context") else None,
            status=HandoffStatus(data["status"]),
            created_at=data["created_at"],
            callback_url=data["callback_url"],
            n8n_execution_id=data.get("n8n_execution_id"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message")
        )


class SelfPreservationManager:
    """
    Manages self-restart operations for Jarvis.

    The flow:
    1. Jarvis detects it needs to restart itself or a dependency
    2. Current remediation state is serialized to database
    3. n8n workflow is triggered with restart command and callback URL
    4. n8n executes restart, polls until Jarvis is healthy
    5. n8n calls /resume endpoint with saved context
    6. Jarvis continues remediation from where it left off
    """

    # Webhook path that n8n will call
    N8N_SELF_RESTART_WEBHOOK = "/webhook/jarvis-self-restart"

    # Targets that require this mechanism (blocked by command_validator normally)
    PROTECTED_TARGETS = {
        SelfRestartTarget.JARVIS,
        SelfRestartTarget.POSTGRES_JARVIS,
        SelfRestartTarget.SKYNET_HOST,
        SelfRestartTarget.DOCKER_DAEMON,
    }

    def __init__(self, db, n8n_client=None, discord_notifier=None):
        """
        Initialize SelfPreservationManager.

        Args:
            db: Database instance for persistence
            n8n_client: N8NClient for triggering workflows
            discord_notifier: Discord notifier for alerts
        """
        self.db = db
        self.n8n_client = n8n_client
        self.discord_notifier = discord_notifier
        self.logger = logger.bind(component="self_preservation")

        # In-memory tracking of active handoff (there can only be one)
        self._active_handoff: Optional[SelfPreservationHandoff] = None

        # Jarvis API URL (for n8n to call back)
        # Use explicit external URL if configured, otherwise fall back to ssh_management-host_host
        if settings.jarvis_external_url:
            self._jarvis_url = settings.jarvis_external_url
        else:
            self._jarvis_url = f"http://{settings.ssh_management-host_host}:{settings.port}"
            self.logger.warning(
                "jarvis_external_url_not_configured",
                fallback_url=self._jarvis_url,
                message="Set JARVIS_EXTERNAL_URL for reliable n8n callbacks"
            )

    async def initiate_self_restart(
        self,
        target: SelfRestartTarget,
        reason: str,
        remediation_context: Optional[RemediationContext] = None,
        timeout_minutes: int = 10
    ) -> Dict[str, Any]:
        """
        Initiate a self-restart operation via n8n handoff.

        HIGH-006 FIX: Uses database transaction with advisory lock to prevent
        concurrent restart race conditions.

        Args:
            target: What to restart (jarvis, postgres-jarvis, etc.)
            reason: Why restart is needed
            remediation_context: Current remediation state to resume after restart
            timeout_minutes: How long n8n should wait for Jarvis to come back

        Returns:
            Dict with handoff_id and status
        """
        # Validate target
        if target not in self.PROTECTED_TARGETS:
            return {
                "success": False,
                "error": f"Target {target.value} is not a protected target"
            }

        # MEDIUM-008 FIX: Check restart count in context to prevent infinite loops
        if remediation_context and remediation_context.restart_count >= remediation_context.max_restarts:
            self.logger.warning(
                "max_restarts_reached",
                alert_name=remediation_context.alert_name,
                restart_count=remediation_context.restart_count,
                max_restarts=remediation_context.max_restarts
            )
            return {
                "success": False,
                "error": f"Maximum restart count ({remediation_context.max_restarts}) reached for this remediation"
            }

        # HIGH-006 FIX: Use database transaction with advisory lock
        # to prevent race condition where two concurrent restart requests
        # both check for active handoff, find none, then both create one
        try:
            async with self.db.pool.acquire() as conn:
                async with conn.transaction():
                    # Acquire advisory lock (unique key for self-restart operations)
                    # This blocks other initiate_self_restart calls until we're done
                    await conn.execute("SELECT pg_advisory_xact_lock(123456789)")

                    # Check for existing active handoff in database (not just memory)
                    existing = await conn.fetchrow("""
                        SELECT handoff_id, status
                        FROM self_preservation_handoffs
                        WHERE status IN ('pending', 'in_progress')
                        LIMIT 1
                    """)

                    if existing:
                        return {
                            "success": False,
                            "error": f"Existing handoff {existing['handoff_id']} is still active (status: {existing['status']})"
                        }

                    # Generate handoff ID
                    handoff_id = f"sp-{uuid.uuid4().hex[:12]}"

                    # Build callback URL
                    callback_url = f"{self._jarvis_url}/resume"

                    # Increment restart count if resuming
                    if remediation_context:
                        remediation_context.restart_count += 1

                    # Create handoff record
                    handoff = SelfPreservationHandoff(
                        handoff_id=handoff_id,
                        restart_target=target,
                        restart_reason=reason,
                        remediation_context=remediation_context,
                        status=HandoffStatus.PENDING,
                        created_at=datetime.utcnow().isoformat(),
                        callback_url=callback_url
                    )

                    self.logger.info(
                        "initiating_self_restart",
                        handoff_id=handoff_id,
                        target=target.value,
                        reason=reason,
                        has_context=remediation_context is not None,
                        restart_count=remediation_context.restart_count if remediation_context else 0
                    )

                    # Insert handoff within transaction
                    context_json = json.dumps(handoff.remediation_context.to_dict()) if handoff.remediation_context else None
                    await conn.execute("""
                        INSERT INTO self_preservation_handoffs (
                            handoff_id, restart_target, restart_reason,
                            remediation_context, status, callback_url,
                            n8n_execution_id, error_message, created_at, completed_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                        handoff.handoff_id,
                        handoff.restart_target.value,
                        handoff.restart_reason,
                        context_json,
                        handoff.status.value,
                        handoff.callback_url,
                        handoff.n8n_execution_id,
                        handoff.error_message,
                        handoff.created_at,
                        handoff.completed_at
                    )
                    # Transaction commits here, advisory lock is released

        except Exception as e:
            self.logger.error(
                "handoff_persistence_failed",
                handoff_id=handoff_id if 'handoff_id' in dir() else 'unknown',
                error=str(e)
            )
            metrics.record_self_restart_failure(target.value, "handoff_save_failed")
            return {
                "success": False,
                "error": f"Failed to persist handoff: {str(e)}"
            }

        # Notify Discord
        if self.discord_notifier:
            try:
                await self._notify_self_restart_initiated(handoff)
            except Exception as e:
                self.logger.warning("discord_notification_failed", error=str(e))

        # Trigger n8n workflow
        if self.n8n_client:
            try:
                n8n_result = await self._trigger_n8n_restart_workflow(
                    handoff=handoff,
                    timeout_minutes=timeout_minutes
                )

                if not n8n_result.get("success"):
                    # n8n trigger failed - abort handoff
                    handoff.status = HandoffStatus.FAILED
                    handoff.error_message = n8n_result.get("error", "n8n trigger failed")
                    await self._save_handoff(handoff)

                    metrics.record_self_restart(target.value, "failure")
                    metrics.record_self_restart_failure(target.value, "n8n_trigger_failed")
                    return {
                        "success": False,
                        "error": f"n8n workflow trigger failed: {n8n_result.get('error')}"
                    }

                # Update with n8n execution ID
                handoff.n8n_execution_id = n8n_result.get("execution_id")
                handoff.status = HandoffStatus.IN_PROGRESS
                await self._save_handoff(handoff)

                # Record that self-restart is now active
                metrics.set_self_restart_active(True)

            except Exception as e:
                self.logger.error(
                    "n8n_trigger_exception",
                    handoff_id=handoff_id,
                    error=str(e)
                )
                handoff.status = HandoffStatus.FAILED
                handoff.error_message = str(e)
                await self._save_handoff(handoff)

                metrics.record_self_restart(target.value, "failure")
                metrics.record_self_restart_failure(target.value, "n8n_trigger_failed")
                return {
                    "success": False,
                    "error": f"n8n workflow exception: {str(e)}"
                }
        else:
            self.logger.warning(
                "n8n_client_not_available",
                handoff_id=handoff_id,
                message="n8n not configured - handoff saved but restart must be manual"
            )

        self._active_handoff = handoff

        return {
            "success": True,
            "handoff_id": handoff_id,
            "status": handoff.status.value,
            "message": f"Self-restart initiated for {target.value}. Jarvis will resume after restart."
        }

    async def resume_from_handoff(
        self,
        handoff_id: str,
        health_verified: bool = True
    ) -> Dict[str, Any]:
        """
        Resume from a saved handoff after restart.

        Called by n8n via /resume endpoint after Jarvis is healthy again.

        Args:
            handoff_id: ID of the handoff to resume
            health_verified: Whether n8n verified Jarvis health

        Returns:
            Dict with remediation context to continue
        """
        self.logger.info(
            "resuming_from_handoff",
            handoff_id=handoff_id,
            health_verified=health_verified
        )

        # Load handoff from database
        try:
            handoff = await self._load_handoff(handoff_id)
        except Exception as e:
            self.logger.error(
                "handoff_load_failed",
                handoff_id=handoff_id,
                error=str(e)
            )
            return {
                "success": False,
                "error": f"Failed to load handoff: {str(e)}"
            }

        if not handoff:
            return {
                "success": False,
                "error": f"Handoff {handoff_id} not found"
            }

        if handoff.status not in (HandoffStatus.PENDING, HandoffStatus.IN_PROGRESS):
            return {
                "success": False,
                "error": f"Handoff {handoff_id} is in status {handoff.status.value}, cannot resume"
            }

        # Mark handoff as completed
        handoff.status = HandoffStatus.COMPLETED
        handoff.completed_at = datetime.utcnow().isoformat()
        await self._save_handoff(handoff)

        # Calculate duration and record metrics
        try:
            start = datetime.fromisoformat(handoff.created_at)
            end = datetime.fromisoformat(handoff.completed_at)
            duration_seconds = (end - start).total_seconds()
            metrics.record_self_restart(handoff.restart_target.value, "success", duration_seconds)
        except Exception:
            metrics.record_self_restart(handoff.restart_target.value, "success")

        metrics.set_self_restart_active(False)

        # Clear active handoff
        self._active_handoff = None

        # Notify Discord
        if self.discord_notifier:
            try:
                await self._notify_self_restart_completed(handoff)
            except Exception as e:
                self.logger.warning("discord_notification_failed", error=str(e))

        self.logger.info(
            "handoff_resumed_successfully",
            handoff_id=handoff_id,
            had_context=handoff.remediation_context is not None
        )

        return {
            "success": True,
            "handoff_id": handoff_id,
            "restart_target": handoff.restart_target.value,
            "remediation_context": handoff.remediation_context.to_dict() if handoff.remediation_context else None
        }

    async def check_pending_handoffs(self) -> Optional[SelfPreservationHandoff]:
        """
        Check for pending handoffs on startup.

        Called during Jarvis startup to detect if we're recovering from a restart.

        Returns:
            Pending handoff if found, None otherwise
        """
        try:
            handoff = await self._load_latest_pending_handoff()

            if handoff:
                self.logger.info(
                    "pending_handoff_found_on_startup",
                    handoff_id=handoff.handoff_id,
                    target=handoff.restart_target.value,
                    created_at=handoff.created_at
                )
                self._active_handoff = handoff

            return handoff

        except Exception as e:
            self.logger.warning(
                "pending_handoff_check_failed",
                error=str(e)
            )
            return None

    async def cleanup_stale_handoffs(self) -> int:
        """
        Clean up stale handoffs that never received a callback.

        Called during startup to prevent old in_progress handoffs from
        blocking new self-restart requests forever.

        HIGH-004 FIX: Added LIMIT to prevent unbounded queries.

        Returns:
            Number of handoffs cleaned up
        """
        max_age_minutes = settings.stale_handoff_cleanup_minutes

        # HIGH-004 FIX: Use LIMIT to prevent unbounded cleanup
        # Process in batches of 100 to avoid exhausting DB connections
        query = """
            UPDATE self_preservation_handoffs
            SET status = 'timeout',
                error_message = 'Cleanup: no callback received within timeout',
                completed_at = NOW()
            WHERE handoff_id IN (
                SELECT handoff_id
                FROM self_preservation_handoffs
                WHERE status IN ('pending', 'in_progress')
                AND created_at < NOW() - INTERVAL '%s minutes'
                LIMIT 100
            )
            RETURNING handoff_id, restart_target, created_at
        """

        try:
            total_cleaned = 0

            # Process in batches until no more stale handoffs
            while True:
                async with self.db.pool.acquire() as conn:
                    # PostgreSQL doesn't support parameterized interval, use string formatting
                    formatted_query = query.replace('%s', str(max_age_minutes))
                    rows = await conn.fetch(formatted_query)

                if not rows:
                    break

                batch_count = len(rows)
                total_cleaned += batch_count

                for row in rows:
                    self.logger.warning(
                        "stale_handoff_cleaned",
                        handoff_id=row['handoff_id'],
                        target=row['restart_target'],
                        created_at=row['created_at'],
                        max_age_minutes=max_age_minutes
                    )
                    # Record timeout metric
                    metrics.record_self_restart(row['restart_target'], 'timeout')

                # If we got fewer than 100, we're done
                if batch_count < 100:
                    break

            if total_cleaned > 0:
                self.logger.info(
                    "stale_handoffs_cleanup_complete",
                    cleaned_count=total_cleaned,
                    max_age_minutes=max_age_minutes
                )

            return total_cleaned

        except Exception as e:
            self.logger.error(
                "stale_handoff_cleanup_failed",
                error=str(e)
            )
            return 0

    async def cancel_handoff(self, handoff_id: str, reason: str = "Cancelled by user") -> Dict[str, Any]:
        """
        Cancel an active handoff.

        Args:
            handoff_id: ID of handoff to cancel
            reason: Why it's being cancelled

        Returns:
            Result dict
        """
        try:
            handoff = await self._load_handoff(handoff_id)
        except Exception as e:
            return {"success": False, "error": str(e)}

        if not handoff:
            return {"success": False, "error": f"Handoff {handoff_id} not found"}

        if handoff.status in (HandoffStatus.COMPLETED, HandoffStatus.FAILED):
            return {"success": False, "error": f"Handoff already in terminal state: {handoff.status.value}"}

        handoff.status = HandoffStatus.CANCELLED
        handoff.completed_at = datetime.utcnow().isoformat()
        handoff.error_message = reason
        await self._save_handoff(handoff)

        # Record cancellation in metrics
        metrics.record_self_restart(handoff.restart_target.value, "cancelled")
        metrics.set_self_restart_active(False)

        if self._active_handoff and self._active_handoff.handoff_id == handoff_id:
            self._active_handoff = None

        self.logger.info(
            "handoff_cancelled",
            handoff_id=handoff_id,
            reason=reason
        )

        return {"success": True, "handoff_id": handoff_id, "status": "cancelled"}

    def get_restart_command(self, target: SelfRestartTarget) -> str:
        """
        Get the SSH command to restart a target.

        Used by n8n workflow to know what command to execute.

        Args:
            target: What to restart

        Returns:
            SSH command string
        """
        commands = {
            SelfRestartTarget.JARVIS: "docker restart jarvis",
            SelfRestartTarget.POSTGRES_JARVIS: "docker restart postgres-jarvis && sleep 10 && docker restart jarvis",
            SelfRestartTarget.DOCKER_DAEMON: "sudo systemctl restart docker",
            SelfRestartTarget.SKYNET_HOST: "sudo reboot",
        }
        return commands.get(target, f"echo 'Unknown target: {target.value}'")

    # =========================================================================
    # Private methods
    # =========================================================================

    async def _save_handoff(self, handoff: SelfPreservationHandoff) -> None:
        """Save or update handoff in database."""
        query = """
            INSERT INTO self_preservation_handoffs (
                handoff_id, restart_target, restart_reason,
                remediation_context, status, callback_url,
                n8n_execution_id, error_message, created_at, completed_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (handoff_id) DO UPDATE SET
                status = EXCLUDED.status,
                n8n_execution_id = EXCLUDED.n8n_execution_id,
                error_message = EXCLUDED.error_message,
                completed_at = EXCLUDED.completed_at
        """

        context_json = json.dumps(handoff.remediation_context.to_dict()) if handoff.remediation_context else None

        async with self.db.pool.acquire() as conn:
            await conn.execute(
                query,
                handoff.handoff_id,
                handoff.restart_target.value,
                handoff.restart_reason,
                context_json,
                handoff.status.value,
                handoff.callback_url,
                handoff.n8n_execution_id,
                handoff.error_message,
                handoff.created_at,
                handoff.completed_at
            )

    async def _load_handoff(self, handoff_id: str) -> Optional[SelfPreservationHandoff]:
        """Load handoff from database."""
        query = """
            SELECT handoff_id, restart_target, restart_reason,
                   remediation_context, status, callback_url,
                   n8n_execution_id, error_message, created_at, completed_at
            FROM self_preservation_handoffs
            WHERE handoff_id = $1
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query, handoff_id)

        if not row:
            return None

        context = None
        if row['remediation_context']:
            context_data = json.loads(row['remediation_context'])
            context = RemediationContext.from_dict(context_data)

        return SelfPreservationHandoff(
            handoff_id=row['handoff_id'],
            restart_target=SelfRestartTarget(row['restart_target']),
            restart_reason=row['restart_reason'],
            remediation_context=context,
            status=HandoffStatus(row['status']),
            callback_url=row['callback_url'],
            n8n_execution_id=row['n8n_execution_id'],
            error_message=row['error_message'],
            created_at=row['created_at'],
            completed_at=row['completed_at']
        )

    async def _load_latest_pending_handoff(self) -> Optional[SelfPreservationHandoff]:
        """Load the most recent pending or in-progress handoff."""
        query = """
            SELECT handoff_id, restart_target, restart_reason,
                   remediation_context, status, callback_url,
                   n8n_execution_id, error_message, created_at, completed_at
            FROM self_preservation_handoffs
            WHERE status IN ('pending', 'in_progress')
            ORDER BY created_at DESC
            LIMIT 1
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query)

        if not row:
            return None

        context = None
        if row['remediation_context']:
            context_data = json.loads(row['remediation_context'])
            context = RemediationContext.from_dict(context_data)

        return SelfPreservationHandoff(
            handoff_id=row['handoff_id'],
            restart_target=SelfRestartTarget(row['restart_target']),
            restart_reason=row['restart_reason'],
            remediation_context=context,
            status=HandoffStatus(row['status']),
            callback_url=row['callback_url'],
            n8n_execution_id=row['n8n_execution_id'],
            error_message=row['error_message'],
            created_at=row['created_at'],
            completed_at=row['completed_at']
        )

    async def _trigger_n8n_restart_workflow(
        self,
        handoff: SelfPreservationHandoff,
        timeout_minutes: int
    ) -> Dict[str, Any]:
        """Trigger the n8n self-restart workflow."""
        workflow_data = {
            "handoff_id": handoff.handoff_id,
            "restart_target": handoff.restart_target.value,
            "restart_command": self.get_restart_command(handoff.restart_target),
            "restart_reason": handoff.restart_reason,
            "callback_url": handoff.callback_url,
            "jarvis_health_url": f"{self._jarvis_url}/health",
            "timeout_minutes": timeout_minutes,
            "ssh_host": settings.ssh_management-host_host,
            "ssh_user": settings.ssh_management-host_user
        }

        self.logger.info(
            "triggering_n8n_restart_workflow",
            handoff_id=handoff.handoff_id,
            workflow_data=workflow_data
        )

        # Use webhook trigger for faster response
        result = await self.n8n_client.trigger_webhook(
            webhook_path=self.N8N_SELF_RESTART_WEBHOOK,
            data=workflow_data
        )

        return result

    async def _notify_self_restart_initiated(self, handoff: SelfPreservationHandoff) -> None:
        """Send Discord notification that self-restart is starting."""
        message = f"""## Self-Restart Initiated

**Handoff ID:** `{handoff.handoff_id}`
**Target:** {handoff.restart_target.value}
**Reason:** {handoff.restart_reason}
**Time:** {handoff.created_at}

Jarvis is handing off to n8n for restart orchestration.
Will resume automatically after restart completes.

{"**Remediation in progress will resume after restart.**" if handoff.remediation_context else ""}
"""
        await self.discord_notifier.send_webhook({
            "username": "Jarvis - Self-Preservation",
            "content": message
        })

    async def _notify_self_restart_completed(self, handoff: SelfPreservationHandoff) -> None:
        """Send Discord notification that self-restart completed."""
        duration = ""
        if handoff.created_at and handoff.completed_at:
            try:
                start = datetime.fromisoformat(handoff.created_at)
                end = datetime.fromisoformat(handoff.completed_at)
                duration = f"\n**Duration:** {int((end - start).total_seconds())} seconds"
            except Exception:
                pass

        message = f"""## Self-Restart Completed

**Handoff ID:** `{handoff.handoff_id}`
**Target:** {handoff.restart_target.value}
**Status:** {handoff.status.value}{duration}

Jarvis has successfully restarted and resumed operations.

{"**Resuming previous remediation...**" if handoff.remediation_context else ""}
"""
        await self.discord_notifier.send_webhook({
            "username": "Jarvis - Self-Preservation",
            "content": message
        })


# Global instance (initialized in main.py lifespan)
self_preservation_manager: Optional[SelfPreservationManager] = None


def init_self_preservation_manager(db, n8n_client=None, discord_notifier=None) -> SelfPreservationManager:
    """Initialize the global self-preservation manager."""
    global self_preservation_manager
    self_preservation_manager = SelfPreservationManager(
        db=db,
        n8n_client=n8n_client,
        discord_notifier=discord_notifier
    )
    return self_preservation_manager


def get_self_preservation_manager() -> Optional[SelfPreservationManager]:
    """Get the global self-preservation manager."""
    return self_preservation_manager
