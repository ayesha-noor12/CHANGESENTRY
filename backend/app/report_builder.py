"""Combine repository facts, model hypotheses, advisories and real test outcomes into a verdict."""
from app.models import Report, Verdict

ALWAYS_NOT_PERFORMED = [
    "Call graph covers static imports and direct calls only; dynamic dispatch, reflection and "
    "framework-level wiring may hide additional relationships.",
    "Only the approved test templates were executed; behaviour outside their contracts was not tested.",
    "No checks were run against a deployed environment or its runtime configuration.",
]


def finalize(report: Report) -> Report:
    notes = []
    if report.model.status == "not_configured":
        notes.append("Nemotron analysis not performed: NEBIUS_API_KEY / NEBIUS_BASE_URL / NEBIUS_MODEL not set.")
    elif report.model.status == "error":
        notes.append(f"Nemotron analysis failed: {report.model.error}")
    for check in report.static_checks:
        if check.status == "not_run":
            notes.append(f"{check.name} not run: {check.summary}")
    for adv in report.advisories:
        if adv.tavily_status in ("not_configured", "error"):
            notes.append(f"Tavily advisory search for {adv.name} {adv.new_version} not performed: {adv.tavily_error}")
        if adv.osv_status == "error":
            notes.append(f"OSV lookup for {adv.name} {adv.new_version} failed: {adv.osv_error}")
    for risk in report.risks:
        if risk.status == "not_tested":
            reason = risk.verification.note if risk.verification else "no supported verification template"
            notes.append(f"Risk '{risk.title}' was not tested: {reason}.")
    report.checks_not_performed = notes + ALWAYS_NOT_PERFORMED
    report.verdict = _verdict(report)
    return report


def _verdict(report: Report) -> Verdict:
    confirmed = [r for r in report.risks if r.status == "confirmed_by_test"]
    unverified = [r for r in report.risks if r.status in ("not_tested", "test_error")]
    not_reproduced = [r for r in report.risks if r.status == "not_reproduced"]
    affected = [a for a in report.advisories if a.osv_status == "affected"]
    details = []
    for r in confirmed:
        details.append(f"Confirmed by test: {r.title} ({r.file}).")
    for a in affected:
        ids = ", ".join(v.id for v in a.osv_vulns[:4])
        details.append(f"{a.name} {a.new_version} is listed as affected in OSV ({ids}).")
    for r in unverified:
        details.append(f"Unverified hypothesis: {r.title} ({r.status.replace('_', ' ')}).")
    for r in not_reproduced:
        details.append(f"Tested and not reproduced: {r.title}.")
    if report.baseline_tests and report.baseline_tests.status == "failed":
        details.append(f"Existing test suite failed: {report.baseline_tests.summary}.")

    if confirmed or affected:
        n = len(confirmed) + len(affected)
        return Verdict(status="issues_confirmed", headline=f"{n} issue(s) confirmed by test or advisory database",
                       details=details)
    if unverified:
        return Verdict(status="unverified_concerns",
                       headline=f"{len(unverified)} concern(s) raised but not confirmed by a test", details=details)
    if report.model.status != "ok":
        return Verdict(status="analysis_incomplete",
                       headline="No issue detected by the deterministic checks; model analysis did not complete",
                       details=details)
    return Verdict(status="no_issue_detected", headline="No issue detected by the checks run",
                   details=details or ["This is not a guarantee that the change is safe to merge."])
