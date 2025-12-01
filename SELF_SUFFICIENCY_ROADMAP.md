# Jarvis Self-Sufficiency Roadmap

**Version:** 2.0
**Created:** 2025-12-01
**Updated:** 2025-12-01
**Target:** 95%+ autonomous alert resolution
**Current State:** v3.8.0 - All Phases Complete (Phase 1-4 implemented)

---

## Executive Summary

This document outlines the implementation plan to transform Jarvis from a 22% success rate reactive system into a 95%+ self-sufficient autonomous incident response platform. The roadmap is divided into four phases over 8-14 weeks, with each phase delivering measurable improvements to autonomous resolution capabilities.

### Current Performance Baseline

| Metric | Current (v3.4.0) | Phase 1 Target | Phase 2 Target | Final Target |
|--------|------------------|----------------|----------------|--------------|
| Success Rate | 22.2% | 50% | 70% | 95%+ |
| Escalation Rate | 63% | 40% | 20% | <10% |
| Mean Time to Resolution | 57s | 45s | 30s | <60s |
| Pattern Coverage | 25 patterns | 35 patterns | 50 patterns | 80+ patterns |
| API Calls Saved | 11% | 40% | 60% | 80%+ |

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Gap Analysis](#2-gap-analysis)
3. [Phase 1: Foundation (Weeks 1-2)](#3-phase-1-foundation-weeks-1-2)
4. [Phase 2: Intelligence (Weeks 3-6)](#4-phase-2-intelligence-weeks-3-6)
5. [Phase 3: Advanced Capabilities (Weeks 7-10)](#5-phase-3-advanced-capabilities-weeks-7-10)
6. [Phase 4: Polish & Scale (Weeks 11-14)](#6-phase-4-polish--scale-weeks-11-14)
7. [New Prometheus Alert Rules](#7-new-prometheus-alert-rules)
8. [Risk Assessment & Mitigations](#8-risk-assessment--mitigations)
9. [Success Metrics & Monitoring](#9-success-metrics--monitoring)
10. [Implementation Checklist](#10-implementation-checklist)

---

## 1. Current State Analysis

### 1.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Current Jarvis v3.4.0                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Alertmanager ──webhook──► FastAPI ──► Claude Agent ──► SSH Executor       │
│       │                       │              │               │              │
│       │                       ▼              │               ▼              │
│       │                  PostgreSQL ◄────────┘         Target Hosts         │
│       │                       │                    (Nexus, HA, Outpost,     │
│       │                       ▼                         Skynet)             │
│       │                Learning Engine                                      │
│       │                       │                                             │
│       ▼                       ▼                                             │
│  Discord ◄───────────── Notifications                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Current Capabilities

| Component | Status | Maturity |
|-----------|--------|----------|
| Webhook Handler | FastAPI with Basic Auth, fingerprint deduplication | Mature |
| Claude Agent | Agentic loop with tool calling (run_command, gather_logs) | Mature |
| SSH Executor | Connection pooling, safe pipe patterns, 68 blocked patterns | Mature |
| Learning Engine | Pattern fingerprinting, confidence scoring, similarity matching | Good |
| Database | PostgreSQL with 7 tables, escalation cooldowns | Mature |
| Discord Notifier | Rich embeds, connection pooling, truncation | Mature |
| Host Monitor | Offline detection, ping-based recovery | Good |
| Alert Suppressor | Cascading rules, host-offline suppression | Good |

### 1.3 v3.4.0 Key Features

1. **BackupStale Pattern Matching** - System label fingerprinting for correct host targeting
2. **Safe Pipe Commands** - Whitelist for diagnostic pipes (`dmesg | tail`, `docker ps | grep`)
3. **25 Pre-seeded Patterns** - 18 high-confidence, 7 medium-confidence
4. **Investigation-First AI** - Confidence-gated execution (30%/50%/70%/90% thresholds)
5. **Anti-Spam Controls** - 5-minute fingerprint cooldown, 4-hour escalation cooldown

### 1.4 Alert Coverage Analysis

**Well-Covered (have patterns):**
- FrigateDatabaseError (90% confidence)
- ContainerUnhealthy (85% confidence)
- BackupStale (85-100% confidence, system-specific)
- ContainerDown (80-90% confidence)
- WireGuardVPNDown (80% confidence)

**Partially Covered:**
- HighMemoryUsage (pattern exists, limited remediation options)
- DiskSpaceLow (pattern exists, cleanup commands limited)
- TLSCertExpiringSoon (detection only, no auto-renewal)

**Not Covered:**
- Home Assistant addon failures
- Zigbee2MQTT issues
- MQTT broker problems
- Network quality degradation
- Proactive/predictive alerts

---

## 2. Gap Analysis

### 2.1 Intelligence Gaps

| Gap | Current State | Impact | Priority |
|-----|---------------|--------|----------|
| No alert verification | Success based on exit code only | Can't confirm fixes worked | Critical |
| No Loki log context | SSH-gathered logs only | Missing application errors | Critical |
| No Prometheus history | Point-in-time alerts only | No trend correlation | High |
| No root cause correlation | Each alert independent | Duplicate work, missed causes | High |
| Conservative learning | 79% avg confidence, 11% API saved | Too many Claude calls | Medium |
| No proactive detection | React only to fired alerts | Miss preventable issues | Medium |

### 2.2 Remediation Gaps

| Gap | Current State | Impact | Priority |
|-----|---------------|--------|----------|
| No verification loop | Fire-and-forget execution | Unknown if fix worked | Critical |
| Limited HA integration | SSH commands only | Can't restart addons | High |
| No rollback capability | No state snapshots | Can't undo bad fixes | High |
| No n8n orchestration | Single command sequences | Complex fixes impossible | Medium |
| No cross-system atomic | Sequential execution | Partial fixes possible | Medium |

### 2.3 Self-Preservation Gaps

| Gap | Current State | Impact | Priority |
|-----|---------------|--------|----------|
| No graceful shutdown persistence | AlertQueue for DB only | Lost in-flight work | Medium |
| No health self-check | External monitoring only | Can't detect own issues | Medium |
| No auto-recovery | Docker restart policy | Slow recovery | Low |
| No Claude API fallback | Hard dependency | Offline = no remediation | High |

### 2.4 Monitoring Gaps

| Missing Alert | Category | Impact |
|---------------|----------|--------|
| JarvisDown | Self-monitoring | No remediation when Jarvis offline |
| Zigbee2MQTTDown | Home Automation | Zigbee devices offline |
| MQTTBrokerDown | Home Automation | All MQTT integrations offline |
| DNSResolutionSlow | Network | User experience degradation |
| MemoryExhaustionPredicted | Proactive | Could prevent OOM events |
| ContainerMemoryLeak | Proactive | Could prevent crashes |
| UPSOnBattery | Power | Awareness of power events |

---

## 3. Phase 1: Foundation (Weeks 1-2)

**Goal:** Improve success rate from 22% to 50%

### 3.1 Alert Verification Loop

**Priority:** Critical
**Effort:** 3-4 days
**Impact:** +15-20% success rate

**Problem:** Jarvis marks remediations as "successful" based on command exit codes, but doesn't verify the alert actually resolved.

**Solution:** Query Prometheus after remediation to verify alert state.

**Implementation:**

Create new file `app/prometheus_client.py`:

```python
"""Prometheus API client for alert verification and metric queries."""

import httpx
from typing import Optional
from datetime import datetime, timedelta

class PrometheusClient:
    """Query Prometheus for alert status and metrics."""

    def __init__(self, base_url: str = "http://192.168.0.11:9090"):
        self.base_url = base_url
        self.timeout = 10.0

    async def get_alert_status(self, alert_name: str, instance: str = None) -> str:
        """
        Check if an alert is currently firing.

        Returns: "firing", "pending", or "resolved"
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/alerts"
            )
            response.raise_for_status()
            data = response.json()

            for alert in data.get("data", {}).get("alerts", []):
                if alert["labels"].get("alertname") == alert_name:
                    if instance and alert["labels"].get("instance") != instance:
                        continue
                    return alert["state"]  # "firing" or "pending"

            return "resolved"

    async def verify_remediation(
        self,
        alert_name: str,
        instance: str = None,
        max_wait_seconds: int = 120,
        poll_interval: int = 10
    ) -> tuple[bool, str]:
        """
        Poll Prometheus to verify alert has resolved.

        Returns: (success: bool, final_status: str)
        """
        import asyncio

        checks = max_wait_seconds // poll_interval
        for i in range(checks):
            await asyncio.sleep(poll_interval)
            status = await self.get_alert_status(alert_name, instance)

            if status == "resolved":
                return True, f"Alert resolved after {(i + 1) * poll_interval}s"

        return False, f"Alert still {status} after {max_wait_seconds}s"

    async def query_instant(self, query: str) -> list[dict]:
        """Execute instant PromQL query."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query}
            )
            response.raise_for_status()
            return response.json().get("data", {}).get("result", [])

    async def query_range(
        self,
        query: str,
        hours: int = 2,
        step: str = "1m"
    ) -> list[dict]:
        """Execute range PromQL query for historical data."""
        end = datetime.now()
        start = end - timedelta(hours=hours)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "step": step
                }
            )
            response.raise_for_status()
            return response.json().get("data", {}).get("result", [])
```

**Integration in `claude_agent.py`:**

```python
# Add to ClaudeAgent class

async def _verify_remediation_success(
    self,
    alert: Alert,
    commands_executed: list[str]
) -> tuple[bool, str]:
    """Verify remediation by checking if alert resolved."""

    # Skip verification for diagnostic-only commands
    if all(self._is_diagnostic_command(cmd) for cmd in commands_executed):
        return True, "Diagnostic only, no verification needed"

    # Wait and check alert status
    success, message = await self.prometheus_client.verify_remediation(
        alert_name=alert.labels.alertname,
        instance=alert.labels.get("instance"),
        max_wait_seconds=120,
        poll_interval=10
    )

    return success, message
```

**Files to modify:**
- `app/prometheus_client.py` (new)
- `app/claude_agent.py` (add verification call)
- `app/main.py` (update success determination)
- `app/learning_engine.py` (only learn from verified successes)

**Testing:**
1. Send test alert that Jarvis can fix
2. Verify Jarvis waits and confirms resolution
3. Verify failed fixes are correctly marked

---

### 3.2 Loki Log Context Gathering

**Priority:** Critical
**Effort:** 2-3 days
**Impact:** +10-15% success rate

**Problem:** Claude only sees SSH-gathered logs, missing aggregated application errors from Loki.

**Solution:** Add Loki LogQL query tool for Claude agent.

**Implementation:**

Create new file `app/loki_client.py`:

```python
"""Loki API client for log queries."""

import httpx
from typing import Optional
from datetime import datetime, timedelta
import re

class LokiClient:
    """Query Loki for aggregated logs."""

    def __init__(self, base_url: str = "http://192.168.0.11:3100"):
        self.base_url = base_url
        self.timeout = 15.0

    async def query_logs(
        self,
        query: str,
        time_range_minutes: int = 15,
        limit: int = 100
    ) -> list[dict]:
        """
        Execute LogQL query.

        Args:
            query: LogQL query (e.g., '{job="docker"} |= "error"')
            time_range_minutes: How far back to search
            limit: Max log lines to return

        Returns: List of log entries with timestamp and message
        """
        end = datetime.now()
        start = end - timedelta(minutes=time_range_minutes)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "start": int(start.timestamp() * 1e9),
                    "end": int(end.timestamp() * 1e9),
                    "limit": limit
                }
            )
            response.raise_for_status()

            results = []
            data = response.json().get("data", {}).get("result", [])
            for stream in data:
                labels = stream.get("stream", {})
                for value in stream.get("values", []):
                    results.append({
                        "timestamp": value[0],
                        "message": value[1],
                        "labels": labels
                    })

            return results

    async def get_container_errors(
        self,
        container: str,
        minutes: int = 15,
        limit: int = 50
    ) -> str:
        """Get recent errors from a specific container."""
        query = f'{{container="{container}"}} |~ "(?i)(error|exception|fatal|panic|fail)"'
        logs = await self.query_logs(query, minutes, limit)

        if not logs:
            return f"No errors found for {container} in last {minutes} minutes"

        # Format for Claude consumption
        output = [f"Recent errors from {container} (last {minutes}m):"]
        for log in logs[:20]:  # Limit output size
            msg = log["message"][:500]  # Truncate long messages
            output.append(f"  {msg}")

        return "\n".join(output)

    async def get_service_logs(
        self,
        service: str,
        minutes: int = 10,
        limit: int = 100
    ) -> str:
        """Get recent logs from a service (any level)."""
        query = f'{{job=~".*{service}.*"}} | json'
        logs = await self.query_logs(query, minutes, limit)

        if not logs:
            return f"No logs found for {service} in last {minutes} minutes"

        output = [f"Recent logs from {service}:"]
        for log in logs[:30]:
            msg = log["message"][:300]
            output.append(f"  {msg}")

        return "\n".join(output)

    async def search_logs(
        self,
        pattern: str,
        job: str = None,
        minutes: int = 30,
        limit: int = 100
    ) -> str:
        """Search logs for a specific pattern."""
        if job:
            query = f'{{job="{job}"}} |~ "{pattern}"'
        else:
            query = f'{{job=~".+"}} |~ "{pattern}"'

        logs = await self.query_logs(query, minutes, limit)

        if not logs:
            return f"No logs matching '{pattern}' in last {minutes} minutes"

        output = [f"Logs matching '{pattern}':"]
        for log in logs[:25]:
            labels = log.get("labels", {})
            job_name = labels.get("job", "unknown")
            msg = log["message"][:400]
            output.append(f"  [{job_name}] {msg}")

        return "\n".join(output)
```

**New tool for Claude agent:**

```python
# Add to claude_agent.py TOOLS list

{
    "name": "query_loki_logs",
    "description": "Query aggregated logs from Loki. Use this to find application-level errors, correlate events across services, or search for specific patterns in logs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": ["container_errors", "service_logs", "search"],
                "description": "Type of log query"
            },
            "target": {
                "type": "string",
                "description": "Container name, service name, or search pattern"
            },
            "minutes": {
                "type": "integer",
                "description": "How many minutes back to search (default: 15)",
                "default": 15
            }
        },
        "required": ["query_type", "target"]
    }
}
```

**Files to modify:**
- `app/loki_client.py` (new)
- `app/claude_agent.py` (add tool and handler)
- `app/config.py` (add LOKI_URL setting)

---

### 3.3 Pattern Auto-Learning from Failures

**Priority:** High
**Effort:** 1-2 days
**Impact:** +5-10% success rate

**Problem:** Learning engine only stores successful patterns. Failed attempts (63% of cases) provide no learning value.

**Solution:** Analyze escalated alerts to identify what might have worked, store negative patterns to avoid.

**Implementation:**

Add to `app/learning_engine.py`:

```python
async def record_failure_pattern(
    self,
    alert_name: str,
    alert_instance: str,
    commands_attempted: list[str],
    failure_reason: str,
    symptom_fingerprint: str
) -> None:
    """
    Record a failed remediation pattern to avoid in future.

    This helps Jarvis learn what NOT to do.
    """
    pattern_signature = self._generate_signature(alert_name, commands_attempted)

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

    await self.db.execute(
        query,
        alert_name,
        alert_instance,
        pattern_signature,
        symptom_fingerprint,
        commands_attempted,
        failure_reason
    )

async def get_failed_patterns(
    self,
    alert_name: str,
    limit: int = 5
) -> list[dict]:
    """Get patterns that have failed for this alert type."""
    query = """
        SELECT pattern_signature, commands_attempted, failure_reason, failure_count
        FROM remediation_failures
        WHERE alert_name = $1
        ORDER BY failure_count DESC, last_failed_at DESC
        LIMIT $2
    """

    return await self.db.fetch(query, alert_name, limit)

async def analyze_escalation_for_improvements(
    self,
    alert: dict,
    attempts: list[dict]
) -> dict:
    """
    Use Claude to analyze failed attempts and suggest pattern improvements.

    Called after escalation to learn from failures.
    """
    # Build context from attempts
    attempt_summary = []
    for a in attempts:
        attempt_summary.append({
            "commands": a.get("commands_executed", []),
            "success": a.get("success", False),
            "error": a.get("error_message", "")
        })

    prompt = f"""Analyze this escalated alert and failed remediation attempts.

Alert: {alert.get('labels', {}).get('alertname')}
Instance: {alert.get('labels', {}).get('instance')}
Description: {alert.get('annotations', {}).get('description', 'N/A')}

Attempts made:
{json.dumps(attempt_summary, indent=2)}

Based on this information:
1. What was likely the actual root cause?
2. What commands might have fixed this?
3. What patterns should we avoid in the future?
4. What additional context would have helped?

Respond in JSON format:
{{
    "likely_root_cause": "...",
    "suggested_commands": ["...", "..."],
    "patterns_to_avoid": ["...", "..."],
    "missing_context": ["...", "..."]
}}
"""

    # This would call Claude for analysis
    # Store results for human review
    return {
        "alert": alert,
        "attempts": attempts,
        "analysis_pending": True
    }
```

**Database schema addition:**

```sql
-- Add to init-db.sql

CREATE TABLE IF NOT EXISTS remediation_failures (
    id SERIAL PRIMARY KEY,
    alert_name VARCHAR(255) NOT NULL,
    alert_instance VARCHAR(255),
    pattern_signature VARCHAR(64) NOT NULL UNIQUE,
    symptom_fingerprint TEXT,
    commands_attempted TEXT[],
    failure_reason TEXT,
    failure_count INTEGER DEFAULT 1,
    last_failed_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_failures_alert ON remediation_failures(alert_name);
CREATE INDEX idx_failures_signature ON remediation_failures(pattern_signature);
```

---

### 3.4 Phase 1 Testing Plan

| Test Case | Expected Result |
|-----------|-----------------|
| Send ContainerDown alert | Jarvis fixes, verifies via Prometheus, marks success |
| Send unfixable alert | Jarvis attempts, verification fails, escalates |
| Send alert for crashing container | Jarvis queries Loki errors, includes in analysis |
| Simulate repeated failure | Failure pattern recorded, avoided on retry |

---

## 4. Phase 2: Intelligence (Weeks 3-6)

**Goal:** Improve success rate from 50% to 70%

### 4.1 Prometheus Metric History Queries

**Priority:** High
**Effort:** 3-4 days

**Problem:** Jarvis only sees point-in-time alerts, missing trend context (memory growing, disk filling).

**Solution:** Extend PrometheusClient with range queries, add tool for Claude.

**Implementation (extend `prometheus_client.py`):**

```python
async def get_metric_trend(
    self,
    metric: str,
    instance: str,
    hours: int = 6
) -> dict:
    """
    Get metric trend for analysis.

    Returns: {current, min, max, avg, trend}
    """
    query = f'{metric}{{instance="{instance}"}}'
    results = await self.query_range(query, hours=hours, step="5m")

    if not results:
        return {"error": f"No data for {metric}"}

    values = [float(v[1]) for v in results[0].get("values", [])]

    if len(values) < 2:
        return {"error": "Insufficient data points"}

    # Calculate trend (positive = increasing, negative = decreasing)
    trend = (values[-1] - values[0]) / len(values)

    return {
        "metric": metric,
        "current": values[-1],
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
        "trend": trend,
        "trend_direction": "increasing" if trend > 0 else "decreasing",
        "data_points": len(values)
    }

async def predict_exhaustion(
    self,
    metric: str,
    instance: str,
    threshold: float = 0
) -> dict:
    """
    Predict when a metric will hit a threshold.

    Useful for disk/memory exhaustion prediction.
    """
    trend_data = await self.get_metric_trend(metric, instance, hours=24)

    if "error" in trend_data:
        return trend_data

    current = trend_data["current"]
    trend = trend_data["trend"]

    if trend >= 0:
        return {
            "prediction": "stable_or_improving",
            "current": current,
            "trend": trend
        }

    # Calculate time to threshold
    remaining = current - threshold
    if trend != 0:
        hours_to_threshold = abs(remaining / trend) / 12  # trend is per 5m
    else:
        hours_to_threshold = float('inf')

    return {
        "prediction": "will_exhaust",
        "current": current,
        "threshold": threshold,
        "hours_remaining": round(hours_to_threshold, 1),
        "trend_per_hour": trend * 12
    }
```

**New Claude tool:**

```python
{
    "name": "query_metric_history",
    "description": "Query Prometheus for metric history and trends. Use to understand if a problem is getting worse, correlate with events, or predict exhaustion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "description": "Prometheus metric name (e.g., node_memory_MemAvailable_bytes)"
            },
            "instance": {
                "type": "string",
                "description": "Target instance (e.g., 192.168.0.11:9100)"
            },
            "hours": {
                "type": "integer",
                "description": "Hours of history to query (default: 6)",
                "default": 6
            },
            "predict_exhaustion": {
                "type": "boolean",
                "description": "If true, predict when metric will hit zero",
                "default": false
            }
        },
        "required": ["metric", "instance"]
    }
}
```

---

### 4.2 Root Cause Correlation Engine

**Priority:** High
**Effort:** 5-7 days

**Problem:** Multiple alerts fire during incidents, Jarvis treats each independently.

**Solution:** Correlate alerts by time and dependency relationships.

**Implementation:**

Create new file `app/alert_correlator.py`:

```python
"""Alert correlation engine for root cause analysis."""

from typing import Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass
class Incident:
    """A correlated group of alerts."""
    id: str
    root_cause_alert: str
    related_alerts: list[str]
    correlation_type: str  # "dependency", "temporal", "host"
    created_at: datetime

class AlertCorrelator:
    """Correlate multiple alerts to find root cause."""

    # Service dependency map
    DEPENDENCIES = {
        # Service: [depends on...]
        "grafana": ["prometheus", "loki"],
        "prometheus": ["docker"],
        "loki": ["docker"],
        "frigate": ["docker", "coral-tpu"],
        "n8n": ["n8n-db", "docker"],
        "home-assistant": ["mqtt", "zigbee2mqtt"],
        "zigbee2mqtt": ["mqtt"],
        "caddy": ["docker"],
        "adguard": ["docker", "unbound"],
    }

    # Cascading alert patterns
    CASCADE_PATTERNS = {
        # If these alerts fire together, first is root cause
        ("WireGuardVPNDown", "OutpostDown"): "WireGuardVPNDown",
        ("WireGuardVPNDown", "N8NDown"): "WireGuardVPNDown",
        ("DockerDaemonUnresponsive", "ContainerDown"): "DockerDaemonUnresponsive",
        ("HighMemoryUsage", "ContainerOOMKilled"): "HighMemoryUsage",
        ("DiskSpaceCritical", "ContainerDown"): "DiskSpaceCritical",
        ("PostgreSQLDown", "N8NDown"): "PostgreSQLDown",
        ("MQTTBrokerDown", "Zigbee2MQTTDown"): "MQTTBrokerDown",
    }

    # Time window for temporal correlation (seconds)
    CORRELATION_WINDOW = 120

    def __init__(self, db):
        self.db = db
        self.active_incidents: dict[str, Incident] = {}

    async def correlate_alert(self, alert: dict) -> Optional[Incident]:
        """
        Check if alert correlates with existing incident or starts new one.

        Returns: Incident if correlated, None if new standalone alert
        """
        alert_name = alert["labels"]["alertname"]
        alert_time = datetime.fromisoformat(alert.get("startsAt", datetime.now().isoformat()))

        # Check for cascade patterns
        recent_alerts = await self._get_recent_alerts(self.CORRELATION_WINDOW)

        for (alert_a, alert_b), root in self.CASCADE_PATTERNS.items():
            recent_names = [a["labels"]["alertname"] for a in recent_alerts]

            if alert_name in (alert_a, alert_b):
                other = alert_a if alert_name == alert_b else alert_b
                if other in recent_names:
                    return Incident(
                        id=f"incident-{datetime.now().timestamp()}",
                        root_cause_alert=root,
                        related_alerts=[alert_a, alert_b],
                        correlation_type="cascade",
                        created_at=datetime.now()
                    )

        # Check dependency correlation
        for service, deps in self.DEPENDENCIES.items():
            if alert_name.lower().startswith(service):
                # Check if any dependency is also alerting
                for dep in deps:
                    dep_alerts = [a for a in recent_alerts
                                  if dep.lower() in a["labels"]["alertname"].lower()]
                    if dep_alerts:
                        return Incident(
                            id=f"incident-{datetime.now().timestamp()}",
                            root_cause_alert=dep_alerts[0]["labels"]["alertname"],
                            related_alerts=[alert_name],
                            correlation_type="dependency",
                            created_at=datetime.now()
                        )

        return None

    async def _get_recent_alerts(self, seconds: int) -> list[dict]:
        """Get alerts that fired in the last N seconds."""
        query = """
            SELECT alert_name, alert_instance, timestamp, labels
            FROM remediation_log
            WHERE timestamp > NOW() - INTERVAL '%s seconds'
            ORDER BY timestamp DESC
        """
        rows = await self.db.fetch(query, seconds)
        return [{"labels": {"alertname": r["alert_name"], "instance": r["alert_instance"]}}
                for r in rows]

    def get_remediation_priority(self, incident: Incident) -> list[str]:
        """
        Return alerts in order they should be remediated.

        Root cause first, then dependents.
        """
        priority = [incident.root_cause_alert]
        priority.extend([a for a in incident.related_alerts if a != incident.root_cause_alert])
        return priority
```

**Integration:**
- Call correlator before processing each alert
- If correlated, check if root cause is already being handled
- Skip downstream alerts while root cause remediation in progress

---

### 4.3 Home Assistant Integration

**Priority:** High
**Effort:** 3-4 days

**Problem:** Can only restart HA services via SSH, not addons or automations.

**Solution:** Add Home Assistant Supervisor API client.

**Implementation:**

Create new file `app/homeassistant_client.py`:

```python
"""Home Assistant Supervisor API client."""

import httpx
from typing import Optional

class HomeAssistantClient:
    """Interact with Home Assistant for remediation."""

    def __init__(
        self,
        base_url: str = "http://192.168.0.10:8123",
        supervisor_url: str = "http://192.168.0.10/api/hassio",
        token: str = None
    ):
        self.base_url = base_url
        self.supervisor_url = supervisor_url
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def restart_addon(self, addon_slug: str) -> dict:
        """
        Restart a Home Assistant addon.

        Args:
            addon_slug: e.g., "core_mosquitto", "a]0d7b954_zigbee2mqtt"
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.supervisor_url}/addons/{addon_slug}/restart",
                headers=self.headers
            )
            return {"success": response.status_code == 200, "status": response.status_code}

    async def get_addon_info(self, addon_slug: str) -> dict:
        """Get addon status and info."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.supervisor_url}/addons/{addon_slug}/info",
                headers=self.headers
            )
            if response.status_code == 200:
                return response.json().get("data", {})
            return {"error": f"Status {response.status_code}"}

    async def reload_automations(self) -> dict:
        """Reload all automations."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/api/services/automation/reload",
                headers=self.headers
            )
            return {"success": response.status_code == 200}

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict = None
    ) -> dict:
        """Call any Home Assistant service."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                headers=self.headers,
                json=data or {}
            )
            return {"success": response.status_code in (200, 201)}

    async def restart_integration(self, entry_id: str) -> dict:
        """Reload a config entry (integration)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/api/config/config_entries/entry/{entry_id}/reload",
                headers=self.headers
            )
            return {"success": response.status_code == 200}
```

**New Claude tools:**

```python
{
    "name": "restart_ha_addon",
    "description": "Restart a Home Assistant addon via Supervisor API. Use for Zigbee2MQTT, MQTT broker, or other addon issues.",
    "input_schema": {
        "type": "object",
        "properties": {
            "addon_slug": {
                "type": "string",
                "description": "Addon slug (e.g., 'core_mosquitto', 'a]0d7b954_zigbee2mqtt')"
            }
        },
        "required": ["addon_slug"]
    }
},
{
    "name": "reload_ha_automations",
    "description": "Reload all Home Assistant automations. Use when automations are stuck or not triggering.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
```

---

### 4.4 Phase 2 Testing Plan

| Test Case | Expected Result |
|-----------|-----------------|
| Query memory trend for host | Returns current, trend, prediction |
| Simulate VPN + Outpost alerts | Correlator identifies VPN as root cause |
| Zigbee2MQTT addon down | Jarvis restarts via HA Supervisor API |
| Automation stuck | Jarvis reloads automations via HA API |

---

## 5. Phase 3: Advanced Capabilities (Weeks 7-10)

**Goal:** Improve success rate from 70% to 85%

### 5.1 n8n Workflow Orchestration

**Priority:** Medium
**Effort:** 1-2 weeks

**Problem:** Complex multi-step remediations impossible with single command sequences.

**Solution:** Trigger n8n workflows for complex operations.

**Use Cases:**
- Database backup → stop service → restore → verify → restart
- Certificate renewal → deploy → reload services → verify
- Full system health check with detailed reporting

**Implementation:**

Create `app/n8n_client.py`:

```python
"""n8n workflow orchestration client."""

import httpx
from typing import Optional

class N8NClient:
    """Trigger n8n workflows for complex remediation."""

    def __init__(
        self,
        base_url: str = "https://n8n.theburrow.casa",
        api_key: str = None
    ):
        self.base_url = base_url
        self.headers = {
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json"
        }

    async def execute_workflow(
        self,
        workflow_id: str,
        data: dict = None,
        wait_for_completion: bool = True,
        timeout: int = 300
    ) -> dict:
        """
        Trigger a workflow and optionally wait for completion.

        Args:
            workflow_id: n8n workflow ID
            data: Input data for the workflow
            wait_for_completion: If True, poll until workflow completes
            timeout: Max seconds to wait

        Returns: Workflow execution result
        """
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Trigger workflow
            response = await client.post(
                f"{self.base_url}/api/v1/workflows/{workflow_id}/execute",
                headers=self.headers,
                json={"data": data or {}}
            )

            if response.status_code != 200:
                return {"success": False, "error": response.text}

            execution = response.json()
            execution_id = execution.get("executionId")

            if not wait_for_completion:
                return {"success": True, "execution_id": execution_id, "status": "started"}

            # Poll for completion
            import asyncio
            for _ in range(timeout // 5):
                await asyncio.sleep(5)

                status_response = await client.get(
                    f"{self.base_url}/api/v1/executions/{execution_id}",
                    headers=self.headers
                )

                if status_response.status_code == 200:
                    status_data = status_response.json()
                    if status_data.get("finished"):
                        return {
                            "success": status_data.get("status") == "success",
                            "execution_id": execution_id,
                            "status": status_data.get("status"),
                            "data": status_data.get("data")
                        }

            return {"success": False, "error": "Timeout waiting for workflow"}

    async def get_workflow_by_name(self, name: str) -> Optional[str]:
        """Find workflow ID by name."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/workflows",
                headers=self.headers
            )

            if response.status_code == 200:
                workflows = response.json().get("data", [])
                for wf in workflows:
                    if wf.get("name") == name:
                        return wf.get("id")

            return None
```

**Remediation workflows to create in n8n:**
1. `jarvis-database-recovery` - Backup, restore, verify database
2. `jarvis-certificate-renewal` - Renew, deploy, reload certs
3. `jarvis-full-health-check` - Comprehensive system check with report

---

### 5.2 Proactive Issue Detection

**Priority:** Medium
**Effort:** 1-2 weeks

**Problem:** Jarvis only reacts to fired alerts, missing preventable issues.

**Solution:** Scheduled proactive monitoring independent of Alertmanager.

**Implementation:**

Create `app/proactive_monitor.py`:

```python
"""Proactive issue detection and prevention."""

import asyncio
from datetime import datetime, timedelta

class ProactiveMonitor:
    """Detect and fix issues before they become alerts."""

    def __init__(self, prometheus_client, ssh_executor, discord_notifier, db):
        self.prometheus = prometheus_client
        self.ssh = ssh_executor
        self.discord = discord_notifier
        self.db = db
        self.check_interval = 300  # 5 minutes

    async def run_loop(self):
        """Main proactive monitoring loop."""
        while True:
            try:
                await self.check_disk_fill_rates()
                await self.check_certificate_expiry()
                await self.check_memory_trends()
                await self.check_container_restarts()
                await self.check_backup_freshness()
            except Exception as e:
                # Log but don't crash
                print(f"Proactive monitor error: {e}")

            await asyncio.sleep(self.check_interval)

    async def check_disk_fill_rates(self):
        """If disk will be full in <24h, cleanup now."""
        hosts = ["192.168.0.11:9100", "192.168.0.10:9100", "192.168.0.13:9100"]

        for host in hosts:
            prediction = await self.prometheus.predict_exhaustion(
                metric="node_filesystem_avail_bytes",
                instance=host,
                threshold=1073741824  # 1GB
            )

            if prediction.get("prediction") == "will_exhaust":
                hours = prediction.get("hours_remaining", 999)
                if hours < 24:
                    # Trigger preemptive cleanup
                    await self._preemptive_disk_cleanup(host, hours)

    async def _preemptive_disk_cleanup(self, host: str, hours_remaining: float):
        """Run disk cleanup before space runs out."""
        hostname = host.split(":")[0]
        host_map = {
            "192.168.0.11": "nexus",
            "192.168.0.10": "homeassistant",
            "192.168.0.13": "skynet"
        }
        target = host_map.get(hostname)

        if target:
            # Notify about proactive action
            await self.discord.send_notification(
                title="Proactive Disk Cleanup",
                description=f"Disk on {target} predicted to fill in {hours_remaining:.1f}h. Running cleanup.",
                color=0xFFA500  # Orange
            )

            # Run cleanup commands
            commands = [
                "docker system prune -f",
                "journalctl --vacuum-time=3d",
            ]

            for cmd in commands:
                await self.ssh.execute_command(target, cmd)

    async def check_certificate_expiry(self):
        """Warn if certs expire in <30 days."""
        results = await self.prometheus.query_instant(
            'probe_ssl_earliest_cert_expiry - time()'
        )

        for result in results:
            seconds_remaining = float(result["value"][1])
            days_remaining = seconds_remaining / 86400

            if days_remaining < 30:
                instance = result["metric"].get("instance", "unknown")
                await self.discord.send_notification(
                    title="Certificate Expiry Warning",
                    description=f"Certificate for {instance} expires in {days_remaining:.0f} days",
                    color=0xFFA500
                )

    async def check_memory_trends(self):
        """Detect containers with memory leaks."""
        # Query containers with steadily growing memory over 6h
        results = await self.prometheus.query_instant(
            'rate(container_memory_working_set_bytes[6h]) > 5000000'  # Growing >5MB/h
        )

        for result in results:
            container = result["metric"].get("name", "unknown")
            growth_rate = float(result["value"][1]) * 3600 / 1048576  # MB/hour

            await self.discord.send_notification(
                title="Memory Leak Detected",
                description=f"Container {container} memory growing {growth_rate:.1f}MB/hour",
                color=0xFFA500
            )

    async def check_container_restarts(self):
        """Detect containers restarting frequently."""
        results = await self.prometheus.query_instant(
            'increase(container_restart_count[1h]) > 3'
        )

        for result in results:
            container = result["metric"].get("name", "unknown")
            restarts = int(float(result["value"][1]))

            await self.discord.send_notification(
                title="Container Restart Loop",
                description=f"Container {container} restarted {restarts} times in last hour",
                color=0xFF0000
            )

    async def check_backup_freshness(self):
        """Verify backups are recent enough."""
        results = await self.prometheus.query_instant(
            '(time() - backup_last_success_timestamp) > 129600'  # >36 hours
        )

        for result in results:
            system = result["metric"].get("system", "unknown")
            hours_old = (float(result["value"][1])) / 3600

            # Don't notify if alert will fire - let Jarvis handle it
            # This is for awareness only
            await self.db.log_proactive_check(
                check_type="backup_freshness",
                target=system,
                finding=f"Backup is {hours_old:.1f} hours old"
            )
```

---

### 5.3 Rollback Capability

**Priority:** Medium
**Effort:** 4-5 days

**Problem:** If remediation makes things worse, no way to undo.

**Solution:** Snapshot state before changes, enable rollback.

**Implementation:**

Create `app/rollback_manager.py`:

```python
"""State snapshot and rollback manager."""

import json
from datetime import datetime
from typing import Optional

class RollbackManager:
    """Track state before remediation for potential rollback."""

    def __init__(self, ssh_executor, db):
        self.ssh = ssh_executor
        self.db = db

    async def snapshot_container_state(
        self,
        host: str,
        container: str
    ) -> str:
        """
        Capture container state before changes.

        Returns: snapshot_id
        """
        # Capture current state
        inspect_result = await self.ssh.execute_command(
            host,
            f"docker inspect {container}"
        )

        logs_result = await self.ssh.execute_command(
            host,
            f"docker logs --tail 100 {container}"
        )

        snapshot_id = f"snap-{datetime.now().timestamp()}"

        await self.db.execute(
            """
            INSERT INTO state_snapshots (
                snapshot_id, host, target_type, target_name,
                state_data, created_at
            ) VALUES ($1, $2, 'container', $3, $4, NOW())
            """,
            snapshot_id,
            host,
            container,
            json.dumps({
                "inspect": inspect_result.stdout,
                "logs": logs_result.stdout,
                "captured_at": datetime.now().isoformat()
            })
        )

        return snapshot_id

    async def snapshot_service_state(
        self,
        host: str,
        service: str
    ) -> str:
        """Capture systemd service state before changes."""
        status_result = await self.ssh.execute_command(
            host,
            f"systemctl status {service}"
        )

        config_result = await self.ssh.execute_command(
            host,
            f"systemctl cat {service}"
        )

        snapshot_id = f"snap-{datetime.now().timestamp()}"

        await self.db.execute(
            """
            INSERT INTO state_snapshots (
                snapshot_id, host, target_type, target_name,
                state_data, created_at
            ) VALUES ($1, $2, 'service', $3, $4, NOW())
            """,
            snapshot_id,
            host,
            service,
            json.dumps({
                "status": status_result.stdout,
                "config": config_result.stdout,
                "captured_at": datetime.now().isoformat()
            })
        )

        return snapshot_id

    async def rollback(self, snapshot_id: str) -> dict:
        """
        Attempt to restore previous state.

        Note: This is best-effort - some changes may not be reversible.
        """
        snapshot = await self.db.fetchrow(
            "SELECT * FROM state_snapshots WHERE snapshot_id = $1",
            snapshot_id
        )

        if not snapshot:
            return {"success": False, "error": "Snapshot not found"}

        state_data = json.loads(snapshot["state_data"])
        host = snapshot["host"]
        target = snapshot["target_name"]
        target_type = snapshot["target_type"]

        if target_type == "container":
            # For containers, we can restart to restore state
            # (assuming no persistent changes were made)
            result = await self.ssh.execute_command(
                host,
                f"docker restart {target}"
            )
            return {"success": result.returncode == 0, "action": "container_restart"}

        elif target_type == "service":
            result = await self.ssh.execute_command(
                host,
                f"systemctl restart {target}"
            )
            return {"success": result.returncode == 0, "action": "service_restart"}

        return {"success": False, "error": f"Unknown target type: {target_type}"}
```

**Database schema:**

```sql
CREATE TABLE IF NOT EXISTS state_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_id VARCHAR(64) UNIQUE NOT NULL,
    host VARCHAR(50) NOT NULL,
    target_type VARCHAR(20) NOT NULL,  -- 'container', 'service', 'file'
    target_name VARCHAR(255) NOT NULL,
    state_data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    used_for_rollback BOOLEAN DEFAULT FALSE,
    rollback_at TIMESTAMP
);

CREATE INDEX idx_snapshots_id ON state_snapshots(snapshot_id);
CREATE INDEX idx_snapshots_target ON state_snapshots(host, target_name);
```

---

## 6. Phase 4: Polish & Scale (Weeks 11-14)

**Goal:** Achieve 95%+ success rate, production-grade operations

### 6.1 Export Prometheus Metrics

**Priority:** Medium
**Effort:** 1-2 days

Add `/metrics` endpoint to Jarvis for self-monitoring:

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Metrics
remediation_total = Counter(
    'jarvis_remediation_total',
    'Total remediation attempts',
    ['alert_name', 'status']  # success, failure, escalated, skipped
)

remediation_duration = Histogram(
    'jarvis_remediation_duration_seconds',
    'Remediation duration',
    ['alert_name'],
    buckets=[5, 10, 30, 60, 120, 300, 600]
)

pattern_matches = Counter(
    'jarvis_pattern_matches_total',
    'Pattern matching results',
    ['result']  # hit, miss
)

api_calls = Counter(
    'jarvis_claude_api_calls_total',
    'Claude API calls',
    ['model', 'status']
)

active_remediations = Gauge(
    'jarvis_active_remediations',
    'Currently active remediations'
)

# Endpoint
@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type="text/plain"
    )
```

### 6.2 Web UI for Manual Approval

**Priority:** Low
**Effort:** 2-3 weeks

A React/Vue dashboard for:
- Real-time alert status
- Manual approval workflow for high-risk actions
- Pattern management (view, edit, delete)
- Historical analytics
- Configuration management

**Scope:**
- Read-only initially (view alerts, patterns, history)
- Phase 2: Add approval workflow
- Phase 3: Full pattern management

### 6.3 Runbook Integration

**Priority:** Low
**Effort:** 1 week

Load runbooks from markdown files to provide Claude with structured remediation guidance:

```python
class RunbookManager:
    """Load runbooks for remediation guidance."""

    def __init__(self, runbook_dir: str = "/app/runbooks"):
        self.runbook_dir = runbook_dir
        self.runbooks = {}
        self._load_runbooks()

    def _load_runbooks(self):
        """Load all runbook markdown files."""
        import glob
        for path in glob.glob(f"{self.runbook_dir}/*.md"):
            alert_name = path.split("/")[-1].replace(".md", "")
            with open(path) as f:
                self.runbooks[alert_name] = f.read()

    def get_runbook(self, alert_name: str) -> Optional[str]:
        """Get runbook content for an alert."""
        # Exact match
        if alert_name in self.runbooks:
            return self.runbooks[alert_name]

        # Partial match
        for name, content in self.runbooks.items():
            if name.lower() in alert_name.lower():
                return content

        return None
```

**Runbook format example (`runbooks/ContainerDown.md`):**

```markdown
# ContainerDown Remediation Runbook

## Overview
This alert fires when a Docker container stops unexpectedly.

## Investigation Steps
1. Check container logs: `docker logs <container> --tail 100`
2. Check container exit code: `docker inspect <container> --format '{{.State.ExitCode}}'`
3. Check host resources: `docker stats --no-stream`

## Common Causes
- Out of memory (exit code 137)
- Application crash (exit code 1)
- Dependency failure
- Disk space exhaustion

## Remediation
1. If exit code 137: Check memory limits, consider increasing
2. If exit code 1: Check logs for error, may need config fix
3. If dependency: Fix dependency first

## Commands
```bash
docker restart <container>
docker logs <container> --tail 200
docker inspect <container>
```
```

---

## 7. New Prometheus Alert Rules

Add these alerts to `/home/t1/homelab/configs/prometheus/alert_rules.yml`:

```yaml
# =====================================================================
# Jarvis Self-Monitoring
# =====================================================================
- name: jarvis_monitoring
  interval: 30s
  rules:
    - alert: JarvisDown
      expr: up{job="jarvis"} == 0
      for: 2m
      labels:
        severity: critical
        category: monitoring
        remediation_host: skynet
      annotations:
        summary: "Jarvis AI Remediation Service is DOWN"
        description: "Jarvis has been unreachable for 2 minutes. Auto-remediation is offline."
        remediation_hint: "Check Docker on Skynet: docker ps | grep jarvis"
        remediation_commands: "docker restart jarvis"

    - alert: JarvisHighEscalationRate
      expr: |
        (
          sum(increase(jarvis_remediation_total{status="escalated"}[1h])) /
          sum(increase(jarvis_remediation_total[1h]))
        ) > 0.5
      for: 1h
      labels:
        severity: warning
        category: monitoring
      annotations:
        summary: "Jarvis escalation rate above 50%"
        description: "More than half of remediations are being escalated. Review patterns."
        remediation_hint: "Manual review required. Check pattern coverage and confidence."

    - alert: JarvisDatabaseDown
      expr: jarvis_database_connected == 0
      for: 5m
      labels:
        severity: critical
        category: database
        remediation_host: skynet
      annotations:
        summary: "Jarvis cannot connect to PostgreSQL"
        description: "Jarvis database connection has been down for 5 minutes."
        remediation_hint: "Check postgres-jarvis container on Skynet."
        remediation_commands: "docker restart postgres-jarvis"

    - alert: JarvisClaudeAPIErrors
      expr: increase(jarvis_claude_api_calls_total{status="error"}[15m]) > 5
      for: 5m
      labels:
        severity: warning
        category: api
      annotations:
        summary: "Jarvis experiencing Claude API errors"
        description: "Multiple Claude API errors in last 15 minutes."
        remediation_hint: "Check API key validity, rate limits, or Anthropic status."

# =====================================================================
# Home Assistant Addon Monitoring
# =====================================================================
- name: homeassistant_addons
  interval: 60s
  rules:
    - alert: Zigbee2MQTTDown
      expr: homeassistant_addon_state{addon="zigbee2mqtt"} != 1
      for: 3m
      labels:
        severity: critical
        category: home_automation
        remediation_host: homeassistant
        service: zigbee2mqtt
      annotations:
        summary: "Zigbee2MQTT addon is DOWN"
        description: "Zigbee2MQTT has been down for 3 minutes. Zigbee devices offline."
        remediation_hint: "Restart Zigbee2MQTT addon via Supervisor API."
        remediation_commands: "ha addons restart core_zigbee2mqtt"

    - alert: MQTTBrokerDown
      expr: homeassistant_addon_state{addon="mosquitto"} != 1
      for: 2m
      labels:
        severity: critical
        category: home_automation
        remediation_host: homeassistant
        service: mosquitto
      annotations:
        summary: "MQTT Broker is DOWN"
        description: "Mosquitto has been down for 2 minutes. All MQTT integrations offline."
        remediation_hint: "Restart Mosquitto addon."
        remediation_commands: "ha addons restart core_mosquitto"

# =====================================================================
# Network Quality Monitoring
# =====================================================================
- name: network_quality
  interval: 60s
  rules:
    - alert: HighPacketLoss
      expr: |
        (
          rate(node_network_transmit_drop_total[5m]) /
          rate(node_network_transmit_packets_total[5m])
        ) > 0.01
      for: 10m
      labels:
        severity: warning
        category: network
      annotations:
        summary: "High packet loss on {{ $labels.instance }}"
        description: "Packet loss above 1% for 10 minutes on {{ $labels.device }}."
        remediation_hint: "Check network switch, cables, interface errors."
        remediation_commands: "ip -s link show {{ $labels.device }}"

    - alert: DNSResolutionSlow
      expr: probe_dns_lookup_time_seconds > 0.5
      for: 5m
      labels:
        severity: warning
        category: network
        remediation_host: nexus
      annotations:
        summary: "DNS resolution is slow"
        description: "DNS lookups taking more than 500ms."
        remediation_hint: "Check AdGuard and Unbound containers."
        remediation_commands: "docker restart adguard; docker restart unbound"

# =====================================================================
# Resource Prediction (Proactive)
# =====================================================================
- name: resource_prediction
  interval: 5m
  rules:
    - alert: MemoryExhaustionPredicted
      expr: |
        predict_linear(node_memory_MemAvailable_bytes[6h], 4 * 3600) < 0
      for: 30m
      labels:
        severity: warning
        category: resources
      annotations:
        summary: "Memory exhaustion predicted on {{ $labels.instance }}"
        description: "Based on trends, memory will exhaust within 4 hours."
        remediation_hint: "Identify memory-hungry services for preemptive restart."
        remediation_commands: "docker stats --no-stream --format 'table {{.Name}}\\t{{.MemUsage}}' | sort -k2 -hr | head -10"

    - alert: DiskExhaustionPredicted
      expr: |
        predict_linear(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}[6h], 24 * 3600) < 1073741824
      for: 1h
      labels:
        severity: warning
        category: resources
      annotations:
        summary: "Disk exhaustion predicted on {{ $labels.instance }}"
        description: "Disk will have <1GB free within 24 hours."
        remediation_hint: "Run disk cleanup before alert escalates."
        remediation_commands: "docker system prune -f; journalctl --vacuum-time=3d"

    - alert: ContainerMemoryLeak
      expr: |
        rate(container_memory_working_set_bytes{name!=""}[1h]) > 10000000
        and container_memory_working_set_bytes > 1000000000
      for: 2h
      labels:
        severity: warning
        category: containers
      annotations:
        summary: "Possible memory leak in {{ $labels.name }}"
        description: "Container memory growing at {{ $value | humanize }}B/hour."
        remediation_hint: "Consider preemptive restart."
        remediation_commands: "docker restart {{ $labels.name }}"

# =====================================================================
# UPS Monitoring
# =====================================================================
- name: ups_monitoring
  interval: 60s
  rules:
    - alert: UPSOnBattery
      expr: network_ups_tools_ups_status{flag="OB"} == 1
      for: 1m
      labels:
        severity: critical
        category: power
      annotations:
        summary: "UPS running on battery power"
        description: "Power outage detected. UPS on battery."
        remediation_hint: "Monitor battery runtime. Prepare for graceful shutdown if needed."
        remediation_commands: "upsc cp1500@192.168.0.11"

    - alert: UPSLowBattery
      expr: network_ups_tools_battery_charge < 20
      for: 2m
      labels:
        severity: critical
        category: power
      annotations:
        summary: "UPS battery critically low ({{ $value }}%)"
        description: "Battery below 20%. Shutdown may be imminent."
        remediation_hint: "Initiate graceful shutdown if power not restored soon."
        remediation_commands: "upsc cp1500@192.168.0.11 battery.runtime"

    - alert: UPSBatteryNeedsReplacement
      expr: network_ups_tools_battery_charge_low > 50
      for: 1h
      labels:
        severity: warning
        category: power
      annotations:
        summary: "UPS battery may need replacement"
        description: "Low battery threshold unusually high. Battery degraded."
        remediation_hint: "Schedule UPS battery replacement."

# =====================================================================
# Docker Daemon Health
# =====================================================================
- name: docker_health
  interval: 30s
  rules:
    - alert: DockerDaemonUnresponsive
      expr: time() - container_last_seen{name=~".+"} > 120
      for: 2m
      labels:
        severity: critical
        category: containers
      annotations:
        summary: "Docker daemon unresponsive on {{ $labels.instance }}"
        description: "No container metrics for 2 minutes. Docker may be hung."
        remediation_hint: "Docker restart is high-risk. Verify before proceeding."
        remediation_commands: "sudo systemctl status docker"

    - alert: TooManyContainerRestarts
      expr: increase(container_restart_count[1h]) > 5
      for: 5m
      labels:
        severity: warning
        category: containers
      annotations:
        summary: "Container {{ $labels.name }} restarting frequently"
        description: "Container has restarted {{ $value }} times in the last hour."
        remediation_hint: "Check container logs for crash cause."
        remediation_commands: "docker logs {{ $labels.name }} --tail 100"
```

---

## 8. Risk Assessment & Mitigations

### 8.1 High Risk

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Aggressive auto-fix causes cascade | Medium | High | Verification loop, rollback capability, enhanced blocked patterns |
| Claude API outage | Low | High | Pattern-only fallback mode, local pattern cache |
| SSH key compromise | Low | Critical | Audit logging, key rotation, per-host limited keys |
| Learning engine learns bad patterns | Medium | Medium | Minimum success count (5+), human review for new patterns |

### 8.2 Medium Risk

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Loki/Prometheus adds latency | Medium | Low | Aggressive timeouts, optional for fast path |
| Cost overrun from Claude API | Low | Medium | Pattern matching reduces calls, budget alerts |
| Database growth unbounded | Medium | Low | 30-day retention policy, monthly partition |

### 8.3 Low Risk

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Discord rate limiting | Low | Low | Already have notification batching |
| n8n workflow failures | Low | Low | Timeout handling, fallback to direct commands |

---

## 9. Success Metrics & Monitoring

### 9.1 Key Performance Indicators

| Metric | Current | Phase 1 | Phase 2 | Phase 3 | Final |
|--------|---------|---------|---------|---------|-------|
| Success Rate | 22.2% | 50% | 70% | 85% | 95%+ |
| Escalation Rate | 63% | 40% | 20% | 12% | <10% |
| MTTR (Mean Time to Resolution) | 57s | 45s | 30s | 30s | <60s |
| Pattern Coverage | 25 | 35 | 50 | 70 | 80+ |
| API Calls Saved | 11% | 40% | 60% | 70% | 80%+ |
| False Positive Fixes | Unknown | <5% | <3% | <2% | <1% |

### 9.2 Monitoring Dashboard

Create Grafana dashboard with:
- Remediation success/failure/escalation over time
- MTTR histogram
- Pattern hit rate
- Claude API usage and cost
- Active alerts vs resolved by Jarvis
- Top escalated alert types (areas for improvement)

### 9.3 Weekly Review Process

Every Sunday:
1. Review escalated alerts from past week
2. Identify patterns that could be added
3. Review any false positive fixes
4. Update blocked command list if needed
5. Check API cost against budget

---

## 10. Implementation Checklist

### Phase 1 (Weeks 1-2) - COMPLETE (v3.5.0)

- [x] **3.1 Alert Verification Loop**
  - [x] Create `app/prometheus_client.py`
  - [x] Add `verify_remediation()` method
  - [x] Integrate into `claude_agent.py`
  - [x] Update `learning_engine.py` to require verified success
  - [x] Test with ContainerDown alert
  - [x] Test with unfixable alert

- [x] **3.2 Loki Log Context**
  - [x] Create `app/loki_client.py`
  - [x] Add `query_loki_logs` tool to Claude agent
  - [x] Update system prompt with Loki usage guidance
  - [x] Test with application error scenario
  - [x] Test log search functionality

- [x] **3.3 Failure Pattern Learning**
  - [x] Add `remediation_failures` table to `init-db.sql`
  - [x] Implement `record_failure_pattern()` in learning engine
  - [x] Add negative pattern checking before remediation
  - [x] Test failure recording
  - [x] Test pattern avoidance

### Phase 2 (Weeks 3-6) - COMPLETE (v3.6.0)

- [x] **4.1 Prometheus Metric History**
  - [x] Extend `prometheus_client.py` with `query_range()`
  - [x] Add `get_metric_trend()` method
  - [x] Add `predict_exhaustion()` method
  - [x] Add `query_metric_history` tool to Claude
  - [x] Test trend analysis
  - [x] Test exhaustion prediction

- [x] **4.2 Root Cause Correlation**
  - [x] Create `app/alert_correlator.py`
  - [x] Define dependency map
  - [x] Define cascade patterns
  - [x] Integrate into main webhook handler
  - [x] Test with VPN + downstream alerts
  - [x] Test with container + dependency alerts

- [x] **4.3 Home Assistant Integration**
  - [x] Create `app/homeassistant_client.py`
  - [x] Add HA_TOKEN to configuration
  - [x] Add `restart_ha_addon` tool
  - [x] Add `reload_ha_automations` tool
  - [x] Test addon restart
  - [x] Test automation reload

### Phase 3 (Weeks 7-10) - COMPLETE (v3.7.0)

- [x] **5.1 n8n Workflow Orchestration**
  - [x] Create `app/n8n_client.py`
  - [ ] Create `jarvis-database-recovery` workflow in n8n (optional, created on-demand)
  - [ ] Create `jarvis-certificate-renewal` workflow (optional, created on-demand)
  - [x] Add `trigger_workflow` tool to Claude
  - [x] Test workflow execution
  - [x] Test timeout handling

- [x] **5.2 Proactive Monitoring**
  - [x] Create `app/proactive_monitor.py`
  - [x] Implement disk fill rate check
  - [x] Implement certificate expiry check
  - [x] Implement memory trend check
  - [x] Start proactive loop on app startup
  - [x] Test preemptive cleanup

- [x] **5.3 Rollback Capability**
  - [x] Create `app/rollback_manager.py`
  - [x] Add `state_snapshots` table
  - [x] Implement container state snapshot
  - [x] Implement service state snapshot
  - [x] Integrate snapshot before remediation
  - [x] Test rollback functionality

### Phase 4 (Weeks 11-14) - COMPLETE (v3.8.0)

- [x] **6.1 Prometheus Metrics Export**
  - [x] Add prometheus_client dependency
  - [x] Define metrics (counters, histograms, gauges)
  - [x] Add `/metrics` endpoint
  - [ ] Configure Prometheus scrape job (deployment task)
  - [ ] Create Grafana dashboard (deployment task)

- [ ] **6.2 New Alert Rules** (deployment task - not part of codebase)
  - [ ] Add Jarvis self-monitoring alerts
  - [ ] Add HA addon alerts
  - [ ] Add network quality alerts
  - [ ] Add resource prediction alerts
  - [ ] Add UPS monitoring alerts
  - [ ] Test alert firing and remediation

- [x] **6.3 Documentation & Polish**
  - [ ] Update ARCHITECTURE.md (future enhancement)
  - [x] Update CLAUDE.md
  - [x] Create runbook templates (5 runbooks created)
  - [x] Final testing of all phases
  - [x] Performance tuning

---

## Appendix A: File Summary

### New Files to Create

| File | Purpose | Phase |
|------|---------|-------|
| `app/prometheus_client.py` | Prometheus API queries | 1 |
| `app/loki_client.py` | Loki log queries | 1 |
| `app/alert_correlator.py` | Root cause correlation | 2 |
| `app/homeassistant_client.py` | HA Supervisor API | 2 |
| `app/n8n_client.py` | n8n workflow triggers | 3 |
| `app/proactive_monitor.py` | Proactive issue detection | 3 |
| `app/rollback_manager.py` | State snapshots and rollback | 3 |
| `app/runbook_manager.py` | Runbook loading | 4 |

### Files to Modify

| File | Changes | Phase |
|------|---------|-------|
| `app/claude_agent.py` | Add new tools, verification | 1-3 |
| `app/learning_engine.py` | Failure patterns, verified learning | 1 |
| `app/main.py` | Correlation, proactive startup | 2-3 |
| `app/config.py` | New service URLs and tokens | 1-3 |
| `init-db.sql` | New tables | 1, 3 |
| `docker-compose.yml` | New environment variables | 1-3 |

---

## Appendix B: Environment Variables

Add to `.env`:

```bash
# Phase 1
PROMETHEUS_URL=http://192.168.0.11:9090
LOKI_URL=http://192.168.0.11:3100

# Phase 2
HA_URL=http://192.168.0.10:8123
HA_SUPERVISOR_URL=http://192.168.0.10/api/hassio
HA_TOKEN=your_long_lived_access_token

# Phase 3
N8N_URL=https://n8n.theburrow.casa
N8N_API_KEY=your_n8n_api_key

# Phase 4
RUNBOOK_DIR=/app/runbooks
```

---

*Document Version: 2.0*
*Last Updated: 2025-12-01*
*Status: All Phases Complete - Deployment tasks remain (Prometheus scrape job, Grafana dashboard, alert rules)*
