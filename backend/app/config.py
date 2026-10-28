"""Runtime configuration. Secrets are read from the environment (or backend/.env) only."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = BACKEND_DIR / "scenarios"
TEMPLATES_DIR = Path(__file__).resolve().parent / "test_templates"

load_dotenv(BACKEND_DIR / ".env")

TEST_TIMEOUT_SECONDS = 30
CHECK_TIMEOUT_SECONDS = 60
MAX_OUTPUT_CHARS = 20_000


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def nebius_configured() -> bool:
    return all(env(k) for k in ("NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL"))


def tavily_configured() -> bool:
    return env("TAVILY_API_KEY") is not None


def allowed_origins() -> list[str]:
    raw = env("ALLOWED_ORIGINS") or "http://localhost:3000"
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
