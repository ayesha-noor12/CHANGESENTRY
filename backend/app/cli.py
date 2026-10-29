"""Command-line entry used by the VS Code extension.

    python -m app.cli --repo <path> --base main --head HEAD
    python -m app.cli --repo <path> --base HEAD --head WORKTREE

Progress is written to stderr as one JSON object per line ({"event": "stage", ...});
the finished AnalysisRun is written to stdout as JSON.
"""
import argparse
import json
import sys
from pathlib import Path

from app.git_source import GitError, git_revisions
from app.pipeline import RunStore, run_analysis


class ReportingStore(RunStore):
    def stage(self, run_id: str, key: str, status: str, detail: str = "") -> None:
        super().stage(run_id, key, status, detail)
        label = next(s.label for s in self._runs[run_id].stages if s.key == key)
        _emit({"event": "stage", "key": key, "label": label, "status": status, "detail": detail})


def _emit(event: dict) -> None:
    sys.stderr.write(json.dumps(event) + "\n")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="changesentry")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base", required=True, help="git ref for the original code, e.g. main or HEAD~1")
    parser.add_argument("--head", default="HEAD", help="git ref for the changed code, or WORKTREE")
    args = parser.parse_args(argv)

    store = ReportingStore()
    try:
        with git_revisions(args.repo, args.base, args.head) as scenario:
            run = store.create(scenario.summary.id)
            run_analysis(run.run_id, store, scenario)
    except GitError as exc:
        _emit({"event": "error", "message": str(exc)})
        return 2
    result = store.get(run.run_id)
    print(json.dumps(result.model_dump(), default=str))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
