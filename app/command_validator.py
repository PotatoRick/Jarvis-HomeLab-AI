"""
Command validation and safety checking.
Implements whitelist/blacklist pattern matching to prevent dangerous commands.

Phase 5 Enhancement: Self-preservation awareness - commands targeting Jarvis
dependencies can be allowed if they go through the n8n handoff mechanism.
"""

import re
import structlog
from typing import List, Tuple, Optional
from .models import CommandValidationResult, RiskLevel

logger = structlog.get_logger()


class CommandValidator:
    """Validates commands against whitelist and blacklist patterns."""

    # Dangerous patterns that should NEVER be executed
    DANGEROUS_PATTERNS = [
        # System-level destructive commands
        (r'rm\s+-rf', "Recursive deletion detected"),
        (r'rm\s+.*\*', "Wildcard deletion detected"),
        (r'\breboot\b', "System reboot detected"),
        (r'\bshutdown\b', "System shutdown detected"),
        (r'\bpoweroff\b', "System poweroff detected"),
        (r'\bhalt\b', "System halt detected"),

        # Firewall changes
        (r'\biptables\b', "Firewall modification detected"),
        (r'\bufw\b', "Firewall modification detected"),
        (r'\bnft\b', "Firewall modification detected"),

        # Container/service management restrictions
        (r'docker\s+rm(?!\s+--help)', "Container deletion detected"),
        (r'docker\s+volume\s+rm', "Volume deletion detected"),
        (r'systemctl\s+disable', "Service disable detected"),
        (r'systemctl\s+mask', "Service mask detected"),

        # Self-protection: prevent taking down Jarvis and dependencies
        # NOTE: These are tagged with _SELF_PROTECT for override capability
        (r'docker\s+stop\s+.*jarvis', "Cannot stop Jarvis (use /self-restart API)"),
        (r'docker\s+stop\s+.*postgres-jarvis', "Cannot stop Jarvis database (use /self-restart API)"),
        (r'docker\s+restart\s+.*jarvis', "Cannot restart Jarvis (use /self-restart API)"),
        (r'docker\s+restart\s+.*postgres-jarvis', "Cannot restart Jarvis database (use /self-restart API)"),
        # n8n-db is finance database, separate from Jarvis but still protected
        (r'docker\s+stop\s+.*n8n-db', "Cannot stop finance database"),
        (r'docker\s+restart\s+.*n8n-db', "Cannot restart finance database"),
        # Note: Allow skynet-backup.service but block other skynet services
        (r'systemctl\s+stop\s+skynet\.service', "Cannot stop Skynet main service"),
        (r'systemctl\s+restart\s+skynet\.service', "Cannot restart Skynet main service"),

        # File system modifications
        (r'sed\s+-i', "In-place file edit detected"),
        (r'>\s*/', "File overwrite detected"),
        (r'>>', "File append detected (potential risk)"),
        (r'\btee\b', "File write via tee detected"),

        # Package management
        (r'\bapt\b', "Package management detected"),
        (r'\bapt-get\b', "Package management detected"),
        (r'\bdpkg\b', "Package management detected"),
        (r'\byum\b', "Package management detected"),
        (r'\bdnf\b', "Package management detected"),

        # Disk operations
        (r'mkfs', "Filesystem creation detected"),
        (r'fdisk', "Disk partitioning detected"),
        (r'dd\s+', "Direct disk write detected"),

        # Code execution risks
        (r'curl.*\|\s*bash', "Pipe to bash detected"),
        (r'wget.*\|\s*bash', "Pipe to bash detected"),
        (r'\bkill\s+-9', "Forceful process termination detected"),
    ]

    # Self-protection patterns - these can be overridden with handoff
    # These are the only commands that the self-preservation system can execute
    SELF_PROTECTION_PATTERNS = [
        r'docker\s+(stop|restart)\s+.*jarvis',
        r'docker\s+(stop|restart)\s+.*postgres-jarvis',
        r'systemctl\s+restart\s+docker',
        r'\breboot\b',
    ]

    # SAFE_PATTERNS removed - now using blacklist-only approach
    # All commands are allowed unless they match a DANGEROUS_PATTERN above

    def __init__(self):
        """Initialize the command validator."""
        self.logger = logger.bind(component="command_validator")
        # Track if self-preservation handoff is active
        self._handoff_active = False
        self._handoff_id: Optional[str] = None

    def set_handoff_active(self, handoff_id: str) -> None:
        """
        Enable self-preservation mode, allowing protected commands.

        This should ONLY be called by the SelfPreservationManager when
        a handoff has been successfully initiated.

        Args:
            handoff_id: The active handoff ID for audit trail
        """
        self._handoff_active = True
        self._handoff_id = handoff_id
        self.logger.warning(
            "self_preservation_mode_enabled",
            handoff_id=handoff_id,
            message="Protected commands are now allowed"
        )

    def clear_handoff(self) -> None:
        """Clear self-preservation mode after handoff completes."""
        if self._handoff_active:
            self.logger.info(
                "self_preservation_mode_cleared",
                handoff_id=self._handoff_id
            )
        self._handoff_active = False
        self._handoff_id = None

    def is_self_protection_command(self, command: str) -> bool:
        """
        Check if a command targets Jarvis self-protection.

        Args:
            command: Command to check

        Returns:
            True if command targets Jarvis or its dependencies
        """
        for pattern in self.SELF_PROTECTION_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    def validate_command(
        self,
        command: str,
        allow_self_restart: bool = False
    ) -> Tuple[bool, RiskLevel, str]:
        """
        Validate a single command against safety rules.
        Uses blacklist-only approach: block dangerous commands, allow everything else.

        Args:
            command: The command to validate
            allow_self_restart: If True and handoff is active, allow self-restart commands

        Returns:
            Tuple of (is_safe, risk_level, reason)
        """
        command = command.strip()

        # Check if this is a self-protection command
        is_self_protect = self.is_self_protection_command(command)

        # If self-preservation handoff is active AND this is a self-restart command
        # AND the caller explicitly allows it, permit the command
        if is_self_protect and allow_self_restart and self._handoff_active:
            self.logger.warning(
                "self_restart_command_allowed_via_handoff",
                command=command,
                handoff_id=self._handoff_id,
                message="Command allowed because self-preservation handoff is active"
            )
            return True, RiskLevel.HIGH, f"Allowed via self-preservation handoff {self._handoff_id}"

        # Check dangerous patterns (blacklist)
        for pattern, reason in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                # Add guidance for self-restart attempts
                guidance = ""
                if is_self_protect:
                    guidance = " Use POST /self-restart API for safe self-restart via n8n handoff."

                self.logger.warning(
                    "dangerous_command_rejected",
                    command=command,
                    reason=reason,
                    pattern=pattern,
                    is_self_protect=is_self_protect
                )
                return False, RiskLevel.HIGH, reason + guidance

        # Default allow - command is safe if not in blacklist
        self.logger.info(
            "command_validated",
            command=command,
            risk_level="low"
        )
        return True, RiskLevel.LOW, "Command passed safety checks"

    def validate_commands(
        self,
        commands: List[str],
        allow_self_restart: bool = False
    ) -> CommandValidationResult:
        """
        Validate a list of commands.

        Args:
            commands: List of commands to validate
            allow_self_restart: If True, allow self-restart commands when handoff active

        Returns:
            CommandValidationResult with validation details
        """
        validated = []
        rejected = []
        reasons = []
        overall_safe = True
        max_risk = RiskLevel.LOW

        for cmd in commands:
            is_safe, risk_level, reason = self.validate_command(
                cmd,
                allow_self_restart=allow_self_restart
            )

            if is_safe:
                validated.append(cmd)
                # Track the highest risk level among safe commands
                if risk_level == RiskLevel.HIGH:
                    max_risk = RiskLevel.HIGH
                elif risk_level == RiskLevel.MEDIUM and max_risk == RiskLevel.LOW:
                    max_risk = RiskLevel.MEDIUM
            else:
                rejected.append(cmd)
                reasons.append(f"{cmd}: {reason}")
                overall_safe = False

        self.logger.info(
            "command_batch_validated",
            total_commands=len(commands),
            validated=len(validated),
            rejected=len(rejected),
            safe=overall_safe,
            max_risk=max_risk.value if overall_safe else "high",
            handoff_active=self._handoff_active
        )

        return CommandValidationResult(
            safe=overall_safe,
            validated_commands=validated,
            rejected_commands=rejected,
            rejection_reasons=reasons
        )

    def get_self_restart_guidance(self, command: str) -> str:
        """
        Get guidance for a blocked self-restart command.

        Args:
            command: The blocked command

        Returns:
            Helpful guidance string
        """
        if not self.is_self_protection_command(command):
            return "This command is not a self-restart command."

        return """This command targets Jarvis or its dependencies and is blocked for safety.

To safely restart Jarvis components, use the self-preservation mechanism:

1. Via API:
   POST /self-restart?target=jarvis&reason=Your+reason

   Valid targets: jarvis, postgres-jarvis, docker-daemon, skynet-host

2. Via curl:
   curl -X POST "http://localhost:8000/self-restart?target=jarvis&reason=Needs+restart" \\
        -u alertmanager:YOUR_PASSWORD

This triggers an n8n workflow that:
- Saves Jarvis's current state
- Performs the restart
- Polls until Jarvis is healthy
- Resumes any interrupted remediation

Never directly restart Jarvis - always use the handoff mechanism."""

    async def check_maintenance_mode(self) -> bool:
        """
        Check if system is in maintenance mode.

        Returns:
            True if in maintenance mode, False otherwise
        """
        # This will be implemented to query the database
        # For now, return False
        return False
