"""n8n webhook client for Discord bot.

Handles HTTP requests to n8n workflow webhook that orchestrates:
- Session management (PostgreSQL)
- Claude Code execution (SSH to Management-Host)
- Response formatting
"""

import aiohttp
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class N8NClient:
    """Async HTTP client for n8n webhook."""

    def __init__(self, webhook_url: str, auth_token: Optional[str] = None):
        """Initialize n8n client.

        Args:
            webhook_url: Full n8n webhook URL
            auth_token: Optional basic auth token
        """
        self.webhook_url = webhook_url
        self.auth_token = auth_token
        self.session: Optional[aiohttp.ClientSession] = None

        logger.info(f"n8n client initialized: {webhook_url}")

    async def start(self) -> None:
        """Initialize HTTP session (call during bot startup)."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            logger.info("n8n HTTP session started")

    async def close(self) -> None:
        """Close HTTP session (call during bot shutdown)."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("n8n HTTP session closed")

    async def execute_claude_code(
        self,
        user_id: str,
        username: str,
        channel_id: str,
        prompt: str,
        agent_hint: Optional[str] = None,
        action: str = "execute",
    ) -> Dict[str, Any]:
        """Send request to n8n webhook to execute Claude Code.

        Args:
            user_id: Discord user ID
            username: Discord username
            channel_id: Discord channel ID
            prompt: User's prompt for Claude
            agent_hint: Optional agent type hint (e.g., "homelab-architect")
            action: Action type ("execute", "new_session", "end_session")

        Returns:
            Dict with response from n8n workflow:
            {
                "success": bool,
                "response": str,
                "session_id": str,
                "error": str (optional)
            }

        Raises:
            aiohttp.ClientError: On network errors
            ValueError: If session not initialized
        """
        if not self.session:
            raise ValueError("n8n client not initialized. Call start() first.")

        # Build request payload
        payload = {
            "user_id": user_id,
            "username": username,
            "channel_id": channel_id,
            "prompt": prompt,
            "action": action,
        }

        if agent_hint:
            payload["agent_hint"] = agent_hint

        # Add auth header if configured
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        logger.info(
            f"Sending request to n8n: user={username}, action={action}, "
            f"agent={agent_hint or 'auto'}, prompt_len={len(prompt)}"
        )

        try:
            async with self.session.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=300),  # 5 min timeout
            ) as response:
                response.raise_for_status()
                result = await response.json()

                logger.info(
                    f"n8n response received: success={result.get('success')}, "
                    f"session_id={result.get('session_id')}"
                )

                return result

        except aiohttp.ClientResponseError as e:
            logger.error(f"n8n HTTP error: {e.status} {e.message}")
            return {
                "success": False,
                "error": f"n8n returned {e.status}: {e.message}",
            }

        except aiohttp.ClientError as e:
            logger.error(f"n8n network error: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to reach n8n: {str(e)}",
            }

        except Exception as e:
            logger.error(f"n8n unexpected error: {str(e)}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
            }

    async def end_session(
        self, user_id: str, username: str, channel_id: str
    ) -> Dict[str, Any]:
        """End the current session for a user.

        Args:
            user_id: Discord user ID
            username: Discord username
            channel_id: Discord channel ID

        Returns:
            Response from n8n workflow
        """
        logger.info(f"Ending session for user {username} ({user_id})")

        return await self.execute_claude_code(
            user_id=user_id,
            username=username,
            channel_id=channel_id,
            prompt="",  # Empty prompt for end_session action
            action="end_session",
        )

    async def new_session(
        self, user_id: str, username: str, channel_id: str, prompt: str
    ) -> Dict[str, Any]:
        """Force creation of a new session (ignore existing session).

        Args:
            user_id: Discord user ID
            username: Discord username
            channel_id: Discord channel ID
            prompt: User's prompt for Claude

        Returns:
            Response from n8n workflow
        """
        logger.info(f"Creating new session for user {username} ({user_id})")

        return await self.execute_claude_code(
            user_id=user_id,
            username=username,
            channel_id=channel_id,
            prompt=prompt,
            action="new_session",
        )
