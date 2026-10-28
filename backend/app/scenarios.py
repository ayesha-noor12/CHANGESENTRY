"""Predefined demo scenarios. Only these fixtures are ever analyzed or executed."""
import json
from dataclasses import dataclass
from pathlib import Path

from app.config import SCENARIOS_DIR
from app.models import ScenarioSummary


@dataclass
class Scenario:
    summary: ScenarioSummary
    root: Path
    harness: dict
    expected: dict

    @property
    def before_dir(self) -> Path:
        return self.root / "before"

    @property
    def after_dir(self) -> Path:
        return self.root / "after"


def _load(path: Path) -> Scenario:
    meta = json.loads((path / "scenario.json").read_text(encoding="utf-8"))
    return Scenario(
        summary=ScenarioSummary(id=meta["id"], title=meta["title"], description=meta["description"],
                                category=meta["category"]),
        root=path,
        harness=meta.get("harness", {}),
        expected=meta.get("expected", {}),
    )


ORDER = ["auth-boundary", "checkout-regression", "safe-change"]


def list_scenarios() -> list[Scenario]:
    found = {p.name: _load(p) for p in SCENARIOS_DIR.iterdir() if (p / "scenario.json").is_file()}
    return [found[k] for k in sorted(found, key=lambda k: (ORDER.index(k) if k in ORDER else 99, k))]


def get_scenario(scenario_id: str) -> Scenario | None:
    # Look up by id from the known list; the request value is never used as a path.
    return next((s for s in list_scenarios() if s.summary.id == scenario_id), None)
