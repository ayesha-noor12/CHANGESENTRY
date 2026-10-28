"""Access-control helpers shared by every route module."""
from app.router import PermissionDenied


def require_user(user):
    """Raise PermissionDenied unless a user is authenticated."""
    if not user or not user.get("id"):
        raise PermissionDenied("authentication required")
    return user


def require_admin(user):
    """Raise PermissionDenied unless the user is an authenticated admin."""
    user = require_user(user)
    if user.get("role") != "admin":
        raise PermissionDenied("admin role required")
    return user
