import pytest

from apps.core.rate_limiter import RedisRateLimiter


@pytest.mark.django_db
class TestRedisRateLimiter:
    """Tests for Redis-backed sliding window rate limiter."""

    def setup_method(self) -> None:
        self.account_id = "test_acc_limiter"
        self.limiter = RedisRateLimiter(limit_per_window=10000, window_seconds=60)
        self.limiter.reset(self.account_id)

    def teardown_method(self) -> None:
        self.limiter.reset(self.account_id)

    def test_consume_within_limit_success(self) -> None:
        allowed, current, limit = self.limiter.check_and_consume(self.account_id, 5000)
        assert allowed is True
        assert current == 5000
        assert limit == 10000

        # Consume remaining
        allowed2, current2, limit2 = self.limiter.check_and_consume(self.account_id, 5000)
        assert allowed2 is True
        assert current2 == 10000

    def test_exceeding_limit_is_rejected(self) -> None:
        # First consume 8,000
        allowed, _, _ = self.limiter.check_and_consume(self.account_id, 8000)
        assert allowed is True

        # Attempt to consume 3,000 more (exceeds 10,000)
        allowed, current, limit = self.limiter.check_and_consume(self.account_id, 3000)
        assert allowed is False
        assert current == 8000
        assert limit == 10000

    def test_multi_tenant_isolation(self) -> None:
        other_acc = "other_acc_test"
        self.limiter.reset(other_acc)

        # Exhaust test_acc_limiter
        self.limiter.check_and_consume(self.account_id, 10000)
        rejected, _, _ = self.limiter.check_and_consume(self.account_id, 1)
        assert rejected is False

        # other_acc should still have full quota
        allowed, current, _ = self.limiter.check_and_consume(other_acc, 5000)
        assert allowed is True
        assert current == 5000

        self.limiter.reset(other_acc)
