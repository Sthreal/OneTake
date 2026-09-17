from onetake_api.platform.errors import DomainError


class ProjectValidationError(DomainError):
    code = "VALIDATION_ERROR"
    http_status = 422
    retryable = False


class ProjectNotFoundError(DomainError):
    code = "PROJECT_NOT_FOUND"
    http_status = 404
    retryable = False