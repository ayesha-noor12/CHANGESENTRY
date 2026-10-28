// Mirrors backend/app/models.py. Keep the two in sync.

export type Scenario = { id: string; title: string; description: string; category: string };

export type ChangedFile = {
  path: string;
  change_type: "added" | "modified" | "deleted";
  language: string;
  additions: number;
  deletions: number;
  diff: string;
  added_lines: number[];
};

export type GraphNode = {
  id: string;
  label: string;
  kind: "function" | "route" | "file";
  file: string;
  line: number | null;
  changed: boolean;
  route: string | null;
  depth: number;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  kind: "calls" | "imports" | "declares_dependency";
  confidence: "resolved" | "candidate";
  evidence: string;
};

export type CommandResult = {
  name: string;
  command: string;
  status: "passed" | "failed" | "findings" | "error" | "timeout" | "not_run";
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number;
  summary: string;
};

export type DeterministicSignal = {
  rule: string;
  file: string;
  line: number | null;
  symbol: string;
  message: string;
  evidence: string;
};

export type ModelStatus = {
  status: "ok" | "error" | "not_configured" | "skipped";
  model: string | null;
  summary: string;
  error: string | null;
  attempts: number;
  rejected_items: string[];
};

export type Impact = {
  file: string;
  symbol: string;
  relationship: string;
  evidence: string;
  confidence: "high" | "medium" | "low";
};

export type Verification = {
  template: string;
  target: string;
  outcome: "confirmed" | "not_reproduced" | "error" | "not_run";
  command: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number;
  test_code: string;
  test_cases: { name: string; result: string; message: string; time: number }[];
  note: string;
};

export type RiskStatus = "confirmed_by_test" | "not_reproduced" | "not_tested" | "test_error";

export type Risk = {
  id: string;
  source: "model" | "deterministic";
  kind: "security" | "regression";
  title: string;
  severity: "high" | "medium" | "low";
  file: string;
  line: number | null;
  evidence: string;
  explanation: string;
  status: RiskStatus;
  test_template: string;
  test_target: string;
  validation_notes: string[];
  plan: { source: string; expected_behavior: string; reason: string } | null;
  verification: Verification | null;
};

export type DependencyAdvisory = {
  name: string;
  ecosystem: string;
  old_version: string | null;
  new_version: string;
  osv_status: "affected" | "no_known_vulns" | "error" | "not_run";
  osv_error: string | null;
  osv_vulns: { id: string; summary: string; aliases: string[]; url: string }[];
  tavily_status: "ok" | "error" | "not_configured" | "not_run";
  tavily_error: string | null;
  tavily_query: string | null;
  tavily_results: { title: string | null; url: string | null; snippet: string | null }[];
};

export type Verdict = {
  status: "issues_confirmed" | "unverified_concerns" | "no_issue_detected" | "analysis_incomplete";
  headline: string;
  details: string[];
};

export type Report = {
  scenario: Scenario;
  changed_files: ChangedFile[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
  static_checks: CommandResult[];
  baseline_tests: CommandResult | null;
  deterministic_signals: DeterministicSignal[];
  model: ModelStatus;
  impacts: Impact[];
  risks: Risk[];
  advisories: DependencyAdvisory[];
  checks_not_performed: string[];
  verdict: Verdict | null;
};

export type Stage = {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "skipped" | "error";
  detail: string;
};

export type AnalysisRun = {
  run_id: string;
  scenario_id: string;
  status: "queued" | "running" | "completed" | "failed";
  stages: Stage[];
  started_at: number;
  finished_at: number | null;
  error: string | null;
  report: Report | null;
};

export type Health = {
  status: string;
  nemotron_configured: boolean;
  model: string | null;
  tavily_configured: boolean;
};
