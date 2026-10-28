"""Liveness endpoint used by the load balancer."""
from app.router import route


@route("/health")
def health(request):
    """Return a static liveness payload.

    The load balancer only checks for HTTP 200; the body is informational.
    """
    return {"status": "ok"}
