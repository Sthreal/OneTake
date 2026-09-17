from contextvars import ContextVar

from onetake_api.platform.ids import new_id

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    value = _request_id.get()
    if value:
        return value
    value = new_id("req")
    set_request_id(value)
    return value