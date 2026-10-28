"""Application entry point: importing the route modules registers their handlers."""
from app.router import dispatch, registered_routes
from app.routes import admin, health, orders  # noqa: F401

__all__ = ["dispatch", "registered_routes"]
