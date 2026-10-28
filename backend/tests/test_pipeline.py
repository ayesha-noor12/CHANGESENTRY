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


def test_auth_guard_template_confirms_and_does_not_overclaim():
    s, index, _ = _load("auth-boundary")
    catalog = build_catalog(index, s.harness)
    webhook = run_verification(s.after_dir, catalog, "auth_guard", "POST /webhooks/payment-provider")
    assert webhook.outcome == "confirmed", webhook.stdout
    admin = run_verification(s.after_dir, catalog, "auth_guard", "POST /admin/orders/refund")
    assert admin.outcome == "not_reproduced", admin.stdout


def test_nonnegative_template_detects_regression_only_after_change():
    s, after_index, _ = _load("checkout-regression")
    after = run_verification(s.after_dir, build_catalog(after_index, s.harness), "nonnegative_total",
                             "shop.checkout:checkout_total")
    assert after.outcome == "confirmed", after.stdout
    _, before_index, _ = _load("checkout-regression", "before")
    before = run_verification(s.before_dir, build_catalog(before_index, s.harness), "nonnegative_total",
                              "shop.checkout:checkout_total")
    assert before.outcome == "not_reproduced", before.stdout


def test_unapproved_target_is_never_executed():
    s, index, _ = _load("auth-boundary")
    catalog = build_catalog(index, s.harness)
    result = run_verification(s.after_dir, catalog, "auth_guard", "POST /anything; rm -rf /")
    assert result.outcome == "not_run" and result.command == ""


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
