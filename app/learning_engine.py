"""
Machine Learning Engine for Alert Remediation

Learns patterns from successful remediations and applies them automatically
to reduce AI API usage and improve response times.

v3.0 ENHANCEMENTS:
- Stores investigation chains (not just fix commands)
- Tracks source vs instance host mismatches
- Learns which hosts to check for specific alert types
- Skynet host support
"""

import json
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
        alert_labels: Dict[str, str],
        investigation_chain: Optional[List[Dict]] = None,
        actual_remediation_host: Optional[str] = None,
        instance_was_misleading: bool = False
    ) -> Optional[int]:
        """
        Extract a remediation pattern from a successful attempt.

        Creates or updates a pattern in the database based on the successful
        remediation. Uses intelligent fingerprinting to group similar issues.

        v3.0: Now stores investigation chains and tracks host mismatches.
        CRITICAL-005 FIX: Added input validation and proper error handling.

        Args:
            attempt: Successful remediation attempt
            alert_labels: Alert labels for categorization
            investigation_chain: v3.0 - Steps taken to investigate
            actual_remediation_host: v3.0 - Where fix was actually applied (may differ from instance)
            instance_was_misleading: v3.0 - True if instance label didn't match remediation host

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

        # CRITICAL-005 FIX: Truncate fingerprint if too long
        max_fingerprint_len = 5000
        if len(symptom_fingerprint) > max_fingerprint_len:
            symptom_fingerprint = symptom_fingerprint[:max_fingerprint_len]
            self.logger.warning(
                "symptom_fingerprint_truncated",
                original_length=len(symptom_fingerprint),
                max_length=max_fingerprint_len
            )

        # Determine alert category
        category = self._categorize_alert(attempt.alert_name)

        # Extract root cause from AI analysis
        root_cause = self._extract_root_cause(attempt.ai_analysis)

        # v3.0: Build enhanced metadata
        metadata = {
            "investigation_chain": investigation_chain or [],
            "actual_remediation_host": actual_remediation_host,
            "instance_label_misleading": instance_was_misleading,
            "alert_instance": attempt.alert_instance,
        }

        # CRITICAL-005 FIX: Validate metadata is JSON serializable
        try:
            import json
            json.dumps(metadata)
        except (TypeError, ValueError) as e:
            self.logger.error(
                "metadata_not_json_serializable",
                error=str(e),
                alert_name=attempt.alert_name
            )
            # Use minimal metadata instead of failing completely
            metadata = {
                "alert_instance": attempt.alert_instance,
                "serialization_error": str(e)
            }

        self.logger.info(
            "extracting_pattern",
            alert_name=attempt.alert_name,
            category=category,
            symptom=symptom_fingerprint[:100],
            investigation_steps=len(investigation_chain) if investigation_chain else 0,
            instance_misleading=instance_was_misleading
        )

        try:
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
                    success=True,
                    metadata=metadata
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
                    risk_level=attempt.risk_level,
                    metadata=metadata
                )
                self.logger.info(
                    "pattern_created",
                    pattern_id=pattern_id,
                    alert_name=attempt.alert_name,
                    has_investigation_chain=bool(investigation_chain)
                )

            # Invalidate cache
            self._cache_timestamp = None

            return pattern_id

        except Exception as e:
            # CRITICAL-005 FIX: Log error with full context but don't crash
            self.logger.error(
                "pattern_extraction_database_error",
                alert_name=attempt.alert_name,
                symptom_fingerprint=symptom_fingerprint[:100],
                error=str(e),
                error_type=type(e).__name__
            )
            # Return None to indicate failure, caller should handle
            return None

    async def find_similar_patterns(
        self,
        alert_name: str,
        alert_labels: Dict[str, str],
        min_confidence: float = 0.50
    ) -> List[Dict[str, Any]]:
        """
        Find patterns similar to the incoming alert.

        Uses symptom fingerprinting and confidence scoring to match
        alerts to known remediation patterns.

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

        self.logger.info(
            "searching_patterns",
            alert_name=alert_name,
            symptom_fingerprint=symptom_fingerprint[:100]
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

            # Calculate similarity score (could be enhanced with ML)
            similarity = self._calculate_similarity(
                symptom_fingerprint,
                pattern['symptom_fingerprint']
            )

            if similarity >= 0.7:  # 70% similarity threshold
                matches.append({
                    **pattern,
                    'similarity_score': similarity,
                    'effective_confidence': pattern['confidence_score'] * similarity
                })

        # Sort by effective confidence (pattern confidence * similarity)
        matches.sort(key=lambda x: x['effective_confidence'], reverse=True)

        self.logger.info(
            "patterns_found",
            alert_name=alert_name,
            match_count=len(matches),
            top_confidence=matches[0]['effective_confidence'] if matches else 0
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
    ) -> Optional[float]:
        """
        Record the outcome of using a learned pattern.

        Updates pattern statistics using Bayesian confidence scoring.

        HIGH-006 FIX: Now properly returns the new confidence value.

        Args:
            pattern_id: ID of the pattern used
            success: Whether remediation succeeded
            execution_time: Time taken in seconds

        Returns:
            New confidence score after update, or None on error
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

        # HIGH-006 FIX: Return the new confidence value
        return new_confidence

    def _build_symptom_fingerprint(
        self,
        alert_name: str,
        labels: Dict[str, str]
    ) -> str:
        """
        Build a fingerprint string from alert characteristics.

        This helps group similar alerts together even if they have
        different instances or minor label variations.

        v3.2: Added 'system' label support for backup alerts (homeassistant, nexus, etc.)
        """
        # Key labels that indicate symptom type
        key_labels = [
            'alertname',
            'job',
            'severity',
            'container',
            'service',
            'host',
            'device',
            'filesystem',
            'system',  # v3.2: For backup alerts (homeassistant, nexus, etc.)
        ]

        parts = [alert_name]
        for label in key_labels:
            if label in labels:
                value = labels[label]
                # Normalize instance-specific values
                if label in ['instance', 'host']:
                    # Extract host type (nexus, homeassistant, skynet, outpost)
                    if 'nexus' in value.lower() or '192.168.0.11' in value:
                        parts.append('host:nexus')
                    elif 'homeassistant' in value.lower() or '192.168.0.10' in value:
                        parts.append('host:homeassistant')
                    elif 'skynet' in value.lower() or '192.168.0.13' in value:
                        parts.append('host:skynet')
                    elif 'outpost' in value.lower() or '72.60.163.242' in value:
                        parts.append('host:outpost')
                    else:
                        parts.append(f'{label}:generic')
                else:
                    # Include label as-is (e.g., system:homeassistant for backup alerts)
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
        risk_level: Optional[RiskLevel],
        metadata: Optional[Dict[str, Any]] = None,
        target_host: Optional[str] = None
    ) -> int:
        """Create a new remediation pattern.

        v3.0: Now stores metadata including investigation chain.
        v3.2: Added target_host for explicit host override.
        MEDIUM-008 FIX: Uses INSERT ON CONFLICT to handle race conditions
        where two processes try to create the same pattern simultaneously.
        """
        # Extract target_host from metadata if not explicitly provided
        if target_host is None and metadata and 'actual_remediation_host' in metadata:
            target_host = metadata['actual_remediation_host']

        # MEDIUM-008 FIX: Use UPSERT to handle race conditions gracefully
        query = """
            INSERT INTO remediation_patterns (
                alert_name,
                alert_category,
                symptom_fingerprint,
                root_cause,
                solution_commands,
                target_host,
                risk_level,
                metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (alert_name, symptom_fingerprint)
            DO UPDATE SET
                success_count = remediation_patterns.success_count + 1,
                solution_commands = EXCLUDED.solution_commands,
                metadata = COALESCE(remediation_patterns.metadata, '{}'::jsonb) || COALESCE(EXCLUDED.metadata::jsonb, '{}'::jsonb),
                updated_at = NOW()
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
                target_host,
                risk_level.value if risk_level else 'MEDIUM',
                json.dumps(metadata) if metadata else None
            )

        return pattern_id

    async def _update_pattern(
        self,
        pattern_id: int,
        commands: List[str],
        success: bool,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Update an existing pattern with new outcome.

        v3.0: Now merges metadata including investigation chain.
        """
        # v3.0: Use JSONB merge if metadata provided
        # HIGH-004 FIX: Use correct column names from schema (last_used_at, updated_at)
        if metadata:
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
                    metadata = COALESCE(metadata, '{}'::jsonb) || $4::jsonb,
                    last_used_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
                RETURNING id
            """
            async with self.db.pool.acquire() as conn:
                return await conn.fetchval(query, pattern_id, commands, success, json.dumps(metadata))
        else:
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

        HIGH-008 FIX: Uses weighted Jaccard similarity where important labels
        (alert name, host, container, service) contribute more to the score
        than generic labels.
        """
        parts1 = set(fingerprint1.split('|'))
        parts2 = set(fingerprint2.split('|'))

        if not parts1 or not parts2:
            return 0.0

        # HIGH-008 FIX: Define weights for different label types
        # Higher weights for more important distinguishing features
        label_weights = {
            'host': 3.0,        # Host is critical for routing
            'container': 2.5,   # Container specificity
            'service': 2.5,     # Service specificity
            'system': 2.0,      # System (for backup alerts)
            'job': 1.5,         # Job type
            'severity': 1.0,    # Severity is common
            'device': 2.0,      # Device specificity
            'filesystem': 2.0,  # Filesystem specificity
        }
        default_weight = 1.0
        alert_name_weight = 4.0  # Alert name is most important

        def get_weight(part: str) -> float:
            """Get weight for a fingerprint part."""
            # First part (index 0) is always alert name
            if ':' not in part:
                return alert_name_weight
            label = part.split(':')[0]
            return label_weights.get(label, default_weight)

        # Calculate weighted intersection and union
        intersection = parts1 & parts2
        union = parts1 | parts2

        weighted_intersection = sum(get_weight(p) for p in intersection)
        weighted_union = sum(get_weight(p) for p in union)

        return weighted_intersection / weighted_union if weighted_union > 0 else 0.0

    async def _refresh_pattern_cache(self, force_refresh: bool = False):
        """
        Refresh the in-memory pattern cache if needed.

        MEDIUM-002 FIX: Added force_refresh parameter to bypass TTL check.
        MEDIUM-015 FIX: Uses timezone-aware datetime for accurate TTL checks.

        Args:
            force_refresh: If True, bypasses TTL check and refreshes immediately
        """
        from datetime import timezone
        now = datetime.now(timezone.utc)

        if (force_refresh or
            self._cache_timestamp is None or
            now - self._cache_timestamp > self._cache_ttl):

            query = """
                SELECT
                    id,
                    alert_name,
                    alert_category,
                    symptom_fingerprint,
                    root_cause,
                    solution_commands,
                    target_host,
                    success_count,
                    failure_count,
                    confidence_score,
                    risk_level,
                    usage_count,
                    avg_execution_time,
                    last_used_at,
                    metadata
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
