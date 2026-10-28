"""Deterministic checks and the existing test suite, run in a disposable copy.

Results are evidence. An empty result does not mean the code is secure.
"""
import re
import sys
from pathlib import Path

from app.config import CHECK_TIMEOUT_SECONDS
from app.models import CommandResult
from app.sandbox import run_command, tool_path


def run_ruff(workspace: Path, python_files: list[str]) -> CommandResult:
    exe = tool_path("ruff")
    if exe is None:
        return CommandResult(name="ruff", command="ruff check", status="not_run", summary="ruff is not installed")
    if not python_files:
        return CommandResult(name="ruff", command="ruff check", status="not_run", summary="no changed Python files")
    result, code = run_command("ruff", [exe, "check", "--no-cache", "--isolated", "--output-format", "concise",
                                        *python_files], workspace, CHECK_TIMEOUT_SECONDS)
    if code == 1:
        result.status = "findings"
        count = len(re.findall(r"^\S+:\d+:\d+:", result.stdout, re.M))
        result.summary = f"{count} lint finding(s) in changed files"
    elif code == 0:
        result.summary = "no lint findings in changed files"
    elif result.status == "failed":
        result.status = "error"
        result.summary = "ruff did not complete"
    return result


def run_bandit(workspace: Path, python_files: list[str]) -> CommandResult:
    exe = tool_path("bandit")
    if exe is None:
        return CommandResult(name="bandit", command="bandit", status="not_run", summary="bandit is not installed")
    # Test files use assert by design (B101); scanning them only adds noise.
    python_files = [p for p in python_files if not p.startswith("tests/") and "/test_" not in f"/{p}"]
    if not python_files:
        return CommandResult(name="bandit", command="bandit", status="not_run", summary="no changed Python files")
    result, code = run_command("bandit", [exe, "-q", "-f", "txt", *python_files], workspace, CHECK_TIMEOUT_SECONDS)
    if code == 1:
        result.status = "findings"
        issues = re.findall(r"^>> Issue:", result.stdout, re.M)
        result.summary = f"{len(issues)} bandit issue(s) in changed files"
    elif code == 0:
        result.summary = "no bandit issues in changed files (bandit does not model authorization logic)"
    elif result.status == "failed":
        result.status = "error"
        result.summary = "bandit did not complete"
    return result


def run_existing_tests(workspace: Path) -> CommandResult:
    if not (workspace / "tests").is_dir():
        return CommandResult(name="existing tests", command="pytest", status="not_run",
                             summary="repository has no tests/ directory")
    result, code = run_command(
        "existing tests",
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        workspace, CHECK_TIMEOUT_SECONDS,
    )
    tail = next((line for line in reversed(result.stdout.splitlines()) if line.strip()), "")
    result.summary = tail.strip("= ").strip() or result.summary
    if code not in (0, 1, None):
        result.status = "error"
    return result
