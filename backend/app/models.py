"""Pydantic schemas shared by the pipeline, the API and the frontend contract."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

TemplateId = Literal["auth_guard", "nonnegative_total", "none"]


# ---------------------------------------------------------------- scenarios

class ScenarioSummary(BaseModel):
    id: str
    title: str
    description: str
    category: str


# ---------------------------------------------------------------- changes

class ChangedFile(BaseModel):
    path: str
    change_type: Literal["added", "modified", "deleted"]
    language: str
    additions: int
    deletions: int
    diff: str
    added_lines: list[int] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str
    kind: Literal["function", "route", "file"]
    file: str
    line: Optional[int] = None
    changed: bool = False
    route: Optional[str] = None
    depth: int = 0


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: Literal["calls", "imports", "declares_dependency"]
    confidence: Literal["resolved", "candidate"]
    evidence: str


class ImpactGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ---------------------------------------------------------------- checks

class CommandResult(BaseModel):
    name: str
    command: str
    status: Literal["passed", "failed", "findings", "error", "timeout", "not_run"]
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    summary: str = ""


class DeterministicSignal(BaseModel):
    rule: str
    file: str
    line: Optional[int]
    symbol: str
    message: str
    evidence: str
    suggested_template: TemplateId = "none"
    suggested_target: str = ""


# ---------------------------------------------------------------- model output (validated)

class ModelImpact(BaseModel):
    file: str
    symbol: str
    relationship: str
    evidence: str
    confidence: Literal["high", "medium", "low"]


class ModelRisk(BaseModel):
    kind: Literal["security", "regression"]
    title: str
    severity: Literal["high", "medium", "low"]
    file: str
    line: Optional[int] = None
    evidence: str
    explanation: str
    status: Literal["hypothesis"] = "hypothesis"
    test_template: TemplateId = "none"
    test_target: str = ""


class ModelAnalysisEnvelope(BaseModel):
    """Top level is validated strictly; items are validated one by one afterwards."""
    summary: str
    impacts: list[dict] = Field(default_factory=list)
    risks: list[dict] = Field(default_factory=list)


class ModelPlan(BaseModel):
    test_template: TemplateId
    target: str
    expected_behavior: str
    reason: str


# ---------------------------------------------------------------- report

class ModelStatus(BaseModel):
    status: Literal["ok", "error", "not_configured", "skipped"]
    model: Optional[str] = None
    summary: str = ""
    error: Optional[str] = None
    attempts: int = 0
    rejected_items: list[str] = Field(default_factory=list)


class VerificationPlan(BaseModel):
    source: Literal["model", "risk", "deterministic"]
    expected_behavior: str = ""
    reason: str = ""


class RevisionRun(BaseModel):
    """One execution of the verification test against one revision."""
    revision: Literal["base", "head"]
    outcome: Literal["passed", "violated", "error"]
    command: str = ""
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    test_cases: list[dict] = Field(default_factory=list)
    note: str = ""


class RequirementEvidence(BaseModel):
    """Base-revision evidence that the tested invariant was already a requirement."""
    kind: Literal["enforced_in_base", "stated_in_base"]
    file: str
    line: int
    text: str
    reason: str


DifferentialOutcome = Literal[
    "regression_confirmed",  # base passes, head violates, requirement established in base
    "behavior_changed",      # base passes, head violates, no independent requirement found
    "fails_on_both",         # pre-existing issue, invalid test or incompatible assumption
    "fixed_on_head",         # base violates, head passes: possible improvement or intentional change
    "not_reproduced",        # passes on both revisions
    "inconclusive",          # at least one revision could not run to a conclusive result
    "not_run",
]


class Verification(BaseModel):
    template: str
    target: str
    outcome: DifferentialOutcome
    test_code: str = ""
    test_sha256: str = ""
    base: Optional[RevisionRun] = None
    head: Optional[RevisionRun] = None
    requirements: list[RequirementEvidence] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    note: str = ""


class Risk(BaseModel):
    id: str
    source: Literal["model", "deterministic"]
    kind: Literal["security", "regression"]
    title: str
    severity: Literal["high", "medium", "low"]
    file: str
    line: Optional[int] = None
    evidence: str
    explanation: str
    status: Literal["confirmed_by_test", "behavior_changed", "preexisting_issue", "not_reproduced",
                    "not_tested", "test_error"] = "not_tested"
    test_template: TemplateId = "none"
    test_target: str = ""
    validation_notes: list[str] = Field(default_factory=list)
    plan: Optional[VerificationPlan] = None
    verification: Optional[Verification] = None


class AdvisoryResult(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None


class OsvVuln(BaseModel):
    id: str
    summary: str = ""
    aliases: list[str] = Field(default_factory=list)
    url: str


class DependencyAdvisory(BaseModel):
    name: str
    ecosystem: str
    old_version: Optional[str]
    new_version: str
    osv_status: Literal["affected", "no_known_vulns", "error", "not_run"]
    osv_error: Optional[str] = None
    osv_vulns: list[OsvVuln] = Field(default_factory=list)
    tavily_status: Literal["ok", "error", "not_configured", "not_run"]
    tavily_error: Optional[str] = None
    tavily_query: Optional[str] = None
    tavily_results: list[AdvisoryResult] = Field(default_factory=list)


class Verdict(BaseModel):
    status: Literal["issues_confirmed", "unverified_concerns", "no_issue_detected", "analysis_incomplete"]
    headline: str
    details: list[str] = Field(default_factory=list)


class Report(BaseModel):
    scenario: ScenarioSummary
    changed_files: list[ChangedFile] = Field(default_factory=list)
    graph: ImpactGraph = Field(default_factory=lambda: ImpactGraph(nodes=[], edges=[]))
    static_checks: list[CommandResult] = Field(default_factory=list)
    baseline_tests: Optional[CommandResult] = None       # existing suite on the head revision
    base_existing_tests: Optional[CommandResult] = None  # the same suite on the base revision
    deterministic_signals: list[DeterministicSignal] = Field(default_factory=list)
    model: ModelStatus = Field(default_factory=lambda: ModelStatus(status="skipped"))
    impacts: list[ModelImpact] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    advisories: list[DependencyAdvisory] = Field(default_factory=list)
    checks_not_performed: list[str] = Field(default_factory=list)
    verdict: Optional[Verdict] = None


class Stage(BaseModel):
    key: str
    label: str
    status: Literal["pending", "running", "done", "skipped", "error"] = "pending"
    detail: str = ""


class AnalysisRun(BaseModel):
    run_id: str
    scenario_id: str
    status: Literal["queued", "running", "completed", "failed"]
    stages: list[Stage]
    started_at: float
    finished_at: Optional[float] = None
    error: Optional[str] = None
    report: Optional[Report] = None


class AnalyzeRequest(BaseModel):
    scenario_id: str
    wait: bool = False
