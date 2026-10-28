"""End-to-end analysis of one predefined scenario, with stage progress for the dashboard."""
import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError

from app import nemotron_client, prompts
from app.advisory_search import changed_dependencies, search_advisories
from app.config import nebius_configured
from app.models import (
    AnalysisRun, ModelAnalysisEnvelope, ModelImpact, ModelPlan, ModelRisk, ModelStatus, Report, Risk, Stage,
    VerificationPlan,
)
from app.report_builder import finalize
from app.repository_analyzer import RepoIndex, build_graph, build_index, compute_changes, guard_consistency, read_tree
from app.sandbox import disposable_copy
from app.scenarios import Scenario, get_scenario
from app.static_checks import run_bandit, run_existing_tests, run_ruff
from app.test_runner import TEMPLATE_DESCRIPTIONS, TargetCatalog, build_catalog, run_verification

STAGES = [
    ("load", "Load scenario"),
    ("diff", "Parse diff and AST"),
    ("map", "Map files and functions"),
    ("checks", "Run deterministic checks"),
    ("model", "Nemotron analysis"),
    ("advisories", "Advisory search"),
    ("validate", "Validate AI response"),
    ("plan", "Plan verification"),
    ("verify", "Run verification tests"),
    ("report", "Build evidence report"),
]
MAX_PLANNED_RISKS = 3
STATUS_FROM_OUTCOME = {"confirmed": "confirmed_by_test", "not_reproduced": "not_reproduced",
                       "error": "test_error", "not_run": "not_tested"}


class RunStore:
    def __init__(self):
        self._runs: dict[str, AnalysisRun] = {}
        self._lock = threading.Lock()

    def create(self, scenario_id: str) -> AnalysisRun:
        run = AnalysisRun(run_id=uuid.uuid4().hex[:12], scenario_id=scenario_id, status="queued",
                          stages=[Stage(key=k, label=label) for k, label in STAGES], started_at=time.time())
        with self._lock:
            self._runs[run.run_id] = run
            if len(self._runs) > 200:
                self._runs.pop(next(iter(self._runs)))
        return run

    def get(self, run_id: str) -> AnalysisRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run else None

    def stage(self, run_id: str, key: str, status: str, detail: str = "") -> None:
        with self._lock:
            run = self._runs[run_id]
            run.status = "running"
            for stage in run.stages:
                if stage.key == key:
                    stage.status, stage.detail = status, detail

    def publish(self, run_id: str, report: Report) -> None:
        with self._lock:
            self._runs[run_id].report = report.model_copy(deep=True)

    def finish(self, run_id: str, error: str | None = None) -> None:
        with self._lock:
            run = self._runs[run_id]
            run.status = "failed" if error else "completed"
            run.error = error
            run.finished_at = time.time()
            for stage in run.stages:
                if stage.status == "running":
                    stage.status = "error" if error else "done"


STORE = RunStore()


def run_analysis(run_id: str, store: RunStore = STORE) -> None:
    try:
        _run(run_id, store)
        store.finish(run_id)
    except Exception as exc:  # surfaced to the dashboard; never replaced with a fabricated report
        traceback.print_exc()
        store.finish(run_id, error=f"{type(exc).__name__}: {exc}")


def _run(run_id: str, store: RunStore) -> None:
    run = store.get(run_id)
    store.stage(run_id, "load", "running")
    scenario = get_scenario(run.scenario_id)
    if scenario is None:
        raise ValueError(f"unknown scenario '{run.scenario_id}'")
    before, after = read_tree(scenario.before_dir), read_tree(scenario.after_dir)
    store.stage(run_id, "load", "done", f"{len(after)} files in the changed version")

    store.stage(run_id, "diff", "running")
    changes = compute_changes(before, after)
    index = build_index(after)
    store.stage(run_id, "diff", "done", f"{len(changes)} changed file(s), {len(index.functions)} functions indexed")

    store.stage(run_id, "map", "running")
    graph, changed = build_graph(index, changes)
    report = Report(scenario=scenario.summary, changed_files=changes, graph=graph)
    store.publish(run_id, report)
    store.stage(run_id, "map", "done", f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")

    store.stage(run_id, "checks", "running")
    python_files = [c.path for c in changes if c.language == "python" and c.change_type != "deleted"]
    with disposable_copy(scenario.after_dir) as workspace:
        report.static_checks = [run_ruff(workspace, python_files), run_bandit(workspace, python_files)]
        report.baseline_tests = run_existing_tests(workspace)
    report.deterministic_signals = guard_consistency(index, changed)
    store.publish(run_id, report)
    store.stage(run_id, "checks", "done",
                f"existing tests: {report.baseline_tests.summary}; {len(report.deterministic_signals)} signal(s)")

    catalog = build_catalog(index, scenario.harness)
    has_deps = bool(changed_dependencies(before, after))
    store.stage(run_id, "model", "running" if nebius_configured() else "skipped",
                "" if nebius_configured() else "Token Factory not configured")
    store.stage(run_id, "advisories", "running" if has_deps else "skipped",
                "" if has_deps else "no dependency changes")
    with ThreadPoolExecutor(max_workers=2) as pool:
        model_future = pool.submit(_model_analysis, report, index, catalog)
        advisory_future = pool.submit(search_advisories, before, after) if has_deps else None
        envelope, report.model = model_future.result()
        if nebius_configured():
            store.stage(run_id, "model", "done" if report.model.status == "ok" else "error",
                        report.model.error or f"{report.model.attempts} call(s)")
        if advisory_future:
            report.advisories = advisory_future.result()
            store.stage(run_id, "advisories", "done", f"{len(report.advisories)} dependency change(s) searched")
    store.publish(run_id, report)

    store.stage(run_id, "validate", "running")
    _validate(report, envelope, index, catalog)
    _add_deterministic_risks(report, catalog)
    store.publish(run_id, report)
    store.stage(run_id, "validate", "done",
                f"{len(report.risks)} risk(s) accepted, {len(report.model.rejected_items)} item(s) rejected")

    store.stage(run_id, "plan", "running")
    _plan(report, index, catalog)
    store.stage(run_id, "plan", "done")

    store.stage(run_id, "verify", "running")
    _verify(report, scenario, catalog)
    store.publish(run_id, report)
    store.stage(run_id, "verify", "done",
                f"{sum(1 for r in report.risks if r.verification and r.verification.outcome != 'not_run')} test run(s)")

    store.stage(run_id, "report", "running")
    finalize(report)
    store.publish(run_id, report)
    store.stage(run_id, "report", "done", report.verdict.headline)


# ---------------------------------------------------------------- model analysis

def _model_analysis(report: Report, index: RepoIndex, catalog: TargetCatalog):
    if not nebius_configured():
        return None, ModelStatus(status="not_configured", error="Token Factory credentials are not configured")
    prompt = prompts.ANALYSIS_TEMPLATE.format(
        changed_files=prompts.dumps([{"path": c.path, "change_type": c.change_type,
                                      "additions": c.additions, "deletions": c.deletions}
                                     for c in report.changed_files]),
        git_diff=_cap("\n\n".join(c.diff for c in report.changed_files), 12_000),
        relationship_edges="\n".join(f"- {e.source} -[{e.kind}, {e.confidence}]-> {e.target}  ({e.evidence})"
                                     for e in report.graph.edges) or "(none found)",
        source_excerpts=_cap(_excerpts(report, index), 16_000),
        static_check_results=_cap(prompts.dumps(
            [{"tool": c.name, "status": c.status, "summary": c.summary, "output": c.stdout[:1500]}
             for c in report.static_checks]
            + [{"tool": "changesentry guard-consistency rule", "signal": s.message, "evidence": s.evidence}
               for s in report.deterministic_signals]), 6_000),
        baseline_test_results=_cap(prompts.dumps({
            "command": report.baseline_tests.command, "status": report.baseline_tests.status,
            "summary": report.baseline_tests.summary, "output": report.baseline_tests.stdout[-1500:]}), 3_000),
        approved_test_templates=prompts.dumps(catalog.describe()),
    )
    try:
        envelope, attempts = nemotron_client.chat_json(prompts.SYSTEM_PROMPT, prompt, ModelAnalysisEnvelope)
    except nemotron_client.ModelUnavailable as exc:
        return None, ModelStatus(status="error", model=nemotron_client.model_name(), error=str(exc))
    return envelope, ModelStatus(status="ok", model=nemotron_client.model_name(), summary=envelope.summary,
                                 attempts=attempts)


def _excerpts(report: Report, index: RepoIndex) -> str:
    parts = []
    for node in report.graph.nodes:
        if node.id in index.functions:
            tag = "CHANGED" if node.changed else f"connected (distance {node.depth})"
            parts.append(f"# {node.file} :: {node.id} [{tag}]\n{index.excerpt(node.id)}")
    return "\n\n".join(parts) or "(no Python functions in the impact set)"


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def _normalize_path(path: str) -> str:
    path = path.strip().lstrip("./")
    return path[2:] if path.startswith(("a/", "b/")) else path


def _validate(report: Report, envelope: ModelAnalysisEnvelope | None, index: RepoIndex,
              catalog: TargetCatalog) -> None:
    if envelope is None:
        return
    rejected = report.model.rejected_items
    for i, raw in enumerate(envelope.impacts):
        try:
            impact = ModelImpact.model_validate(raw)
        except ValidationError as exc:
            rejected.append(f"impact[{i}] malformed: {exc.errors()[0]['msg']}")
            continue
        impact.file = _normalize_path(impact.file)
        if impact.file not in index.files:
            rejected.append(f"impact[{i}] references unknown file '{impact.file}'")
            continue
        report.impacts.append(impact)
    for i, raw in enumerate(envelope.risks):
        try:
            item = ModelRisk.model_validate(raw)
        except ValidationError as exc:
            err = exc.errors()[0]
            rejected.append(f"risk[{i}] malformed field '{'.'.join(map(str, err['loc']))}': {err['msg']}")
            continue
        item.file = _normalize_path(item.file)
        if item.file not in index.files:
            rejected.append(f"risk[{i}] '{item.title}' references unknown file '{item.file}'")
            continue
        notes = []
        line_count = len(index.files[item.file].splitlines())
        if item.line is not None and not 1 <= item.line <= line_count:
            notes.append(f"model cited line {item.line}, outside the file (1-{line_count}); line dropped")
            item.line = None
        error = catalog.validate(item.test_template, item.test_target.strip())
        if error:
            notes.append(f"proposed test rejected: {error}")
            item.test_template, item.test_target = "none", ""
        report.risks.append(Risk(
            id=f"r{len(report.risks) + 1}", source="model", kind=item.kind, title=item.title,
            severity=item.severity, file=item.file, line=item.line, evidence=item.evidence,
            explanation=item.explanation, test_template=item.test_template,
            test_target=item.test_target.strip(), validation_notes=notes,
        ))


def _add_deterministic_risks(report: Report, catalog: TargetCatalog) -> None:
    covered = {(r.test_template, r.test_target) for r in report.risks}
    for signal in report.deterministic_signals:
        key = (signal.suggested_template, signal.suggested_target)
        if key in covered or catalog.validate(*key):
            continue
        covered.add(key)
        report.risks.append(Risk(
            id=f"r{len(report.risks) + 1}", source="deterministic", kind="security", severity="medium",
            title=f"Unguarded call on {signal.suggested_target}", file=signal.file, line=signal.line,
            evidence=signal.evidence, explanation=signal.message,
            test_template=signal.suggested_template, test_target=signal.suggested_target,
            plan=VerificationPlan(source="deterministic", expected_behavior=TEMPLATE_DESCRIPTIONS["auth_guard"],
                                  reason=f"Raised by the {signal.rule} rule."),
        ))


# ---------------------------------------------------------------- verification

def _plan(report: Report, index: RepoIndex, catalog: TargetCatalog) -> None:
    to_plan = [r for r in report.risks if r.source == "model" and r.test_template != "none"][:MAX_PLANNED_RISKS]
    if not to_plan or report.model.status != "ok":
        return
    inventory = sorted(fid for fid in index.functions if fid.split(":")[1].startswith("test_"))

    def plan_one(risk: Risk):
        prompt = prompts.PLAN_TEMPLATE.format(
            risk_json=prompts.dumps(risk.model_dump(include={"kind", "title", "severity", "file", "line",
                                                             "evidence", "explanation", "test_template",
                                                             "test_target"})),
            approved_test_templates=prompts.dumps(catalog.describe()),
            test_inventory=prompts.dumps(inventory),
        )
        try:
            plan, _ = nemotron_client.chat_json(prompts.SYSTEM_PROMPT, prompt, ModelPlan)
        except nemotron_client.ModelUnavailable as exc:
            return risk, None, str(exc)
        return risk, plan, None

    with ThreadPoolExecutor(max_workers=MAX_PLANNED_RISKS) as pool:
        results = list(pool.map(plan_one, to_plan))
    for risk, plan, error in results:
        if plan is None:
            risk.validation_notes.append(f"verification planning failed ({error}); using the risk's own proposal")
            risk.plan = VerificationPlan(source="risk", reason="Template proposed in the risk analysis.")
            continue
        target = plan.target.strip()
        problem = catalog.validate(plan.test_template, target)
        if problem:
            risk.validation_notes.append(f"plan rejected: {problem}; using the risk's own proposal")
            risk.plan = VerificationPlan(source="risk", reason="Template proposed in the risk analysis.")
            continue
        risk.test_template, risk.test_target = plan.test_template, target
        risk.plan = VerificationPlan(source="model", expected_behavior=plan.expected_behavior, reason=plan.reason)


def _verify(report: Report, scenario: Scenario, catalog: TargetCatalog) -> None:
    cache = {}
    for risk in report.risks:
        key = (risk.test_template, risk.test_target)
        if key not in cache:
            cache[key] = run_verification(scenario.after_dir, catalog, *key)
        risk.verification = cache[key].model_copy(deep=True)
        risk.status = STATUS_FROM_OUTCOME[risk.verification.outcome]


def run_sync(scenario_id: str) -> AnalysisRun:
    run = STORE.create(scenario_id)
    run_analysis(run.run_id)
    return STORE.get(run.run_id)


if __name__ == "__main__":  # python -m app.pipeline <scenario>
    import sys
    result = run_sync(sys.argv[1] if len(sys.argv) > 1 else "auth-boundary")
    print(json.dumps(result.model_dump(), indent=2, default=str))
