"""Business failures; HTTP status and response formatting belong to adapters."""


class ApplicationError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ApplicationError):
    """The requested business record does not exist."""


class ConflictError(ApplicationError):
    """The current facts or state prevent the requested operation."""


class ValidationError(ApplicationError):
    """The supplied business values do not satisfy the existing rules."""
