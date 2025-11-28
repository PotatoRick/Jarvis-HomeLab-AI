"""
PostgreSQL database operations using asyncpg.
Handles remediation log tracking, maintenance windows, and command whitelist.
"""

import asyncio
import asyncpg
import structlog
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from functools import wraps
from .config import settings
from .models import RemediationAttempt, MaintenanceWindow

logger = structlog.get_logger()


def retry_with_backoff(max_retries=10, base_delay=1, max_delay=30):
    """
    Decorator to retry async functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        # Last attempt, re-raise the exception
                        raise

                    # Calculate exponential backoff delay
                    delay = min(base_delay * (2 ** attempt), max_delay)

                    logger.warning(
                        "retry_attempt",
                        function=func.__name__,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e)
                    )

                    await asyncio.sleep(delay)

        return wrapper
    return decorator


class Database:
    """PostgreSQL database interface."""

    def __init__(self):
        """Initialize database connection pool."""
        self.pool: Optional[asyncpg.Pool] = None
        self.logger = logger.bind(component="database")

    @retry_with_backoff(max_retries=10, base_delay=1, max_delay=30)
    async def connect(self):
        """
        Establish database connection pool with retry logic.

        Retries up to 10 times with exponential backoff (1s, 2s, 4s, 8s, 16s, 30s max).
        This allows Jarvis to start even if PostgreSQL is still initializing.
        """
        self.pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=settings.database_pool_size,
            command_timeout=30,
        )
        self.logger.info("database_connected", pool_size=settings.database_pool_size)

    async def disconnect(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            self.logger.info("database_disconnected")

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            self.logger.error("health_check_failed", error=str(e))
            return False

    async def get_attempt_count(
        self,
        alert_name: str,
        alert_instance: str,
        window_hours: int = 24
    ) -> int:
        """
        Get number of remediation attempts for an alert in the time window.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance identifier
            window_hours: Time window in hours

        Returns:
            Number of attempts
        """
        query = """
            SELECT COUNT(*)
            FROM remediation_log
            WHERE alert_name = $1
              AND alert_instance = $2
              AND timestamp > NOW() - INTERVAL '1 hour' * $3
        """

        async with self.pool.acquire() as conn:
            count = await conn.fetchval(query, alert_name, alert_instance, window_hours)

        self.logger.info(
            "attempt_count_retrieved",
            alert_name=alert_name,
            alert_instance=alert_instance,
            count=count,
            window_hours=window_hours
        )

        return count

    async def log_remediation_attempt(self, attempt: RemediationAttempt) -> int:
        """
        Log a remediation attempt to the database.

        Args:
            attempt: RemediationAttempt instance

        Returns:
            ID of the inserted record
        """
        query = """
            INSERT INTO remediation_log (
                alert_name,
                alert_instance,
                alert_fingerprint,
                severity,
                attempt_number,
                ai_analysis,
                ai_reasoning,
                remediation_plan,
                commands_executed,
                command_outputs,
                exit_codes,
                success,
                error_message,
                execution_duration_seconds,
                risk_level,
                escalated,
                user_approved,
                discord_message_id,
                discord_thread_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            record_id = await conn.fetchval(
                query,
                attempt.alert_name,
                attempt.alert_instance,
                attempt.alert_fingerprint,
                attempt.severity,
                attempt.attempt_number,
                attempt.ai_analysis,
                attempt.ai_reasoning,
                attempt.remediation_plan,
                attempt.commands_executed,
                attempt.command_outputs,
                attempt.exit_codes,
                attempt.success,
                attempt.error_message,
                attempt.execution_duration_seconds,
                attempt.risk_level.value if attempt.risk_level else None,
                attempt.escalated,
                attempt.user_approved,
                attempt.discord_message_id,
                attempt.discord_thread_id
            )

        self.logger.info(
            "remediation_attempt_logged",
            record_id=record_id,
            alert_name=attempt.alert_name,
            success=attempt.success,
            escalated=attempt.escalated
        )

        return record_id

    async def get_recent_attempts(
        self,
        alert_name: str,
        alert_instance: str,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get recent remediation attempts for escalation context.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance identifier
            limit: Maximum number of attempts to retrieve

        Returns:
            List of attempt dictionaries
        """
        query = """
            SELECT
                id,
                timestamp,
                attempt_number,
                ai_analysis,
                commands_executed,
                success,
                error_message,
                execution_duration_seconds
            FROM remediation_log
            WHERE alert_name = $1
              AND alert_instance = $2
            ORDER BY timestamp DESC
            LIMIT $3
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, alert_name, alert_instance, limit)

        attempts = [dict(row) for row in rows]

        self.logger.info(
            "recent_attempts_retrieved",
            alert_name=alert_name,
            alert_instance=alert_instance,
            count=len(attempts)
        )

        return attempts

    async def clear_attempts(self, alert_name: str, alert_instance: str) -> int:
        """
        Clear (delete) remediation attempts for a specific alert.

        Called when alert resolves to reset the counter.

        Args:
            alert_name: Alert name
            alert_instance: Alert instance

        Returns:
            Number of deleted records
        """
        query = """
            DELETE FROM remediation_log
            WHERE alert_name = $1
              AND alert_instance = $2
              AND timestamp > NOW() - INTERVAL '24 hours'
        """

        async with self.pool.acquire() as conn:
            result = await conn.execute(query, alert_name, alert_instance)

        # Extract count from result string like "DELETE 5"
        count = int(result.split()[-1]) if result and result.split() else 0

        self.logger.info(
            "attempts_cleared",
            alert_name=alert_name,
            alert_instance=alert_instance,
            count=count
        )

        return count

    async def is_maintenance_mode(self) -> bool:
        """
        Check if system is currently in maintenance mode.

        Returns:
            True if in maintenance mode, False otherwise
        """
        query = """
            SELECT COUNT(*) > 0
            FROM maintenance_windows
            WHERE is_active = TRUE
              AND ended_at IS NULL
        """

        async with self.pool.acquire() as conn:
            in_maintenance = await conn.fetchval(query)

        if in_maintenance:
            self.logger.info("maintenance_mode_active")

        return in_maintenance

    async def get_active_maintenance_window(self, host: str = None) -> Optional[Dict[str, Any]]:
        """
        Get active maintenance window for a specific host or global maintenance.

        Args:
            host: Host name to check (nexus, homeassistant, outpost)
                  If None, only checks for global maintenance windows

        Returns:
            Maintenance window dict if active, None otherwise
        """
        query = """
            SELECT id, host, started_at, reason, suppressed_alert_count
            FROM maintenance_windows
            WHERE is_active = TRUE
              AND ended_at IS NULL
              AND (host = $1 OR host IS NULL)
            ORDER BY host NULLS FIRST
            LIMIT 1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, host)

        return dict(row) if row else None

    async def increment_maintenance_suppression_count(self, window_id: int):
        """
        Increment the suppressed alert counter for a maintenance window.

        Args:
            window_id: ID of the maintenance window
        """
        query = """
            UPDATE maintenance_windows
            SET suppressed_alert_count = suppressed_alert_count + 1
            WHERE id = $1
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, window_id)

    async def create_maintenance_window(self, window: MaintenanceWindow) -> int:
        """
        Create a maintenance window.

        Args:
            window: MaintenanceWindow instance

        Returns:
            ID of the created window
        """
        query = """
            INSERT INTO maintenance_windows (start_time, end_time, reason, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            window_id = await conn.fetchval(
                query,
                window.start_time,
                window.end_time,
                window.reason,
                window.created_by
            )

        self.logger.info(
            "maintenance_window_created",
            window_id=window_id,
            end_time=window.end_time.isoformat(),
            created_by=window.created_by
        )

        return window_id

    async def get_command_whitelist(self) -> List[Dict[str, Any]]:
        """
        Get all enabled command whitelist patterns from database.

        Returns:
            List of whitelist pattern dictionaries
        """
        query = """
            SELECT pattern, description, risk_level
            FROM command_whitelist
            WHERE enabled = TRUE
            ORDER BY risk_level, pattern
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)

        patterns = [dict(row) for row in rows]

        self.logger.info("whitelist_patterns_retrieved", count=len(patterns))

        return patterns

    async def get_statistics(self, days: int = 7) -> Dict[str, Any]:
        """
        Get remediation statistics for monitoring.

        Args:
            days: Number of days to look back

        Returns:
            Dictionary with statistics
        """
        query = """
            SELECT
                COUNT(*) as total_attempts,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN escalated THEN 1 ELSE 0 END) as escalated,
                AVG(execution_duration_seconds) as avg_duration,
                COUNT(DISTINCT alert_name) as unique_alerts
            FROM remediation_log
            WHERE timestamp > NOW() - INTERVAL '1 day' * $1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, days)

        stats = dict(row)
        stats['success_rate'] = (
            (stats['successful'] / stats['total_attempts'] * 100)
            if stats['total_attempts'] > 0 else 0
        )

        self.logger.info("statistics_retrieved", days=days, **stats)

        return stats


# Global database instance
db = Database()
