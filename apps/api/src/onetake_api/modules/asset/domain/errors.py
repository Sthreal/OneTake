from onetake_api.platform.errors import DomainError


class AssetValidationError(DomainError):
    code = "ASSET_VALIDATION_ERROR"
    http_status = 422
    retryable = False


class AssetNotFoundError(DomainError):
    code = "ASSET_NOT_FOUND"
    http_status = 404
    retryable = False


class AssetNotUploadedError(DomainError):
    code = "ASSET_NOT_UPLOADED"
    http_status = 409
    retryable = True


class AssetDuplicateError(DomainError):
    code = "ASSET_DUPLICATE"
    http_status = 409
    retryable = False


class AssetStateError(DomainError):
    code = "ASSET_STATE_ERROR"
    http_status = 409
    retryable = False