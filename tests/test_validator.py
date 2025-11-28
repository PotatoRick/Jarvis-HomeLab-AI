"""
Tests for command validator.
"""

import pytest
from app.command_validator import CommandValidator
from app.models import RiskLevel


@pytest.fixture
def validator():
    return CommandValidator()


class TestCommandValidator:
    """Test command validation."""

    def test_safe_systemctl_restart(self, validator):
        """Test that systemctl restart is allowed."""
        is_safe, risk, reason = validator.validate_command("systemctl restart docker")
        assert is_safe is True
        assert risk == RiskLevel.LOW

    def test_safe_docker_restart(self, validator):
        """Test that docker restart is allowed."""
        is_safe, risk, reason = validator.validate_command("docker restart caddy")
        assert is_safe is True
        assert risk == RiskLevel.LOW

    def test_dangerous_rm_rf(self, validator):
        """Test that rm -rf is blocked."""
        is_safe, risk, reason = validator.validate_command("rm -rf /tmp/test")
        assert is_safe is False
        assert risk == RiskLevel.HIGH
        assert "deletion" in reason.lower()

    def test_dangerous_reboot(self, validator):
        """Test that reboot is blocked."""
        is_safe, risk, reason = validator.validate_command("reboot")
        assert is_safe is False
        assert risk == RiskLevel.HIGH

    def test_not_whitelisted(self, validator):
        """Test that non-whitelisted commands are rejected."""
        is_safe, risk, reason = validator.validate_command("some-unknown-command")
        assert is_safe is False
        assert "not in whitelist" in reason.lower()

    def test_batch_validation_all_safe(self, validator):
        """Test batch validation with all safe commands."""
        commands = [
            "systemctl restart wg-quick@wg0",
            "docker restart n8n",
            "sleep 5"
        ]

        result = validator.validate_commands(commands)
        assert result.safe is True
        assert len(result.validated_commands) == 3
        assert len(result.rejected_commands) == 0

    def test_batch_validation_mixed(self, validator):
        """Test batch validation with mixed safe/unsafe commands."""
        commands = [
            "systemctl restart docker",
            "rm -rf /tmp",
            "docker restart caddy"
        ]

        result = validator.validate_commands(commands)
        assert result.safe is False
        assert len(result.validated_commands) == 2  # First and third
        assert len(result.rejected_commands) == 1
        assert "rm -rf /tmp" in result.rejected_commands
