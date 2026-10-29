"""Offline tests: no API keys or network required (model and advisory calls are stubbed)."""
import pytest

from app import nemotron_client, pipeline
from app.models import ModelAnalysisEnvelope, ModelPlan, ModelStatus, Report
from app.repository_analyzer import build_graph, build_index, compute_changes, guard_consistency, read_tree
from app.scenarios import get_scenario
from app.test_runner import build_catalog, run_verification


def _load(scenario_id, version="after"):
    s = get_scenario(scenario_id)
    before, after = read_tree(s.before_dir), read_tree(s.after_dir)
    index = build_index(after if version == "after" else before)
    changes = compute_changes(before, after)
    return s, index, changes


def _differential(scenario_id, template, target):
    s, head, _ = _load(scenario_id)
    _, base, _ = _load(scenario_id, "before")
    return run_verification(s.before_dir, s.after_dir, build_catalog(head, s.harness), template, target,
                            base_index=base, head_index=head)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in ("NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(pipeline, "search_advisories", lambda before, after: [])


def test_auth_boundary_graph_links_new_route_to_existing_service():
    _, index, changes = _load("auth-boundary")
    graph, changed = build_graph(index, changes)
    assert "app.routes.webhooks:payment_provider_webhook" in changed
    edges = {(e.source, e.target): e for e in graph.edges}
    edge = edges[("app.routes.webhooks:payment_provider_webhook", "app.services.billing:issue_refund")]
    assert edge.confidence == "resolved"
    # The existing guarded caller and its guard are pulled into the impact set.
    ids = {n.id for n in graph.nodes}
    assert {"app.routes.admin:refund_order", "app.auth:require_admin"} <= ids


def test_guard_consistency_flags_only_the_unguarded_route():
    _, index, changes = _load("auth-boundary")
    _, changed = build_graph(index, changes)
    signals = guard_consistency(index, changed)
    assert [s.suggested_target for s in signals] == ["POST /webhooks/payment-provider"]

    _, index, changes = _load("safe-change")
    _, changed = build_graph(index, changes)
    assert guard_consistency(index, changed) == []


def test_auth_guard_passes_on_base_and_fails_on_head():
    webhook = _differential("auth-boundary", "auth_guard", "POST /webhooks/payment-provider")
    assert (webhook.base.outcome, webhook.head.outcome) == ("passed", "violated"), webhook.head.stdout
    assert webhook.outcome == "regression_confirmed"
    assert any(e.file == "app/routes/admin.py" and "require_admin" in e.text for e in webhook.requirements)
    assert webhook.caveats and "does not exist in the base revision" in webhook.caveats[0]
    admin = _differential("auth-boundary", "auth_guard", "POST /admin/orders/refund")
    assert admin.outcome == "not_reproduced", admin.head.stdout


def test_nonnegative_runs_identical_inputs_on_both_revisions():
    result = _differential("checkout-regression", "nonnegative_total", "shop.checkout:checkout_total")
    assert (result.base.outcome, result.head.outcome) == ("passed", "violated"), result.base.stdout
    assert result.outcome == "regression_confirmed"
    assert any(e.file == "docs/pricing.md" for e in result.requirements)
    checked = [line for run in (result.base, result.head) for line in run.stdout.splitlines()
               if line.startswith("shop.checkout.checkout_total: checked")]
    assert len(checked) == 2 and checked[0].split(",")[0] == checked[1].split(",")[0]


def test_classification_needs_a_base_requirement_to_confirm():
    from app.models import RevisionRun
    from app.test_runner import classify
    passed, violated, error = (RevisionRun(revision="base", outcome=o) for o in ("passed", "violated", "error"))
    assert classify(passed, violated, True)[0] == "regression_confirmed"
    assert classify(passed, violated, False)[0] == "behavior_changed"
    assert classify(violated, violated, True)[0] == "fails_on_both"
    assert classify(violated, passed, True)[0] == "fixed_on_head"
    assert classify(passed, passed, True)[0] == "not_reproduced"
    assert classify(error, violated, True)[0] == "inconclusive"


def test_unapproved_target_is_never_executed():
    s, index, _ = _load("auth-boundary")
    catalog = build_catalog(index, s.harness)
    result = run_verification(s.before_dir, s.after_dir, catalog, "auth_guard", "POST /anything; rm -rf /",
                              base_index=index, head_index=index)
    assert result.outcome == "not_run" and result.base is None and result.head is None


def test_validation_rejects_invented_files_and_targets():
    s, index, changes = _load("auth-boundary")
    catalog = build_catalog(index, s.harness)
    report = Report(scenario=s.summary, changed_files=changes)
    report.model = ModelStatus(status="ok")
    envelope = ModelAnalysisEnvelope(summary="x", impacts=[], risks=[
        {"kind": "security", "title": "invented", "severity": "high", "file": "app/secret.py", "line": 1,
         "evidence": "", "explanation": "", "test_template": "none", "test_target": ""},
        {"kind": "security", "title": "bad target", "severity": "high", "file": "app/routes/webhooks.py",
         "line": 999, "evidence": "e", "explanation": "x", "test_template": "auth_guard", "test_target": "GET /nope"},
        {"kind": "made-up", "title": "malformed"},
    ])
    pipeline._validate(report, envelope, index, catalog)
    assert len(report.risks) == 1
    risk = report.risks[0]
    assert risk.test_template == "none" and risk.line is None
    assert len(report.model.rejected_items) == 2


def test_offline_runs_are_honest_about_missing_model():
    auth = pipeline.run_sync("auth-boundary").report
    assert auth.model.status == "not_configured"
    assert auth.verdict.status == "issues_confirmed"
    assert [r.source for r in auth.risks] == ["deterministic"]

    safe = pipeline.run_sync("safe-change").report
    assert safe.risks == []
    assert safe.verdict.status == "analysis_incomplete"
    assert any("Nemotron analysis not performed" in n for n in safe.checks_not_performed)


def test_full_flow_with_stubbed_model(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test")
    monkeypatch.setenv("NEBIUS_BASE_URL", "http://localhost.invalid")
    monkeypatch.setenv("NEBIUS_MODEL", "stub")

    def fake_chat_json(system, user, schema):
        if schema is ModelPlan:
            return ModelPlan(test_template="nonnegative_total", target="shop.checkout:checkout_total",
                             expected_behavior="total >= 0", reason="checkout calls apply_discount"), 1
        return ModelAnalysisEnvelope(summary="coupon stacking", impacts=[
            {"file": "shop/invoice.py", "symbol": "invoice_line", "relationship": "calls apply_discount",
             "evidence": "net = apply_discount(subtotal, percent)", "confidence": "high"}], risks=[
            {"kind": "regression", "title": "Negative totals", "severity": "high", "file": "shop/pricing.py",
             "line": 13, "evidence": "return round(discounted - coupon_amount, 2)", "explanation": "no clamp",
             "test_template": "nonnegative_total", "test_target": "shop.pricing:apply_discount"}]), 1

    monkeypatch.setattr(nemotron_client, "chat_json", fake_chat_json)
    report = pipeline.run_sync("checkout-regression").report
    assert report.model.status == "ok"
    risk = report.risks[0]
    assert risk.plan.source == "model" and risk.test_target == "shop.checkout:checkout_total"
    assert risk.status == "confirmed_by_test"
    assert report.verdict.status == "issues_confirmed"


def test_cli_analyzes_two_git_commits(tmp_path, capsys):
    import json

    from app import cli
    from scripts import make_demo_repo

    repo = tmp_path / "checkout"
    assert make_demo_repo.main("checkout-regression", str(repo)) == 0
    assert cli.main(["--repo", str(repo), "--base", "HEAD~1", "--head", "HEAD"]) == 0
    run = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert run["status"] == "completed"
    assert [c["path"] for c in run["report"]["changed_files"]] == ["shop/pricing.py"]
    assert run["report"]["base_existing_tests"]["status"] == "passed"


def test_cli_reports_unknown_git_ref(tmp_path, capsys):
    from app import cli
    from scripts import make_demo_repo

    repo = tmp_path / "safe"
    make_demo_repo.main("safe-change", str(repo))
    assert cli.main(["--repo", str(repo), "--base", "no-such-ref"]) == 2
    assert '"event": "error"' in capsys.readouterr().err
