"""Minimal in-process router used by the sample application.

Handlers are registered with the ``route`` decorator and invoked through
``dispatch``. No network server is involved, which keeps the demo safe to test.
"""
from dataclasses import dataclass, field
from typing import Optional


class PermissionDenied(Exception):
    """Raised when the current user may not perform an action."""


class BadRequest(Exception):
    """Raised when a request payload is invalid."""


@dataclass
class Request:
    method: str
    path: str
    body: dict = field(default_factory=dict)
    user: Optional[dict] = None
    headers: dict = field(default_factory=dict)


@dataclass
class Response:
    status: int
    body: dict


_ROUTES = {}


def route(path, method="GET"):
    """Register a handler for ``method path``."""

    def decorator(func):
        _ROUTES[(method.upper(), path)] = func
        return func

    return decorator


def dispatch(method, path, body=None, user=None, headers=None):
    """Invoke the handler registered for ``method path`` and return a Response."""
    handler = _ROUTES.get((method.upper(), path))
    if handler is None:
        return Response(404, {"error": "not found"})
    request = Request(method.upper(), path, body or {}, user, headers or {})
    try:
        result = handler(request)
    except PermissionDenied as exc:
        return Response(403, {"error": str(exc) or "forbidden"})
    except BadRequest as exc:
        return Response(400, {"error": str(exc)})
    if isinstance(result, Response):
        return result
    return Response(200, result)


def registered_routes():
    return sorted(_ROUTES)
