"""Liveness endpoint."""
from app.router import route


@route("/health")
def health(request):
    """Return a static liveness payload."""
    return {"status": "ok"}
