"""
External Service Health Monitor

Monitors health of external services (Cloudflare, IP detection APIs) to determine
if DDNS failures are due to external outages vs actual infrastructure issues.
"""

import structlog
import aiohttp
import asyncio
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum


class ServiceStatus(Enum):
    """External service status"""
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    OUTAGE = "outage"
    UNKNOWN = "unknown"


@dataclass
class ServiceHealth:
    """Health status for an external service"""
    service: str
    status: ServiceStatus
    last_checked: datetime
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    status_page_url: Optional[str] = None


class ExternalServiceMonitor:
    """
    Monitors health of external services to provide context for alert suppression.

    Checks:
    - Cloudflare API and status page
    - Multiple IP detection services (ipify, ipinfo, icanhazip)
    - Caches results to avoid excessive API calls
    """

    # Service health check configurations
    SERVICES = {
        "cloudflare_api": {
            "name": "Cloudflare API",
            "check_url": "https://api.cloudflare.com/client/v4/user/tokens/verify",
            "method": "GET",
            "timeout": 10,
            "status_page": "https://www.cloudflarestatus.com"
        },
        "cloudflare_status": {
            "name": "Cloudflare Status Page",
            "check_url": "https://www.cloudflarestatus.com/api/v2/status.json",
            "method": "GET",
            "timeout": 10,
            "status_page": "https://www.cloudflarestatus.com"
        },
        "ipify": {
            "name": "ipify.org",
            "check_url": "https://api.ipify.org?format=json",
            "method": "GET",
            "timeout": 5,
            "status_page": None
        },
        "ipinfo": {
            "name": "ipinfo.io",
            "check_url": "https://ipinfo.io/json",
            "method": "GET",
            "timeout": 5,
            "status_page": None
        },
        "icanhazip": {
            "name": "icanhazip.com",
            "check_url": "https://icanhazip.com",
            "method": "GET",
            "timeout": 5,
            "status_page": None
        }
    }

    def __init__(self, cache_ttl_seconds: int = 300):
        """
        Initialize external service monitor.

        Args:
            cache_ttl_seconds: How long to cache health check results (default 5 minutes)
        """
        self.logger = structlog.get_logger(__name__)
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._health_cache: Dict[str, ServiceHealth] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """Initialize HTTP session"""
        self._session = aiohttp.ClientSession()
        self.logger.info("external_service_monitor_started")

    async def stop(self):
        """Cleanup HTTP session"""
        if self._session:
            await self._session.close()
        self.logger.info("external_service_monitor_stopped")

    async def check_service_health(self, service_key: str, force_refresh: bool = False) -> ServiceHealth:
        """
        Check health of a specific external service.

        Args:
            service_key: Key from SERVICES dict
            force_refresh: Skip cache and force fresh check

        Returns:
            ServiceHealth object with current status
        """
        # Check cache first (unless force refresh)
        if not force_refresh and service_key in self._health_cache:
            cached = self._health_cache[service_key]
            age = datetime.utcnow() - cached.last_checked
            if age < self.cache_ttl:
                self.logger.debug(
                    "service_health_from_cache",
                    service=service_key,
                    status=cached.status.value,
                    age_seconds=int(age.total_seconds())
                )
                return cached

        # Perform fresh health check
        if service_key not in self.SERVICES:
            return ServiceHealth(
                service=service_key,
                status=ServiceStatus.UNKNOWN,
                last_checked=datetime.utcnow(),
                error_message=f"Unknown service: {service_key}"
            )

        config = self.SERVICES[service_key]
        health = await self._perform_health_check(service_key, config)

        # Update cache
        self._health_cache[service_key] = health

        return health

    async def _perform_health_check(self, service_key: str, config: dict) -> ServiceHealth:
        """
        Perform actual HTTP health check for a service.

        Args:
            service_key: Service identifier
            config: Service configuration dict

        Returns:
            ServiceHealth with check results
        """
        if not self._session:
            await self.start()

        start_time = datetime.utcnow()

        try:
            async with self._session.request(
                method=config["method"],
                url=config["check_url"],
                timeout=aiohttp.ClientTimeout(total=config["timeout"])
            ) as response:
                elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

                # Special handling for Cloudflare status page
                if service_key == "cloudflare_status":
                    data = await response.json()
                    cf_status = data.get("status", {}).get("indicator", "none")

                    if cf_status == "none":
                        status = ServiceStatus.OPERATIONAL
                    elif cf_status in ["minor", "major"]:
                        status = ServiceStatus.DEGRADED
                    elif cf_status == "critical":
                        status = ServiceStatus.OUTAGE
                    else:
                        status = ServiceStatus.UNKNOWN

                    self.logger.info(
                        "cloudflare_status_checked",
                        indicator=cf_status,
                        status=status.value,
                        response_time_ms=int(elapsed_ms)
                    )

                    return ServiceHealth(
                        service=config["name"],
                        status=status,
                        last_checked=datetime.utcnow(),
                        response_time_ms=elapsed_ms,
                        status_page_url=config["status_page"]
                    )

                # For other services, check HTTP status
                if 200 <= response.status < 300:
                    status = ServiceStatus.OPERATIONAL
                elif 500 <= response.status < 600:
                    status = ServiceStatus.OUTAGE
                else:
                    status = ServiceStatus.DEGRADED

                self.logger.info(
                    "service_health_checked",
                    service=service_key,
                    status=status.value,
                    http_status=response.status,
                    response_time_ms=int(elapsed_ms)
                )

                return ServiceHealth(
                    service=config["name"],
                    status=status,
                    last_checked=datetime.utcnow(),
                    response_time_ms=elapsed_ms,
                    status_page_url=config["status_page"]
                )

        except asyncio.TimeoutError:
            self.logger.warning(
                "service_health_timeout",
                service=service_key,
                timeout=config["timeout"]
            )
            return ServiceHealth(
                service=config["name"],
                status=ServiceStatus.OUTAGE,
                last_checked=datetime.utcnow(),
                error_message="Request timeout",
                status_page_url=config["status_page"]
            )

        except Exception as e:
            self.logger.error(
                "service_health_check_failed",
                service=service_key,
                error=str(e)
            )
            return ServiceHealth(
                service=config["name"],
                status=ServiceStatus.OUTAGE,
                last_checked=datetime.utcnow(),
                error_message=str(e),
                status_page_url=config["status_page"]
            )

    async def is_cloudflare_healthy(self) -> bool:
        """
        Quick check if Cloudflare is operational.

        Returns:
            True if Cloudflare API and status page are operational
        """
        # Check both API and status page
        api_health = await self.check_service_health("cloudflare_api")
        status_health = await self.check_service_health("cloudflare_status")

        # Consider healthy if BOTH are operational or degraded (not outage)
        return (
            api_health.status in [ServiceStatus.OPERATIONAL, ServiceStatus.DEGRADED] and
            status_health.status in [ServiceStatus.OPERATIONAL, ServiceStatus.DEGRADED]
        )

    async def get_working_ip_service(self) -> Optional[str]:
        """
        Find a working IP detection service.

        Returns:
            URL of first working service, or None if all are down
        """
        for service_key in ["ipify", "ipinfo", "icanhazip"]:
            health = await self.check_service_health(service_key)
            if health.status == ServiceStatus.OPERATIONAL:
                return self.SERVICES[service_key]["check_url"]

        self.logger.warning("all_ip_services_unavailable")
        return None

    async def get_all_service_health(self) -> Dict[str, ServiceHealth]:
        """
        Get health status for all monitored services.

        Returns:
            Dict mapping service keys to ServiceHealth objects
        """
        results = {}

        # Check all services in parallel
        tasks = [
            self.check_service_health(service_key)
            for service_key in self.SERVICES.keys()
        ]

        health_results = await asyncio.gather(*tasks, return_exceptions=True)

        for service_key, health in zip(self.SERVICES.keys(), health_results):
            if isinstance(health, Exception):
                results[service_key] = ServiceHealth(
                    service=self.SERVICES[service_key]["name"],
                    status=ServiceStatus.UNKNOWN,
                    last_checked=datetime.utcnow(),
                    error_message=str(health)
                )
            else:
                results[service_key] = health

        return results

    def clear_cache(self):
        """Clear health check cache (force fresh checks)"""
        self._health_cache.clear()
        self.logger.info("service_health_cache_cleared")
