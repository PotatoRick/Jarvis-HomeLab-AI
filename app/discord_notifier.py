"""
Discord webhook notifications for remediation events.
Sends formatted alerts about successful/failed remediations and escalations.
"""

import aiohttp
import structlog
from typing import List, Optional
from datetime import datetime
from .config import settings
from .models import RemediationAttempt, RiskLevel

logger = structlog.get_logger()


class DiscordNotifier:
    """Sends notifications to Discord via webhook."""

    def __init__(self):
        """Initialize Discord notifier."""
        self.webhook_url = settings.discord_webhook_url
        self.enabled = settings.discord_enabled
        self.logger = logger.bind(component="discord_notifier")

    async def send_webhook(self, payload: dict) -> bool:
        """
        Send a webhook payload to Discord.

        Args:
            payload: Discord webhook JSON payload

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            self.logger.info("discord_disabled", message="Notification skipped")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 204:
                        self.logger.info("discord_notification_sent")
                        return True
                    else:
                        error_text = await response.text()
                        self.logger.error(
                            "discord_webhook_failed",
                            status=response.status,
                            error=error_text
                        )
                        return False

        except Exception as e:
            self.logger.error(
                "discord_webhook_exception",
                error=str(e)
            )
            return False

    async def notify_success(
        self,
        attempt: RemediationAttempt,
        execution_time: int,
        max_attempts: int
    ):
        """
        Notify about successful remediation.

        Args:
            attempt: RemediationAttempt instance
            execution_time: Execution time in seconds
        """
        commands_formatted = "\n".join(attempt.commands_executed)

        embed = {
            "title": "✅ Alert Auto-Remediated",
            "description": f"**{attempt.alert_name}** on `{attempt.alert_instance}` has been automatically fixed.",
            "color": 0x00ff00,  # Green
            "fields": [
                {
                    "name": "Severity",
                    "value": attempt.severity.upper(),
                    "inline": True
                },
                {
                    "name": "Attempt",
                    "value": f"{attempt.attempt_number}/{max_attempts}",
                    "inline": True
                },
                {
                    "name": "Duration",
                    "value": f"{execution_time} seconds",
                    "inline": True
                },
                {
                    "name": "AI Analysis",
                    "value": attempt.ai_analysis[:1000] if attempt.ai_analysis else "No analysis",
                    "inline": False
                },
                {
                    "name": "Commands Executed",
                    "value": f"```bash\n{commands_formatted[:1000]}\n```",
                    "inline": False
                },
                {
                    "name": "Expected Outcome",
                    "value": attempt.remediation_plan[:500] if attempt.remediation_plan else "Service restored",
                    "inline": False
                }
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": "Jarvis"
            }
        }

        payload = {
            "username": "Jarvis",
            "embeds": [embed]
        }

        await self.send_webhook(payload)

    async def notify_failure(
        self,
        attempt: RemediationAttempt,
        execution_time: int,
        max_attempts: int
    ):
        """
        Notify about failed remediation.

        Args:
            attempt: RemediationAttempt instance
            execution_time: Execution time in seconds
            max_attempts: Maximum attempts allowed
        """
        commands_formatted = "\n".join(attempt.commands_executed) if attempt.commands_executed else "No commands executed"
        error_msg = attempt.error_message or "Unknown error"

        embed = {
            "title": "⚠️ Auto-Remediation Failed",
            "description": f"**{attempt.alert_name}** on `{attempt.alert_instance}` - Attempt {attempt.attempt_number}/{max_attempts}",
            "color": 0xffa500,  # Orange
            "fields": [
                {
                    "name": "Severity",
                    "value": attempt.severity.upper(),
                    "inline": True
                },
                {
                    "name": "Attempts Remaining",
                    "value": str(max_attempts - attempt.attempt_number),
                    "inline": True
                },
                {
                    "name": "Duration",
                    "value": f"{execution_time} seconds",
                    "inline": True
                },
                {
                    "name": "Error",
                    "value": f"```\n{error_msg[:1000]}\n```",
                    "inline": False
                },
                {
                    "name": "Commands Attempted",
                    "value": f"```bash\n{commands_formatted[:1000]}\n```",
                    "inline": False
                }
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": "Jarvis"
            }
        }

        payload = {
            "username": "Jarvis",
            "embeds": [embed]
        }

        await self.send_webhook(payload)

    async def notify_escalation(
        self,
        attempt: RemediationAttempt,
        previous_attempts: List[dict]
    ):
        """
        Notify about alert escalation after max attempts.

        Args:
            attempt: Current RemediationAttempt
            previous_attempts: List of previous attempt details
        """
        # Build summary of previous attempts
        attempts_summary = []
        for i, prev in enumerate(previous_attempts[:3], 1):
            cmd_list = ", ".join(prev.get("commands_executed", [])[:2])
            attempts_summary.append(
                f"{i}. {cmd_list} - {'✓ Success' if prev.get('success') else '✗ Failed'}"
            )

        attempts_text = "\n".join(attempts_summary) if attempts_summary else "No previous attempts"

        embed = {
            "title": "🚨 Alert Escalation Required",
            "description": f"**{attempt.alert_name}** on `{attempt.alert_instance}` has failed auto-remediation {len(previous_attempts)} times.",
            "color": 0xff0000,  # Red
            "fields": [
                {
                    "name": "Severity",
                    "value": attempt.severity.upper(),
                    "inline": True
                },
                {
                    "name": "Total Attempts",
                    "value": str(len(previous_attempts)),
                    "inline": True
                },
                {
                    "name": "Urgency",
                    "value": "🔴 HIGH" if attempt.severity == "critical" else "🟡 MEDIUM",
                    "inline": True
                },
                {
                    "name": "Summary",
                    "value": attempt.ai_analysis[:1000] if attempt.ai_analysis else "Automated remediation exhausted",
                    "inline": False
                },
                {
                    "name": "Previous Attempts",
                    "value": attempts_text[:1000],
                    "inline": False
                },
                {
                    "name": "Suggested Next Action",
                    "value": attempt.ai_reasoning[:500] if attempt.ai_reasoning else "Manual investigation required",
                    "inline": False
                },
                {
                    "name": "Manual Intervention Required",
                    "value": "Please investigate this alert manually. Auto-remediation has been exhausted.",
                    "inline": False
                }
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": "Jarvis - Manual Review Needed"
            }
        }

        payload = {
            "username": "Jarvis",
            "content": "@here",  # Ping everyone
            "embeds": [embed]
        }

        await self.send_webhook(payload)

    async def notify_dangerous_command(
        self,
        alert_name: str,
        alert_instance: str,
        rejected_commands: List[str],
        reasons: List[str]
    ):
        """
        Notify about dangerous command rejection.

        Args:
            alert_name: Name of the alert
            alert_instance: Instance identifier
            rejected_commands: List of rejected commands
            reasons: Rejection reasons
        """
        commands_text = "\n".join([f"- {cmd}" for cmd in rejected_commands[:5]])
        reasons_text = "\n".join([f"- {r}" for r in reasons[:5]])

        embed = {
            "title": "⛔ Dangerous Command Rejected",
            "description": f"AI suggested unsafe commands for **{alert_name}** on `{alert_instance}`",
            "color": 0xff0000,
            "fields": [
                {
                    "name": "Rejected Commands",
                    "value": f"```bash\n{commands_text}\n```",
                    "inline": False
                },
                {
                    "name": "Reasons",
                    "value": reasons_text,
                    "inline": False
                },
                {
                    "name": "Action",
                    "value": "Alert escalated for manual review",
                    "inline": False
                }
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": "Jarvis - Safety Check"
            }
        }

        payload = {
            "username": "Jarvis",
            "embeds": [embed]
        }

        await self.send_webhook(payload)

    async def notify_maintenance_mode(
        self,
        enabled: bool,
        duration_minutes: Optional[int] = None,
        reason: Optional[str] = None
    ):
        """
        Notify about maintenance mode change.

        Args:
            enabled: Whether maintenance mode is enabled
            duration_minutes: Duration in minutes
            reason: Reason for maintenance
        """
        if enabled:
            title = "🔧 Maintenance Mode Enabled"
            color = 0x0000ff  # Blue
            description = f"Auto-remediation disabled for {duration_minutes} minutes"
        else:
            title = "✅ Maintenance Mode Disabled"
            color = 0x00ff00
            description = "Auto-remediation re-enabled"

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "fields": [],
            "timestamp": datetime.utcnow().isoformat()
        }

        if reason:
            embed["fields"].append({
                "name": "Reason",
                "value": reason,
                "inline": False
            })

        payload = {
            "username": "Jarvis",
            "embeds": [embed]
        }

        await self.send_webhook(payload)


# Global Discord notifier instance
discord_notifier = DiscordNotifier()
