"""
Configuration management for AI Remediation Service.
Loads settings from environment variables with validation.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "AI Remediation Service"
    app_version: str = "3.3.1"
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
    claude_model: str = "claude-sonnet-4-5-20250929"
    claude_max_tokens: int = 4000
    claude_timeout: int = 60

    # SSH Configuration
    # HIGH-003 FIX: All hosts use consistent key path /app/ssh_key (mounted in docker-compose.yml)
    ssh_nexus_host: str = "192.168.0.11"
    ssh_nexus_user: str = "jordan"
    ssh_nexus_key_path: str = "/app/ssh_key"

    ssh_homeassistant_host: str = "192.168.0.10"
    ssh_homeassistant_user: str = "root"
    ssh_homeassistant_key_path: str = "/app/ssh_key"

    ssh_outpost_host: str = "localhost"
    ssh_outpost_user: str = "root"
    ssh_outpost_key_path: str = "/app/ssh_key"

    # Skynet - where Jarvis runs, but SSH to access host filesystem
    ssh_skynet_host: str = "192.168.0.13"
    ssh_skynet_user: str = "t1"
    ssh_skynet_key_path: str = "/app/ssh_key"

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Global settings instance
settings = Settings()
