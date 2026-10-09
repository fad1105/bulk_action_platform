"""Domain exceptions for Bulk Action Platform."""


class BulkActionPlatformException(Exception):
    """Base exception for bulk action platform."""

    pass


class RateLimitExceededException(BulkActionPlatformException):
    """Raised when an account exceeds its allowed processing rate limit."""

    def __init__(self, account_id: str, limit: int, current_usage: int, requested: int):
        self.account_id = account_id
        self.limit = limit
        self.current_usage = current_usage
        self.requested = requested
        super().__init__(
            f"Rate limit exceeded for account '{account_id}'. "
            f"Limit: {limit}/min, Current: {current_usage}/min, Requested: {requested}."
        )


class EntityNotFoundException(BulkActionPlatformException):
    """Raised when an entity is not registered or not found."""

    pass


class UnsupportedEntityTypeException(BulkActionPlatformException):
    """Raised when an entity type is not supported."""

    pass


class UnsupportedActionTypeException(BulkActionPlatformException):
    """Raised when an action type is not supported for an entity."""

    pass


class BulkActionValidationException(BulkActionPlatformException):
    """Raised when action payload or configuration fails validation."""

    pass


class ChunkProcessingException(BulkActionPlatformException):
    """Raised when chunk execution encounters a fatal processing error."""

    pass


class ChunkNotFoundException(BulkActionPlatformException):
    """Raised when a chunk ID does not exist in the database (e.g. orphaned task)."""

    pass
