"""Turn a bundled scenario into a real git repository with two commits (base, then the change).

Usage (from backend/):  python -m scripts.make_demo_repo checkout-regression ~/changesentry-demos/checkout
Then open the folder in VS Code and run "ChangeSentry: Check my changes" with base HEAD~1.
"""
import shutil
import subprocess
import sys
from pathlib import Path

from app.scenarios import get_scenario

COMMIT_MESSAGES = {
    "checkout-regression": "Let coupons stack with percentage discounts",
    "auth-boundary": "Add payment-provider webhook for chargebacks",
    "safe-change": "Document the health endpoint",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=ChangeSentry demo",
                    "-c", "user.email=demo@changesentry.invalid", *args], check=True, capture_output=True)


def _replace_contents(source: Path, repo: Path) -> None:
    for child in repo.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    shutil.copytree(source, repo, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))


def main(scenario_id: str, dest: str) -> int:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        print(f"unknown scenario '{scenario_id}'")
        return 1
    repo = Path(dest).expanduser().resolve()
    if repo.exists() and any(repo.iterdir()):
        print(f"{repo} already exists and is not empty")
        return 1
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _replace_contents(scenario.before_dir, repo)
    harness = scenario.harness.get("dispatch_module")
    if harness:
        (repo / ".changesentry.json").write_text(f'{{"dispatch_module": "{harness}"}}\n', encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Initial version")
    keep = {name: (repo / name).read_text() for name in (".changesentry.json", ".gitignore") if (repo / name).exists()}
    _replace_contents(scenario.after_dir, repo)
    for name, text in keep.items():
        (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", COMMIT_MESSAGES.get(scenario_id, "Change under review"))
    print(f"Created {repo} with 2 commits. Compare HEAD~1 (base) with HEAD.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
