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

        # Validate required 'host' parameter for most tools
        if tool_name in ["gather_logs", "check_service_status", "restart_service", "execute_safe_command"]:
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
            host = HostType(tool_input["host"])

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

        user_prompt = f"""# Alert Details
- **Alert Name:** {alert_name}
- **Instance:** {alert_instance}
- **Severity:** {severity}
- **Description:** {description}

{system_context_section}

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
