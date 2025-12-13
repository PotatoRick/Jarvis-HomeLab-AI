"""Message parser for Discord bot.

Parses user messages to extract:
- Agent hints (e.g., "ask homelab-architect")
- Session commands (e.g., "done", "cancel")
- Prompts for Claude Code
"""

import re
from typing import Optional, Tuple


# Known agent types that can be explicitly requested
VALID_AGENTS = [
    "homelab-architect",
    "homelab-security-auditor",
    "home-assistant-expert",
    "n8n-workflow-architect",
    "financial-automation-guru",
    "omada-network-engineer",
    "python-claude-code-expert",
    "technical-documenter",
    "senior-qa-engineer",
    "web-game-developer",
    "jarvis-incident-architect",
]


def parse_agent_hint(message: str) -> Tuple[Optional[str], str]:
    """Parse message for agent hint and extract prompt.

    Supported formats:
    - "ask homelab-architect how do I configure VLANs?"
    - "ask @homelab-architect how do I configure VLANs?"
    - "ask 'homelab-architect' how do I configure VLANs?"
    - Just regular prompt (no agent hint)

    Args:
        message: User's Discord message (with @Jarvis mention removed)

    Returns:
        Tuple of (agent_name or None, prompt)

    Examples:
        >>> parse_agent_hint("ask homelab-architect how do VLANs work?")
        ("homelab-architect", "how do VLANs work?")

        >>> parse_agent_hint("how do VLANs work?")
        (None, "how do VLANs work?")
    """
    message = message.strip()

    # Pattern: ask [agent] [prompt]
    # Matches: "ask homelab-architect", "ask @homelab-architect", "ask 'homelab-architect'"
    pattern = r"^ask\s+[@']?([a-z-]+)['']?\s+(.+)$"
    match = re.match(pattern, message, re.IGNORECASE)

    if match:
        agent_hint = match.group(1).lower()
        prompt = match.group(2).strip()

        # Validate agent name
        if agent_hint in VALID_AGENTS:
            return (agent_hint, prompt)
        else:
            # Invalid agent name - treat entire message as prompt
            return (None, message)

    # No agent hint - return full message as prompt
    return (None, message)


def is_session_command(message: str) -> bool:
    """Check if message is a session control command.

    Session commands:
    - "done" - End current session
    - "cancel" - Cancel current session
    - "new" - Force new session

    Args:
        message: User's message (cleaned)

    Returns:
        True if message is a session command

    Examples:
        >>> is_session_command("done")
        True
        >>> is_session_command("how do I...")
        False
    """
    message_lower = message.strip().lower()
    return message_lower in ["done", "cancel", "new", "new session"]


def extract_prompt(message: str, bot_mention: str) -> str:
    """Extract prompt from message by removing bot mention.

    Args:
        message: Raw Discord message content
        bot_mention: Bot mention string (e.g., "<@1447434205112827906>")

    Returns:
        Cleaned prompt text

    Examples:
        >>> extract_prompt("<@123> how do VLANs work?", "<@123>")
        "how do VLANs work?"

        >>> extract_prompt("@Jarvis how do VLANs work?", "@Jarvis")
        "how do VLANs work?"
    """
    # Remove bot mention
    prompt = message.replace(bot_mention, "").strip()

    # Remove common variations
    prompt = re.sub(r"@Jarvis\s+", "", prompt, flags=re.IGNORECASE)

    return prompt.strip()


def validate_prompt(prompt: str) -> Tuple[bool, Optional[str]]:
    """Validate that prompt is not empty and meets basic requirements.

    Args:
        prompt: Extracted prompt text

    Returns:
        Tuple of (is_valid, error_message)

    Examples:
        >>> validate_prompt("how do VLANs work?")
        (True, None)

        >>> validate_prompt("")
        (False, "Empty message. Ask me a question!")
    """
    if not prompt or len(prompt.strip()) == 0:
        return (False, "Empty message. Ask me a question!")

    if len(prompt) < 3:
        return (False, "Message too short. Please provide more context.")

    if len(prompt) > 4000:
        return (False, "Message too long (max 4000 characters).")

    return (True, None)
