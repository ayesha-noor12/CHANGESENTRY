"""Validate a verification plan against approved templates, render it, and run it.

The model only chooses a template id and a target. The backend checks both
against the repository index, fills the template with ``repr`` literals, writes
it into a disposable copy and runs a fixed pytest command with a timeout.
"""
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from string import Template

from app.config import TEMPLATES_DIR, TEST_TIMEOUT_SECONDS
from app.models import Verification
from app.repository_analyzer import RepoIndex, sample_payload
from app.sandbox import disposable_copy, run_command

MARKER = "CHANGESENTRY_INVARIANT_VIOLATED"
TEST_FILE = "tests/test_changesentry_verification.py"

TEMPLATE_DESCRIPTIONS = {
    "auth_guard": "Privileged route must reject unauthenticated and non-admin callers with 401/403. "
                  "Target format: 'METHOD /path' of a route.",
    "nonnegative_total": "Monetary function must never return a negative value for supported inputs "
                         "(percent 0-100, non-negative amounts). Target format: 'module:function'.",
}


@dataclass
class TargetCatalog:
    """Targets the backend will accept for each template, derived from the AST index."""
    auth_guard: dict[str, dict]
    nonnegative_total: dict[str, dict]

    def describe(self) -> dict:
        return {
            "auth_guard": {"description": TEMPLATE_DESCRIPTIONS["auth_guard"],
                           "valid_targets": sorted(self.auth_guard)},
            "nonnegative_total": {"description": TEMPLATE_DESCRIPTIONS["nonnegative_total"],
                                  "valid_targets": sorted(self.nonnegative_total)},
            "none": {"description": "No supported template applies.", "valid_targets": [""]},
        }

    def validate(self, template: str, target: str) -> str | None:
        """Return an error message, or None when the pair is acceptable."""
        if template == "none":
            return None
        options = getattr(self, template, None)
        if options is None:
            return f"unsupported template '{template}'"
        if target not in options:
            return f"target '{target}' is not a valid {template} target in this repository"
        return None


def build_catalog(index: RepoIndex, harness: dict) -> TargetCatalog:
    auth = {}
    if harness.get("dispatch_module"):
        for route, fn in index.routes().items():
            method, path = route.split(" ", 1)
            auth[route] = {"dispatch_module": harness["dispatch_module"], "method": method, "path": path,
                           "payload": sample_payload(fn.body_keys)}
    nonneg = {
        fid: {"module": fn.module, "function": fn.name}
        for fid, fn in index.numeric_functions().items()
        if "." not in fn.name
    }
    return TargetCatalog(auth_guard=auth, nonnegative_total=nonneg)


def render(template: str, params: dict) -> str:
    source = (TEMPLATES_DIR / f"{template}.py.tmpl").read_text(encoding="utf-8")
    return Template(source).substitute({k: repr(v) for k, v in params.items()})


def run_verification(fixture_dir: Path, catalog: TargetCatalog, template: str, target: str) -> Verification:
    error = catalog.validate(template, target)
    if template == "none" or error:
        return Verification(template=template, target=target, outcome="not_run",
                            note=error or "no supported template applies")
    params = getattr(catalog, template)[target]
    code = render(template, params)
    with disposable_copy(fixture_dir) as workspace:
        test_path = workspace / TEST_FILE
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(code, encoding="utf-8")
        junit = workspace.parent / "junit.xml"
        result, exit_code = run_command(
            "verification",
            [sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-s",
             f"--junitxml={junit}", TEST_FILE],
            workspace, TEST_TIMEOUT_SECONDS,
        )
        cases = _parse_junit(junit)
    command = result.command.replace(f"--junitxml={junit}", "--junitxml=<tmp>/junit.xml")

    failed = [c for c in cases if c["result"] == "failed"]
    errored = [c for c in cases if c["result"] == "error"]
    if result.status == "timeout":
        outcome, note = "error", "test timed out"
    elif failed and all(MARKER in c["message"] for c in failed) and not errored:
        outcome, note = "confirmed", f"{len(failed)} of {len(cases)} test case(s) demonstrated the violation"
    elif exit_code == 0 and cases:
        outcome, note = "not_reproduced", f"all {len(cases)} test case(s) passed"
    else:
        outcome, note = "error", "the test could not run to a conclusive result (see output)"
    return Verification(
        template=template, target=target, outcome=outcome, command=command, exit_code=exit_code,
        stdout=result.stdout, stderr=result.stderr, duration_ms=result.duration_ms,
        test_code=code, test_cases=cases, note=note,
    )


def _parse_junit(path: Path) -> list[dict]:
    if not path.exists():
        return []
    cases = []
    for case in ET.parse(path).getroot().iter("testcase"):
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            el = case.find(tag)
            if el is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = (el.get("message") or "")[:500]
                break
        cases.append({"name": case.get("name"), "result": outcome, "message": message,
                      "time": float(case.get("time") or 0)})
    return cases
