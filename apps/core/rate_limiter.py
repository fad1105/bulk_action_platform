import logging
import time
import uuid
from typing import Optional

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local member_id = ARGV[5]

-- 1. Remove expired entries outside the sliding window
local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Calculate current total within the active window
local entries = redis.call('ZRANGE', key, 0, -1)
local current_total = 0
for _, entry in ipairs(entries) do
    local colon = string.find(entry, ":")
    if colon then
        local count = tonumber(string.sub(entry, 1, colon - 1))
        if count then
            current_total = current_total + count
        end
    end
end

-- 3. Check limit
if current_total + requested > limit then
    return {0, current_total, limit}
end

-- 4. Record consumption
local new_entry = tostring(requested) .. ":" .. member_id
redis.call('ZADD', key, now, new_entry)
redis.call('EXPIRE', key, math.ceil(window * 2))

return {1, current_total + requested, limit}
"""


class RedisRateLimiter:
    """
    Redis-backed sliding window rate limiter for multi-tenant accounts.

    Tracks entity operations per account over a configurable time window (default: 60s).
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        limit_per_window: Optional[int] = None,
        window_seconds: int = 60,
    ) -> None:
        """
        Initialize the rate limiter.

        Args:
            redis_client: Optional redis client instance. Defaults to settings.REDIS_URL.
            limit_per_window: Maximum entities permitted within the window. Defaults to settings.RATE_LIMIT_ENTITIES_PER_MINUTE.
            window_seconds: Duration of rate limit sliding window in seconds.
        """
        self.redis_client = redis_client or redis.Redis.from_url(
            getattr(settings, "REDIS_URL", "redis://localhost:6379/2"),
            decode_responses=True,
        )
        self.limit = limit_per_window or getattr(settings, "RATE_LIMIT_ENTITIES_PER_MINUTE", 10000)
        self.window_seconds = window_seconds
        self._script = self.redis_client.register_script(SLIDING_WINDOW_LUA)

    def _get_key(self, account_id: str) -> str:
        """Return Redis key for the specified account."""
        return f"rate_limit:account:{account_id}"

    def check_and_consume(self, account_id: str, count: int) -> tuple[bool, int, int]:
        """
        Atomically check if the account can consume `count` entities, and if so, record consumption.

        Args:
            account_id: Tenant or account identifier.
            count: Number of entities to process.

        Returns:
            Tuple of (allowed: bool, current_or_new_total: int, limit: int).
        """
        if count <= 0:
            return True, 0, self.limit

        key = self._get_key(account_id)
        now = time.time()
        member_id = uuid.uuid4().hex

        try:
            allowed, current_total, limit = self._script(
                keys=[key],
                args=[now, self.window_seconds, self.limit, count, member_id],
            )
            is_allowed = bool(allowed)

            if not is_allowed:
                logger.warning(
                    "rate_limit_exceeded",
                    extra={
                        "account_id": account_id,
                        "requested": count,
                        "current_usage": current_total,
                        "limit": limit,
                    },
                )
            else:
                logger.debug(
                    "rate_limit_consumed",
                    extra={
                        "account_id": account_id,
                        "requested": count,
                        "new_usage": current_total,
                        "limit": limit,
                    },
                )

            return is_allowed, int(current_total), int(limit)
        except redis.RedisError as exc:
            logger.error(
                "rate_limiter_redis_error",
                extra={"account_id": account_id, "error": str(exc)},
            )
            # In case of Redis outage, can be configured to fail-open or fail-closed.
            # Defaulting to fail-closed with error or re-raising
            raise

    def get_current_usage(self, account_id: str) -> int:
        """
        Get current entity count consumed by account in the active window.

        Args:
            account_id: Tenant or account identifier.

        Returns:
            Current count of entities processed in current window.
        """
        key = self._get_key(account_id)
        now = time.time()
        clear_before = now - self.window_seconds
        try:
            self.redis_client.zremrangebyscore(key, "-inf", clear_before)
            entries = self.redis_client.zrange(key, 0, -1)
            total = 0
            for entry in entries:
                if ":" in entry:
                    part = entry.split(":", 1)[0]
                    total += int(part) if part.isdigit() else 0
            return total
        except redis.RedisError as exc:
            logger.error("rate_limiter_read_error", extra={"account_id": account_id, "error": str(exc)})
            return 0

    def reset(self, account_id: str) -> None:
        """
        Reset rate limit consumption for account (useful for tests and admin overrides).

        Args:
            account_id: Tenant or account identifier.
        """
        key = self._get_key(account_id)
        try:
            self.redis_client.delete(key)
        except redis.RedisError as exc:
            logger.error("rate_limiter_reset_error", extra={"account_id": account_id, "error": str(exc)})
