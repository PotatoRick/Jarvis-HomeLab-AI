"""
SSH command execution on remote homelab systems.
Uses asyncssh for non-blocking SSH operations.
"""

import asyncio
import asyncssh
import structlog
from typing import List, Tuple, Optional
from datetime import datetime
from .config import settings
from .models import HostType, SSHExecutionResult

logger = structlog.get_logger()


class SSHExecutor:
    """Executes commands on remote systems via SSH."""

    def __init__(self, host_monitor=None):
        """Initialize SSH executor."""
        self.logger = logger.bind(component="ssh_executor")
        self._connections = {}
        self.host_monitor = host_monitor  # Optional host monitor for tracking

        # Host configuration mapping
        self.host_config = {
            HostType.NEXUS: {
                "host": settings.ssh_nexus_host,
                "username": settings.ssh_nexus_user,
                "client_keys": [settings.ssh_nexus_key_path],
            },
            HostType.HOMEASSISTANT: {
                "host": settings.ssh_homeassistant_host,
                "username": settings.ssh_homeassistant_user,
                "client_keys": [settings.ssh_homeassistant_key_path],
            },
            HostType.OUTPOST: {
                "host": settings.ssh_outpost_host,
                "username": settings.ssh_outpost_user,
                "client_keys": [settings.ssh_outpost_key_path],
            },
            HostType.SKYNET: {
                "host": settings.ssh_skynet_host,
                "username": settings.ssh_skynet_user,
                "client_keys": [settings.ssh_skynet_key_path],
            },
        }

    async def _get_connection(self, host: HostType) -> asyncssh.SSHClientConnection:
        """
        Get or create SSH connection to a host.
        Reuses existing connections when available.

        Args:
            host: Target host type

        Returns:
            SSH connection object
        """
        # For localhost (Outpost or Skynet when running locally), use subprocess instead
        if host == HostType.OUTPOST and settings.ssh_outpost_host == "localhost":
            # Return None to signal we should use subprocess instead
            return None
        if host == HostType.SKYNET and settings.ssh_skynet_host == "localhost":
            # Skynet is where Jarvis runs - execute locally
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

        Args:
            host: Target host type
            command: Command to execute
            timeout: Execution timeout in seconds
            max_retries: Maximum retry attempts on connection errors

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
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

                # Handle local execution (Outpost or Skynet)
                if host == HostType.OUTPOST and settings.ssh_outpost_host == "localhost":
                    return await self._execute_local(command, timeout)
                if host == HostType.SKYNET and settings.ssh_skynet_host == "localhost":
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
                    except:
                        pass
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

        Args:
            command: Command to execute
            timeout: Execution timeout

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        try:
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

    async def execute_commands(
        self,
        host: HostType,
        commands: List[str],
        timeout: Optional[int] = None
    ) -> SSHExecutionResult:
        """
        Execute a sequence of commands on a remote host.

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
            stdout, stderr, exit_code = await self.execute_command(host, cmd, timeout)

            output = f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}" if stderr else stdout
            outputs.append(output)
            exit_codes.append(exit_code)

            if exit_code != 0:
                overall_success = False
                self.logger.warning(
                    "command_failed_in_batch",
                    host=host.value,
                    command=cmd,
                    exit_code=exit_code
                )
                # Stop execution on first failure
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
