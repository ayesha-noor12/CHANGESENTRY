"""Disposable workspaces and bounded subprocess execution.

Only fixed command lines built by the backend are executed here; nothing the
model returns is ever passed to a shell.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import MAX_OUTPUT_CHARS
from app.models import CommandResult

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX
    resource = None

VENV_BIN = Path(sys.executable).parent


@contextmanager
def disposable_copy(source: Path):
    """Copy a fixture into a temporary directory that is deleted afterwards."""
    root = Path(tempfile.mkdtemp(prefix="changesentry-"))
    workspace = root / "repo"
    shutil.copytree(source, workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    try:
        yield workspace
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _limit_resources():  # runs in the child before exec
    if resource is None:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    except ValueError:  # macOS does not allow lowering RLIMIT_AS
        pass
    os.setsid()


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated {len(text) - MAX_OUTPUT_CHARS} chars]"


def run_command(name: str, argv: list[str], cwd: Path, timeout: int) -> tuple[CommandResult, int | None]:
    """Run argv with a scrubbed environment. API keys are never passed to the child."""
    child_env = {
        "PATH": f"{VENV_BIN}{os.pathsep}/usr/bin:/bin",
        "PYTHONPATH": str(cwd),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "HOME": str(cwd),
        "LANG": "C.UTF-8",
    }
    display = " ".join(_display_arg(a, cwd) for a in argv)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=_limit_resources if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return CommandResult(
            name=name, command=display, status="timeout", stdout=_scrub(_truncate(out), cwd),
            stderr=f"Timed out after {timeout}s", duration_ms=elapsed, summary=f"timed out after {timeout}s",
        ), None
    except FileNotFoundError as exc:
        return CommandResult(name=name, command=display, status="not_run", stderr=str(exc),
                             summary="tool not installed"), None
    elapsed = int((time.monotonic() - start) * 1000)
    return CommandResult(
        name=name,
        command=display,
        status="passed" if proc.returncode == 0 else "failed",
        exit_code=proc.returncode,
        stdout=_scrub(_truncate(proc.stdout), cwd),
        stderr=_scrub(_truncate(proc.stderr), cwd),
        duration_ms=elapsed,
    ), proc.returncode


def _display_arg(arg: str, cwd: Path) -> str:
    if arg == sys.executable:
        return "python"
    if arg.startswith(str(VENV_BIN)):
        return Path(arg).name
    return _scrub(arg, cwd)


def _scrub(text: str, cwd: Path) -> str:
    """Replace temporary paths so output is readable and reveals nothing about the host."""
    return text.replace(str(cwd), "<workspace>").replace(str(VENV_BIN.parent), "<venv>")


def tool_path(name: str) -> str | None:
    candidate = VENV_BIN / name
    if candidate.exists():
        return str(candidate)
    return shutil.which(name)
