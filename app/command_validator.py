"""
Command validation and safety checking.
Implements whitelist/blacklist pattern matching to prevent dangerous commands.
"""

import re
import structlog
from typing import List, Tuple
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
        (r'docker\s+stop\s+.*jarvis', "Cannot stop Jarvis (AI remediation service)"),
        (r'docker\s+stop\s+.*n8n-db', "Cannot stop finance database"),
        (r'docker\s+restart\s+.*jarvis', "Cannot restart Jarvis (AI remediation service)"),
        (r'docker\s+restart\s+.*n8n-db', "Cannot restart finance database"),
        (r'systemctl\s+stop\s+.*skynet', "Cannot stop Skynet services"),
        (r'systemctl\s+restart\s+.*skynet', "Cannot restart Skynet services"),

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

    # SAFE_PATTERNS removed - now using blacklist-only approach
    # All commands are allowed unless they match a DANGEROUS_PATTERN above

    def __init__(self):
        """Initialize the command validator."""
        self.logger = logger.bind(component="command_validator")

    def validate_command(self, command: str) -> Tuple[bool, RiskLevel, str]:
        """
        Validate a single command against safety rules.
        Uses blacklist-only approach: block dangerous commands, allow everything else.

        Args:
            command: The command to validate

        Returns:
            Tuple of (is_safe, risk_level, reason)
        """
        command = command.strip()

        # Check dangerous patterns (blacklist)
        for pattern, reason in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                self.logger.warning(
                    "dangerous_command_rejected",
                    command=command,
                    reason=reason,
                    pattern=pattern
                )
                return False, RiskLevel.HIGH, reason

        # Default allow - command is safe if not in blacklist
        self.logger.info(
            "command_validated",
            command=command,
            risk_level="low"
        )
        return True, RiskLevel.LOW, "Command passed safety checks"

    def validate_commands(self, commands: List[str]) -> CommandValidationResult:
        """
        Validate a list of commands.

        Args:
            commands: List of commands to validate

        Returns:
            CommandValidationResult with validation details
        """
        validated = []
        rejected = []
        reasons = []
        overall_safe = True
        max_risk = RiskLevel.LOW

        for cmd in commands:
            is_safe, risk_level, reason = self.validate_command(cmd)

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
            max_risk=max_risk.value if overall_safe else "high"
        )

        return CommandValidationResult(
            safe=overall_safe,
            validated_commands=validated,
            rejected_commands=rejected,
            rejection_reasons=reasons
        )

    async def check_maintenance_mode(self) -> bool:
        """
        Check if system is in maintenance mode.

        Returns:
            True if in maintenance mode, False otherwise
        """
        # This will be implemented to query the database
        # For now, return False
        return False
