"""
Claude AI agent for alert analysis and remediation suggestions.

v3.0 MAJOR OVERHAUL: Investigation-first approach with confidence-gated execution.

Key changes from v2.x:
- Added Skynet as a valid host (where Jarvis runs)
- New investigation tools: read_file, check_crontab, check_file_age, list_directory, test_connectivity
- Confidence-gated execution: actions limited by confidence level
- Adaptive iteration limits: 10 base, extends to 15 if making progress
- Self-verification before executing commands
- Investigation chain tracking for learning
- Hint extraction from alert descriptions
"""

import anthropic
import structlog
import json
import asyncio
from typing import Dict, List, Any, Optional
from .config import settings
from .models import ClaudeAnalysis, HostType, RiskLevel
from .ssh_executor import ssh_executor

logger = structlog.get_logger()


class ClaudeAgent:
    """Claude AI agent for intelligent alert remediation with investigation-first approach."""

    def __init__(self):
        """Initialize Claude API client."""
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.logger = logger.bind(component="claude_agent")
        # Rate limit retry configuration
        self.max_retries = 3
        self.base_delay = 10  # seconds
        # v3.0: Adaptive iteration limits
        self.base_iterations = 10
        self.extended_iterations = 15

    def _get_tools_definition(self) -> List[Dict[str, Any]]:
        """
        Define tools available to Claude for investigation and remediation.

        v3.0: Added investigation tools and Skynet host.

        Returns:
            List of tool definitions
        """
        return [
            # ============================================================
            # INVESTIGATION TOOLS (v3.0) - Read-only, always allowed
            # ============================================================
            {
                "name": "read_file",
                "description": "Read the contents of a file to understand configuration, scripts, or logs. Use this to trace data flows and understand what scripts do.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
                            "description": "Which system to read the file from"
                        },
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file to read"
                        },
                        "lines": {
                            "type": "integer",
                            "description": "Number of lines to read (default all, use for large files)",
                            "default": 0
                        }
                    },
                    "required": ["host", "path"]
                }
            },
            {
                "name": "check_crontab",
                "description": "Check cron jobs for a user on a system. Essential for diagnosing scheduled task issues.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
                            "description": "Which system to check crontab on"
                        },
                        "user": {
                            "type": "string",
                            "description": "User whose crontab to check (default: current user)",
                            "default": ""
                        }
                    },
                    "required": ["host"]
                }
            },
            {
                "name": "check_file_age",
                "description": "Check when a file was last modified. Useful for verifying if scripts ran recently or if data is stale.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
                            "description": "Which system to check"
                        },
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file"
                        }
                    },
                    "required": ["host", "path"]
                }
            },
            {
                "name": "list_directory",
                "description": "List files in a directory to understand structure and find relevant files.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
                            "description": "Which system to list directory on"
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory path to list"
                        },
                        "show_hidden": {
                            "type": "boolean",
                            "description": "Show hidden files (default: false)",
                            "default": False
                        }
                    },
                    "required": ["host", "path"]
                }
            },
            {
                "name": "test_connectivity",
                "description": "Test if a host can reach another host/service. Useful for network and VPN troubleshooting.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "from_host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
                            "description": "Host to test FROM"
                        },
                        "to_target": {
                            "type": "string",
                            "description": "Target to test (IP, hostname, or URL)"
                        },
                        "port": {
                            "type": "integer",
                            "description": "Port to test (optional, uses ping if not specified)"
                        }
                    },
                    "required": ["from_host", "to_target"]
                }
            },
            # ============================================================
            # DIAGNOSTIC TOOLS - Information gathering
            # ============================================================
            {
                "name": "gather_logs",
                "description": "Gather recent logs from a system service to understand what's happening. Use this to diagnose issues.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
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
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
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
            # ============================================================
            # REMEDIATION TOOLS - Require sufficient confidence
            # ============================================================
            {
                "name": "restart_service",
                "description": "Restart a Docker container, systemd service, or Home Assistant. This is a safe operation that often resolves issues. REQUIRES confidence >= 50%.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
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
                "description": "Execute a validated safe command on a system. Use for read-only commands or well-known safe operations. Commands are validated against a blacklist.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "enum": ["nexus", "homeassistant", "outpost", "skynet"],
                            "description": "Which system to execute on"
                        },
                        "command": {
                            "type": "string",
                            "description": "The command to execute (will be validated against blacklist)"
                        }
                    },
                    "required": ["host", "command"]
                }
            },
            # ============================================================
            # META TOOLS - For self-reflection
            # ============================================================
            {
                "name": "update_confidence",
                "description": "Update your confidence level based on what you've learned. Call this after gathering information to track your investigation progress.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "new_confidence": {
                            "type": "number",
                            "description": "New confidence level 0.0-1.0"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why confidence changed (what did you learn?)"
                        }
                    },
                    "required": ["new_confidence", "reason"]
                }
            },
            {
                "name": "verify_hypothesis",
                "description": "Before executing remediation, verify your hypothesis is correct. Call this to self-check before taking action.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hypothesis": {
                            "type": "string",
                            "description": "Your current hypothesis about the root cause"
                        },
                        "target_host": {
                            "type": "string",
                            "description": "Host where you plan to remediate"
                        },
                        "planned_action": {
                            "type": "string",
                            "description": "What you plan to do"
                        },
                        "alert_instance": {
                            "type": "string",
                            "description": "The instance from the alert (to check for mismatch)"
                        }
                    },
                    "required": ["hypothesis", "target_host", "planned_action", "alert_instance"]
                }
            }
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        current_confidence: float,
        investigation_steps: List[Dict]
    ) -> Dict[str, Any]:
        """
        Execute a tool call from Claude with confidence gating.

        Args:
            tool_name: Name of the tool
            tool_input: Tool parameters
            current_confidence: Current confidence level for gating
            investigation_steps: List to track investigation steps

        Returns:
            Tool execution result
        """
        self.logger.info(
            "executing_tool",
            tool_name=tool_name,
            tool_input=tool_input,
            confidence=current_confidence
        )

        try:
            # Get host (different parameter names for different tools)
            host_str = tool_input.get("host") or tool_input.get("from_host")
            if host_str:
                host = HostType(host_str)
            else:
                host = None

            # ============================================================
            # INVESTIGATION TOOLS (v3.0) - Always allowed
            # ============================================================

            if tool_name == "read_file":
                path = tool_input["path"]
                lines = tool_input.get("lines", 0)

                if lines > 0:
                    command = f"head -n {lines} '{path}'"
                else:
                    command = f"cat '{path}'"

                stdout, stderr, exit_code = await ssh_executor.execute_command(host, command)

                step = {
                    "tool": "read_file",
                    "host": host.value,
                    "command": command,
                    "purpose": f"Read file {path}",
                    "success": exit_code == 0
                }
                investigation_steps.append(step)

                if exit_code != 0:
                    return {"success": False, "error": stderr or "File not found or not readable"}

                return {
                    "success": True,
                    "content": stdout[:4000],  # Limit for context
                    "truncated": len(stdout) > 4000
                }

            elif tool_name == "check_crontab":
                user = tool_input.get("user", "")
                if user:
                    command = f"crontab -u {user} -l 2>/dev/null || echo 'No crontab for {user}'"
                else:
                    command = "crontab -l 2>/dev/null || echo 'No crontab for current user'"

                stdout, stderr, exit_code = await ssh_executor.execute_command(host, command)

                step = {
                    "tool": "check_crontab",
                    "host": host.value,
                    "command": command,
                    "purpose": f"Check crontab for user {user or 'current'}",
                    "success": True
                }
                investigation_steps.append(step)

                return {"success": True, "crontab": stdout}

            elif tool_name == "check_file_age":
                path = tool_input["path"]
                command = f"stat -c '%y' '{path}' 2>/dev/null && echo '---' && ls -la '{path}' 2>/dev/null"

                stdout, stderr, exit_code = await ssh_executor.execute_command(host, command)

                step = {
                    "tool": "check_file_age",
                    "host": host.value,
                    "command": command,
                    "purpose": f"Check age of {path}",
                    "success": exit_code == 0
                }
                investigation_steps.append(step)

                if exit_code != 0:
                    return {"success": False, "error": f"File not found: {path}"}

                return {"success": True, "file_info": stdout}

            elif tool_name == "list_directory":
                path = tool_input["path"]
                show_hidden = tool_input.get("show_hidden", False)
                flags = "-la" if show_hidden else "-l"
                command = f"ls {flags} '{path}' 2>/dev/null"

                stdout, stderr, exit_code = await ssh_executor.execute_command(host, command)

                step = {
                    "tool": "list_directory",
                    "host": host.value,
                    "command": command,
                    "purpose": f"List directory {path}",
                    "success": exit_code == 0
                }
                investigation_steps.append(step)

                if exit_code != 0:
                    return {"success": False, "error": f"Directory not found or not readable: {path}"}

                return {"success": True, "listing": stdout}

            elif tool_name == "test_connectivity":
                from_host = HostType(tool_input["from_host"])
                to_target = tool_input["to_target"]
                port = tool_input.get("port")

                if port:
                    # Test TCP connectivity
                    command = f"timeout 5 bash -c 'echo > /dev/tcp/{to_target}/{port}' 2>/dev/null && echo 'REACHABLE' || echo 'UNREACHABLE'"
                else:
                    # Test ping
                    command = f"ping -c 2 -W 2 {to_target} 2>/dev/null && echo 'REACHABLE' || echo 'UNREACHABLE'"

                stdout, stderr, exit_code = await ssh_executor.execute_command(from_host, command)

                step = {
                    "tool": "test_connectivity",
                    "host": from_host.value,
                    "command": command,
                    "purpose": f"Test connectivity from {from_host.value} to {to_target}",
                    "success": "REACHABLE" in stdout
                }
                investigation_steps.append(step)

                return {
                    "success": True,
                    "reachable": "REACHABLE" in stdout,
                    "output": stdout
                }

            # ============================================================
            # DIAGNOSTIC TOOLS
            # ============================================================

            elif tool_name == "gather_logs":
                logs = await ssh_executor.gather_logs(
                    host=host,
                    service_type=tool_input["service_type"],
                    service_name=tool_input.get("service_name"),
                    lines=tool_input.get("lines", 100)
                )

                step = {
                    "tool": "gather_logs",
                    "host": host.value,
                    "command": f"logs for {tool_input.get('service_name', 'system')}",
                    "purpose": f"Gather logs from {tool_input['service_type']} service",
                    "success": True
                }
                investigation_steps.append(step)

                return {
                    "success": True,
                    "logs": logs[:3000]  # Limit log size for context
                }

            elif tool_name == "check_service_status":
                status = await ssh_executor.check_service_status(
                    host=host,
                    service_name=tool_input["service_name"],
                    service_type=tool_input.get("service_type", "systemd")
                )

                step = {
                    "tool": "check_service_status",
                    "host": host.value,
                    "command": f"status of {tool_input['service_name']}",
                    "purpose": f"Check if {tool_input['service_name']} is running",
                    "success": True
                }
                investigation_steps.append(step)

                return {
                    "success": True,
                    "status": status
                }

            # ============================================================
            # REMEDIATION TOOLS - Confidence gated
            # ============================================================

            elif tool_name == "restart_service":
                # Check confidence threshold for restarts
                if current_confidence < 0.50:
                    return {
                        "success": False,
                        "error": f"Confidence too low ({current_confidence:.0%}) for restart. Need >= 50%. Gather more information first.",
                        "blocked_by_confidence": True
                    }

                service_type = tool_input["service_type"]
                service_name = tool_input["service_name"]

                if service_type == "docker":
                    command = f"docker restart {service_name}"
                elif service_type == "systemd":
                    command = f"sudo systemctl restart {service_name}"
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

                step = {
                    "tool": "restart_service",
                    "host": host.value,
                    "command": command,
                    "purpose": f"Restart {service_type} service {service_name}",
                    "success": result.success
                }
                investigation_steps.append(step)

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

                step = {
                    "tool": "execute_safe_command",
                    "host": host.value,
                    "command": command,
                    "purpose": "Execute custom command",
                    "success": result.success
                }
                investigation_steps.append(step)

                return {
                    "success": result.success,
                    "output": result.outputs[0] if result.outputs else "",
                    "exit_code": result.exit_codes[0] if result.exit_codes else -1
                }

            # ============================================================
            # META TOOLS
            # ============================================================

            elif tool_name == "update_confidence":
                new_confidence = tool_input["new_confidence"]
                reason = tool_input["reason"]

                self.logger.info(
                    "confidence_updated",
                    old_confidence=current_confidence,
                    new_confidence=new_confidence,
                    reason=reason
                )

                return {
                    "success": True,
                    "previous_confidence": current_confidence,
                    "new_confidence": new_confidence,
                    "acknowledged": True
                }

            elif tool_name == "verify_hypothesis":
                hypothesis = tool_input["hypothesis"]
                target_host = tool_input["target_host"]
                planned_action = tool_input["planned_action"]
                alert_instance = tool_input["alert_instance"]

                # Check for host mismatch
                instance_host = None
                if "nexus" in alert_instance.lower() or "192.168.0.11" in alert_instance:
                    instance_host = "nexus"
                elif "skynet" in alert_instance.lower() or "192.168.0.13" in alert_instance:
                    instance_host = "skynet"
                elif "outpost" in alert_instance.lower() or "72.60.163.242" in alert_instance:
                    instance_host = "outpost"
                elif "homeassistant" in alert_instance.lower() or "192.168.0.10" in alert_instance:
                    instance_host = "homeassistant"

                host_mismatch = instance_host and instance_host != target_host.lower()

                verification = {
                    "hypothesis_acknowledged": True,
                    "target_host": target_host,
                    "planned_action": planned_action,
                    "alert_instance_host": instance_host,
                    "host_mismatch_warning": host_mismatch,
                }

                if host_mismatch:
                    verification["warning"] = (
                        f"ATTENTION: Alert instance suggests '{instance_host}' but you plan to act on '{target_host}'. "
                        f"This may be correct (e.g., metrics scraped from one host but problem on another), "
                        f"but please verify this is intentional."
                    )

                return {"success": True, **verification}

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

    async def _call_claude_with_retry(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ):
        """
        Call Claude API with exponential backoff retry on rate limits.

        Args:
            system: System prompt
            messages: Conversation messages
            tools: Tool definitions

        Returns:
            Claude API response

        Raises:
            Exception: If all retries exhausted or non-retryable error
        """
        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=settings.claude_model,
                    max_tokens=settings.claude_max_tokens,
                    system=system,
                    messages=messages,
                    tools=tools,
                    temperature=0.0  # Deterministic for operational tasks
                )
                return response

            except anthropic.RateLimitError as e:
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt)
                    self.logger.warning(
                        "rate_limit_hit_retrying",
                        attempt=attempt + 1,
                        max_retries=self.max_retries,
                        retry_delay=delay,
                        error=str(e)
                    )
                    await asyncio.sleep(delay)
                else:
                    self.logger.error(
                        "rate_limit_exhausted",
                        attempts=self.max_retries,
                        error=str(e)
                    )
                    raise

            except Exception as e:
                self.logger.error(
                    "claude_api_error",
                    error=str(e),
                    attempt=attempt + 1
                )
                raise

    async def analyze_alert_with_tools(
        self,
        alert_data: Dict[str, Any],
        system_context: Optional[str] = None,
        hints: Optional[Dict[str, Any]] = None
    ) -> ClaudeAnalysis:
        """
        Analyze an alert using Claude with investigation-first approach.

        v3.0: Major overhaul with confidence tracking, hint integration, and
        adaptive iteration limits.

        Args:
            alert_data: Alert information
            system_context: Additional system documentation
            hints: Extracted hints from alert description

        Returns:
            ClaudeAnalysis with remediation plan and investigation chain
        """
        alert_name = alert_data.get("alert_name", "Unknown")
        alert_instance = alert_data.get("alert_instance", "unknown")
        severity = alert_data.get("severity", "warning")
        description = alert_data.get("description", "No description provided")

        # v3.0: Track confidence and investigation steps
        current_confidence = 0.25  # Start with low confidence
        investigation_steps = []

        # Build the enhanced v3.0 system prompt
        system_prompt = self._build_system_prompt_v3(hints)

        # Build hint context for Claude
        hint_context = ""
        if hints:
            if hints.get("remediation_host_hint"):
                hint_context += f"\n**IMPORTANT HINT**: Alert description mentions '{hints['remediation_host_hint']}' - this may be where the fix needs to happen, even if the instance label says something else.\n"
            if hints.get("suggested_commands"):
                hint_context += f"\n**Suggested commands from alert**: {', '.join(hints['suggested_commands'][:3])}\n"
            if hints.get("mentioned_paths"):
                hint_context += f"\n**Paths mentioned**: {', '.join(hints['mentioned_paths'][:3])}\n"

        system_context_section = f"# System Context\n{system_context}" if system_context else ""

        user_prompt = f"""# Alert Details
- **Alert Name:** {alert_name}
- **Instance:** {alert_instance}
- **Severity:** {severity}
- **Description:** {description}
{hint_context}
{system_context_section}

## Your Task
1. **INVESTIGATE FIRST** - Don't jump to fixes. Understand the problem.
2. Read the alert description carefully for hints about which system to check.
3. Use investigation tools to trace the root cause.
4. Update your confidence as you learn more.
5. Before executing remediation, call verify_hypothesis to sanity-check yourself.
6. Only then, provide remediation commands.

Current confidence: {current_confidence:.0%}
"""

        messages = [{"role": "user", "content": user_prompt}]
        tools = self._get_tools_definition()

        self.logger.info(
            "starting_claude_analysis",
            alert_name=alert_name,
            alert_instance=alert_instance,
            initial_confidence=current_confidence,
            has_hints=bool(hints)
        )

        # v3.0: Adaptive iteration limit
        max_iterations = self.base_iterations
        iteration = 0
        executed_commands = []
        making_progress = True

        while iteration < max_iterations:
            iteration += 1

            try:
                response = await self._call_claude_with_retry(
                    system=system_prompt,
                    messages=messages,
                    tools=tools
                )

                self.logger.info(
                    "claude_response_received",
                    stop_reason=response.stop_reason,
                    iteration=iteration,
                    confidence=current_confidence
                )

                if response.stop_reason == "tool_use":
                    tool_results = []

                    for block in response.content:
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_input = block.input

                            # Execute the tool
                            result = await self._execute_tool(
                                tool_name,
                                tool_input,
                                current_confidence,
                                investigation_steps
                            )

                            # Handle confidence update tool
                            if tool_name == "update_confidence" and result.get("success"):
                                new_conf = tool_input.get("new_confidence", current_confidence)
                                if new_conf != current_confidence:
                                    making_progress = True
                                    # Extend iterations if we're making progress
                                    if iteration > self.base_iterations - 2 and making_progress:
                                        max_iterations = self.extended_iterations
                                        self.logger.info(
                                            "extending_iterations",
                                            new_max=max_iterations,
                                            reason="making_progress"
                                        )
                                current_confidence = new_conf

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
                                        executed_commands.append(f"sudo systemctl restart {service_name}")

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result)
                            })

                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})

                elif response.stop_reason == "end_turn":
                    # Claude has finished - extract final analysis
                    final_text = ""
                    for block in response.content:
                        if hasattr(block, "text"):
                            final_text += block.text

                    analysis = self._parse_analysis_from_text(final_text, current_confidence, investigation_steps)

                    # If commands are empty and we executed some via tools, use those
                    if not analysis.commands and executed_commands:
                        analysis.commands = executed_commands

                    self.logger.info(
                        "claude_analysis_completed",
                        alert_name=alert_name,
                        risk=analysis.risk.value,
                        command_count=len(analysis.commands),
                        final_confidence=current_confidence,
                        investigation_steps=len(investigation_steps),
                        iterations_used=iteration
                    )

                    return analysis

                else:
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
            reasoning="Automated analysis exceeded iteration limit",
            confidence=current_confidence,
            investigation_steps=[{"step": i, **s} for i, s in enumerate(investigation_steps)]
        )

    def _build_system_prompt_v3(self, hints: Optional[Dict[str, Any]] = None) -> str:
        """
        Build the v3.0 system prompt with investigation-first approach.

        Args:
            hints: Optional hints extracted from alert

        Returns:
            System prompt string
        """
        hint_section = ""
        if hints:
            if hints.get("remediation_host_hint"):
                hint_section = f"""
## ALERT HINT DETECTED
The alert description mentions **{hints['remediation_host_hint']}**.
This is likely where you should investigate and remediate, even if the `instance` label says something else.
The `instance` label tells you where metrics are SCRAPED from, not necessarily where the PROBLEM is.
"""

        return f"""You are Jarvis v3.0, an intelligent AI SRE managing The Burrow homelab infrastructure.

## CRITICAL: INVESTIGATION-FIRST APPROACH
You are NOT a simple runbook executor. You are a THINKER. Before attempting any fix:
1. **Question everything** - The alert `instance` label may not be where the problem is
2. **Read the alert description** - It often contains hints about where to look
3. **Trace data flows** - Understand where data comes from before trying to fix
4. **Build confidence** - Start at 25% and increase as you learn

## INFRASTRUCTURE OVERVIEW
- **Nexus** (192.168.0.11): Main Docker host - Caddy, Frigate, AdGuard, Prometheus, Grafana, Vaultwarden
- **Home Assistant** (192.168.0.10): Automation hub with Zigbee2MQTT
- **Outpost** (72.60.163.242): VPS gateway - Headscale VPN, n8n, Actual Budget
- **Skynet** (192.168.0.13): Management - runs THIS AI remediation service, Ansible, backup scripts
{hint_section}
## DATA FLOW PATTERNS (IMPORTANT!)
Understanding these prevents you from fixing the wrong system:

1. **Backup Health Check**:
   - Script runs on **Skynet** (`/home/t1/homelab/scripts/backup/check_b2_backups.sh`)
   - Script SCPs metrics file to **Nexus** (`/var/lib/node_exporter/textfile_collector/`)
   - Prometheus on **Nexus** scrapes the metrics
   - Alert shows `instance: nexus` but problem may be on **Skynet** (cron job) or network (SCP failing)

2. **Prometheus Metrics**:
   - All metrics scraped BY Nexus FROM other systems
   - `instance: nexus` means scraped from Nexus
   - `instance: outpost` means scraped from Outpost via VPN
   - Scrape failures could be network, VPN, or the exporter itself

3. **VPN Connectivity**:
   - WireGuard site-to-site: Nexus (10.99.0.1) <-> Outpost (10.99.0.2)
   - Headscale: Remote access VPN (100.64.0.0/10 range)
   - VPN issues need checking BOTH endpoints

## CONFIDENCE-GATED EXECUTION
Your confidence level gates what actions you can take:
- **< 30%**: Only read-only investigation (read_file, check_crontab, logs)
- **30-50%**: Safe diagnostic commands
- **50-70%**: Can restart services if you have a clear hypothesis
- **70-90%**: Can apply learned patterns
- **> 90%**: Full remediation capability

Call `update_confidence` as you learn to track your progress.
Call `verify_hypothesis` before taking remediation action to sanity-check yourself.

## NEW INVESTIGATION TOOLS (USE THESE!)
- `read_file`: Read scripts and configs to understand what they do
- `check_crontab`: See scheduled jobs (ESSENTIAL for backup/monitoring alerts)
- `check_file_age`: When was a file last modified?
- `list_directory`: What files exist?
- `test_connectivity`: Can host A reach host B?

## COMMAND EXECUTION RULES
1. **Always use sudo** for systemctl commands: `sudo systemctl restart X`
2. Docker commands do NOT need sudo (user is in docker group)
3. Home Assistant uses `ha core restart` (no sudo needed)
4. On Skynet, you can run commands directly (Jarvis runs there)

## RESPONSE FORMAT
After investigation, provide your final analysis in this JSON format:

{{
  "analysis": "Root cause analysis based on your investigation",
  "commands": ["command1", "command2"],
  "risk": "low|medium|high",
  "expected_outcome": "What should happen after executing these commands",
  "reasoning": "Why these commands will resolve the issue, including investigation findings",
  "target_host": "host where commands should run (may differ from alert instance!)",
  "confidence": 0.75,
  "instance_label_misleading": true|false
}}

## SAFETY CONSTRAINTS
- Only use systemctl restart, docker restart, basic service management
- DO NOT suggest: reboots, data deletion, firewall changes, file edits
- If the issue requires human intervention, set risk="high" and say so
- Commands must be idempotent (safe to run multiple times)

## EXAMPLE INVESTIGATION

Alert: BackupHealthCheckStale, instance: nexus

BAD approach (v2.x): "Instance is nexus, restart cron on nexus"

GOOD approach (v3.0):
1. Read alert description: "Check cron job on Skynet"
2. Aha! Instance is nexus but hint says Skynet. Use check_crontab on skynet.
3. Found cron job exists. Use read_file to understand what the script does.
4. Script runs on Skynet, SCPs to Nexus. Use check_file_age on Nexus for the metrics file.
5. File is stale! Test connectivity - can Skynet SCP to Nexus?
6. Confidence now 70%+. Run the script manually on Skynet to test.
7. Verify hypothesis: "Problem is script not running, fix on Skynet not Nexus"
8. Execute fix with high confidence.

THINK before you act. You are smarter than a runbook."""

    def _parse_analysis_from_text(
        self,
        text: str,
        confidence: float,
        investigation_steps: List[Dict]
    ) -> ClaudeAnalysis:
        """
        Parse ClaudeAnalysis from response text.

        Args:
            text: Response text containing JSON
            confidence: Final confidence level
            investigation_steps: Investigation steps taken

        Returns:
            ClaudeAnalysis instance
        """
        try:
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)

            if json_match:
                json_str = json_match.group(0)

                # Clean up control characters that can break JSON parsing
                # Replace newlines in string values, remove other control chars
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)

                data = json.loads(json_str)

                return ClaudeAnalysis(
                    analysis=data.get("analysis", "No analysis provided"),
                    commands=data.get("commands", []),
                    risk=RiskLevel(data.get("risk", "high")),
                    expected_outcome=data.get("expected_outcome", "Unknown"),
                    reasoning=data.get("reasoning", "No reasoning provided"),
                    estimated_duration=data.get("estimated_duration", "unknown"),
                    target_host=data.get("target_host"),
                    confidence=data.get("confidence", confidence),
                    investigation_steps=investigation_steps,
                    instance_label_misleading=data.get("instance_label_misleading", False)
                )

        except json.JSONDecodeError as e:
            # Try a more aggressive cleanup for malformed JSON
            self.logger.warning(
                "json_parse_retry",
                error=str(e),
                attempting="aggressive_cleanup"
            )
            try:
                import re
                # Extract key fields manually if JSON is malformed
                analysis = re.search(r'"analysis"\s*:\s*"([^"]*)"', text)
                commands = re.findall(r'"commands"\s*:\s*\[(.*?)\]', text, re.DOTALL)
                risk = re.search(r'"risk"\s*:\s*"(\w+)"', text)

                cmd_list = []
                if commands:
                    cmd_list = re.findall(r'"([^"]+)"', commands[0])

                return ClaudeAnalysis(
                    analysis=analysis.group(1) if analysis else "Parsed from malformed response",
                    commands=cmd_list,
                    risk=RiskLevel(risk.group(1)) if risk else RiskLevel.HIGH,
                    expected_outcome="Extracted from malformed JSON",
                    reasoning=text[:300],
                    confidence=confidence,
                    investigation_steps=investigation_steps
                )
            except Exception:
                pass

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
            reasoning=text[:500],
            confidence=confidence,
            investigation_steps=investigation_steps
        )


# Global Claude agent instance
claude_agent = ClaudeAgent()
