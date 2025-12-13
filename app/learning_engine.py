"""
Machine Learning Engine for Alert Remediation

Learns patterns from successful remediations and applies them automatically
to reduce AI API usage and improve response times.
"""

import structlog
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from .database import Database
from .models import RemediationAttempt, RiskLevel

logger = structlog.get_logger()


class LearningEngine:
    """
    Manages learned remediation patterns and provides intelligent matching.

    Learns from successful remediations to build a knowledge base that can:
    - Match incoming alerts to known patterns
    - Suggest remediation commands without AI calls
    - Track pattern confidence and success rates
    - Continuously improve through feedback
    """

    # Configuration
    HIGH_CONFIDENCE_THRESHOLD = 0.75  # Skip Claude if confidence >= 75%
    MEDIUM_CONFIDENCE_THRESHOLD = 0.50  # Pass to Claude as context if >= 50%
    MIN_SUCCESS_COUNT = 2  # Minimum successes before trusting pattern
    LEARNING_RATE = 0.1  # Bayesian update rate

    def __init__(self, db: Database):
        self.db = db
        self.logger = logger.bind(component="learning_engine")
        # In-memory cache of patterns (refreshed periodically)
        self._pattern_cache: List[Dict[str, Any]] = []
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)

    async def extract_pattern(
        self,
        attempt: RemediationAttempt,
        alert_labels: Dict[str, str]
    ) -> Optional[int]:
        """
        Extract a remediation pattern from a successful attempt.

        Creates or updates a pattern in the database based on the successful
        remediation. Uses intelligent fingerprinting to group similar issues.

        Args:
            attempt: Successful remediation attempt
            alert_labels: Alert labels for categorization

        Returns:
            Pattern ID if created/updated, None on failure
        """
        if not attempt.success:
            self.logger.warning(
                "skip_pattern_extraction",
                reason="attempt_not_successful"
            )
            return None

        # Build symptom fingerprint from alert labels
        symptom_fingerprint = self._build_symptom_fingerprint(
            attempt.alert_name,
            alert_labels
        )

        # Determine alert category
        category = self._categorize_alert(attempt.alert_name)

        # Extract root cause from AI analysis
        root_cause = self._extract_root_cause(attempt.ai_analysis)

        self.logger.info(
            "extracting_pattern",
            alert_name=attempt.alert_name,
            category=category,
            symptom=symptom_fingerprint[:100]
        )

        # Check if pattern exists
        existing_pattern = await self._find_existing_pattern(
            attempt.alert_name,
            symptom_fingerprint
        )

        if existing_pattern:
            # Update existing pattern
            pattern_id = await self._update_pattern(
                existing_pattern['id'],
                attempt.commands_executed,
                success=True
            )
            self.logger.info(
                "pattern_updated",
                pattern_id=pattern_id,
                new_success_count=existing_pattern['success_count'] + 1
            )
        else:
            # Create new pattern
            pattern_id = await self._create_pattern(
                alert_name=attempt.alert_name,
                category=category,
                symptom_fingerprint=symptom_fingerprint,
                root_cause=root_cause,
                solution_commands=attempt.commands_executed,
                risk_level=attempt.risk_level
            )
            self.logger.info(
                "pattern_created",
                pattern_id=pattern_id,
                alert_name=attempt.alert_name
            )

        # Invalidate cache
        self._cache_timestamp = None

        return pattern_id

    async def find_similar_patterns(
        self,
        alert_name: str,
        alert_labels: Dict[str, str],
        min_confidence: float = 0.50
    ) -> List[Dict[str, Any]]:
        """
        Find patterns similar to the incoming alert.

        Uses symptom fingerprinting and confidence scoring to match
        alerts to known remediation patterns. For alerts with 'system'
        or 'remediation_host' labels, prioritizes patterns with matching
        target_host.

        Args:
            alert_name: Name of the alert
            alert_labels: Alert labels for fingerprinting
            min_confidence: Minimum confidence threshold (default 50%)

        Returns:
            List of matching patterns, ordered by confidence (highest first)
        """
        # Build fingerprint for incoming alert
        symptom_fingerprint = self._build_symptom_fingerprint(
            alert_name,
            alert_labels
        )

        # Extract target system from labels (for BackupStale, etc.)
        alert_target_system = (
            alert_labels.get('system') or
            alert_labels.get('remediation_host') or
            None
        )

        self.logger.info(
            "searching_patterns",
            alert_name=alert_name,
            symptom_fingerprint=symptom_fingerprint[:100],
            alert_target_system=alert_target_system
        )

        # Refresh cache if needed
        await self._refresh_pattern_cache()

        # Find matching patterns
        matches = []
        for pattern in self._pattern_cache:
            # Exact alert name match
            if pattern['alert_name'] != alert_name:
                continue

            # Check minimum success count
            if pattern['success_count'] < self.MIN_SUCCESS_COUNT:
                continue

            # Check confidence threshold
            if pattern['confidence_score'] < min_confidence:
                continue

            # CRITICAL: Check target_host matching for system-specific patterns
            pattern_target = pattern.get('target_host')
            if alert_target_system and pattern_target:
                # Both have target info - must match
                if pattern_target.lower() != alert_target_system.lower():
                    self.logger.debug(
                        "pattern_target_mismatch",
                        pattern_id=pattern['id'],
                        pattern_target=pattern_target,
                        alert_target=alert_target_system
                    )
                    continue
            elif alert_target_system and not pattern_target:
                # Alert has system info but pattern doesn't - skip generic patterns
                # when we have specific ones
                self.logger.debug(
                    "skipping_generic_pattern",
                    pattern_id=pattern['id'],
                    reason="alert has system label but pattern has no target_host"
                )
                continue

            # Calculate similarity score
            similarity = self._calculate_similarity(
                symptom_fingerprint,
                pattern['symptom_fingerprint']
            )

            # For patterns with matching target_host, boost similarity
            target_match_boost = 0.0
            if alert_target_system and pattern_target:
                if pattern_target.lower() == alert_target_system.lower():
                    target_match_boost = 0.1
                    self.logger.debug(
                        "target_host_match_boost",
                        pattern_id=pattern['id'],
                        target=pattern_target
                    )

            effective_similarity = min(1.0, similarity + target_match_boost)

            if effective_similarity >= 0.7:  # 70% similarity threshold
                matches.append({
                    **pattern,
                    'similarity_score': effective_similarity,
                    'effective_confidence': pattern['confidence_score'] * effective_similarity
                })

        # Sort by effective confidence (pattern confidence * similarity)
        matches.sort(key=lambda x: x['effective_confidence'], reverse=True)

        self.logger.info(
            "patterns_found",
            alert_name=alert_name,
            match_count=len(matches),
            top_confidence=matches[0]['effective_confidence'] if matches else 0,
            top_pattern_id=matches[0]['id'] if matches else None
        )

        return matches

    async def should_use_pattern(
        self,
        alert_name: str,
        alert_labels: Dict[str, str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Determine if we should use a learned pattern instead of Claude.

        Args:
            alert_name: Name of the alert
            alert_labels: Alert labels

        Returns:
            Tuple of (should_use_pattern, pattern_dict or None)
            - (True, pattern) if confidence >= 75% - use pattern directly
            - (False, pattern) if confidence 50-75% - pass to Claude as context
            - (False, None) if no good match - use Claude without context
        """
        patterns = await self.find_similar_patterns(
            alert_name,
            alert_labels,
            min_confidence=self.MEDIUM_CONFIDENCE_THRESHOLD
        )

        if not patterns:
            return False, None

        best_pattern = patterns[0]
        confidence = best_pattern['effective_confidence']

        if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            self.logger.info(
                "using_learned_pattern",
                pattern_id=best_pattern['id'],
                confidence=confidence,
                alert_name=alert_name
            )
            return True, best_pattern
        elif confidence >= self.MEDIUM_CONFIDENCE_THRESHOLD:
            self.logger.info(
                "pattern_as_context",
                pattern_id=best_pattern['id'],
                confidence=confidence,
                alert_name=alert_name
            )
            return False, best_pattern
        else:
            return False, None

    async def record_outcome(
        self,
        pattern_id: int,
        success: bool,
        execution_time: int
    ):
        """
        Record the outcome of using a learned pattern.

        Updates pattern statistics using Bayesian confidence scoring.

        Args:
            pattern_id: ID of the pattern used
            success: Whether remediation succeeded
            execution_time: Time taken in seconds
        """
        query = """
            UPDATE remediation_patterns
            SET
                success_count = success_count + CASE WHEN $2 THEN 1 ELSE 0 END,
                failure_count = failure_count + CASE WHEN NOT $2 THEN 1 ELSE 0 END,
                confidence_score = (
                    success_count::float + CASE WHEN $2 THEN 1 ELSE 0 END
                ) / (
                    success_count + failure_count + 1
                ),
                avg_execution_time = (
                    COALESCE(avg_execution_time, 0) * usage_count + $3
                ) / (usage_count + 1),
                usage_count = usage_count + 1,
                last_used_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
            RETURNING confidence_score
        """

        async with self.db.pool.acquire() as conn:
            new_confidence = await conn.fetchval(
                query,
                pattern_id,
                success,
                execution_time
            )

        self.logger.info(
            "pattern_outcome_recorded",
            pattern_id=pattern_id,
            success=success,
            new_confidence=new_confidence
        )

        # Invalidate cache
        self._cache_timestamp = None

    def _build_symptom_fingerprint(
        self,
        alert_name: str,
        labels: Dict[str, str]
    ) -> str:
        """
        Build a fingerprint string from alert characteristics.

        This helps group similar alerts together even if they have
        different instances or minor label variations.

        IMPORTANT: For BackupStale alerts, the 'system' label indicates which
        backup is stale (service-host, management-host, ha-host, vps-host) - this is
        critical for pattern matching.
        """
        # Priority labels for fingerprinting (checked first)
        # 'system' is critical for BackupStale alerts
        priority_labels = [
            'system',           # Which system's backup is stale
            'remediation_host', # Where to run the fix
            'category',         # Alert category (backup, container, etc)
        ]

        # Standard labels that indicate symptom type
        standard_labels = [
            'alertname',
            'job',
            'severity',
            'container',
            'service',
            'host',
            'device',
            'filesystem'
        ]

        parts = [alert_name]

        # First, add priority labels (most important for pattern matching)
        for label in priority_labels:
            if label in labels:
                value = labels[label]
                parts.append(f'{label}:{value}')

        # Then add standard labels
        for label in standard_labels:
            if label in labels:
                value = labels[label]
                # Normalize instance-specific values
                if label in ['instance', 'host']:
                    # Extract host type (service-host, ha-host, etc) - hostname-based for portability
                    if 'service-host' in value.lower():
                        parts.append('host:service-host')
                    elif 'ha-host' in value.lower() or 'ha' in value.lower():
                        parts.append('host:ha-host')
                    elif 'vps-host' in value.lower() or 'vps' in value.lower():
                        parts.append('host:vps-host')
                    elif 'management-host' in value.lower():
                        parts.append('host:management-host')
                    else:
                        parts.append(f'{label}:generic')
                else:
                    parts.append(f'{label}:{value}')

        return '|'.join(parts)

    def _categorize_alert(self, alert_name: str) -> str:
        """Categorize alert into broad categories."""
        alert_lower = alert_name.lower()

        if 'container' in alert_lower or 'docker' in alert_lower:
            return 'containers'
        elif 'disk' in alert_lower or 'filesystem' in alert_lower:
            return 'storage'
        elif 'cpu' in alert_lower or 'memory' in alert_lower:
            return 'resources'
        elif 'network' in alert_lower or 'vpn' in alert_lower:
            return 'network'
        elif 'database' in alert_lower or 'postgres' in alert_lower or 'mysql' in alert_lower:
            return 'database'
        elif 'ssl' in alert_lower or 'cert' in alert_lower:
            return 'security'
        else:
            return 'system'

    def _extract_root_cause(self, ai_analysis: Optional[str]) -> Optional[str]:
        """Extract root cause summary from AI analysis."""
        if not ai_analysis:
            return None

        # Simple extraction - first sentence or up to 200 chars
        lines = ai_analysis.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) > 20:  # Skip very short lines
                # Extract first sentence
                if '.' in line:
                    return line.split('.')[0] + '.'
                else:
                    return line[:200]

        return ai_analysis[:200]

    async def _find_existing_pattern(
        self,
        alert_name: str,
        symptom_fingerprint: str
    ) -> Optional[Dict[str, Any]]:
        """Find existing pattern with same fingerprint."""
        query = """
            SELECT id, success_count, failure_count, confidence_score
            FROM remediation_patterns
            WHERE alert_name = $1
              AND symptom_fingerprint = $2
            LIMIT 1
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query, alert_name, symptom_fingerprint)

        return dict(row) if row else None

    async def _create_pattern(
        self,
        alert_name: str,
        category: str,
        symptom_fingerprint: str,
        root_cause: Optional[str],
        solution_commands: List[str],
        risk_level: Optional[RiskLevel]
    ) -> int:
        """Create a new remediation pattern."""
        query = """
            INSERT INTO remediation_patterns (
                alert_name,
                alert_category,
                symptom_fingerprint,
                root_cause,
                solution_commands,
                risk_level
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """

        async with self.db.pool.acquire() as conn:
            pattern_id = await conn.fetchval(
                query,
                alert_name,
                category,
                symptom_fingerprint,
                root_cause,
                solution_commands,
                risk_level.value if risk_level else 'MEDIUM'
            )

        return pattern_id

    async def _update_pattern(
        self,
        pattern_id: int,
        commands: List[str],
        success: bool
    ) -> int:
        """Update an existing pattern with new outcome."""
        query = """
            UPDATE remediation_patterns
            SET
                success_count = success_count + CASE WHEN $3 THEN 1 ELSE 0 END,
                failure_count = failure_count + CASE WHEN NOT $3 THEN 1 ELSE 0 END,
                confidence_score = (
                    success_count::float + CASE WHEN $3 THEN 1 ELSE 0 END
                ) / (
                    success_count + failure_count + 1
                ),
                solution_commands = $2,
                usage_count = usage_count + 1,
                last_used_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
            RETURNING id
        """

        async with self.db.pool.acquire() as conn:
            return await conn.fetchval(query, pattern_id, commands, success)

    def _calculate_similarity(self, fingerprint1: str, fingerprint2: str) -> float:
        """
        Calculate similarity between two symptom fingerprints.

        Uses a weighted approach:
        1. If pattern fingerprint is subset of alert fingerprint, high match
        2. Critical labels (system, container) must match for high confidence
        3. Jaccard similarity for general matching

        Args:
            fingerprint1: Incoming alert fingerprint
            fingerprint2: Stored pattern fingerprint
        """
        parts1 = set(fingerprint1.split('|'))
        parts2 = set(fingerprint2.split('|'))

        if not parts1 or not parts2:
            return 0.0

        intersection = parts1 & parts2
        intersection_count = len(intersection)

        # Critical labels that MUST match for high confidence
        critical_labels = ['system:', 'container:', 'remediation_host:']

        # Check if all critical labels in pattern match
        pattern_critical = [p for p in parts2 if any(p.startswith(c) for c in critical_labels)]
        alert_critical = [p for p in parts1 if any(p.startswith(c) for c in critical_labels)]

        # If pattern has critical labels, they must all be in alert
        if pattern_critical:
            if not all(pc in parts1 for pc in pattern_critical):
                # Critical label mismatch - low similarity
                return 0.3

        # If pattern is a subset of alert (all pattern parts match), high score
        if parts2.issubset(parts1):
            # Pattern fully matches - scale by how specific the pattern is
            return min(0.95, 0.7 + (len(parts2) / 10))

        # Standard Jaccard similarity
        union_count = len(parts1 | parts2)
        jaccard = intersection_count / union_count if union_count > 0 else 0.0

        # Boost score if critical labels match
        critical_match_boost = 0.0
        if pattern_critical and all(pc in parts1 for pc in pattern_critical):
            critical_match_boost = 0.15

        return min(1.0, jaccard + critical_match_boost)

    async def _refresh_pattern_cache(self):
        """Refresh the in-memory pattern cache if needed."""
        now = datetime.utcnow()

        if (self._cache_timestamp is None or
            now - self._cache_timestamp > self._cache_ttl):

            query = """
                SELECT
                    id,
                    alert_name,
                    alert_category,
                    symptom_fingerprint,
                    root_cause,
                    solution_commands,
                    success_count,
                    failure_count,
                    confidence_score,
                    risk_level,
                    usage_count,
                    avg_execution_time,
                    last_used_at,
                    target_host
                FROM remediation_patterns
                WHERE enabled = TRUE
                ORDER BY confidence_score DESC, usage_count DESC
            """

            async with self.db.pool.acquire() as conn:
                rows = await conn.fetch(query)

            self._pattern_cache = [dict(row) for row in rows]
            self._cache_timestamp = now

            self.logger.info(
                "pattern_cache_refreshed",
                pattern_count=len(self._pattern_cache)
            )

    async def get_pattern_stats(self) -> Dict[str, Any]:
        """Get learning engine statistics."""
        query = """
            SELECT
                COUNT(*) as total_patterns,
                COUNT(*) FILTER (WHERE confidence_score >= 0.75) as high_confidence,
                COUNT(*) FILTER (WHERE confidence_score >= 0.50 AND confidence_score < 0.75) as medium_confidence,
                AVG(confidence_score) as avg_confidence,
                SUM(usage_count) as total_usage,
                SUM(success_count) as total_successes,
                SUM(failure_count) as total_failures
            FROM remediation_patterns
            WHERE enabled = TRUE
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query)

        stats = dict(row)

        # Calculate API savings estimate
        if stats['total_usage'] and stats['high_confidence']:
            # Estimate: high confidence patterns would have called Claude
            stats['estimated_api_calls_saved'] = stats['high_confidence'] * (
                stats['total_usage'] / stats['total_patterns'] if stats['total_patterns'] else 0
            )
        else:
            stats['estimated_api_calls_saved'] = 0

        return stats

    # =========================================================================
    # Phase 1: Failure Pattern Learning
    # =========================================================================

    def _generate_failure_signature(
        self,
        alert_name: str,
        commands: List[str]
    ) -> str:
        """Generate a unique signature for a failed remediation pattern."""
        import hashlib
        # Sort commands for consistent hashing
        sorted_cmds = sorted(commands) if commands else []
        content = f"{alert_name}|{'|'.join(sorted_cmds)}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def record_failure_pattern(
        self,
        alert_name: str,
        alert_instance: str,
        commands_attempted: List[str],
        failure_reason: str,
        symptom_fingerprint: Optional[str] = None
    ) -> None:
        """
        Record a failed remediation pattern to avoid in future.

        This helps Jarvis learn what NOT to do.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance that failed
            commands_attempted: Commands that were tried
            failure_reason: Why the remediation failed
            symptom_fingerprint: Optional symptom fingerprint
        """
        pattern_signature = self._generate_failure_signature(alert_name, commands_attempted)

        query = """
            INSERT INTO remediation_failures (
                alert_name,
                alert_instance,
                pattern_signature,
                symptom_fingerprint,
                commands_attempted,
                failure_reason,
                failure_count,
                last_failed_at
            ) VALUES ($1, $2, $3, $4, $5, $6, 1, NOW())
            ON CONFLICT (pattern_signature) DO UPDATE SET
                failure_count = remediation_failures.failure_count + 1,
                last_failed_at = NOW(),
                failure_reason = EXCLUDED.failure_reason
        """

        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    query,
                    alert_name,
                    alert_instance,
                    pattern_signature,
                    symptom_fingerprint,
                    commands_attempted,
                    failure_reason
                )

            self.logger.info(
                "failure_pattern_recorded",
                alert_name=alert_name,
                signature=pattern_signature[:16],
                commands_count=len(commands_attempted)
            )
        except Exception as e:
            self.logger.error(
                "failure_pattern_record_failed",
                alert_name=alert_name,
                error=str(e)
            )

    async def get_failed_patterns(
        self,
        alert_name: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get patterns that have failed for this alert type.

        Args:
            alert_name: Alert name to look up
            limit: Maximum patterns to return

        Returns:
            List of failed pattern records
        """
        query = """
            SELECT
                pattern_signature,
                commands_attempted,
                failure_reason,
                failure_count,
                last_failed_at
            FROM remediation_failures
            WHERE alert_name = $1
            ORDER BY failure_count DESC, last_failed_at DESC
            LIMIT $2
        """

        async with self.db.pool.acquire() as conn:
            rows = await conn.fetch(query, alert_name, limit)

        return [dict(row) for row in rows]

    async def should_avoid_commands(
        self,
        alert_name: str,
        commands: List[str],
        min_failures: int = 2
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a set of commands should be avoided for an alert.

        Args:
            alert_name: Alert name
            commands: Commands to check
            min_failures: Minimum failure count to trigger avoidance

        Returns:
            Tuple of (should_avoid, reason)
        """
        signature = self._generate_failure_signature(alert_name, commands)

        query = """
            SELECT failure_count, failure_reason, last_failed_at
            FROM remediation_failures
            WHERE pattern_signature = $1
              AND failure_count >= $2
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query, signature, min_failures)

        if row:
            return True, f"Pattern failed {row['failure_count']} times: {row['failure_reason']}"

        return False, None

    async def get_failure_stats(self) -> Dict[str, Any]:
        """Get failure pattern statistics."""
        query = """
            SELECT
                COUNT(*) as total_failure_patterns,
                SUM(failure_count) as total_failures_recorded,
                COUNT(*) FILTER (WHERE failure_count >= 3) as chronic_failures,
                MAX(last_failed_at) as most_recent_failure
            FROM remediation_failures
        """

        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(query)

        return dict(row) if row else {}
