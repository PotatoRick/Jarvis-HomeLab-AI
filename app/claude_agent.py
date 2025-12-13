"""
Claude AI agent for alert analysis and remediation suggestions.
Uses Claude API with function calling to provide tool-based remediation.
"""

import anthropic
import structlog
import json
from typing import Dict, List, Any, Optional
from .config import settings
from .models import ClaudeAnalysis, HostType, RiskLevel
from .ssh_executor import ssh_executor
from .loki_client import loki_client
from .prometheus_client import prometheus_client
from .ha-host_client import ha_client, init_ha_client
from .n8n_client import n8n_client, init_n8n_client
from .runbook_manager import get_runbook_manager

logger = structlog.get_logger()


class ClaudeAgent:
    """Claude AI agent for intelligent alert remediation."""

    def __init__(self):
        """Initialize Claude API client."""
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.logger = logger.bind(component="claude_agent")

        # Track current remediation context for self-restart handoff (Phase 5)
        self._current_context: Optional[Dict[str, Any]] = None

    def set_remediation_context(
        self,
        alert_name: str,
        alert_instance: str,
        alert_fingerprint: str,
        severity: str,
        attempt_number: int,
        target_host: str,
        service_name: Optional[str] = None,
        service_type: Optional[str] = None,
        hints: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Set the current remediation context for potential self-restart handoff.

        Called before starting analyze_alert_with_tools so context can be
        captured if a self-restart is triggered mid-remediation.

        Args:
            alert_name: Name of the alert being processed
            alert_instance: Instance identifier
            alert_fingerprint: Unique alert fingerprint
            severity: Alert severity level
            attempt_number: Current attempt number
            target_host: Target host for remediation
            service_name: Service being remediated
            service_type: Type of service (docker, systemd, etc.)
            hints: Extracted hints from alert
        """
        self._current_context = {
            "alert_name": alert_name,
            "alert_instance": alert_instance,
            "alert_fingerprint": alert_fingerprint,
            "severity": severity,
            "attempt_number": attempt_number,
            "target_host": target_host,
            "service_name": service_name,
            "service_type": service_type,
            "hints": hints,
            "commands_executed": [],
            "command_outputs": [],
            "diagnostic_info": {},
            "ai_analysis": None,
            "ai_reasoning": None,
            "planned_commands": [],
        }
        self.logger.debug(
            "remediation_context_set",
            alert_name=alert_name,
            target_host=target_host
        )

    def update_context_commands(
        self,
        command: str,
        output: str,
        success: bool
    ) -> None:
        """Update context with executed command results."""
        if self._current_context:
            self._current_context["commands_executed"].append(command)
            self._current_context["command_outputs"].append(output)
            self._current_context["diagnostic_info"][f"cmd_{len(self._current_context['commands_executed'])}"] = {
                "command": command,
                "success": success
            }

    def update_context_analysis(
        self,
        analysis: str,
        reasoning: str,
        planned_commands: List[str]
    ) -> None:
        """Update context with AI analysis results."""
        if self._current_context:
            self._current_context["ai_analysis"] = analysis
            self._current_context["ai_reasoning"] = reasoning
            self._current_context["planned_commands"] = planned_commands

    def get_remediation_context(self) -> Optional[Dict[str, Any]]:
        """Get the current remediation context for handoff."""
        return self._current_context

    def clear_remediation_context(self) -> None:
        """Clear the current remediation context after completion."""
        self._current_context = None

    def _get_tools_definition(self) -> List[Dict[str, Any]]:
        """
        Define tools available to Claude for remediation.

        Returns:
            List of tool definitions
        """
        return [
            {
                "name": "gather_logs",
                "description": "Gather recent logs from a system service to understand what's happening. Use this first to diagnose the issue.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["service-host", "ha-host", "vps-host", "management-host"],
                            "description": "Which system to gather logs from"
                        },
                        "service_type": {
                            "type": "string",
                            "enum": ["docker", "systemd", "system"],
                            "description": "Type of service (docker container, systemd service, or system logs)"
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Name of the service or container (not needed for system logs)"
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of log lines to retrieve (default 100)",
                            "default": 100
                        }
                    },
                    "required": ["host", "service_type"]
                }
            },
            {
                "name": "check_service_status",
                "description": "Check if a service is running and get its current status.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["service-host", "ha-host", "vps-host", "management-host"],
                            "description": "Which system to check"
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Name of the service or container"
                        },
                        "service_type": {
                            "type": "string",
                            "enum": ["docker", "systemd"],
                            "description": "Type of service",
                            "default": "systemd"
                        }
                    },
                    "required": ["host", "service_name"]
                }
            },
            {
                "name": "restart_service",
                "description": "Restart a Docker container, systemd service, or Home Assistant. This is a safe operation that often resolves issues.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["service-host", "ha-host", "vps-host", "management-host"],
                            "description": "Which system the service is on"
                        },
                        "service_type": {
                            "type": "string",
                            "enum": ["docker", "systemd", "ha-host"],
                            "description": "Type of service to restart"
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Name of the service or container (use 'core' for Home Assistant)"
                        }
                    },
                    "required": ["host", "service_type", "service_name"]
                }
            },
            {
                "name": "execute_safe_command",
                "description": "Execute a validated safe command on a system. Only use this for read-only commands or well-known safe operations.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["service-host", "ha-host", "vps-host", "management-host"],
                            "description": "Which system to execute on"
                        },
                        "command": {
                            "type": "string",
                            "description": "The command to execute (will be validated against whitelist)"
                        }
                    },
                    "required": ["host", "command"]
                }
            },
            {
                "name": "query_loki_logs",
                "description": "Query aggregated logs from Loki. Use this to find application-level errors, correlate events across services, or search for specific patterns in logs. This provides centralized log access without needing SSH.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "enum": ["container_errors", "service_logs", "search"],
                            "description": "Type of log query: container_errors (errors from specific container), service_logs (all logs from service), search (pattern search)"
                        },
                        "target": {
                            "type": "string",
                            "description": "Container name, service name, or search pattern depending on query_type"
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "How many minutes back to search (default: 15)",
                            "default": 15
                        }
                    },
                    "required": ["query_type", "target"]
                }
            },
            {
                "name": "query_metric_history",
                "description": "Query Prometheus for metric history and trends. Use to understand if a problem is getting worse, correlate with events, or predict resource exhaustion. Helpful for memory, disk, CPU trending.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "description": "Prometheus metric name (e.g., node_memory_MemAvailable_bytes, node_filesystem_avail_bytes, container_memory_working_set_bytes)"
                        },
                        "instance": {
                            "type": "string",
                            "description": "Target instance (e.g., 'hostname:9100' for node_exporter, 'hostname:9323' for Docker)"
                        },
                        "hours": {
                            "type": "integer",
                            "description": "Hours of history to query (default: 6)",
                            "default": 6
                        },
                        "predict_exhaustion": {
                            "type": "boolean",
                            "description": "If true, predict when metric will hit zero (useful for disk/memory)",
                            "default": False
                        }
                    },
                    "required": ["metric", "instance"]
                }
            },
            {
                "name": "restart_ha_addon",
                "description": "Restart a Home Assistant addon via Supervisor API. Use for Zigbee2MQTT, MQTT broker (Mosquitto), or other addon issues. Common addons: zigbee2mqtt, mosquitto/mqtt, matter, grafana, influxdb.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "addon_slug": {
                            "type": "string",
                            "description": "Addon name or slug (e.g., 'zigbee2mqtt', 'mosquitto', 'a0d7b954_zigbee2mqtt'). Common names are automatically resolved."
                        }
                    },
                    "required": ["addon_slug"]
                }
            },
            {
                "name": "reload_ha_automations",
                "description": "Reload all Home Assistant automations. Use when automations are stuck, not triggering, or after YAML changes.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_ha_addon_info",
                "description": "Get status and info about a Home Assistant addon. Use to check if an addon is running, what version it is, or if updates are available.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "addon_slug": {
                            "type": "string",
                            "description": "Addon name or slug (e.g., 'zigbee2mqtt', 'mosquitto')"
                        }
                    },
                    "required": ["addon_slug"]
                }
            },
            {
                "name": "execute_n8n_workflow",
                "description": "Execute an n8n workflow for complex multi-step operations. Use for database recovery, certificate renewal, system health checks, or any operation requiring multiple coordinated steps. Known workflows: jarvis-database-recovery, jarvis-certificate-renewal, jarvis-full-health-check, jarvis-docker-cleanup.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "workflow_name": {
                            "type": "string",
                            "description": "Workflow name (e.g., 'jarvis-database-recovery', 'jarvis-full-health-check')"
                        },
                        "data": {
                            "type": "object",
                            "description": "Optional input data for the workflow (key-value pairs)"
                        },
                        "wait_for_completion": {
                            "type": "boolean",
                            "description": "If true, wait for workflow to complete (default: true)",
                            "default": True
                        }
                    },
                    "required": ["workflow_name"]
                }
            },
            {
                "name": "list_n8n_workflows",
                "description": "List all available n8n workflows. Use to discover what workflows are available for complex operations.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "initiate_self_restart",
                "description": "Initiate a safe self-restart of Jarvis or its dependencies via n8n handoff. ONLY use this when you've determined that Jarvis itself, its database (postgres-jarvis), or the Docker daemon needs to be restarted to resolve an issue. This is the ONLY safe way to restart these components - direct restart commands are blocked. The restart is orchestrated by n8n which will: 1) Save current state, 2) Execute restart, 3) Poll until healthy, 4) Resume any interrupted work. Valid targets: jarvis, postgres-jarvis, docker-daemon, management-host-host.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "enum": ["jarvis", "postgres-jarvis", "docker-daemon", "management-host-host"],
                            "description": "What to restart: jarvis (the AI remediation container), postgres-jarvis (Jarvis database), docker-daemon (Docker service on Management-Host), management-host-host (full host reboot - use with extreme caution)"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Explanation of why this restart is needed (for audit trail)"
                        }
                    },
                    "required": ["target", "reason"]
                }
            }
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool call from Claude.

        MEDIUM-009 FIX: Added input validation for tool parameters.

        Args:
            tool_name: Name of the tool
            tool_input: Tool parameters

        Returns:
            Tool execution result
        """
        self.logger.info(
            "executing_tool",
            tool_name=tool_name,
            tool_input=tool_input
        )

        # MEDIUM-009 FIX: Validate tool input
        if not isinstance(tool_input, dict):
            return {
                "success": False,
                "error": f"Invalid tool input: expected dict, got {type(tool_input).__name__}"
            }

        # Validate required 'host' parameter for SSH-based tools
        ssh_tools = ["gather_logs", "check_service_status", "restart_service", "execute_safe_command"]
        if tool_name in ssh_tools:
            if "host" not in tool_input:
                return {
                    "success": False,
                    "error": f"Missing required parameter 'host' for tool '{tool_name}'"
                }

            host_value = tool_input.get("host")
            if not isinstance(host_value, str):
                return {
                    "success": False,
                    "error": f"Invalid 'host' parameter: expected string, got {type(host_value).__name__}"
                }

        try:
            # Only parse host for SSH-based tools
            host = HostType(tool_input["host"]) if tool_name in ssh_tools else None

            if tool_name == "gather_logs":
                logs = await ssh_executor.gather_logs(
                    host=host,
                    service_type=tool_input["service_type"],
                    service_name=tool_input.get("service_name"),
                    lines=tool_input.get("lines", 100)
                )
                return {
                    "success": True,
                    "logs": logs[:2000]  # Limit log size for context
                }

            elif tool_name == "check_service_status":
                status = await ssh_executor.check_service_status(
                    host=host,
                    service_name=tool_input["service_name"],
                    service_type=tool_input.get("service_type", "systemd")
                )
                return {
                    "success": True,
                    "status": status
                }

            elif tool_name == "restart_service":
                service_type = tool_input["service_type"]
                service_name = tool_input["service_name"]

                if service_type == "docker":
                    command = f"docker restart {service_name}"
                elif service_type == "systemd":
                    command = f"systemctl restart {service_name}"
                elif service_type == "ha-host":
                    command = "ha core restart"
                else:
                    return {
                        "success": False,
                        "error": f"Unknown service type: {service_type}"
                    }

                result = await ssh_executor.execute_commands(
                    host=host,
                    commands=[command]
                )

                # Phase 5: Track command execution for potential self-restart handoff
                output = result.outputs[0] if result.outputs else ""
                self.update_context_commands(command, output, result.success)

                return {
                    "success": result.success,
                    "output": output,
                    "exit_code": result.exit_codes[0] if result.exit_codes else -1
                }

            elif tool_name == "execute_safe_command":
                command = tool_input["command"]

                result = await ssh_executor.execute_commands(
                    host=host,
                    commands=[command]
                )

                # Phase 5: Track command execution for potential self-restart handoff
                output = result.outputs[0] if result.outputs else ""
                self.update_context_commands(command, output, result.success)

                return {
                    "success": result.success,
                    "output": output,
                    "exit_code": result.exit_codes[0] if result.exit_codes else -1
                }

            elif tool_name == "query_loki_logs":
                # Loki queries don't need SSH host validation
                query_type = tool_input.get("query_type")
                target = tool_input.get("target")
                minutes = tool_input.get("minutes", 15)

                try:
                    if query_type == "container_errors":
                        logs = await loki_client.get_container_errors(
                            container=target,
                            minutes=minutes
                        )
                    elif query_type == "service_logs":
                        logs = await loki_client.get_service_logs(
                            service=target,
                            minutes=minutes
                        )
                    elif query_type == "search":
                        logs = await loki_client.search_logs(
                            pattern=target,
                            minutes=minutes
                        )
                    else:
                        return {
                            "success": False,
                            "error": f"Unknown query_type: {query_type}"
                        }

                    return {
                        "success": True,
                        "logs": logs
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Loki query failed: {str(e)}"
                    }

            elif tool_name == "query_metric_history":
                # Prometheus queries don't need SSH host validation
                metric = tool_input.get("metric")
                instance = tool_input.get("instance")
                hours = tool_input.get("hours", 6)
                predict = tool_input.get("predict_exhaustion", False)

                if not metric or not instance:
                    return {
                        "success": False,
                        "error": "Both 'metric' and 'instance' are required"
                    }

                try:
                    # Get metric trend data
                    trend = await prometheus_client.get_metric_trend(
                        metric=metric,
                        instance=instance,
                        hours=hours
                    )

                    result = {
                        "success": True,
                        "trend": trend
                    }

                    # Optionally predict exhaustion
                    if predict:
                        prediction = await prometheus_client.predict_exhaustion(
                            metric=metric,
                            instance=instance,
                            threshold=0
                        )
                        result["exhaustion_prediction"] = prediction

                    return result

                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Prometheus query failed: {str(e)}"
                    }

            elif tool_name == "restart_ha_addon":
                # Home Assistant addon restart via Supervisor API
                addon_slug = tool_input.get("addon_slug")

                if not addon_slug:
                    return {
                        "success": False,
                        "error": "addon_slug is required"
                    }

                # Check if HA client is initialized
                if ha_client is None:
                    return {
                        "success": False,
                        "error": "Home Assistant client not configured (HA_TOKEN not set)"
                    }

                try:
                    result = await ha_client.restart_addon(addon_slug)
                    return result

                except Exception as e:
                    return {
                        "success": False,
                        "error": f"HA addon restart failed: {str(e)}"
                    }

            elif tool_name == "reload_ha_automations":
                # Reload Home Assistant automations
                if ha_client is None:
                    return {
                        "success": False,
                        "error": "Home Assistant client not configured (HA_TOKEN not set)"
                    }

                try:
                    result = await ha_client.reload_automations()
                    return result

                except Exception as e:
                    return {
                        "success": False,
                        "error": f"HA automation reload failed: {str(e)}"
                    }

            elif tool_name == "get_ha_addon_info":
                # Get Home Assistant addon info
                addon_slug = tool_input.get("addon_slug")

                if not addon_slug:
                    return {
                        "success": False,
                        "error": "addon_slug is required"
                    }

                if ha_client is None:
                    return {
                        "success": False,
                        "error": "Home Assistant client not configured (HA_TOKEN not set)"
                    }

                try:
                    result = await ha_client.get_addon_info(addon_slug)
                    return result

                except Exception as e:
                    return {
                        "success": False,
                        "error": f"HA addon info query failed: {str(e)}"
                    }

            elif tool_name == "execute_n8n_workflow":
                # Execute n8n workflow for complex operations
                workflow_name = tool_input.get("workflow_name")
                data = tool_input.get("data", {})
                wait = tool_input.get("wait_for_completion", True)

                if not workflow_name:
                    return {
                        "success": False,
                        "error": "workflow_name is required"
                    }

                if n8n_client is None:
                    return {
                        "success": False,
                        "error": "n8n client not configured (N8N_API_KEY not set)"
                    }

                try:
                    result = await n8n_client.execute_workflow_by_name(
                        workflow_name=workflow_name,
                        data=data,
                        wait_for_completion=wait,
                        timeout=300
                    )
                    return result

                except Exception as e:
                    return {
                        "success": False,
                        "error": f"n8n workflow execution failed: {str(e)}"
                    }

            elif tool_name == "list_n8n_workflows":
                # List available n8n workflows
                if n8n_client is None:
                    return {
                        "success": False,
                        "error": "n8n client not configured (N8N_API_KEY not set)"
                    }

                try:
                    result = await n8n_client.list_workflows()
                    return result

                except Exception as e:
                    return {
                        "success": False,
                        "error": f"n8n workflow list failed: {str(e)}"
                    }

            elif tool_name == "initiate_self_restart":
                # Phase 5: Self-preservation - safe self-restart via n8n handoff
                from .self_preservation import get_self_preservation_manager, SelfRestartTarget, RemediationContext

                target = tool_input.get("target")
                reason = tool_input.get("reason")

                if not target:
                    return {
                        "success": False,
                        "error": "target is required"
                    }

                if not reason:
                    return {
                        "success": False,
                        "error": "reason is required"
                    }

                # Validate target
                try:
                    restart_target = SelfRestartTarget(target)
                except ValueError:
                    valid_targets = [t.value for t in SelfRestartTarget]
                    return {
                        "success": False,
                        "error": f"Invalid target '{target}'. Valid targets: {valid_targets}"
                    }

                sp_mgr = get_self_preservation_manager()
                if sp_mgr is None:
                    return {
                        "success": False,
                        "error": "Self-preservation manager not initialized"
                    }

                # Build remediation context from current state (Phase 5 enhancement)
                remediation_ctx = None
                if self._current_context:
                    try:
                        remediation_ctx = RemediationContext(
                            alert_name=self._current_context.get("alert_name", "unknown"),
                            alert_instance=self._current_context.get("alert_instance", "unknown"),
                            alert_fingerprint=self._current_context.get("alert_fingerprint", "unknown"),
                            severity=self._current_context.get("severity", "warning"),
                            attempt_number=self._current_context.get("attempt_number", 1),
                            commands_executed=self._current_context.get("commands_executed", []),
                            command_outputs=self._current_context.get("command_outputs", []),
                            diagnostic_info=self._current_context.get("diagnostic_info", {}),
                            ai_analysis=self._current_context.get("ai_analysis"),
                            ai_reasoning=self._current_context.get("ai_reasoning"),
                            planned_commands=self._current_context.get("planned_commands", []),
                            target_host=self._current_context.get("target_host", "unknown"),
                            service_name=self._current_context.get("service_name"),
                            service_type=self._current_context.get("service_type"),
                        )
                        self.logger.info(
                            "remediation_context_passed_to_self_restart",
                            alert_name=remediation_ctx.alert_name,
                            commands_executed=len(remediation_ctx.commands_executed)
                        )
                    except Exception as e:
                        self.logger.warning(
                            "remediation_context_build_failed",
                            error=str(e)
                        )
                        # Continue without context - better than failing

                try:
                    result = await sp_mgr.initiate_self_restart(
                        target=restart_target,
                        reason=reason,
                        remediation_context=remediation_ctx  # Pass context for continuation after restart
                    )

                    if result.get("success"):
                        return {
                            "success": True,
                            "handoff_id": result.get("handoff_id"),
                            "message": f"Self-restart initiated for {target}. n8n will orchestrate the restart and resume.",
                            "note": "Jarvis will be temporarily unavailable during restart."
                        }
                    else:
                        return result

                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Self-restart initiation failed: {str(e)}"
                    }

            else:
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}"
                }

        except Exception as e:
            self.logger.error(
                "tool_execution_failed",
                tool_name=tool_name,
                error=str(e)
            )
            return {
                "success": False,
                "error": str(e)
            }

    async def analyze_alert_with_tools(
        self,
        alert_data: Dict[str, Any],
        system_context: Optional[str] = None,
        hints: Optional[Dict[str, Any]] = None
    ) -> ClaudeAnalysis:
        """
        Analyze an alert using Claude with function calling.

        v3.0: Now accepts hints parameter for investigation-first approach.

        Args:
            alert_data: Alert information
            system_context: Additional system documentation
            hints: Optional hints extracted from alert (target_host, remediation suggestions)

        Returns:
            ClaudeAnalysis with remediation plan
        """
        alert_name = alert_data.get("alert_name", "Unknown")
        alert_instance = alert_data.get("alert_instance", "unknown")
        severity = alert_data.get("severity", "warning")
        description = alert_data.get("description", "No description provided")

        # Phase 4: Get runbook context if available
        runbook_context = ""
        runbook_mgr = get_runbook_manager()
        if runbook_mgr:
            runbook_context = runbook_mgr.get_runbook_context(alert_name)
            if runbook_context:
                self.logger.info(
                    "runbook_found",
                    alert_name=alert_name,
                    runbook_included=True
                )

        # Build initial prompt
        system_prompt = """You are an AI SRE managing The Burrow homelab infrastructure. You receive alerts from Prometheus/Alertmanager and must diagnose and fix issues.

You have access to tools to gather logs, check service status, restart services, and execute safe commands. Use these tools to:

1. First, gather logs to understand what's happening
2. Check service status if needed
3. Based on your analysis, restart services or execute safe commands to fix the issue

After using tools to diagnose and attempt remediation, provide your final analysis in this exact JSON format:

{
  "analysis": "Brief root cause analysis based on what you found",
  "commands": ["command1", "command2"],
  "risk": "low|medium|high",
  "expected_outcome": "What should happen after executing these commands",
  "reasoning": "Why these commands will resolve the issue",
  "estimated_duration": "30 seconds"
}

SAFETY CONSTRAINTS:
- Only use systemctl restart, docker restart, basic service management
- DO NOT suggest: reboots, data deletion, firewall changes, file edits
- If the issue requires human intervention, set risk="high"
- Commands must be idempotent (safe to run multiple times)

The commands you list should reflect what you've already done via tools, or what should be done if you haven't used tools yet."""

        system_context_section = f"# System Context\n{system_context}" if system_context else ""
        runbook_section = f"\n{runbook_context}" if runbook_context else ""

        # v3.8.1: Include hints in the prompt for system-specific remediation
        hints_section = ""
        if hints:
            hints_lines = []
            if hints.get("system"):
                hints_lines.append(f"- **System:** {hints['system']}")
            if hints.get("target_host"):
                hints_lines.append(f"- **Target Host:** {hints['target_host']}")
            if hints.get("system_specific_command"):
                hints_lines.append(f"- **Recommended Command:** `{hints['system_specific_command']}`")
            if hints.get("remediation_hint"):
                hints_lines.append(f"- **Remediation Hint:** {hints['remediation_hint']}")
            if hints.get("suggested_remediation"):
                hints_lines.append(f"- **Suggested Remediation:** {hints['suggested_remediation']}")
            if hints_lines:
                hints_section = "# Remediation Hints\n" + "\n".join(hints_lines)
                self.logger.info(
                    "hints_included_in_prompt",
                    alert_name=alert_name,
                    hints_count=len(hints_lines),
                    has_system_specific_command=bool(hints.get("system_specific_command"))
                )

        user_prompt = f"""# Alert Details
- **Alert Name:** {alert_name}
- **Instance:** {alert_instance}
- **Severity:** {severity}
- **Description:** {description}

{hints_section}
{system_context_section}
{runbook_section}

Please diagnose this alert and attempt remediation. If a **Recommended Command** is provided above, use that exact command. Use your tools first, then provide your final analysis."""

        messages = [{"role": "user", "content": user_prompt}]
        tools = self._get_tools_definition()

        self.logger.info(
            "starting_claude_analysis",
            alert_name=alert_name,
            alert_instance=alert_instance
        )

        # Tool use loop (max 5 iterations to prevent infinite loops)
        max_iterations = 5
        iteration = 0
        executed_commands = []

        while iteration < max_iterations:
            iteration += 1

            try:
                response = self.client.messages.create(
                    model=settings.claude_model,
                    max_tokens=settings.claude_max_tokens,
                    system=system_prompt,
                    messages=messages,
                    tools=tools,
                    temperature=0.0  # Deterministic for operational tasks
                )

                self.logger.info(
                    "claude_response_received",
                    stop_reason=response.stop_reason,
                    iteration=iteration
                )

                # Check if Claude wants to use a tool
                if response.stop_reason == "tool_use":
                    # Process tool use blocks
                    tool_results = []

                    for block in response.content:
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_input = block.input

                            # Execute the tool
                            result = await self._execute_tool(tool_name, tool_input)

                            # Track commands for final analysis
                            if tool_name in ["restart_service", "execute_safe_command"]:
                                if "command" in tool_input:
                                    executed_commands.append(tool_input["command"])
                                elif tool_name == "restart_service":
                                    service_type = tool_input["service_type"]
                                    service_name = tool_input["service_name"]
                                    if service_type == "docker":
                                        executed_commands.append(f"docker restart {service_name}")
                                    elif service_type == "systemd":
                                        executed_commands.append(f"systemctl restart {service_name}")

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result)
                            })

                    # Add assistant's response and tool results to message history
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})

                elif response.stop_reason == "end_turn":
                    # Claude has finished - extract final analysis
                    final_text = ""
                    for block in response.content:
                        if hasattr(block, "text"):
                            final_text += block.text

                    # Try to parse JSON from response
                    analysis = self._parse_analysis_from_text(final_text)

                    # If commands are empty and we executed some via tools, use those
                    if not analysis.commands and executed_commands:
                        analysis.commands = executed_commands

                    # Phase 5: Update context with analysis for potential self-restart handoff
                    self.update_context_analysis(
                        analysis=analysis.analysis,
                        reasoning=analysis.reasoning,
                        planned_commands=analysis.commands
                    )

                    self.logger.info(
                        "claude_analysis_completed",
                        alert_name=alert_name,
                        risk=analysis.risk.value,
                        command_count=len(analysis.commands)
                    )

                    return analysis

                else:
                    # Unexpected stop reason
                    self.logger.warning(
                        "unexpected_stop_reason",
                        stop_reason=response.stop_reason
                    )
                    break

            except anthropic.APIError as e:
                self.logger.error(
                    "claude_api_error",
                    error=str(e)
                )
                raise

        # If we exit the loop without returning, provide a fallback
        self.logger.warning("max_iterations_reached", iterations=max_iterations)

        return ClaudeAnalysis(
            analysis="Analysis incomplete - max iterations reached",
            commands=executed_commands if executed_commands else [],
            risk=RiskLevel.HIGH,
            expected_outcome="Manual intervention required",
            reasoning="Automated analysis exceeded iteration limit"
        )

    def _parse_analysis_from_text(self, text: str) -> ClaudeAnalysis:
        """
        Parse ClaudeAnalysis from response text.

        Args:
            text: Response text containing JSON

        Returns:
            ClaudeAnalysis instance
        """
        try:
            # Try to find JSON block
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)

            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)

                return ClaudeAnalysis(
                    analysis=data.get("analysis", "No analysis provided"),
                    commands=data.get("commands", []),
                    risk=RiskLevel(data.get("risk", "high")),
                    expected_outcome=data.get("expected_outcome", "Unknown"),
                    reasoning=data.get("reasoning", "No reasoning provided"),
                    estimated_duration=data.get("estimated_duration", "unknown")
                )

        except Exception as e:
            self.logger.error(
                "analysis_parsing_failed",
                error=str(e),
                text=text[:500]
            )

        # Fallback
        return ClaudeAnalysis(
            analysis="Failed to parse analysis from response",
            commands=[],
            risk=RiskLevel.HIGH,
            expected_outcome="Manual review required",
            reasoning=text[:500]
        )


# Global Claude agent instance
claude_agent = ClaudeAgent()
