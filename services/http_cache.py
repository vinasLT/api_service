"""Cache keys that ignore per-request objects such as the API client and DB session."""

import hashlib
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response


def query_key_builder(
    func: Callable[..., Any],
    namespace: str = "",
    *,
    request: Request | None = None,
    response: Response | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> str:
    if request is not None:
        query = "&".join(
            f"{key}={value}" for key, value in sorted(request.query_params.multi_items())
        )
        raw = f"{request.url.path}?{query}"
    else:
        raw = f"{func.__module__}:{func.__name__}"
    digest = hashlib.md5(raw.encode()).hexdigest()
    return f"{namespace}:{digest}"
