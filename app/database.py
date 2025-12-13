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

    HIGH-012 FIX: Now explicitly logs and raises on final failure for clarity.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        # HIGH-012 FIX: Explicitly log final failure before raising
                        logger.error(
                            "retry_exhausted",
                            function=func.__name__,
                            total_attempts=max_retries,
                            final_error=str(e),
                            error_type=type(e).__name__
                        )
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

            # HIGH-012 FIX: Explicit failure case - should never reach here but safety net
            if last_exception:
                raise last_exception
            raise RuntimeError(f"Retry loop completed without success or exception for {func.__name__}")

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

        CRITICAL-001 FIX: Clean up any existing pool before retry to prevent connection leaks.
        """
        # Clean up any existing pool from failed attempts
        if self.pool is not None:
            try:
                await self.pool.close()
                self.logger.debug("cleaned_up_stale_pool_before_retry")
            except Exception:
                pass  # Ignore cleanup errors, we're about to create a new pool
            self.pool = None

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

        Only counts actual remediation attempts, NOT escalation-only records.
        This prevents the "escalation snowball" where each escalation increments
        the counter, causing infinite escalations.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance identifier
            window_hours: Time window in hours

        Returns:
            Number of attempts (excluding escalation-only records)
        """
        # v3.1.0: Exclude escalation-only records from attempt count
        # An escalation-only record has escalated=TRUE and no commands executed
        # HIGH-005 FIX: Use COALESCE for array_length to properly handle NULL arrays and empty arrays
        query = """
            SELECT COUNT(*)
            FROM remediation_log
            WHERE alert_name = $1
              AND alert_instance = $2
              AND timestamp > NOW() - INTERVAL '1 hour' * $3
              AND NOT (escalated = TRUE AND COALESCE(array_length(commands_executed, 1), 0) = 0)
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
            host: Host name to check (service-host, ha-host, vps-host)
                  If None, only checks for global maintenance windows

        Returns:
            Maintenance window dict if active, None otherwise
        """
        # MEDIUM-005 FIX: Normalize host to lowercase for case-insensitive matching
        normalized_host = host.lower() if host else None

        query = """
            SELECT id, host, started_at, reason, suppressed_alert_count
            FROM maintenance_windows
            WHERE is_active = TRUE
              AND ended_at IS NULL
              AND (LOWER(host) = $1 OR host IS NULL)
            ORDER BY host NULLS FIRST
            LIMIT 1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, normalized_host)

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

    # =========================================================================
    # Escalation Cooldown Functions (v3.1.0)
    # =========================================================================

    async def set_escalation_cooldown(
        self,
        alert_name: str,
        alert_instance: str
    ) -> None:
        """
        Record that an alert was escalated, starting its cooldown period.

        Uses UPSERT to update existing cooldown or create new one.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance identifier
        """
        query = """
            INSERT INTO escalation_cooldowns (alert_name, alert_instance, escalated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (alert_name, alert_instance)
            DO UPDATE SET escalated_at = NOW()
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, alert_name, alert_instance)

            self.logger.info(
                "escalation_cooldown_set",
                alert_name=alert_name,
                alert_instance=alert_instance
            )
        except Exception as e:
            self.logger.warning(
                "escalation_cooldown_set_failed",
                alert_name=alert_name,
                alert_instance=alert_instance,
                error=str(e)
            )

    async def check_escalation_cooldown(
        self,
        alert_name: str,
        alert_instance: str,
        cooldown_hours: int = 4
    ) -> tuple[bool, Optional[datetime]]:
        """
        Check if an alert is in escalation cooldown.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance identifier
            cooldown_hours: Hours to wait before re-escalating

        Returns:
            Tuple of (in_cooldown: bool, escalated_at: Optional[datetime])
        """
        query = """
            SELECT escalated_at
            FROM escalation_cooldowns
            WHERE alert_name = $1
              AND alert_instance = $2
              AND escalated_at > NOW() - INTERVAL '1 hour' * $3
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, alert_name, alert_instance, cooldown_hours)

        if row:
            self.logger.info(
                "escalation_cooldown_active",
                alert_name=alert_name,
                alert_instance=alert_instance,
                escalated_at=row['escalated_at'].isoformat()
            )
            return True, row['escalated_at']

        return False, None

    async def clear_escalation_cooldown(
        self,
        alert_name: str,
        alert_instance: str
    ) -> bool:
        """
        Clear escalation cooldown when an alert resolves.

        This allows fresh escalation if the alert fires again.

        CRITICAL-004 FIX: Added explicit error handling and logging to ensure
        database failures don't silently block future escalations.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance identifier

        Returns:
            True if a cooldown was cleared, False if none existed

        Raises:
            Exception: Re-raises database errors after logging
        """
        query = """
            DELETE FROM escalation_cooldowns
            WHERE alert_name = $1
              AND alert_instance = $2
            RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, alert_name, alert_instance)

            if result:
                self.logger.info(
                    "escalation_cooldown_cleared",
                    alert_name=alert_name,
                    alert_instance=alert_instance
                )
                return True
            else:
                self.logger.debug(
                    "escalation_cooldown_not_found",
                    alert_name=alert_name,
                    alert_instance=alert_instance
                )
                return False

        except Exception as e:
            self.logger.error(
                "escalation_cooldown_clear_failed",
                alert_name=alert_name,
                alert_instance=alert_instance,
                error=str(e)
            )
            raise  # Re-raise so caller knows it failed

    # =========================================================================
    # Fingerprint Deduplication Functions (v3.1.0)
    # =========================================================================

    async def check_and_set_fingerprint_atomic(
        self,
        fingerprint: str,
        alert_name: str,
        alert_instance: str,
        cooldown_seconds: int = 300
    ) -> tuple[bool, Optional[datetime]]:
        """
        Atomically check if fingerprint is in cooldown and set it if not.

        CRITICAL-002 FIX: This uses a single atomic operation to prevent race conditions
        where two identical alerts could both pass the cooldown check simultaneously.

        The query:
        1. Tries to INSERT the fingerprint
        2. ON CONFLICT (fingerprint already exists):
           - If processed_at is within cooldown window, don't update (keep old timestamp)
           - If processed_at is older than cooldown, update to NOW()
        3. Returns whether this was a NEW processing (not a cooldown hit)

        Args:
            fingerprint: Alert fingerprint hash
            alert_name: Name of the alert
            alert_instance: Instance identifier
            cooldown_seconds: Seconds to wait before reprocessing

        Returns:
            Tuple of (in_cooldown: bool, processed_at: Optional[datetime])
            - (True, timestamp) if in cooldown - should skip processing
            - (False, None) if not in cooldown - proceed with processing
        """
        # First, try to INSERT. If conflict, check if in cooldown.
        # This two-step approach is clearer and more reliable than complex UPSERT logic.
        check_query = """
            SELECT processed_at
            FROM alert_processing_cache
            WHERE fingerprint = $1
              AND processed_at > NOW() - INTERVAL '1 second' * $2
        """

        insert_query = """
            INSERT INTO alert_processing_cache (fingerprint, alert_name, alert_instance, processed_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (fingerprint) DO UPDATE
            SET processed_at = NOW(),
                alert_name = EXCLUDED.alert_name,
                alert_instance = EXCLUDED.alert_instance
            WHERE alert_processing_cache.processed_at <= NOW() - INTERVAL '1 second' * $4
            RETURNING processed_at
        """

        try:
            async with self.pool.acquire() as conn:
                # Check if fingerprint exists and is in cooldown
                existing = await conn.fetchrow(check_query, fingerprint, cooldown_seconds)

                if existing:
                    # Fingerprint exists and is within cooldown window
                    self.logger.debug(
                        "fingerprint_cooldown_active_atomic",
                        fingerprint=fingerprint[:16] + "...",
                        processed_at=existing['processed_at'].isoformat()
                    )
                    return True, existing['processed_at']

                # Either doesn't exist or cooldown expired - insert/update
                await conn.execute(insert_query, fingerprint, alert_name, alert_instance, cooldown_seconds)

            return False, None

        except Exception as e:
            self.logger.warning(
                "fingerprint_atomic_check_failed",
                fingerprint=fingerprint[:16] + "...",
                error=str(e)
            )
            # On error, allow processing (fail open to avoid blocking alerts)
            return False, None

    async def check_fingerprint_cooldown(
        self,
        fingerprint: str,
        cooldown_seconds: int = 300
    ) -> tuple[bool, Optional[datetime]]:
        """
        Check if an alert fingerprint was recently processed.

        DEPRECATED: Use check_and_set_fingerprint_atomic() instead for race-safe operations.
        This method is kept for backward compatibility.

        Args:
            fingerprint: Alert fingerprint hash
            cooldown_seconds: Seconds to wait before reprocessing

        Returns:
            Tuple of (in_cooldown: bool, processed_at: Optional[datetime])
        """
        query = """
            SELECT processed_at
            FROM alert_processing_cache
            WHERE fingerprint = $1
              AND processed_at > NOW() - INTERVAL '1 second' * $2
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, fingerprint, cooldown_seconds)

        if row:
            self.logger.debug(
                "fingerprint_cooldown_active",
                fingerprint=fingerprint[:16] + "...",
                processed_at=row['processed_at'].isoformat()
            )
            return True, row['processed_at']

        return False, None

    async def set_fingerprint_processed(
        self,
        fingerprint: str,
        alert_name: str,
        alert_instance: str
    ) -> None:
        """
        Record that an alert fingerprint was processed.

        DEPRECATED: Use check_and_set_fingerprint_atomic() instead for race-safe operations.
        This method is kept for backward compatibility.

        Args:
            fingerprint: Alert fingerprint hash
            alert_name: Name of the alert
            alert_instance: Instance identifier
        """
        query = """
            INSERT INTO alert_processing_cache (fingerprint, alert_name, alert_instance, processed_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (fingerprint)
            DO UPDATE SET processed_at = NOW(), alert_name = $2, alert_instance = $3
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, fingerprint, alert_name, alert_instance)
        except Exception as e:
            self.logger.warning(
                "fingerprint_cache_update_failed",
                fingerprint=fingerprint[:16] + "...",
                error=str(e)
            )

    async def cleanup_fingerprint_cache(self, max_age_hours: int = 24) -> int:
        """
        Clean up old entries from the fingerprint cache.

        Should be called periodically to prevent table bloat.

        Args:
            max_age_hours: Delete entries older than this

        Returns:
            Number of entries deleted
        """
        query = """
            DELETE FROM alert_processing_cache
            WHERE processed_at < NOW() - INTERVAL '1 hour' * $1
        """

        async with self.pool.acquire() as conn:
            result = await conn.execute(query, max_age_hours)

        count = int(result.split()[-1]) if result and result.split() else 0

        if count > 0:
            self.logger.info(
                "fingerprint_cache_cleaned",
                deleted_count=count,
                max_age_hours=max_age_hours
            )

        return count


# Global database instance
db = Database()
