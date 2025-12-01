"""
Loki API client for log queries.

Phase 1 of Self-Sufficiency Roadmap: Enables Jarvis to query aggregated logs
from Loki for better root cause analysis.
"""

import httpx
import structlog
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from .config import settings

logger = structlog.get_logger()


class LokiClient:
    """Query Loki for aggregated logs."""

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize Loki client.

        Args:
            base_url: Loki URL (defaults to settings.loki_url)
        """
        self.base_url = base_url or getattr(
            settings, 'loki_url', 'http://192.168.0.11:3100'
        )
        self.timeout = 15.0
        self.logger = logger.bind(component="loki_client")

    async def query_logs(
        self,
        query: str,
        time_range_minutes: int = 15,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Execute LogQL query.

        Args:
            query: LogQL query (e.g., '{job="docker"} |= "error"')
            time_range_minutes: How far back to search
            limit: Max log lines to return

        Returns:
            List of log entries with timestamp, message, and labels
        """
        end = datetime.now()
        start = end - timedelta(minutes=time_range_minutes)

        # Convert to nanoseconds for Loki API
        start_ns = int(start.timestamp() * 1e9)
        end_ns = int(end.timestamp() * 1e9)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/loki/api/v1/query_range",
                    params={
                        "query": query,
                        "start": str(start_ns),
                        "end": str(end_ns),
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

                self.logger.debug(
                    "loki_query_completed",
                    query=query[:100],
                    result_count=len(results)
                )

                return results

        except httpx.HTTPError as e:
            self.logger.error(
                "loki_query_failed",
                query=query[:100],
                error=str(e)
            )
            raise

    async def get_container_errors(
        self,
        container: str,
        minutes: int = 15,
        limit: int = 50
    ) -> str:
        """
        Get recent errors from a specific container.

        Args:
            container: Container name to query
            minutes: How far back to search
            limit: Max log lines to return

        Returns:
            Formatted string of error logs
        """
        query = f'{{container="{container}"}} |~ "(?i)(error|exception|fatal|panic|fail)"'

        try:
            logs = await self.query_logs(query, minutes, limit)
        except Exception as e:
            return f"Failed to query Loki: {str(e)}"

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
        """
        Get recent logs from a service (any level).

        Args:
            service: Service name or pattern to query
            minutes: How far back to search
            limit: Max log lines to return

        Returns:
            Formatted string of logs
        """
        query = f'{{job=~".*{service}.*"}}'

        try:
            logs = await self.query_logs(query, minutes, limit)
        except Exception as e:
            return f"Failed to query Loki: {str(e)}"

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
        job: Optional[str] = None,
        minutes: int = 30,
        limit: int = 100
    ) -> str:
        """
        Search logs for a specific pattern across all services.

        Args:
            pattern: Regex pattern to search for
            job: Optional job name to filter by
            minutes: How far back to search
            limit: Max log lines to return

        Returns:
            Formatted string of matching logs
        """
        if job:
            query = f'{{job="{job}"}} |~ "{pattern}"'
        else:
            query = f'{{job=~".+"}} |~ "{pattern}"'

        try:
            logs = await self.query_logs(query, minutes, limit)
        except Exception as e:
            return f"Failed to query Loki: {str(e)}"

        if not logs:
            return f"No logs matching '{pattern}' in last {minutes} minutes"

        output = [f"Logs matching '{pattern}':"]
        for log in logs[:25]:
            labels = log.get("labels", {})
            job_name = labels.get("job", "unknown")
            msg = log["message"][:400]
            output.append(f"  [{job_name}] {msg}")

        return "\n".join(output)

    async def get_logs_around_time(
        self,
        timestamp: datetime,
        container: Optional[str] = None,
        window_minutes: int = 5,
        limit: int = 50
    ) -> str:
        """
        Get logs around a specific timestamp for incident correlation.

        Args:
            timestamp: Center timestamp for the window
            container: Optional container to filter by
            window_minutes: Minutes before and after timestamp
            limit: Max log lines to return

        Returns:
            Formatted string of logs around the incident time
        """
        start = timestamp - timedelta(minutes=window_minutes)
        end = timestamp + timedelta(minutes=window_minutes)

        start_ns = int(start.timestamp() * 1e9)
        end_ns = int(end.timestamp() * 1e9)

        if container:
            query = f'{{container="{container}"}}'
        else:
            query = '{job=~".+"}'

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/loki/api/v1/query_range",
                    params={
                        "query": query,
                        "start": str(start_ns),
                        "end": str(end_ns),
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

                if not results:
                    return f"No logs found around {timestamp.isoformat()}"

                output = [f"Logs around {timestamp.isoformat()} (+/- {window_minutes}m):"]
                for log in results[:30]:
                    labels = log.get("labels", {})
                    container_name = labels.get("container", labels.get("job", "unknown"))
                    msg = log["message"][:400]
                    output.append(f"  [{container_name}] {msg}")

                return "\n".join(output)

        except httpx.HTTPError as e:
            return f"Failed to query Loki: {str(e)}"

    async def health_check(self) -> bool:
        """
        Check if Loki is reachable.

        Returns:
            True if healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/ready")
                return response.status_code == 200
        except Exception:
            return False


# Global Loki client instance
loki_client = LokiClient()
