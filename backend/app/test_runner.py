"""Validate a verification plan against approved templates, render it, and run it on both revisions.

The model only chooses a template id and a target. The backend checks both
against the repository index, fills the template with ``repr`` literals and
writes the identical file into disposable copies of the base and head
revisions, where it runs a fixed pytest command with a timeout.
"""
import hashlib
import itertools
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from string import Template

from app.config import TEMPLATES_DIR, TEST_TIMEOUT_SECONDS
from app.expectations import find_requirements
from app.models import RevisionRun, Verification
from app.repository_analyzer import FunctionInfo, RepoIndex, sample_payload
from app.sandbox import disposable_copy, run_command

MARKER = "CHANGESENTRY_INVARIANT_VIOLATED"
TEST_FILE = "tests/test_changesentry_verification.py"
PERCENT_VALUES = [0.0, 50.0, 100.0]
AMOUNT_VALUES = [0.0, 10.0, 25.0, 100.0]

TEMPLATE_DESCRIPTIONS = {
    "auth_guard": "Privileged route must reject unauthenticated and non-admin callers with 401/403 "
                  "(404 when the route does not exist). "
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
        fid: {"module": fn.module, "function": fn.name, "cases": _input_cases(fn)}
        for fid, fn in index.numeric_functions().items()
        if "." not in fn.name
    }
    return TargetCatalog(auth_guard=auth, nonnegative_total=nonneg)


def _input_cases(fn: FunctionInfo) -> list[dict]:
    """Every combination of supported values for the function's parameters, fixed at render time."""
    names = [name for name, _ in fn.params]
    grids = [PERCENT_VALUES if ("percent" in n or "rate" in n) else AMOUNT_VALUES for n in names]
    return [dict(zip(names, combo)) for combo in itertools.product(*grids)]


def render(template: str, params: dict) -> str:
    source = (TEMPLATES_DIR / f"{template}.py.tmpl").read_text(encoding="utf-8")
    return Template(source).substitute({k: repr(v) for k, v in params.items()})


def run_verification(base_dir: Path, head_dir: Path, catalog: TargetCatalog, template: str, target: str,
                     base_index: RepoIndex, head_index: RepoIndex) -> Verification:
    """Run one rendered test, byte for byte the same, on the base and head revisions and compare."""
    error = catalog.validate(template, target)
    if template == "none" or error:
        return Verification(template=template, target=target, outcome="not_run",
                            note=error or "no supported template applies")
    code = render(template, getattr(catalog, template)[target])
    base = _run_revision("base", base_dir, code)
    head = _run_revision("head", head_dir, code)
    requirements = find_requirements(template, target, base_index, head_index)
    outcome, note = classify(base, head, bool(requirements))
    return Verification(
        template=template, target=target, outcome=outcome, test_code=code,
        test_sha256=hashlib.sha256(code.encode()).hexdigest(), base=base, head=head,
        requirements=requirements, caveats=_caveats(template, target, base_index), note=note,
    )


def _caveats(template: str, target: str, base_index: RepoIndex) -> list[str]:
    if template == "auth_guard" and target not in base_index.routes():
        return [f"{target} does not exist in the base revision, so base returns 404. Base PASS shows the endpoint "
                "was not reachable before the change; it does not show that the change removed a guard from "
                "this route. The requirement comes from other base routes that guard the same operation."]
    return []


def classify(base: RevisionRun, head: RevisionRun, requirement_established: bool) -> tuple[str, str]:
    pair = (base.outcome, head.outcome)
    if "error" in pair:
        broken = " and ".join(r.revision for r in (base, head) if r.outcome == "error")
        return "inconclusive", f"the test could not run to a conclusive result on {broken} (see output)"
    if pair == ("passed", "violated"):
        if requirement_established:
            return "regression_confirmed", ("passes on base, fails on head, and the base revision already "
                                            "requires this behaviour")
        return "behavior_changed", ("passes on base, fails on head, but no base-revision requirement was found; "
                                    "this may be an intended change")
    if pair == ("violated", "violated"):
        return "fails_on_both", "fails on both revisions: a pre-existing issue or an invalid test"
    if pair == ("violated", "passed"):
        return "fixed_on_head", "fails on base, passes on head: a possible improvement or intentional change"
    return "not_reproduced", "passes on both revisions: the hypothesis was not reproduced by this test"


def _run_revision(revision: str, fixture_dir: Path, code: str) -> RevisionRun:
    with disposable_copy(fixture_dir) as workspace:
        test_path = workspace / TEST_FILE
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(code, encoding="utf-8")
        junit = workspace.parent / "junit.xml"
        result, exit_code = run_command(
            f"verification ({revision})",
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
        outcome, note = "violated", f"{len(failed)} of {len(cases)} test case(s) demonstrated the violation"
    elif exit_code == 0 and cases:
        outcome, note = "passed", f"all {len(cases)} test case(s) passed"
    else:
        outcome, note = "error", "the test could not run to a conclusive result (see output)"
    return RevisionRun(
        revision=revision, outcome=outcome, command=command, exit_code=exit_code, stdout=result.stdout,
        stderr=result.stderr, duration_ms=result.duration_ms, test_cases=cases, note=note,
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
