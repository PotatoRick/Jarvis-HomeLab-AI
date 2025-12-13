"""
SSH command execution on remote homelab systems.
Uses asyncssh for non-blocking SSH operations.
"""

import asyncio
import asyncssh
import os
import re
import stat
import structlog
from typing import List, Tuple, Optional
from datetime import datetime
from .config import settings
from .models import HostType, SSHExecutionResult

logger = structlog.get_logger()


# SECURITY-003 FIX: Patterns that indicate potential command injection
# Note: We allow 2>&1 (stderr redirect) as it's safe and commonly used
DANGEROUS_COMMAND_PATTERNS = [
    r';',                 # Command separator
    r'(?<!\d)&(?![\d>])', # Ampersand (background) but not 2>&1 or &>
    r'`',                 # Backtick command substitution
    r'\$\(',              # Command substitution
    r'\$\{',              # Variable expansion
    r'\$[A-Za-z_]',       # Variable reference
    r'>\s*/',             # Redirect to root paths
    r'>>\s*/',            # Append to root paths
    r'<\s*/',             # Read from root paths
    r'\|\s*bash',         # Pipe to shell
    r'\|\s*sh\b',         # Pipe to shell
    r'\beval\s',          # Eval command
    r'\bsource\s',        # Source command
    r'\bexec\s',          # Exec command
]

# Safe pipe patterns - these are read-only commands commonly used for diagnostics
# Each pattern is (left side regex, right side regex) for "left | right" commands
SAFE_PIPE_PATTERNS = [
    (r'dmesg', r'tail'),                    # dmesg | tail -N
    (r'dmesg', r'head'),                    # dmesg | head -N
    (r'dmesg', r'grep'),                    # dmesg | grep pattern
    (r'docker\s+ps', r'grep'),              # docker ps | grep name
    (r'docker\s+logs', r'tail'),            # docker logs | tail
    (r'docker\s+logs', r'grep'),            # docker logs | grep
    (r'systemctl\s+list', r'grep'),         # systemctl list-* | grep
    (r'journalctl', r'tail'),               # journalctl | tail
    (r'journalctl', r'grep'),               # journalctl | grep
    (r'cat\s', r'grep'),                    # cat file | grep
    (r'cat\s', r'head'),                    # cat file | head
    (r'cat\s', r'tail'),                    # cat file | tail
    (r'ls\s', r'grep'),                     # ls | grep
    (r'ps\s', r'grep'),                     # ps | grep
    (r'find\s', r'head'),                   # find | head
    (r'rclone\s+lsf', r'grep'),             # rclone lsf | grep
    (r'rclone\s+lsf', r'sort'),             # rclone lsf | sort
    (r'rclone\s+lsf', r'head'),             # rclone lsf | head
]

# Compiled pattern for efficiency
DANGEROUS_PATTERN_RE = re.compile('|'.join(DANGEROUS_COMMAND_PATTERNS))


def _is_safe_pipe_command(command: str) -> bool:
    """
    Check if a command containing a pipe matches safe pipe patterns.

    Args:
        command: Command string with pipe(s)

    Returns:
        True if the pipe usage matches a known safe pattern
    """
    if '|' not in command:
        return True

    # Split on pipes and check each pair
    parts = command.split('|')
    for i in range(len(parts) - 1):
        left = parts[i].strip()
        right = parts[i + 1].strip()

        # Check if this pipe matches any safe pattern
        is_safe_pair = False
        for left_pattern, right_pattern in SAFE_PIPE_PATTERNS:
            if re.search(left_pattern, left, re.IGNORECASE) and \
               re.match(right_pattern, right, re.IGNORECASE):
                is_safe_pair = True
                break

        if not is_safe_pair:
            return False

    return True


def validate_command_safety(command: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a command doesn't contain obvious injection attempts.

    SECURITY-003 FIX: Checks for shell metacharacters and dangerous patterns.
    Safe pipe patterns (like dmesg | tail) are explicitly allowed.

    Note: This is a defense-in-depth measure. The primary protection is the
    command whitelist in the Claude agent. This catches anything that slips through.

    Args:
        command: Command string to validate

    Returns:
        Tuple of (is_safe: bool, reason: Optional[str])
    """
    # Check for dangerous patterns first
    if DANGEROUS_PATTERN_RE.search(command):
        match = DANGEROUS_PATTERN_RE.search(command)
        return False, f"Dangerous pattern detected: '{match.group()}'"

    # Check for newlines (could be used to inject commands)
    if '\n' in command or '\r' in command:
        return False, "Newline characters not allowed in commands"

    # Check pipe commands against safe patterns
    if '|' in command and not _is_safe_pipe_command(command):
        return False, "Pipe to unknown command not allowed"

    return True, None


class SSHExecutor:
    """Executes commands on remote systems via SSH."""

    def __init__(self, host_monitor=None):
        """Initialize SSH executor."""
        self.logger = logger.bind(component="ssh_executor")
        self._connections = {}
        self.host_monitor = host_monitor  # Optional host monitor for tracking
        self._keys_validated = False

        # Host configuration mapping
        self.host_config = {
            HostType.NEXUS: {
                "host": settings.ssh_service-host_host,
                "username": settings.ssh_service-host_user,
                "client_keys": [settings.ssh_service-host_key_path],
            },
            HostType.HOMEASSISTANT: {
                "host": settings.ssh_ha-host_host,
                "username": settings.ssh_ha-host_user,
                "client_keys": [settings.ssh_ha-host_key_path],
            },
            HostType.OUTPOST: {
                "host": settings.ssh_vps-host_host,
                "username": settings.ssh_vps-host_user,
                "client_keys": [settings.ssh_vps-host_key_path],
            },
            HostType.SKYNET: {
                "host": settings.ssh_management-host_host,
                "username": settings.ssh_management-host_user,
                "client_keys": [settings.ssh_management-host_key_path],
            },
        }

    def validate_ssh_keys(self) -> dict:
        """
        Validate SSH keys exist and have correct permissions.

        CRITICAL-003 FIX: Validates SSH key files on startup to fail fast with clear
        error messages instead of cryptic SSH authentication failures.

        Returns:
            Dict with validation results for each host
        """
        results = {}
        seen_keys = set()

        for host_type, config in self.host_config.items():
            host_name = host_type.value

            # Skip localhost hosts (don't need SSH keys)
            if config["host"] == "localhost":
                results[host_name] = {"status": "skipped", "reason": "localhost"}
                continue

            for key_path in config["client_keys"]:
                # Skip if we already checked this key
                if key_path in seen_keys:
                    continue
                seen_keys.add(key_path)

                # Check if file exists
                if not os.path.exists(key_path):
                    results[host_name] = {
                        "status": "error",
                        "key_path": key_path,
                        "error": f"SSH key not found: {key_path}"
                    }
                    self.logger.error(
                        "ssh_key_not_found",
                        host=host_name,
                        key_path=key_path
                    )
                    continue

                # Check file permissions
                try:
                    file_stat = os.stat(key_path)
                    mode = file_stat.st_mode & 0o777

                    if mode != 0o600:
                        results[host_name] = {
                            "status": "error",
                            "key_path": key_path,
                            "permissions": oct(mode),
                            "error": f"SSH key has insecure permissions {oct(mode)}, must be 0o600. "
                                     f"Fix with: chmod 600 {key_path}"
                        }
                        self.logger.error(
                            "ssh_key_permissions_invalid",
                            host=host_name,
                            key_path=key_path,
                            actual_mode=oct(mode),
                            required_mode="0o600"
                        )
                    else:
                        results[host_name] = {
                            "status": "ok",
                            "key_path": key_path,
                            "permissions": oct(mode)
                        }
                        self.logger.info(
                            "ssh_key_validated",
                            host=host_name,
                            key_path=key_path
                        )
                except OSError as e:
                    results[host_name] = {
                        "status": "error",
                        "key_path": key_path,
                        "error": f"Cannot stat SSH key: {str(e)}"
                    }
                    self.logger.error(
                        "ssh_key_stat_failed",
                        host=host_name,
                        key_path=key_path,
                        error=str(e)
                    )

        self._keys_validated = True
        return results

    def get_key_validation_errors(self) -> list:
        """
        Get list of SSH key validation errors.

        Returns:
            List of error messages, empty if all keys are valid
        """
        results = self.validate_ssh_keys()
        errors = []

        for host, result in results.items():
            if result["status"] == "error":
                errors.append(f"{host}: {result['error']}")

        return errors

    async def _get_connection(self, host: HostType) -> asyncssh.SSHClientConnection:
        """
        Get or create SSH connection to a host.
        Reuses existing connections when available.

        Args:
            host: Target host type

        Returns:
            SSH connection object
        """
        # For localhost (VPS-Host or Management-Host when running locally), use subprocess instead
        if host == HostType.OUTPOST and settings.ssh_vps-host_host == "localhost":
            # Return None to signal we should use subprocess instead
            return None
        if host == HostType.SKYNET and settings.ssh_management-host_host == "localhost":
            # Management-Host is where Jarvis runs - execute locally
            return None

        # Check if we have an existing connection that's still alive
        if host in self._connections:
            conn = self._connections[host]
            if not conn.is_closed():
                self.logger.debug(
                    "reusing_ssh_connection",
                    host=host.value
                )
                return conn
            else:
                # Connection is closed, remove it
                del self._connections[host]

        config = self.host_config[host]

        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    host=config["host"],
                    username=config["username"],
                    client_keys=config["client_keys"],
                    known_hosts=None,  # Accept any host key (homelab environment)
                ),
                timeout=settings.ssh_connection_timeout
            )

            # Store connection for reuse
            self._connections[host] = conn

            self.logger.info(
                "ssh_connection_established",
                host=host.value,
                remote_host=config["host"]
            )

            # Record successful connection
            if self.host_monitor:
                await self.host_monitor.record_connection_attempt(
                    host.value,
                    success=True
                )

            return conn

        except asyncio.TimeoutError:
            self.logger.error(
                "ssh_connection_timeout",
                host=host.value,
                timeout=settings.ssh_connection_timeout
            )
            # Record failed connection
            if self.host_monitor:
                await self.host_monitor.record_connection_attempt(
                    host.value,
                    success=False,
                    error_message=f"Connection timeout after {settings.ssh_connection_timeout}s"
                )
            raise
        except Exception as e:
            self.logger.error(
                "ssh_connection_failed",
                host=host.value,
                error=str(e)
            )
            # Record failed connection
            if self.host_monitor:
                await self.host_monitor.record_connection_attempt(
                    host.value,
                    success=False,
                    error_message=str(e)
                )
            raise

    async def execute_command(
        self,
        host: HostType,
        command: str,
        timeout: Optional[int] = None,
        max_retries: int = 3
    ) -> Tuple[str, str, int]:
        """
        Execute a single command on a remote host with retry logic.

        Retries on connection errors only (not command failures).
        Uses exponential backoff: 2s, 4s, 8s.

        SECURITY-003 FIX: Validates command against dangerous patterns before execution.

        Args:
            host: Target host type
            command: Command to execute
            timeout: Execution timeout in seconds
            max_retries: Maximum retry attempts on connection errors

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        # SECURITY-003 FIX: Validate command safety before execution
        is_safe, reason = validate_command_safety(command)
        if not is_safe:
            self.logger.error(
                "command_rejected_unsafe",
                host=host.value,
                command=command[:100] + "..." if len(command) > 100 else command,
                reason=reason
            )
            return "", f"Command rejected: {reason}", -1

        timeout = timeout or settings.command_execution_timeout

        for attempt in range(max_retries):
            try:
                self.logger.info(
                    "executing_command",
                    host=host.value,
                    command=command,
                    timeout=timeout,
                    attempt=attempt + 1 if attempt > 0 else None
                )

                # Handle local execution (VPS-Host or Management-Host)
                if host == HostType.OUTPOST and settings.ssh_vps-host_host == "localhost":
                    return await self._execute_local(command, timeout)
                if host == HostType.SKYNET and settings.ssh_management-host_host == "localhost":
                    return await self._execute_local(command, timeout)

                # Remote execution via SSH
                conn = await self._get_connection(host)

                result = await asyncio.wait_for(
                    conn.run(command, check=False),
                    timeout=timeout
                )

                stdout = result.stdout.strip() if result.stdout else ""
                stderr = result.stderr.strip() if result.stderr else ""
                exit_code = result.exit_status

                # Don't close connection - keep it open for reuse

                self.logger.info(
                    "command_executed",
                    host=host.value,
                    exit_code=exit_code,
                    stdout_length=len(stdout),
                    stderr_length=len(stderr)
                )

                return stdout, stderr, exit_code

            except asyncio.TimeoutError:
                # Command timeout is not retryable (it's a command issue, not connection)
                self.logger.error(
                    "command_timeout",
                    host=host.value,
                    command=command,
                    timeout=timeout
                )
                return "", f"Command timed out after {timeout} seconds", -1

            except (ConnectionError, OSError, asyncssh.Error) as e:
                # These are connection errors - retry with backoff
                is_last_attempt = (attempt == max_retries - 1)

                self.logger.warning(
                    "ssh_connection_error_retry" if not is_last_attempt else "ssh_connection_error_failed",
                    host=host.value,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e)
                )

                if is_last_attempt:
                    # Final attempt failed
                    return "", f"SSH connection failed after {max_retries} attempts: {str(e)}", -1

                # Close stale connection before retry
                if host in self._connections:
                    try:
                        self._connections[host].close()
                        self.logger.debug(
                            "stale_connection_closed",
                            host=host.value
                        )
                    except Exception as cleanup_error:
                        # MEDIUM-011 FIX: Log cleanup failures instead of silent pass
                        self.logger.debug(
                            "connection_cleanup_failed",
                            host=host.value,
                            error=str(cleanup_error)
                        )
                    del self._connections[host]

                # Exponential backoff: 2s, 4s, 8s
                delay = 2 ** (attempt + 1)
                await asyncio.sleep(delay)

            except Exception as e:
                # Other errors (non-connection) - don't retry
                self.logger.error(
                    "command_execution_failed",
                    host=host.value,
                    command=command,
                    error=str(e)
                )
                return "", str(e), -1

        # Should never reach here
        return "", "Unexpected retry loop exit", -1

    async def _execute_local(
        self,
        command: str,
        timeout: int
    ) -> Tuple[str, str, int]:
        """
        Execute command locally using subprocess.

        HIGH-009 FIX: Handles sudo commands when running in Docker container.
        Since container runs as root, sudo is unnecessary and may not exist.

        Args:
            command: Command to execute
            timeout: Execution timeout

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        try:
            # HIGH-009 FIX: Strip sudo from commands when running in container
            # Container typically runs as root, and sudo may not be installed
            if os.path.exists('/.dockerenv'):
                if command.strip().startswith('sudo '):
                    command = command.replace('sudo ', '', 1)
                    self.logger.debug(
                        "stripped_sudo_in_container",
                        original_had_sudo=True
                    )

            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )

            stdout = stdout_bytes.decode('utf-8', errors='replace').strip()
            stderr = stderr_bytes.decode('utf-8', errors='replace').strip()
            exit_code = proc.returncode

            return stdout, stderr, exit_code

        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"Command timed out after {timeout} seconds", -1

        except Exception as e:
            return "", str(e), -1

    def _is_diagnostic_command(self, command: str) -> bool:
        """
        Check if a command is a diagnostic/read-only command.

        HIGH-002 FIX: Diagnostic commands should not stop batch execution on failure.
        For example, 'systemctl status' returns non-zero for inactive services,
        but we still want to run the restart command.

        Args:
            command: Command string to check

        Returns:
            True if command is diagnostic (continue on failure)
        """
        diagnostic_patterns = [
            'status', 'ps ', 'ps|', 'logs ', 'journalctl', 'systemctl is-active',
            'docker inspect', 'docker ps', 'cat ', 'head ', 'tail ', 'grep ',
            'ls ', 'df ', 'du ', 'free', 'uptime', 'top -b', 'netstat', 'ss ',
            'find ', 'which ', 'whereis ', 'file ', 'stat '
        ]
        cmd_lower = command.lower()
        return any(pattern in cmd_lower for pattern in diagnostic_patterns)

    # MEDIUM-003 FIX: Maximum command length to prevent injection/overflow
    MAX_COMMAND_LENGTH = 10000

    async def execute_commands(
        self,
        host: HostType,
        commands: List[str],
        timeout: Optional[int] = None
    ) -> SSHExecutionResult:
        """
        Execute a sequence of commands on a remote host.

        HIGH-002 FIX: Diagnostic commands (status, logs, etc.) no longer stop
        execution on failure. Only action commands stop the batch.

        MEDIUM-003 FIX: Commands exceeding MAX_COMMAND_LENGTH are rejected.

        Args:
            host: Target host type
            commands: List of commands to execute
            timeout: Total execution timeout

        Returns:
            SSHExecutionResult with execution details
        """
        start_time = datetime.utcnow()
        outputs = []
        exit_codes = []
        overall_success = True

        self.logger.info(
            "executing_command_batch",
            host=host.value,
            command_count=len(commands)
        )

        for cmd in commands:
            # MEDIUM-003 FIX: Validate command length
            if len(cmd) > self.MAX_COMMAND_LENGTH:
                self.logger.error(
                    "command_too_long",
                    host=host.value,
                    command_length=len(cmd),
                    max_length=self.MAX_COMMAND_LENGTH,
                    command_preview=cmd[:100] + "..."
                )
                outputs.append(f"Error: Command exceeds maximum length of {self.MAX_COMMAND_LENGTH} characters")
                exit_codes.append(-1)
                overall_success = False
                break
            stdout, stderr, exit_code = await self.execute_command(host, cmd, timeout)

            output = f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}" if stderr else stdout
            outputs.append(output)
            exit_codes.append(exit_code)

            if exit_code != 0:
                is_diagnostic = self._is_diagnostic_command(cmd)

                if is_diagnostic:
                    # HIGH-002 FIX: Continue on diagnostic command failure
                    self.logger.info(
                        "diagnostic_command_failed_continuing",
                        host=host.value,
                        command=cmd,
                        exit_code=exit_code
                    )
                    # Don't mark as overall failure for diagnostic commands
                    continue
                else:
                    overall_success = False
                    self.logger.warning(
                        "command_failed_in_batch",
                        host=host.value,
                        command=cmd,
                        exit_code=exit_code
                    )
                    # Stop execution on action command failure
                    break

        end_time = datetime.utcnow()
        duration = int((end_time - start_time).total_seconds())

        result = SSHExecutionResult(
            success=overall_success,
            commands=commands[:len(outputs)],  # Only commands that were executed
            outputs=outputs,
            exit_codes=exit_codes,
            duration_seconds=duration,
            error=None if overall_success else f"Command failed with exit code {exit_codes[-1]}"
        )

        self.logger.info(
            "command_batch_completed",
            host=host.value,
            success=overall_success,
            duration_seconds=duration,
            executed=len(outputs),
            total=len(commands)
        )

        return result

    async def gather_logs(
        self,
        host: HostType,
        service_type: str,
        service_name: Optional[str] = None,
        lines: int = 100
    ) -> str:
        """
        Gather logs from a service on a remote host.

        Args:
            host: Target host type
            service_type: Type of service (docker, systemd, system)
            service_name: Name of the service
            lines: Number of log lines to retrieve

        Returns:
            Log output as string
        """
        # Construct log command based on service type
        if service_type == "docker":
            command = f"docker logs --tail {lines} {service_name} 2>&1"
        elif service_type == "systemd":
            command = f"journalctl -u {service_name} -n {lines} --no-pager"
        elif service_type == "system":
            command = f"dmesg | tail -{lines}"
        else:
            raise ValueError(f"Unknown service type: {service_type}")

        self.logger.info(
            "gathering_logs",
            host=host.value,
            service_type=service_type,
            service_name=service_name,
            lines=lines
        )

        stdout, stderr, exit_code = await self.execute_command(host, command)

        if exit_code != 0:
            self.logger.warning(
                "log_gathering_failed",
                host=host.value,
                service_name=service_name,
                error=stderr
            )
            return f"Failed to gather logs: {stderr}"

        return stdout

    async def check_service_status(
        self,
        host: HostType,
        service_name: str,
        service_type: str = "systemd"
    ) -> str:
        """
        Check the status of a service.

        Args:
            host: Target host type
            service_name: Name of the service
            service_type: Type of service (systemd or docker)

        Returns:
            Status output as string
        """
        if service_type == "docker":
            command = f"docker ps --filter name={service_name} --format '{{{{.Status}}}}'"
        else:
            command = f"systemctl is-active {service_name}"

        stdout, stderr, exit_code = await self.execute_command(host, command)

        return stdout if exit_code == 0 else f"Error: {stderr}"

    async def close_all_connections(self):
        """
        Close all open SSH connections.
        Should be called on shutdown.
        """
        for host, conn in list(self._connections.items()):
            if not conn.is_closed():
                conn.close()
                self.logger.info(
                    "ssh_connection_closed",
                    host=host.value
                )
        self._connections.clear()


# Global SSH executor instance
ssh_executor = SSHExecutor()
