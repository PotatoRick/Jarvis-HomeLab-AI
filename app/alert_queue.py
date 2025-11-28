"""
Alert Queue for Degraded Mode

Queues alerts in memory when database is unavailable,
ensuring Jarvis continues operating during DB outages.
"""

import asyncio
import structlog
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from app.database import Database


@dataclass
class QueuedAlert:
    """Alert queued for later database insert"""
    timestamp: str
    alert_name: str
    alert_instance: str
    severity: str
    alert_labels: Dict
    alert_annotations: Dict
    attempt_number: int
    ai_analysis: Optional[str]
    ai_reasoning: Optional[str]
    remediation_plan: Optional[str]
    commands_executed: List[str]
    command_outputs: List[str]
    exit_codes: List[int]
    success: bool
    error_message: Optional[str]
    execution_duration_seconds: int
    risk_level: str
    escalated: bool
    user_approved: bool
    discord_message_id: Optional[str]
    discord_thread_id: Optional[str]


class AlertQueue:
    """
    In-memory queue for alerts during database degraded mode.

    Queues remediation logs when database is unavailable,
    automatically drains when connection is restored.
    """

    MAX_QUEUE_SIZE = 500  # Maximum alerts to hold in memory
    DRAIN_INTERVAL = 30   # Seconds between drain attempts
    DRAIN_BATCH_SIZE = 100  # Process this many at a time

    def __init__(self, db: Database):
        self.db = db
        self.logger = structlog.get_logger(__name__)

        # In-memory queue (FIFO)
        self.queue: deque[QueuedAlert] = deque(maxlen=self.MAX_QUEUE_SIZE)

        # Queue statistics
        self.total_queued = 0
        self.total_drained = 0
        self.total_dropped = 0  # Dropped when queue is full

        # Background task
        self._drain_task: Optional[asyncio.Task] = None
        self._is_draining = False

    async def start(self):
        """Start background drain task"""
        self.logger.info("alert_queue_starting")
        self._drain_task = asyncio.create_task(self._drain_loop())

    async def stop(self):
        """Stop background drain task"""
        if self._drain_task:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
        self.logger.info("alert_queue_stopped", queued=len(self.queue))

    async def enqueue(self, alert_data: Dict):
        """
        Add an alert to the queue.

        Args:
            alert_data: Alert remediation log data

        Returns:
            True if queued, False if queue is full and alert was dropped
        """
        try:
            queued_alert = QueuedAlert(
                timestamp=alert_data.get('timestamp', datetime.utcnow().isoformat()),
                alert_name=alert_data.get('alert_name', ''),
                alert_instance=alert_data.get('alert_instance', ''),
                severity=alert_data.get('severity', 'warning'),
                alert_labels=alert_data.get('alert_labels', {}),
                alert_annotations=alert_data.get('alert_annotations', {}),
                attempt_number=alert_data.get('attempt_number', 1),
                ai_analysis=alert_data.get('ai_analysis'),
                ai_reasoning=alert_data.get('ai_reasoning'),
                remediation_plan=alert_data.get('remediation_plan'),
                commands_executed=alert_data.get('commands_executed', []),
                command_outputs=alert_data.get('command_outputs', []),
                exit_codes=alert_data.get('exit_codes', []),
                success=alert_data.get('success', False),
                error_message=alert_data.get('error_message'),
                execution_duration_seconds=alert_data.get('execution_duration_seconds', 0),
                risk_level=alert_data.get('risk_level', 'low'),
                escalated=alert_data.get('escalated', False),
                user_approved=alert_data.get('user_approved', False),
                discord_message_id=alert_data.get('discord_message_id'),
                discord_thread_id=alert_data.get('discord_thread_id')
            )

            # Check if queue is full
            if len(self.queue) >= self.MAX_QUEUE_SIZE:
                self.total_dropped += 1
                self.logger.warning(
                    "queue_full_alert_dropped",
                    queue_size=len(self.queue),
                    total_dropped=self.total_dropped,
                    alert_name=alert_data.get('alert_name')
                )
                return False

            self.queue.append(queued_alert)
            self.total_queued += 1

            self.logger.info(
                "alert_queued",
                queue_depth=len(self.queue),
                total_queued=self.total_queued,
                alert_name=alert_data.get('alert_name')
            )

            return True

        except Exception as e:
            self.logger.error(
                "enqueue_failed",
                error=str(e),
                exc_info=True
            )
            return False

    async def _drain_loop(self):
        """Background task to periodically drain the queue"""
        while True:
            try:
                await asyncio.sleep(self.DRAIN_INTERVAL)

                if len(self.queue) > 0 and not self._is_draining:
                    await self._drain_queue()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(
                    "drain_loop_error",
                    error=str(e),
                    exc_info=True
                )

    async def _drain_queue(self):
        """
        Attempt to drain queue to database.

        Processes alerts in batches, stops if database fails.
        """
        if self._is_draining:
            return

        self._is_draining = True

        try:
            # Check if database is available
            if not await self._is_database_available():
                self.logger.debug(
                    "database_unavailable_skip_drain",
                    queue_depth=len(self.queue)
                )
                return

            # Process in batches
            drained_count = 0
            batch_size = min(self.DRAIN_BATCH_SIZE, len(self.queue))

            for _ in range(batch_size):
                if len(self.queue) == 0:
                    break

                alert = self.queue.popleft()

                try:
                    await self._insert_alert(alert)
                    drained_count += 1
                    self.total_drained += 1

                except Exception as e:
                    # Database failed, put alert back at front of queue
                    self.queue.appendleft(alert)
                    self.logger.error(
                        "drain_insert_failed",
                        error=str(e),
                        drained_count=drained_count
                    )
                    break  # Stop draining on first failure

            if drained_count > 0:
                self.logger.info(
                    "queue_drained",
                    drained_count=drained_count,
                    remaining=len(self.queue),
                    total_drained=self.total_drained
                )

        finally:
            self._is_draining = False

    async def _is_database_available(self) -> bool:
        """Check if database connection is available"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def _insert_alert(self, alert: QueuedAlert):
        """Insert a queued alert into the database"""
        query = """
            INSERT INTO remediation_log (
                timestamp, alert_name, alert_instance, severity,
                alert_labels, alert_annotations, attempt_number,
                ai_analysis, ai_reasoning, remediation_plan,
                commands_executed, command_outputs, exit_codes,
                success, error_message, execution_duration_seconds,
                risk_level, escalated, user_approved,
                discord_message_id, discord_thread_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21
            )
        """

        async with self.db.pool.acquire() as conn:
            await conn.execute(
                query,
                datetime.fromisoformat(alert.timestamp) if isinstance(alert.timestamp, str) else alert.timestamp,
                alert.alert_name,
                alert.alert_instance,
                alert.severity,
                alert.alert_labels,
                alert.alert_annotations,
                alert.attempt_number,
                alert.ai_analysis,
                alert.ai_reasoning,
                alert.remediation_plan,
                alert.commands_executed,
                alert.command_outputs,
                alert.exit_codes,
                alert.success,
                alert.error_message,
                alert.execution_duration_seconds,
                alert.risk_level,
                alert.escalated,
                alert.user_approved,
                alert.discord_message_id,
                alert.discord_thread_id
            )

    def get_stats(self) -> Dict:
        """Get queue statistics"""
        oldest_timestamp = None
        if len(self.queue) > 0:
            oldest_timestamp = self.queue[0].timestamp

        return {
            "queue_depth": len(self.queue),
            "total_queued": self.total_queued,
            "total_drained": self.total_drained,
            "total_dropped": self.total_dropped,
            "oldest_alert": oldest_timestamp,
            "is_draining": self._is_draining
        }

    def is_degraded(self) -> bool:
        """Check if currently in degraded mode (queue has items)"""
        return len(self.queue) > 0
