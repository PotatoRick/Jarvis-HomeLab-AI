"""
Home Assistant Supervisor API client for remediation actions.
Allows Jarvis to restart addons, reload automations, and interact with HA services.
"""

import httpx
import structlog
from typing import Optional, Dict, Any, List
from .config import settings

logger = structlog.get_logger()


class HomeAssistantClient:
    """Interact with Home Assistant for remediation actions."""

    # Known addon slugs for common services
    ADDON_SLUGS = {
        "zigbee2mqtt": "a0d7b954_zigbee2mqtt",
        "mosquitto": "core_mosquitto",
        "mqtt": "core_mosquitto",
        "z2m": "a0d7b954_zigbee2mqtt",
        "matter": "core_matter_server",
        "google_assistant": "core_google_assistant",
        "whisper": "core_whisper",
        "piper": "core_piper",
        "openwakeword": "core_openwakeword",
        "terminal": "core_ssh",
        "ssh": "core_ssh",
        "samba": "core_samba",
        "mariadb": "core_mariadb",
        "postgres": "local_postgres",
        "influxdb": "a0d7b954_influxdb",
        "grafana": "a0d7b954_grafana",
        "letsencrypt": "core_letsencrypt",
        "nginx": "core_nginx_proxy",
        "vscode": "a0d7b954_vscode",
    }

    def __init__(
        self,
        base_url: str = None,
        supervisor_url: str = None,
        token: str = None
    ):
        """
        Initialize Home Assistant client.

        Args:
            base_url: Home Assistant API URL (default from config)
            supervisor_url: Home Assistant Supervisor API URL (default from config)
            token: Long-lived access token (default from config)
        """
        self.base_url = base_url or settings.ha_url
        self.supervisor_url = supervisor_url or settings.ha_supervisor_url
        self.token = token or settings.ha_token
        self.timeout = 30.0
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.logger = logger.bind(component="homeassistant_client")

    def _resolve_addon_slug(self, addon: str) -> str:
        """
        Resolve addon name to full slug.

        Args:
            addon: Addon name or slug (e.g., "zigbee2mqtt" or "a0d7b954_zigbee2mqtt")

        Returns:
            Full addon slug
        """
        # If it looks like a full slug, use it directly
        if "_" in addon and len(addon) > 20:
            return addon

        # Try to resolve common names
        lower_addon = addon.lower().replace("-", "_").replace(" ", "_")
        if lower_addon in self.ADDON_SLUGS:
            return self.ADDON_SLUGS[lower_addon]

        # Return as-is if no mapping found
        return addon

    async def get_addon_info(self, addon_slug: str) -> Dict[str, Any]:
        """
        Get addon status and info.

        Args:
            addon_slug: Addon slug (e.g., "core_mosquitto")

        Returns:
            Dict with addon info or error
        """
        resolved_slug = self._resolve_addon_slug(addon_slug)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.supervisor_url}/addons/{resolved_slug}/info",
                    headers=self.headers
                )

                if response.status_code == 200:
                    data = response.json().get("data", {})
                    return {
                        "success": True,
                        "name": data.get("name", resolved_slug),
                        "slug": resolved_slug,
                        "state": data.get("state", "unknown"),
                        "version": data.get("version"),
                        "update_available": data.get("update_available", False),
                        "description": data.get("description", "")
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Status {response.status_code}: {response.text}"
                    }

        except Exception as e:
            self.logger.error("get_addon_info_failed", addon=resolved_slug, error=str(e))
            return {"success": False, "error": str(e)}

    async def restart_addon(self, addon_slug: str) -> Dict[str, Any]:
        """
        Restart a Home Assistant addon.

        Args:
            addon_slug: Addon slug (e.g., "core_mosquitto", "a0d7b954_zigbee2mqtt")

        Returns:
            Dict with success status and details
        """
        resolved_slug = self._resolve_addon_slug(addon_slug)

        self.logger.info("restarting_addon", addon=resolved_slug)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:  # Longer timeout for restart
                response = await client.post(
                    f"{self.supervisor_url}/addons/{resolved_slug}/restart",
                    headers=self.headers
                )

                success = response.status_code == 200
                result = {
                    "success": success,
                    "addon": resolved_slug,
                    "status_code": response.status_code
                }

                if not success:
                    result["error"] = response.text

                self.logger.info(
                    "addon_restart_complete",
                    addon=resolved_slug,
                    success=success,
                    status_code=response.status_code
                )

                return result

        except Exception as e:
            self.logger.error("restart_addon_failed", addon=resolved_slug, error=str(e))
            return {"success": False, "addon": resolved_slug, "error": str(e)}

    async def stop_addon(self, addon_slug: str) -> Dict[str, Any]:
        """
        Stop a Home Assistant addon.

        Args:
            addon_slug: Addon slug

        Returns:
            Dict with success status
        """
        resolved_slug = self._resolve_addon_slug(addon_slug)

        self.logger.info("stopping_addon", addon=resolved_slug)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.supervisor_url}/addons/{resolved_slug}/stop",
                    headers=self.headers
                )

                return {
                    "success": response.status_code == 200,
                    "addon": resolved_slug,
                    "status_code": response.status_code
                }

        except Exception as e:
            self.logger.error("stop_addon_failed", addon=resolved_slug, error=str(e))
            return {"success": False, "addon": resolved_slug, "error": str(e)}

    async def start_addon(self, addon_slug: str) -> Dict[str, Any]:
        """
        Start a Home Assistant addon.

        Args:
            addon_slug: Addon slug

        Returns:
            Dict with success status
        """
        resolved_slug = self._resolve_addon_slug(addon_slug)

        self.logger.info("starting_addon", addon=resolved_slug)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.supervisor_url}/addons/{resolved_slug}/start",
                    headers=self.headers
                )

                return {
                    "success": response.status_code == 200,
                    "addon": resolved_slug,
                    "status_code": response.status_code
                }

        except Exception as e:
            self.logger.error("start_addon_failed", addon=resolved_slug, error=str(e))
            return {"success": False, "addon": resolved_slug, "error": str(e)}

    async def list_addons(self) -> Dict[str, Any]:
        """
        List all installed addons.

        Returns:
            Dict with list of addons
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.supervisor_url}/addons",
                    headers=self.headers
                )

                if response.status_code == 200:
                    addons = response.json().get("data", {}).get("addons", [])
                    return {
                        "success": True,
                        "addons": [
                            {
                                "name": a.get("name"),
                                "slug": a.get("slug"),
                                "state": a.get("state"),
                                "version": a.get("version"),
                                "update_available": a.get("update_available", False)
                            }
                            for a in addons
                        ]
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Status {response.status_code}"
                    }

        except Exception as e:
            self.logger.error("list_addons_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def reload_automations(self) -> Dict[str, Any]:
        """
        Reload all Home Assistant automations.

        Returns:
            Dict with success status
        """
        self.logger.info("reloading_automations")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/services/automation/reload",
                    headers=self.headers
                )

                success = response.status_code == 200
                self.logger.info("automations_reloaded", success=success)

                return {
                    "success": success,
                    "service": "automation.reload"
                }

        except Exception as e:
            self.logger.error("reload_automations_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def reload_scripts(self) -> Dict[str, Any]:
        """
        Reload all Home Assistant scripts.

        Returns:
            Dict with success status
        """
        self.logger.info("reloading_scripts")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/services/script/reload",
                    headers=self.headers
                )

                return {
                    "success": response.status_code == 200,
                    "service": "script.reload"
                }

        except Exception as e:
            self.logger.error("reload_scripts_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def reload_scenes(self) -> Dict[str, Any]:
        """
        Reload all Home Assistant scenes.

        Returns:
            Dict with success status
        """
        self.logger.info("reloading_scenes")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/services/scene/reload",
                    headers=self.headers
                )

                return {
                    "success": response.status_code == 200,
                    "service": "scene.reload"
                }

        except Exception as e:
            self.logger.error("reload_scenes_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def call_service(
        self,
        domain: str,
        service: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Call any Home Assistant service.

        Args:
            domain: Service domain (e.g., "light", "switch", "automation")
            service: Service name (e.g., "turn_on", "reload")
            data: Optional service data

        Returns:
            Dict with success status
        """
        self.logger.info("calling_service", domain=domain, service=service)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/services/{domain}/{service}",
                    headers=self.headers,
                    json=data or {}
                )

                return {
                    "success": response.status_code in (200, 201),
                    "service": f"{domain}.{service}",
                    "status_code": response.status_code
                }

        except Exception as e:
            self.logger.error(
                "call_service_failed",
                domain=domain,
                service=service,
                error=str(e)
            )
            return {"success": False, "error": str(e)}

    async def restart_core(self) -> Dict[str, Any]:
        """
        Restart Home Assistant Core.

        Returns:
            Dict with success status
        """
        self.logger.warning("restarting_ha_core")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:  # Long timeout for core restart
                response = await client.post(
                    f"{self.supervisor_url}/core/restart",
                    headers=self.headers
                )

                return {
                    "success": response.status_code == 200,
                    "action": "core_restart",
                    "status_code": response.status_code
                }

        except Exception as e:
            self.logger.error("restart_core_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_core_info(self) -> Dict[str, Any]:
        """
        Get Home Assistant Core info and status.

        Returns:
            Dict with core info
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.supervisor_url}/core/info",
                    headers=self.headers
                )

                if response.status_code == 200:
                    data = response.json().get("data", {})
                    return {
                        "success": True,
                        "version": data.get("version"),
                        "state": data.get("state", "unknown"),
                        "arch": data.get("arch"),
                        "machine": data.get("machine"),
                        "boot": data.get("boot", False)
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Status {response.status_code}"
                    }

        except Exception as e:
            self.logger.error("get_core_info_failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def reload_config_entry(self, entry_id: str) -> Dict[str, Any]:
        """
        Reload a config entry (integration).

        Args:
            entry_id: Config entry ID

        Returns:
            Dict with success status
        """
        self.logger.info("reloading_config_entry", entry_id=entry_id)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/config/config_entries/entry/{entry_id}/reload",
                    headers=self.headers
                )

                return {
                    "success": response.status_code == 200,
                    "entry_id": entry_id
                }

        except Exception as e:
            self.logger.error(
                "reload_config_entry_failed",
                entry_id=entry_id,
                error=str(e)
            )
            return {"success": False, "error": str(e)}


# Global Home Assistant client instance
ha_client: Optional[HomeAssistantClient] = None


def init_ha_client() -> Optional[HomeAssistantClient]:
    """
    Initialize global Home Assistant client.

    Returns:
        HomeAssistantClient instance or None if not configured
    """
    global ha_client

    # Check if HA is configured
    if not hasattr(settings, 'ha_token') or not settings.ha_token:
        logger.warning("ha_client_not_configured", reason="HA_TOKEN not set")
        return None

    ha_client = HomeAssistantClient()
    logger.info("ha_client_initialized", base_url=settings.ha_url)
    return ha_client
