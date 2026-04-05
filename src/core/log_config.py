from loguru import logger as _logger
from functools import lru_cache
from contextvars import ContextVar
import uuid
import sys

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str | None = None) -> str:
    if request_id is None:
        request_id = str(uuid.uuid4())
    _request_id_ctx.set(request_id)
    return request_id


def get_request_id() -> str:
    return _request_id_ctx.get()


@lru_cache
def get_logger():
    _logger.remove()

    _logger.add(
        sys.stdout,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level} | "
            "{extra[request_id]} | "
            "{name}:{function}:{line} - "
            "{message}"
        ),
        level="DEBUG",
        enqueue=True,
    )

    _logger.configure(
        patcher=lambda record: record["extra"].update(
            request_id=get_request_id()
        )
    )

    return _logger

logger = get_logger()