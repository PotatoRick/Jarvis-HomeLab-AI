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
from .homeassistant_client import ha_client, init_ha_client
from .n8n_client import n8n_client, init_n8n_client
from .runbook_manager import get_runbook_manager

logger = structlog.get_logger()


class ClaudeAgent:
    """Claude AI agent for intelligent alert remediation."""

    def __init__(self):
        """Initialize Claude API client."""
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.logger = logger.bind(component="claude_agent")

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
                            "enum": ["nexus", "homeassistant", "outpost"],
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
                            "enum": ["nexus", "homeassistant", "outpost"],
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
                            "enum": ["nexus", "homeassistant", "outpost"],
                            "description": "Which system the service is on"
                        },
                        "service_type": {
                            "type": "string",
                            "enum": ["docker", "systemd", "homeassistant"],
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
                            "enum": ["nexus", "homeassistant", "outpost"],
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
                            "default": false
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
                            "default": true
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
                elif service_type == "homeassistant":
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

                return {
                    "success": result.success,
                    "output": result.outputs[0] if result.outputs else "",
                    "exit_code": result.exit_codes[0] if result.exit_codes else -1
                }

            elif tool_name == "execute_safe_command":
                command = tool_input["command"]

                result = await ssh_executor.execute_commands(
                    host=host,
                    commands=[command]
                )

                return {
                    "success": result.success,
                    "output": result.outputs[0] if result.outputs else "",
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

        user_prompt = f"""# Alert Details
- **Alert Name:** {alert_name}
- **Instance:** {alert_instance}
- **Severity:** {severity}
- **Description:** {description}

{system_context_section}
{runbook_section}

Please diagnose this alert and attempt remediation. Use your tools first, then provide your final analysis."""

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
