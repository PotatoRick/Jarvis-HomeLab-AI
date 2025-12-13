"""Jarvis Discord Bot - Main entry point.

Listens for @Jarvis mentions in Discord, parses messages, and orchestrates
Claude Code execution via n8n workflow.
"""

import discord
from discord.ext import commands
import logging
import sys
from typing import Optional

from .config import get_config
from .message_parser import (
    parse_agent_hint,
    is_session_command,
    extract_prompt,
    validate_prompt,
)
from .rate_limiter import RateLimiter
from .n8n_client import N8NClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/logs/bot.log"),
    ],
)

logger = logging.getLogger(__name__)


class JarvisBot(commands.Bot):
    """Jarvis Discord Bot with Claude Code integration."""

    def __init__(self):
        """Initialize the bot."""
        # Load config
        self.config = get_config()

        # Set up Discord intents
        intents = discord.Intents.default()
        intents.message_content = True  # Required to read message content
        intents.members = True  # Required to check user roles

        # Initialize bot
        super().__init__(
            command_prefix="!",  # Not used, but required
            intents=intents,
            help_command=None,  # Disable default help
        )

        # Initialize components
        self.rate_limiter = RateLimiter(
            max_requests=self.config.rate_limit_requests,
            window_seconds=self.config.rate_limit_window,
        )

        self.n8n_client = N8NClient(
            webhook_url=self.config.n8n_webhook_url,
            auth_token=self.config.n8n_webhook_auth,
        )

        logger.info("Jarvis bot initialized")

    async def setup_hook(self) -> None:
        """Called when bot is starting up."""
        await self.n8n_client.start()
        logger.info("Bot setup complete")

    async def close(self) -> None:
        """Called when bot is shutting down."""
        await self.n8n_client.close()
        await super().close()
        logger.info("Bot shutdown complete")

    async def on_ready(self) -> None:
        """Called when bot successfully connects to Discord."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Listening in channel ID: {self.config.discord_channel_id}")
        logger.info(f"Required role: {self.config.discord_required_role}")

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages.

        Args:
            message: Discord message object
        """
        # Ignore bot's own messages
        if message.author == self.user:
            return

        # Only respond in configured channel
        if message.channel.id != self.config.discord_channel_id:
            return

        # Check if bot was mentioned
        if self.user not in message.mentions:
            return

        logger.info(
            f"Received mention from {message.author} ({message.author.id}): "
            f"{message.content[:100]}"
        )

        # Check user has required role
        if not self._check_user_role(message.author):
            await message.channel.send(
                f"❌ {message.author.mention} You need the "
                f"`{self.config.discord_required_role}` role to use Jarvis."
            )
            logger.warning(
                f"User {message.author} lacks required role: "
                f"{self.config.discord_required_role}"
            )
            return

        # Extract prompt from message
        prompt = extract_prompt(message.content, self.user.mention)

        # Validate prompt
        is_valid, error_message = validate_prompt(prompt)
        if not is_valid:
            await message.channel.send(f"❌ {error_message}")
            return

        # Check if this is a session command
        if is_session_command(prompt):
            await self._handle_session_command(message, prompt)
            return

        # Check rate limit
        user_id = str(message.author.id)
        allowed, remaining = self.rate_limiter.check_rate_limit(user_id)

        if not allowed:
            reset_seconds = self.rate_limiter.get_reset_time(user_id)
            minutes = reset_seconds // 60
            seconds = reset_seconds % 60
            await message.channel.send(
                f"⏱️ {message.author.mention} Rate limit exceeded! "
                f"Try again in {minutes}m {seconds}s."
            )
            logger.warning(f"Rate limit exceeded for user {message.author}")
            return

        # Parse agent hint
        agent_hint, clean_prompt = parse_agent_hint(prompt)

        # Send typing indicator while processing
        async with message.channel.typing():
            # Call n8n workflow
            result = await self.n8n_client.execute_claude_code(
                user_id=user_id,
                username=str(message.author),
                channel_id=str(message.channel.id),
                prompt=clean_prompt,
                agent_hint=agent_hint,
            )

        # Send response
        await self._send_response(message, result, remaining)

    def _check_user_role(self, user: discord.Member) -> bool:
        """Check if user has required role.

        Args:
            user: Discord member object

        Returns:
            True if user has required role
        """
        required_role = self.config.discord_required_role.lower()
        user_roles = [role.name.lower() for role in user.roles]

        return required_role in user_roles

    async def _handle_session_command(
        self, message: discord.Message, command: str
    ) -> None:
        """Handle session control commands (done, cancel, new).

        Args:
            message: Discord message
            command: Session command
        """
        command_lower = command.lower().strip()
        user_id = str(message.author.id)

        if command_lower in ["done", "cancel"]:
            # End current session
            result = await self.n8n_client.end_session(
                user_id=user_id,
                username=str(message.author),
                channel_id=str(message.channel.id),
            )

            if result.get("success"):
                await message.channel.send(
                    f"✅ {message.author.mention} Session ended. "
                    f"Your next message will start a new session."
                )
            else:
                await message.channel.send(
                    f"❌ Failed to end session: {result.get('error', 'Unknown error')}"
                )

        elif command_lower in ["new", "new session"]:
            # Force new session
            await message.channel.send(
                f"🔄 {message.author.mention} Starting new session. "
                f"Send your message to begin."
            )

        logger.info(f"Session command '{command}' from {message.author}")

    async def _send_response(
        self,
        message: discord.Message,
        result: dict,
        requests_remaining: int,
    ) -> None:
        """Send Claude Code response back to Discord.

        Args:
            message: Original Discord message
            result: Response from n8n workflow
            requests_remaining: User's remaining requests
        """
        if not result.get("success"):
            error = result.get("error", "Unknown error")
            await message.channel.send(
                f"❌ {message.author.mention} Error: {error}"
            )
            logger.error(f"Execution failed: {error}")
            return

        response_text = result.get("response", "No response received")
        session_id = result.get("session_id", "unknown")

        # Build response message
        response_parts = []
        response_parts.append(f"{message.author.mention} Response from Claude Code:")
        response_parts.append("")  # Empty line
        response_parts.append(response_text)
        response_parts.append("")  # Empty line
        response_parts.append(
            f"_Session: {session_id[:8]}... | "
            f"Requests remaining: {requests_remaining}_"
        )

        full_response = "\n".join(response_parts)

        # Check length and split if needed
        if len(full_response) <= 2000:
            await message.channel.send(full_response)
        else:
            # Split into chunks
            chunks = self._split_message(full_response, 2000)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.channel.send(chunk)
                else:
                    await message.channel.send(f"_(continued {i+1}/{len(chunks)})_\n{chunk}")

        logger.info(
            f"Response sent to {message.author}, session {session_id[:8]}, "
            f"{len(response_text)} chars"
        )

    def _split_message(self, text: str, max_length: int) -> list[str]:
        """Split long message into chunks.

        Args:
            text: Full message text
            max_length: Maximum length per chunk

        Returns:
            List of message chunks
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        current_chunk = ""

        for line in text.split("\n"):
            if len(current_chunk) + len(line) + 1 <= max_length:
                current_chunk += line + "\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.rstrip())
                current_chunk = line + "\n"

        if current_chunk:
            chunks.append(current_chunk.rstrip())

        return chunks


def main():
    """Main entry point."""
    try:
        config = get_config()
        bot = JarvisBot()
        bot.run(config.discord_bot_token)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
