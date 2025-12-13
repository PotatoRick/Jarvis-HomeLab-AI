"""
Configuration management for AI Remediation Service.
Loads settings from environment variables with validation.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from typing import Optional
import re


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "AI Remediation Service"
    app_version: str = "3.9.1"
    debug: bool = False

    # API Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Claude API
    anthropic_api_key: str
    claude_model: str = "claude-3-5-haiku-20241022"
    claude_max_tokens: int = 4000
    claude_timeout: int = 60

    # SSH Configuration
    # All hosts use consistent key path /app/ssh_key (mounted in docker-compose.yml)
    # Override these via environment variables for your infrastructure
    ssh_service-host_host: str = "localhost"
    ssh_service-host_user: str = "root"
    ssh_service-host_key_path: str = "/app/ssh_key"

    ssh_ha-host_host: str = "localhost"
    ssh_ha-host_user: str = "root"
    ssh_ha-host_key_path: str = "/app/ssh_key"

    ssh_vps-host_host: str = "localhost"
    ssh_vps-host_user: str = "root"
    ssh_vps-host_key_path: str = "/app/ssh_key"

    # Management-Host - where Jarvis runs, but SSH to access host filesystem
    ssh_management-host_host: str = "localhost"
    ssh_management-host_user: str = "root"
    ssh_management-host_key_path: str = "/app/ssh_key"

    ssh_timeout: int = 60
    ssh_connection_timeout: int = 10

    # Discord Webhook
    discord_webhook_url: str
    discord_enabled: bool = True

    # Remediation Settings
    max_attempts_per_alert: int = 3
    attempt_window_hours: int = 2
    command_execution_timeout: int = 60
    maintenance_mode: bool = False

    # Anti-Spam Settings (v3.1.0)
    fingerprint_cooldown_seconds: int = 300  # 5 minutes - don't reprocess same alert
    escalation_cooldown_hours: int = 4       # 4 hours - don't re-escalate same alert

    # Security
    webhook_auth_username: str = "alertmanager"
    webhook_auth_password: str

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Phase 1: Prometheus & Loki for verification and log queries
    # Override these via environment variables for your infrastructure
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"

    # Verification settings
    verification_enabled: bool = True
    verification_max_wait_seconds: int = 120
    verification_poll_interval: int = 10
    verification_initial_delay: int = 10

    # Phase 2: Home Assistant integration
    # Override these via environment variables for your infrastructure
    ha_url: str = "http://localhost:8123"
    ha_supervisor_url: str = "http://supervisor/core"  # Supervisor API (internal to HA)
    ha_token: Optional[str] = None  # Long-lived access token

    # Phase 3: n8n workflow orchestration
    # Override these via environment variables for your infrastructure
    n8n_url: str = "http://localhost:5678"
    n8n_api_key: Optional[str] = None  # n8n API key for workflow execution

    # Phase 3: Proactive monitoring
    proactive_monitoring_enabled: bool = True
    proactive_check_interval: int = 300  # 5 minutes
    disk_exhaustion_warning_hours: int = 24  # Warn if disk fills in <24h
    cert_expiry_warning_days: int = 30  # Warn if cert expires in <30 days
    memory_leak_threshold_mb_per_hour: float = 5.0  # Memory growth rate threshold

    # Phase 5: Self-preservation settings
    # External URL for n8n to callback to Jarvis (must be reachable from n8n host)
    # Defaults to ssh_management-host_host:port but should be set explicitly in production
    jarvis_external_url: Optional[str] = None  # e.g., "http://<management-host-ip>:8000"
    self_restart_timeout_minutes: int = 10  # Max time for n8n to poll before timeout
    stale_handoff_cleanup_minutes: int = 30  # Auto-cleanup handoffs older than this

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # =========================================================================
    # HIGH-007 FIX: Pydantic validators for Phase 5 configuration
    # =========================================================================

    @field_validator('jarvis_external_url')
    @classmethod
    def validate_jarvis_external_url(cls, v: Optional[str]) -> Optional[str]:
        """
        HIGH-001 FIX: Validate JARVIS_EXTERNAL_URL format.

        Must be a valid HTTP(S) URL and cannot contain 'localhost' since
        n8n runs on VPS-Host and needs to reach Jarvis on Management-Host.
        """
        if v is None:
            return v

        # Check URL format
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
            r'localhost|'  # localhost (will warn)
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE
        )

        if not url_pattern.match(v):
            raise ValueError(
                f"JARVIS_EXTERNAL_URL must be a valid HTTP(S) URL, got: {v}"
            )

        # Warn about localhost (n8n on VPS-Host can't reach localhost)
        # Don't error - might be valid in development
        if 'localhost' in v.lower() or '127.0.0.1' in v:
            import warnings
            warnings.warn(
                f"JARVIS_EXTERNAL_URL contains 'localhost' ({v}). "
                "This will not work if n8n runs on a different host. "
                "Set to Jarvis's reachable IP (e.g., http://<management-host-ip>:8000).",
                UserWarning
            )

        return v

    @field_validator('stale_handoff_cleanup_minutes')
    @classmethod
    def validate_stale_handoff_cleanup(cls, v: int) -> int:
        """
        Validate cleanup minutes is within reasonable bounds.

        Too small: Could clean up legitimate handoffs during slow restarts
        Too large: Old handoffs accumulate and block new restarts
        """
        if v < 10:
            raise ValueError(
                f"stale_handoff_cleanup_minutes must be at least 10, got: {v}. "
                "Values below 10 risk cleaning up legitimate in-progress handoffs."
            )
        if v > 1440:  # 24 hours
            raise ValueError(
                f"stale_handoff_cleanup_minutes must be at most 1440 (24h), got: {v}. "
                "Very long cleanup periods could cause issues."
            )
        return v

    @field_validator('self_restart_timeout_minutes')
    @classmethod
    def validate_self_restart_timeout(cls, v: int) -> int:
        """Validate restart timeout is reasonable."""
        if v < 2:
            raise ValueError(
                f"self_restart_timeout_minutes must be at least 2, got: {v}. "
                "Restarts need time to complete."
            )
        if v > 60:
            raise ValueError(
                f"self_restart_timeout_minutes must be at most 60, got: {v}. "
                "Very long timeouts suggest a problem with the restart."
            )
        return v

    @field_validator('n8n_url')
    @classmethod
    def validate_n8n_url(cls, v: str) -> str:
        """Validate n8n URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError(
                f"n8n_url must start with http:// or https://, got: {v}"
            )
        return v.rstrip('/')  # Normalize: remove trailing slash


# Global settings instance
settings = Settings()
