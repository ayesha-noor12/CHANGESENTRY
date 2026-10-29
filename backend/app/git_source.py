"""Materialize two revisions of a local git repository as a before/after pair.

Used by the VS Code extension through ``app.cli``: the developer analyzes their
own repository on their own machine. ``WORKTREE`` as the head means the current
working tree, including uncommitted and untracked (not ignored) files.
"""
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app.models import ScenarioSummary
from app.scenarios import Scenario

WORKTREE = "WORKTREE"
HARNESS_FILE = ".changesentry.json"
GIT_TIMEOUT_SECONDS = 60


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=GIT_TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise GitError("git is not installed") from None
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode(errors="replace").strip() or f"git {args[0]} failed")
    return proc.stdout


def repo_root(path: Path) -> Path:
    return Path(_git(path, "rev-parse", "--show-toplevel").decode().strip())


def describe(repo: Path, ref: str) -> str:
    if ref == WORKTREE:
        return "working tree"
    return _git(repo, "rev-parse", "--short", f"{ref}^{{commit}}").decode().strip()


def _extract_commit(repo: Path, ref: str, dest: Path) -> None:
    archive = _git(repo, "archive", "--format=tar", f"{ref}^{{commit}}")
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")


def _copy_worktree(repo: Path, dest: Path) -> None:
    listed = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
    dest.mkdir(parents=True)
    for rel in filter(None, listed):
        source = repo / rel
        if source.is_file() and not source.is_symlink():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _harness(after_dir: Path) -> dict:
    """Optional per-repository settings, for example {"dispatch_module": "app.main"} for auth_guard."""
    config = after_dir / HARNESS_FILE
    if not config.is_file():
        return {}
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise GitError(f"{HARNESS_FILE} is not valid JSON: {exc}") from None
    return {k: v for k, v in data.items() if k == "dispatch_module" and isinstance(v, str)}


@contextmanager
def git_revisions(path: Path, base: str, head: str):
    """Yield a Scenario whose before/ and after/ directories hold the two revisions."""
    repo = repo_root(path)
    base_label, head_label = describe(repo, base), describe(repo, head)
    root = Path(tempfile.mkdtemp(prefix="changesentry-git-"))
    try:
        _extract_commit(repo, base, root / "before")
        if head == WORKTREE:
            _copy_worktree(repo, root / "after")
        else:
            _extract_commit(repo, head, root / "after")
        summary = ScenarioSummary(
            id="local", title=f"{repo.name}: {base} ({base_label}) → {head if head != WORKTREE else 'working tree'}"
                                + (f" ({head_label})" if head != WORKTREE else ""),
            description=f"Local repository {repo}", category="local",
        )
        yield Scenario(summary=summary, root=root, harness=_harness(root / "after"), expected={})
    finally:
        shutil.rmtree(root, ignore_errors=True)
