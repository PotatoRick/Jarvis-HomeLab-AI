"""
Prometheus API client for alert verification and metric queries.

Phase 1 of Self-Sufficiency Roadmap: Enables Jarvis to verify remediations
by checking if alerts actually resolved after fix attempts.
"""

import httpx
import asyncio
import structlog
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from .config import settings

logger = structlog.get_logger()


class PrometheusClient:
    """Query Prometheus for alert status and metrics."""

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize Prometheus client.

        Args:
            base_url: Prometheus URL (defaults to settings.prometheus_url)
        """
        self.base_url = base_url or getattr(
            settings, 'prometheus_url', 'http://192.168.0.11:9090'
        )
        self.timeout = 10.0
        self.logger = logger.bind(component="prometheus_client")

    async def get_alert_status(
        self,
        alert_name: str,
        instance: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Check if an alert is currently firing.

        Args:
            alert_name: Name of the alert to check
            instance: Optional instance label to filter by
            labels: Optional additional labels to match

        Returns:
            "firing", "pending", or "resolved"
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/v1/alerts")
                response.raise_for_status()
                data = response.json()

                for alert in data.get("data", {}).get("alerts", []):
                    alert_labels = alert.get("labels", {})

                    # Check alert name match
                    if alert_labels.get("alertname") != alert_name:
                        continue

                    # Check instance match if specified
                    if instance and alert_labels.get("instance") != instance:
                        continue

                    # Check additional labels if specified
                    if labels:
                        match = all(
                            alert_labels.get(k) == v
                            for k, v in labels.items()
                        )
                        if not match:
                            continue

                    return alert.get("state", "firing")

                return "resolved"

        except httpx.HTTPError as e:
            self.logger.error(
                "prometheus_alert_check_failed",
                alert_name=alert_name,
                error=str(e)
            )
            raise

    async def verify_remediation(
        self,
        alert_name: str,
        instance: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        max_wait_seconds: int = 120,
        poll_interval: int = 10,
        initial_delay: int = 10
    ) -> Tuple[bool, str]:
        """
        Poll Prometheus to verify alert has resolved after remediation.

        Args:
            alert_name: Name of the alert to verify
            instance: Optional instance label to filter by
            labels: Optional additional labels to match
            max_wait_seconds: Maximum time to wait for resolution
            poll_interval: Seconds between status checks
            initial_delay: Seconds to wait before first check (allow fix to take effect)

        Returns:
            Tuple of (success: bool, message: str)
        """
        self.logger.info(
            "starting_remediation_verification",
            alert_name=alert_name,
            instance=instance,
            max_wait=max_wait_seconds
        )

        # Wait for fix to take effect
        await asyncio.sleep(initial_delay)

        checks = (max_wait_seconds - initial_delay) // poll_interval
        status = "unknown"

        for i in range(checks):
            try:
                status = await self.get_alert_status(alert_name, instance, labels)

                if status == "resolved":
                    elapsed = initial_delay + ((i + 1) * poll_interval)
                    self.logger.info(
                        "remediation_verified_success",
                        alert_name=alert_name,
                        elapsed_seconds=elapsed
                    )
                    return True, f"Alert resolved after {elapsed}s"

                self.logger.debug(
                    "alert_still_active",
                    alert_name=alert_name,
                    status=status,
                    check_number=i + 1
                )

            except Exception as e:
                self.logger.warning(
                    "verification_check_failed",
                    alert_name=alert_name,
                    error=str(e),
                    check_number=i + 1
                )

            await asyncio.sleep(poll_interval)

        self.logger.warning(
            "remediation_verification_failed",
            alert_name=alert_name,
            final_status=status,
            max_wait=max_wait_seconds
        )
        return False, f"Alert still {status} after {max_wait_seconds}s"

    async def query_instant(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute instant PromQL query.

        Args:
            query: PromQL query string

        Returns:
            List of result dictionaries with metric and value
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": query}
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") != "success":
                    self.logger.error(
                        "prometheus_query_error",
                        query=query,
                        error=data.get("error", "Unknown error")
                    )
                    return []

                return data.get("data", {}).get("result", [])

        except httpx.HTTPError as e:
            self.logger.error(
                "prometheus_query_failed",
                query=query,
                error=str(e)
            )
            raise

    async def query_range(
        self,
        query: str,
        hours: int = 2,
        step: str = "1m"
    ) -> List[Dict[str, Any]]:
        """
        Execute range PromQL query for historical data.

        Args:
            query: PromQL query string
            hours: Hours of history to query
            step: Resolution step (e.g., "1m", "5m")

        Returns:
            List of result dictionaries with metric and values array
        """
        end = datetime.now()
        start = end - timedelta(hours=hours)

        try:
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
                data = response.json()

                if data.get("status") != "success":
                    self.logger.error(
                        "prometheus_range_query_error",
                        query=query,
                        error=data.get("error", "Unknown error")
                    )
                    return []

                return data.get("data", {}).get("result", [])

        except httpx.HTTPError as e:
            self.logger.error(
                "prometheus_range_query_failed",
                query=query,
                error=str(e)
            )
            raise

    async def get_metric_trend(
        self,
        metric: str,
        instance: str,
        hours: int = 6
    ) -> Dict[str, Any]:
        """
        Get metric trend for analysis.

        Args:
            metric: Prometheus metric name
            instance: Target instance (e.g., "192.168.0.11:9100")
            hours: Hours of history to analyze

        Returns:
            Dictionary with current, min, max, avg, trend info
        """
        query = f'{metric}{{instance="{instance}"}}'
        results = await self.query_range(query, hours=hours, step="5m")

        if not results:
            return {"error": f"No data for {metric}"}

        values = []
        for result in results:
            for value in result.get("values", []):
                try:
                    values.append(float(value[1]))
                except (ValueError, IndexError):
                    continue

        if len(values) < 2:
            return {"error": "Insufficient data points"}

        # Calculate trend (positive = increasing, negative = decreasing)
        trend = (values[-1] - values[0]) / len(values) if values else 0

        return {
            "metric": metric,
            "current": values[-1],
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "trend": trend,
            "trend_direction": "increasing" if trend > 0 else "decreasing" if trend < 0 else "stable",
            "data_points": len(values)
        }

    async def predict_exhaustion(
        self,
        metric: str,
        instance: str,
        threshold: float = 0
    ) -> Dict[str, Any]:
        """
        Predict when a metric will hit a threshold.

        Useful for disk/memory exhaustion prediction.

        Args:
            metric: Prometheus metric name (e.g., node_filesystem_avail_bytes)
            instance: Target instance
            threshold: Value to predict reaching (default 0)

        Returns:
            Prediction dictionary with hours_remaining
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
            # Trend is per 5-minute sample, so multiply by 12 for hourly rate
            hours_to_threshold = abs(remaining / (trend * 12))
        else:
            hours_to_threshold = float('inf')

        return {
            "prediction": "will_exhaust",
            "current": current,
            "threshold": threshold,
            "hours_remaining": round(hours_to_threshold, 1),
            "trend_per_hour": trend * 12
        }

    async def health_check(self) -> bool:
        """
        Check if Prometheus is reachable.

        Returns:
            True if healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/-/healthy")
                return response.status_code == 200
        except Exception:
            return False


# Global Prometheus client instance
prometheus_client = PrometheusClient()
