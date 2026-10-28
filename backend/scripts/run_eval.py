"""Evaluation suite: run every scenario end to end and compare with its expected outcome.

Uses whatever integrations are configured in backend/.env (real Nemotron/Tavily calls).
Usage (from backend/):  python -m scripts.run_eval
"""
import sys

from app.pipeline import run_sync
from app.scenarios import list_scenarios


def main() -> int:
    failures = 0
    for scenario in list_scenarios():
        run = run_sync(scenario.summary.id)
        report, expected = run.report, scenario.expected
        if run.status != "completed" or report is None:
            print(f"FAIL {scenario.summary.id}: run {run.status}: {run.error}")
            failures += 1
            continue
        confirmed = sorted({r.test_template for r in report.risks if r.status == "confirmed_by_test"})
        problems = []
        if report.verdict.status != expected["verdict"]:
            problems.append(f"verdict {report.verdict.status} != {expected['verdict']}")
        if confirmed != sorted(expected["confirmed_templates"]):
            problems.append(f"confirmed templates {confirmed} != {expected['confirmed_templates']}")
        if bool(report.advisories) != expected["advisories"]:
            problems.append(f"advisories present={bool(report.advisories)}, expected {expected['advisories']}")
        status = "FAIL" if problems else "PASS"
        failures += bool(problems)
        print(f"{status} {scenario.summary.id}: model={report.model.status} verdict={report.verdict.status} "
              f"risks={len(report.risks)} confirmed={confirmed}")
        for p in problems:
            print(f"     - {p}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
