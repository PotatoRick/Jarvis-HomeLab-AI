"""
n8n workflow orchestration client for complex remediation operations.
Allows Jarvis to trigger multi-step workflows for database recovery,
certificate renewal, system health checks, and more.
"""

import asyncio
import httpx
import structlog
from typing import Optional, Dict, Any, List
from .config import settings

logger = structlog.get_logger()


class N8NClient:
    """Trigger n8n workflows for complex remediation operations."""

    # Known workflow names mapped to their use cases
    KNOWN_WORKFLOWS = {
        "jarvis-database-recovery": "Database backup, restore, and verify",
        "jarvis-certificate-renewal": "Certificate renewal and deployment",
        "jarvis-full-health-check": "Comprehensive system health check",
        "jarvis-docker-cleanup": "Clean up Docker resources across systems",
        "jarvis-backup-verify": "Verify all backup systems are current",
        "jarvis-service-recovery": "Full service recovery with verification",
    }

    def __init__(
        self,
        base_url: str = None,
        api_key: str = None
    ):
        """
        Initialize n8n client.

        Args:
            base_url: n8n API URL (default from config)
            api_key: n8n API key (default from config)
        """
        self.base_url = base_url or settings.n8n_url
        self.api_key = api_key or settings.n8n_api_key
        self.timeout = 30.0
        self.headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            self.headers["X-N8N-API-KEY"] = self.api_key

        self.logger = logger.bind(component="n8n_client")

    async def execute_workflow(
        self,
        workflow_id: str,
        data: Optional[Dict[str, Any]] = None,
        wait_for_completion: bool = True,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Trigger a workflow and optionally wait for completion.

        Args:
            workflow_id: n8n workflow ID
            data: Input data for the workflow
            wait_for_completion: If True, poll until workflow completes
            timeout: Max seconds to wait

        Returns:
            Workflow execution result
        """
        self.logger.info(
            "executing_workflow",
            workflow_id=workflow_id,
            wait=wait_for_completion,
            timeout=timeout
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Trigger workflow
                response = await client.post(
                    f"{self.base_url}/api/v1/workflows/{workflow_id}/execute",
                    headers=self.headers,
                    json={"data": data or {}}
                )

                if response.status_code != 200:
                    self.logger.error(
                        "workflow_trigger_failed",
                        workflow_id=workflow_id,
                        status=response.status_code,
                        response=response.text
                    )
                    return {
                        "success": False,
                        "error": f"Status {response.status_code}: {response.text}"
                    }

                execution = response.json()
                execution_id = execution.get("executionId") or execution.get("id")

                if not execution_id:
                    return {
                        "success": False,
                        "error": "No execution ID returned"
                    }

                self.logger.info(
                    "workflow_triggered",
                    workflow_id=workflow_id,
                    execution_id=execution_id
                )

                if not wait_for_completion:
                    return {
                        "success": True,
                        "execution_id": execution_id,
                        "status": "started"
                    }

                # Poll for completion
                return await self._poll_execution(execution_id, timeout)

        except Exception as e:
            self.logger.error(
                "workflow_execution_error",
                workflow_id=workflow_id,
                error=str(e)
            )
            return {"success": False, "error": str(e)}

    async def _poll_execution(
        self,
        execution_id: str,
        timeout: int
    ) -> Dict[str, Any]:
        """Poll for workflow execution completion."""
        poll_interval = 5
        max_polls = timeout // poll_interval

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(max_polls):
                await asyncio.sleep(poll_interval)

                try:
                    response = await client.get(
                        f"{self.base_url}/api/v1/executions/{execution_id}",
                        headers=self.headers
                    )

                    if response.status_code != 200:
                        continue

                    status_data = response.json()
                    finished = status_data.get("finished", False)

                    if finished:
                        status = status_data.get("status", "unknown")
                        success = status in ("success", "completed")

                        self.logger.info(
                            "workflow_completed",
                            execution_id=execution_id,
                            status=status,
                            success=success
                        )

                        return {
                            "success": success,
                            "execution_id": execution_id,
                            "status": status,
                            "data": status_data.get("data"),
                            "started_at": status_data.get("startedAt"),
                            "stopped_at": status_data.get("stoppedAt")
                        }

                except Exception as e:
                    self.logger.warning(
                        "poll_error",
                        execution_id=execution_id,
                        poll=i,
                        error=str(e)
                    )
                    continue

        self.logger.warning(
            "workflow_timeout",
            execution_id=execution_id,
            timeout=timeout
        )
        return {
            "success": False,
            "execution_id": execution_id,
            "error": f"Timeout after {timeout} seconds"
        }

    async def execute_workflow_by_name(
        self,
        workflow_name: str,
        data: Optional[Dict[str, Any]] = None,
        wait_for_completion: bool = True,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Execute a workflow by its name.

        Args:
            workflow_name: Human-readable workflow name
            data: Input data for the workflow
            wait_for_completion: If True, wait for completion
            timeout: Max seconds to wait

        Returns:
            Workflow execution result
        """
        workflow_id = await self.get_workflow_id_by_name(workflow_name)

        if not workflow_id:
            return {
                "success": False,
                "error": f"Workflow '{workflow_name}' not found"
            }

        return await self.execute_workflow(
            workflow_id=workflow_id,
            data=data,
            wait_for_completion=wait_for_completion,
            timeout=timeout
        )

    async def get_workflow_id_by_name(self, name: str) -> Optional[str]:
        """
        Find workflow ID by name.

        Args:
            name: Workflow name to search for

        Returns:
            Workflow ID or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/workflows",
                    headers=self.headers
                )

                if response.status_code != 200:
                    return None

                data = response.json()
                workflows = data.get("data", []) if isinstance(data, dict) else data

                for wf in workflows:
                    if wf.get("name") == name:
                        return wf.get("id")

                return None

        except Exception as e:
            self.logger.error(
                "get_workflow_by_name_error",
                name=name,
                error=str(e)
            )
            return None

    async def list_workflows(self) -> Dict[str, Any]:
        """
        List all available workflows.

        Returns:
            Dict with list of workflows
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/workflows",
                    headers=self.headers
                )

                if response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Status {response.status_code}"
                    }

                data = response.json()
                workflows = data.get("data", []) if isinstance(data, dict) else data

                return {
                    "success": True,
                    "workflows": [
                        {
                            "id": wf.get("id"),
                            "name": wf.get("name"),
                            "active": wf.get("active", False),
                            "created_at": wf.get("createdAt"),
                            "updated_at": wf.get("updatedAt")
                        }
                        for wf in workflows
                    ]
                }

        except Exception as e:
            self.logger.error("list_workflows_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """
        Get the status of a workflow execution.

        Args:
            execution_id: Execution ID to check

        Returns:
            Execution status details
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/executions/{execution_id}",
                    headers=self.headers
                )

                if response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Status {response.status_code}"
                    }

                data = response.json()
                return {
                    "success": True,
                    "execution_id": execution_id,
                    "status": data.get("status", "unknown"),
                    "finished": data.get("finished", False),
                    "started_at": data.get("startedAt"),
                    "stopped_at": data.get("stoppedAt"),
                    "workflow_id": data.get("workflowId"),
                    "mode": data.get("mode")
                }

        except Exception as e:
            self.logger.error(
                "get_execution_status_error",
                execution_id=execution_id,
                error=str(e)
            )
            return {"success": False, "error": str(e)}

    async def trigger_webhook(
        self,
        webhook_path: str,
        data: Optional[Dict[str, Any]] = None,
        method: str = "POST"
    ) -> Dict[str, Any]:
        """
        Trigger a workflow via webhook.

        Args:
            webhook_path: Webhook path (e.g., "/webhook/jarvis-remediation")
            data: Data to send with the webhook
            method: HTTP method (POST, GET)

        Returns:
            Webhook response
        """
        try:
            url = f"{self.base_url}{webhook_path}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                if method.upper() == "POST":
                    response = await client.post(
                        url,
                        json=data or {}
                    )
                else:
                    response = await client.get(
                        url,
                        params=data or {}
                    )

                return {
                    "success": response.status_code in (200, 201, 202),
                    "status_code": response.status_code,
                    "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
                }

        except Exception as e:
            self.logger.error(
                "trigger_webhook_error",
                webhook_path=webhook_path,
                error=str(e)
            )
            return {"success": False, "error": str(e)}


# Global n8n client instance
n8n_client: Optional[N8NClient] = None


def init_n8n_client() -> Optional[N8NClient]:
    """
    Initialize global n8n client.

    Returns:
        N8NClient instance or None if not configured
    """
    global n8n_client

    # Check if n8n is configured
    if not hasattr(settings, 'n8n_api_key') or not settings.n8n_api_key:
        logger.warning("n8n_client_not_configured", reason="N8N_API_KEY not set")
        return None

    n8n_client = N8NClient()
    logger.info("n8n_client_initialized", base_url=settings.n8n_url)
    return n8n_client
