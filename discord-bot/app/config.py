"""Configuration loader for Jarvis Discord Bot.

Loads environment variables with validation and type safety.
"""

import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Discord
    discord_bot_token: str
    discord_channel_id: int
    discord_required_role: str

    # n8n
    n8n_webhook_url: str
    n8n_webhook_auth: Optional[str]

    # Rate Limiting
    rate_limit_requests: int
    rate_limit_window: int  # seconds

    # Logging
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables.

        Returns:
            Config instance with values from environment

        Raises:
            ValueError: If required environment variables are missing
        """
        missing = []

        # Required variables
        discord_bot_token = os.getenv("DISCORD_BOT_TOKEN")
        if not discord_bot_token:
            missing.append("DISCORD_BOT_TOKEN")

        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            missing.append("DISCORD_CHANNEL_ID")

        discord_required_role = os.getenv("DISCORD_REQUIRED_ROLE")
        if not discord_required_role:
            missing.append("DISCORD_REQUIRED_ROLE")

        n8n_webhook_url = os.getenv("N8N_WEBHOOK_URL")
        if not n8n_webhook_url:
            missing.append("N8N_WEBHOOK_URL")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        # Optional variables with defaults
        n8n_webhook_auth = os.getenv("N8N_WEBHOOK_AUTH")
        rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
        rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW", "300"))
        log_level = os.getenv("LOG_LEVEL", "INFO")

        return cls(
            discord_bot_token=discord_bot_token,
            discord_channel_id=int(discord_channel_id),
            discord_required_role=discord_required_role,
            n8n_webhook_url=n8n_webhook_url,
            n8n_webhook_auth=n8n_webhook_auth,
            rate_limit_requests=rate_limit_requests,
            rate_limit_window=rate_limit_window,
            log_level=log_level.upper(),
        )


# Global config instance (loaded once on import)
config: Optional[Config] = None


def get_config() -> Config:
    """Get the global config instance, loading from env if not yet loaded.

    Returns:
        Config instance
    """
    global config
    if config is None:
        config = Config.from_env()
    return config
