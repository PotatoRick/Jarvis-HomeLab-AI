"""
Health Check Remediation - Autonomous Dockerfile fix for health check failures.

This module contains the intelligence to:
1. Diagnose why a container's health check is failing
2. Identify the fix (e.g., missing binary like curl)
3. Patch the Dockerfile to add the missing dependency
4. Rebuild and restart the container
5. Verify the fix worked (or rollback)

The tools in this module are designed to be called by Claude with minimal
reasoning required - the intelligence is baked into the tool itself.
"""

import structlog
import json
import re
import fnmatch
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .models import HostType
from .ssh_executor import ssh_executor

logger = structlog.get_logger()


class HealthCheckFailureType(Enum):
    """Types of health check failures we can diagnose."""
    MISSING_BINARY = "missing_binary"  # curl, wget, nc not found
    CONNECTION_REFUSED = "connection_refused"  # App not listening
    TIMEOUT = "timeout"  # Health check times out
    PERMISSION_DENIED = "permission_denied"  # Can't execute health check
    UNKNOWN = "unknown"  # Can't determine cause


@dataclass
class HealthCheckDiagnosis:
    """Result of diagnosing a health check failure."""
    failure_type: HealthCheckFailureType
    health_check_command: Optional[str] = None
    error_output: str = ""
    missing_binary: Optional[str] = None
    base_image: Optional[str] = None
    fix_available: bool = False
    suggested_fix: Optional[str] = None
    alternative_health_check: Optional[str] = None


@dataclass
class RemediationResult:
    """Result of attempting to fix a container."""
    success: bool
    reason: str = ""
    actions: List[str] = field(default_factory=list)
    commands_executed: List[str] = field(default_factory=list)
    dockerfile_patched: bool = False
    rollback_performed: bool = False


class HealthCheckRemediation:
    """
    Autonomous health check remediation tool.

    Contains all the intelligence to diagnose and fix health check issues
    so that Claude (even Haiku) just needs to call the tool.
    """

    # Maps error patterns to the binary that's missing and the apt package to install
    ERROR_PATTERNS: Dict[str, Tuple[str, str]] = {
        "curl: not found": ("curl", "curl"),
        "curl: command not found": ("curl", "curl"),
        "/bin/sh: curl: not found": ("curl", "curl"),
        "wget: not found": ("wget", "wget"),
        "wget: command not found": ("wget", "wget"),
        "/bin/sh: wget: not found": ("wget", "wget"),
        "nc: not found": ("nc", "netcat-openbsd"),
        "nc: command not found": ("nc", "netcat-openbsd"),
        "netcat: not found": ("nc", "netcat-openbsd"),
    }

    # Maps base image patterns to package manager commands
    PACKAGE_MANAGERS: Dict[str, str] = {
        "python:*-slim": "apt-get update && apt-get install -y --no-install-recommends {} && rm -rf /var/lib/apt/lists/*",
        "python:*": "apt-get update && apt-get install -y {} && rm -rf /var/lib/apt/lists/*",
        "debian:*": "apt-get update && apt-get install -y {} && rm -rf /var/lib/apt/lists/*",
        "ubuntu:*": "apt-get update && apt-get install -y {} && rm -rf /var/lib/apt/lists/*",
        "node:*-slim": "apt-get update && apt-get install -y --no-install-recommends {} && rm -rf /var/lib/apt/lists/*",
        "node:*": "apt-get update && apt-get install -y {} && rm -rf /var/lib/apt/lists/*",
        "alpine:*": "apk add --no-cache {}",
    }

    # Known Dockerfile paths for services (fallback if labels don't work)
    KNOWN_DOCKERFILE_PATHS: Dict[str, Dict[str, str]] = {
        "nexus": {
            "homepage-analytics": "/home/jordan/docker/home-stack/homepage-analytics/Dockerfile",
        },
        "skynet": {
            "jarvis": "/home/t1/homelab/projects/ai-remediation-service/Dockerfile",
        },
    }

    # Alternative health check commands that don't require extra packages
    ALTERNATIVE_HEALTH_CHECKS: Dict[str, str] = {
        "python": 'python -c "import urllib.request; urllib.request.urlopen(\'http://localhost:{port}/health\')"',
        "node": 'node -e "require(\'http\').get(\'http://localhost:{port}/health\', (r) => process.exit(r.statusCode === 200 ? 0 : 1))"',
        "wget": 'wget -q --spider http://localhost:{port}/health',
    }

    def __init__(self):
        """Initialize the health check remediation tool."""
        self.logger = logger.bind(component="health_check_remediation")

    async def diagnose_health_check_failure(
        self,
        host: str,
        container: str
    ) -> HealthCheckDiagnosis:
        """
        Diagnose why a container's health check is failing.

        Args:
            host: Host where container runs (nexus, homeassistant, outpost, skynet)
            container: Container name

        Returns:
            HealthCheckDiagnosis with failure details and suggested fix
        """
        self.logger.info(
            "diagnosing_health_check",
            host=host,
            container=container
        )

        try:
            # Step 1: Get health check configuration
            health_config = await self._get_health_check_config(host, container)
            if not health_config:
                return HealthCheckDiagnosis(
                    failure_type=HealthCheckFailureType.UNKNOWN,
                    error_output="Could not retrieve health check configuration"
                )

            # Docker inspect returns "Test" (capitalized) not "test"
            health_cmd = health_config.get("Test", [])
            if isinstance(health_cmd, list) and len(health_cmd) > 1:
                # Format: ["CMD", "curl", "-f", "http://localhost/health"]
                # or ["CMD-SHELL", "curl -f http://localhost/health"]
                if health_cmd[0] in ("CMD", "CMD-SHELL"):
                    health_cmd_str = " ".join(health_cmd[1:]) if health_cmd[0] == "CMD" else health_cmd[1]
                else:
                    health_cmd_str = " ".join(health_cmd)
            else:
                health_cmd_str = str(health_cmd)

            # Step 2: Run health check inside container to capture error
            error_output = await self._run_health_check_inside(host, container, health_cmd_str)

            # Step 3: Identify failure type and fix
            diagnosis = await self._analyze_error(host, container, health_cmd_str, error_output)

            self.logger.info(
                "diagnosis_complete",
                host=host,
                container=container,
                failure_type=diagnosis.failure_type.value,
                fix_available=diagnosis.fix_available
            )

            return diagnosis

        except Exception as e:
            self.logger.error(
                "diagnosis_failed",
                host=host,
                container=container,
                error=str(e)
            )
            return HealthCheckDiagnosis(
                failure_type=HealthCheckFailureType.UNKNOWN,
                error_output=f"Diagnosis failed: {str(e)}"
            )

    async def fix_container_crash_loop(
        self,
        host: str,
        container: str
    ) -> RemediationResult:
        """
        Autonomously fix a container stuck in a crash loop.

        This is the main entry point - it handles the full flow:
        1. Diagnose the health check failure
        2. Generate and apply Dockerfile fix
        3. Rebuild and restart container
        4. Verify the fix worked
        5. Rollback if it didn't

        Args:
            host: Host where container runs
            container: Container name

        Returns:
            RemediationResult with success status and actions taken
        """
        self.logger.info(
            "starting_crash_loop_fix",
            host=host,
            container=container
        )

        actions = []
        commands = []

        try:
            # Step 1: Diagnose
            diagnosis = await self.diagnose_health_check_failure(host, container)
            actions.append(f"Diagnosed: {diagnosis.failure_type.value}")

            if not diagnosis.fix_available:
                return RemediationResult(
                    success=False,
                    reason=f"No fix available for {diagnosis.failure_type.value}: {diagnosis.error_output}",
                    actions=actions
                )

            if diagnosis.failure_type != HealthCheckFailureType.MISSING_BINARY:
                return RemediationResult(
                    success=False,
                    reason=f"Can only auto-fix missing binary issues, got: {diagnosis.failure_type.value}",
                    actions=actions
                )

            # Step 2: Locate Dockerfile
            dockerfile_path = await self._locate_dockerfile(host, container)
            if not dockerfile_path:
                return RemediationResult(
                    success=False,
                    reason="Cannot locate Dockerfile for container",
                    actions=actions
                )
            actions.append(f"Located Dockerfile: {dockerfile_path}")

            # Step 3: Read current Dockerfile
            dockerfile_content = await self._read_file(host, dockerfile_path)
            if not dockerfile_content:
                return RemediationResult(
                    success=False,
                    reason="Cannot read Dockerfile content",
                    actions=actions
                )

            # Step 4: Create backup
            backup_path = await self._backup_dockerfile(host, dockerfile_path)
            if backup_path:
                actions.append(f"Created backup: {backup_path}")
                commands.append(f"cp {dockerfile_path} {backup_path}")

            # Step 5: Generate and apply patch
            patched_content = self._patch_dockerfile(
                dockerfile_content,
                diagnosis.base_image or "",
                diagnosis.missing_binary or "",
                diagnosis.suggested_fix or ""
            )

            if not patched_content:
                return RemediationResult(
                    success=False,
                    reason="Failed to generate Dockerfile patch",
                    actions=actions
                )

            # Step 6: Write patched Dockerfile
            write_success = await self._write_dockerfile(host, dockerfile_path, patched_content)
            if not write_success:
                return RemediationResult(
                    success=False,
                    reason="Failed to write patched Dockerfile",
                    actions=actions
                )
            actions.append(f"Patched Dockerfile to add {diagnosis.missing_binary}")

            # Step 7: Get compose directory and rebuild
            compose_dir = await self._get_compose_directory(host, container)
            if not compose_dir:
                # Try to infer from Dockerfile path
                compose_dir = str(dockerfile_path).rsplit("/", 1)[0]

            rebuild_success = await self._rebuild_container(host, container, compose_dir)
            if rebuild_success:
                actions.append(f"Rebuilt container image")
                commands.append(f"docker compose -f {compose_dir}/docker-compose.yml build {container}")
                commands.append(f"docker compose -f {compose_dir}/docker-compose.yml up -d {container}")
            else:
                # Rollback
                if backup_path:
                    await self._restore_backup(host, dockerfile_path, backup_path)
                    actions.append("Rolled back Dockerfile (rebuild failed)")
                return RemediationResult(
                    success=False,
                    reason="Container rebuild failed",
                    actions=actions,
                    commands_executed=commands,
                    rollback_performed=True
                )

            # Step 8: Verify health check passes
            import asyncio
            await asyncio.sleep(10)  # Give container time to start

            healthy = await self._verify_healthy(host, container)
            if healthy:
                actions.append("Verified container is now healthy")
                return RemediationResult(
                    success=True,
                    reason=f"Successfully fixed {container} by adding {diagnosis.missing_binary}",
                    actions=actions,
                    commands_executed=commands,
                    dockerfile_patched=True
                )
            else:
                # Rollback
                if backup_path:
                    await self._restore_backup(host, dockerfile_path, backup_path)
                    await self._rebuild_container(host, container, compose_dir)
                    actions.append("Rolled back Dockerfile and rebuilt (health check still failing)")
                return RemediationResult(
                    success=False,
                    reason="Health check still failing after fix",
                    actions=actions,
                    commands_executed=commands,
                    rollback_performed=True
                )

        except Exception as e:
            self.logger.error(
                "crash_loop_fix_failed",
                host=host,
                container=container,
                error=str(e)
            )
            return RemediationResult(
                success=False,
                reason=f"Fix failed with error: {str(e)}",
                actions=actions,
                commands_executed=commands
            )

    async def _get_health_check_config(
        self,
        host: str,
        container: str
    ) -> Optional[Dict[str, Any]]:
        """Get health check configuration from docker inspect."""
        cmd = f"docker inspect {container} --format='{{{{json .Config.Healthcheck}}}}'"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )

        if result.success and result.outputs:
            try:
                output = result.outputs[0].strip()
                if output and output != "null":
                    return json.loads(output)
            except json.JSONDecodeError:
                pass
        return None

    async def _run_health_check_inside(
        self,
        host: str,
        container: str,
        health_cmd: str
    ) -> str:
        """Run the health check command inside the container to capture error."""
        # Execute the health check command inside the container
        cmd = f"docker exec {container} sh -c '{health_cmd}' 2>&1"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )

        if result.outputs:
            return result.outputs[0]
        return ""

    async def _analyze_error(
        self,
        host: str,
        container: str,
        health_cmd: str,
        error_output: str
    ) -> HealthCheckDiagnosis:
        """Analyze error output to determine failure type and fix."""
        error_lower = error_output.lower()

        # Check for missing binary patterns
        for pattern, (binary, package) in self.ERROR_PATTERNS.items():
            if pattern.lower() in error_lower:
                # Get base image to determine package manager
                base_image = await self._get_base_image(host, container)
                pkg_cmd = self._get_install_command(base_image, package)

                return HealthCheckDiagnosis(
                    failure_type=HealthCheckFailureType.MISSING_BINARY,
                    health_check_command=health_cmd,
                    error_output=error_output,
                    missing_binary=binary,
                    base_image=base_image,
                    fix_available=True if pkg_cmd else False,
                    suggested_fix=f"RUN {pkg_cmd}" if pkg_cmd else None,
                    alternative_health_check=self._get_alternative_health_check(base_image, health_cmd)
                )

        # Check for connection refused
        if "connection refused" in error_lower or "could not connect" in error_lower:
            return HealthCheckDiagnosis(
                failure_type=HealthCheckFailureType.CONNECTION_REFUSED,
                health_check_command=health_cmd,
                error_output=error_output,
                fix_available=False  # This is usually a timing issue, not fixable via Dockerfile
            )

        # Check for timeout
        if "timeout" in error_lower or "timed out" in error_lower:
            return HealthCheckDiagnosis(
                failure_type=HealthCheckFailureType.TIMEOUT,
                health_check_command=health_cmd,
                error_output=error_output,
                fix_available=False
            )

        # Unknown error
        return HealthCheckDiagnosis(
            failure_type=HealthCheckFailureType.UNKNOWN,
            health_check_command=health_cmd,
            error_output=error_output,
            fix_available=False
        )

    async def _get_base_image(self, host: str, container: str) -> Optional[str]:
        """Get the base image of a container."""
        cmd = f"docker inspect {container} --format='{{{{.Config.Image}}}}'"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )

        if result.success and result.outputs:
            return result.outputs[0].strip()
        return None

    def _get_install_command(self, base_image: Optional[str], package: str) -> Optional[str]:
        """Get the package install command for a base image."""
        if not base_image:
            # Default to apt-get for unknown images
            return f"apt-get update && apt-get install -y --no-install-recommends {package} && rm -rf /var/lib/apt/lists/*"

        for pattern, template in self.PACKAGE_MANAGERS.items():
            if fnmatch.fnmatch(base_image, pattern):
                return template.format(package)

        # Default to apt-get
        return f"apt-get update && apt-get install -y --no-install-recommends {package} && rm -rf /var/lib/apt/lists/*"

    def _get_alternative_health_check(
        self,
        base_image: Optional[str],
        current_health_cmd: str
    ) -> Optional[str]:
        """Suggest an alternative health check that doesn't require extra packages."""
        if not base_image:
            return None

        # Extract port from health check if possible
        port_match = re.search(r':(\d+)', current_health_cmd)
        port = port_match.group(1) if port_match else "8080"

        if "python" in base_image.lower():
            return self.ALTERNATIVE_HEALTH_CHECKS["python"].format(port=port)
        elif "node" in base_image.lower():
            return self.ALTERNATIVE_HEALTH_CHECKS["node"].format(port=port)

        return None

    async def _locate_dockerfile(self, host: str, container: str) -> Optional[str]:
        """Locate the Dockerfile for a container."""
        # Try to get from docker-compose label
        cmd = f"docker inspect {container} --format='{{{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}}}'"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )

        if result.success and result.outputs:
            compose_dir = result.outputs[0].strip()
            if compose_dir:
                # Check for Dockerfile in compose directory
                check_cmd = f"test -f {compose_dir}/Dockerfile && echo 'exists'"
                check_result = await ssh_executor.execute_commands(
                    host=HostType(host),
                    commands=[check_cmd]
                )
                if check_result.success and check_result.outputs and "exists" in check_result.outputs[0]:
                    return f"{compose_dir}/Dockerfile"

                # Check for service-specific Dockerfile
                service_name = container.split("-")[0] if "-" in container else container
                service_dockerfile = f"{compose_dir}/{service_name}/Dockerfile"
                check_cmd = f"test -f {service_dockerfile} && echo 'exists'"
                check_result = await ssh_executor.execute_commands(
                    host=HostType(host),
                    commands=[check_cmd]
                )
                if check_result.success and check_result.outputs and "exists" in check_result.outputs[0]:
                    return service_dockerfile

        # Fall back to known paths
        if host in self.KNOWN_DOCKERFILE_PATHS:
            if container in self.KNOWN_DOCKERFILE_PATHS[host]:
                return self.KNOWN_DOCKERFILE_PATHS[host][container]

        return None

    async def _read_file(self, host: str, path: str) -> Optional[str]:
        """Read a file via SSH."""
        cmd = f"cat {path}"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )

        if result.success and result.outputs:
            return result.outputs[0]
        return None

    async def _backup_dockerfile(self, host: str, dockerfile_path: str) -> Optional[str]:
        """Create a backup of the Dockerfile."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{dockerfile_path}.backup-{timestamp}"

        cmd = f"cp {dockerfile_path} {backup_path}"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )

        if result.success:
            return backup_path
        return None

    def _patch_dockerfile(
        self,
        content: str,
        base_image: str,
        missing_binary: str,
        suggested_fix: str
    ) -> Optional[str]:
        """Patch Dockerfile to add missing package."""
        if not suggested_fix:
            return None

        lines = content.split("\n")
        patched_lines = []
        from_found = False

        for line in lines:
            patched_lines.append(line)
            # Add RUN command after FROM line
            if line.strip().upper().startswith("FROM ") and not from_found:
                from_found = True
                # Add a comment and the fix
                patched_lines.append(f"\n# Added by Jarvis to fix health check (missing {missing_binary})")
                patched_lines.append(suggested_fix)

        if not from_found:
            return None

        return "\n".join(patched_lines)

    async def _write_dockerfile(self, host: str, path: str, content: str) -> bool:
        """Write Dockerfile using heredoc to avoid blocked patterns."""
        # Escape any single quotes in content
        escaped_content = content.replace("'", "'\\''")

        # Use heredoc to write file
        cmd = f"""cat > {path} << 'DOCKERFILE_EOF'
{content}
DOCKERFILE_EOF"""

        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd],
            allow_dockerfile_ops=True
        )

        return result.success

    async def _get_compose_directory(self, host: str, container: str) -> Optional[str]:
        """Get the docker-compose directory for a container."""
        cmd = f"docker inspect {container} --format='{{{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}}}'"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )

        if result.success and result.outputs:
            return result.outputs[0].strip()
        return None

    async def _rebuild_container(
        self,
        host: str,
        container: str,
        compose_dir: str
    ) -> bool:
        """Rebuild and restart a container."""
        # Get service name from container name
        # Container names are usually like "service-1" or "project-service-1"
        service_name = container.split("-")[0] if "-" in container else container

        # Try to find the correct service name
        list_cmd = f"docker compose -f {compose_dir}/docker-compose.yml config --services"
        list_result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[list_cmd]
        )

        if list_result.success and list_result.outputs:
            services = list_result.outputs[0].strip().split("\n")
            # Find matching service
            for svc in services:
                if svc in container or container in svc:
                    service_name = svc
                    break

        # Build and restart
        build_cmd = f"docker compose -f {compose_dir}/docker-compose.yml build {service_name}"
        up_cmd = f"docker compose -f {compose_dir}/docker-compose.yml up -d {service_name}"

        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[build_cmd, up_cmd],
            allow_dockerfile_ops=True
        )

        return result.success

    async def _restore_backup(self, host: str, dockerfile_path: str, backup_path: str) -> bool:
        """Restore Dockerfile from backup."""
        cmd = f"cp {backup_path} {dockerfile_path}"
        result = await ssh_executor.execute_commands(
            host=HostType(host),
            commands=[cmd]
        )
        return result.success

    async def _verify_healthy(self, host: str, container: str, max_wait: int = 60) -> bool:
        """Verify container health check passes."""
        import asyncio

        for _ in range(max_wait // 5):
            cmd = f"docker inspect {container} --format='{{{{.State.Health.Status}}}}'"
            result = await ssh_executor.execute_commands(
                host=HostType(host),
                commands=[cmd]
            )

            if result.success and result.outputs:
                status = result.outputs[0].strip()
                if status == "healthy":
                    return True
                elif status == "unhealthy":
                    return False
                # Still starting, wait
            await asyncio.sleep(5)

        return False


# Singleton instance
health_check_remediation = HealthCheckRemediation()
