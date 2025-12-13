"""Rate limiter for Discord bot requests.

Implements per-user rate limiting using sliding window algorithm.
Prevents abuse by limiting requests per user within a time window.
"""

import time
from collections import defaultdict, deque
from typing import Dict, Deque, Tuple
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """In-memory rate limiter using sliding window algorithm.

    Tracks request timestamps per user and enforces limits.
    """

    def __init__(self, max_requests: int, window_seconds: int):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds

        # user_id -> deque of request timestamps
        self.user_requests: Dict[str, Deque[float]] = defaultdict(deque)

        logger.info(
            f"Rate limiter initialized: {max_requests} requests per {window_seconds}s"
        )

    def check_rate_limit(self, user_id: str) -> Tuple[bool, int]:
        """Check if user is within rate limit.

        Args:
            user_id: Discord user ID

        Returns:
            Tuple of (allowed, requests_remaining)
            - allowed: True if request can proceed
            - requests_remaining: Number of requests left in current window

        Examples:
            >>> limiter = RateLimiter(max_requests=10, window_seconds=300)
            >>> limiter.check_rate_limit("user123")
            (True, 9)  # First request allowed, 9 remaining
        """
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        # Get user's request history
        user_history = self.user_requests[user_id]

        # Remove requests outside the time window
        while user_history and user_history[0] < cutoff_time:
            user_history.popleft()

        # Check if under limit
        request_count = len(user_history)
        allowed = request_count < self.max_requests
        requests_remaining = max(0, self.max_requests - request_count - 1)

        if allowed:
            # Record this request
            user_history.append(current_time)
            logger.debug(
                f"Rate limit check for {user_id}: {request_count + 1}/{self.max_requests} "
                f"({requests_remaining} remaining)"
            )
        else:
            # Rate limit exceeded
            oldest_request = user_history[0]
            reset_in = int(oldest_request + self.window_seconds - current_time)
            logger.warning(
                f"Rate limit exceeded for {user_id}: {request_count}/{self.max_requests} "
                f"(resets in {reset_in}s)"
            )

        return (allowed, requests_remaining)

    def get_reset_time(self, user_id: str) -> int:
        """Get seconds until rate limit resets for user.

        Args:
            user_id: Discord user ID

        Returns:
            Seconds until oldest request expires (rate limit resets)
            Returns 0 if user is not rate limited
        """
        user_history = self.user_requests.get(user_id)

        if not user_history or len(user_history) < self.max_requests:
            return 0

        current_time = time.time()
        oldest_request = user_history[0]
        reset_time = oldest_request + self.window_seconds

        return max(0, int(reset_time - current_time))

    def reset_user(self, user_id: str) -> None:
        """Reset rate limit for specific user (admin function).

        Args:
            user_id: Discord user ID
        """
        if user_id in self.user_requests:
            del self.user_requests[user_id]
            logger.info(f"Rate limit reset for user {user_id}")

    def get_stats(self) -> Dict[str, int]:
        """Get rate limiter statistics.

        Returns:
            Dict with keys:
            - total_users: Number of users being tracked
            - rate_limited_users: Number of users currently rate limited
        """
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        total_users = len(self.user_requests)
        rate_limited_users = 0

        for user_id, history in self.user_requests.items():
            # Count requests in current window
            recent_requests = sum(1 for ts in history if ts >= cutoff_time)
            if recent_requests >= self.max_requests:
                rate_limited_users += 1

        return {
            "total_users": total_users,
            "rate_limited_users": rate_limited_users,
        }

    def cleanup_old_entries(self) -> int:
        """Remove users with no recent activity (memory cleanup).

        Removes users whose last request was over 2x the window ago.

        Returns:
            Number of users removed
        """
        current_time = time.time()
        cleanup_cutoff = current_time - (self.window_seconds * 2)

        users_to_remove = []
        for user_id, history in self.user_requests.items():
            if not history or history[-1] < cleanup_cutoff:
                users_to_remove.append(user_id)

        for user_id in users_to_remove:
            del self.user_requests[user_id]

        if users_to_remove:
            logger.info(f"Cleaned up {len(users_to_remove)} inactive users from rate limiter")

        return len(users_to_remove)
