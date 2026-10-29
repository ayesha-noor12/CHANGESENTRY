"use client";

import { useState } from "react";
import type {
  CommandResult,
  DependencyAdvisory,
  DifferentialOutcome,
  Report,
  RevisionRun,
  Risk,
  RiskStatus,
} from "@/lib/types";
import { Badge, Code, Collapsible, Empty, PanelHeader } from "./ui";

const STATUS: Record<RiskStatus, { label: string; tone: "red" | "green" | "slate" | "amber" }> = {
  confirmed_by_test: { label: "Confirmed regression", tone: "red" },
  behavior_changed: { label: "Behaviour changed", tone: "amber" },
  preexisting_issue: { label: "Fails on base too", tone: "amber" },
  not_reproduced: { label: "Not reproduced", tone: "green" },
  not_tested: { label: "Not tested", tone: "slate" },
  test_error: { label: "Test error", tone: "amber" },
};

const OUTCOME: Record<DifferentialOutcome, string> = {
  regression_confirmed: "Regression confirmed",
  behavior_changed: "Possible regression: no base requirement found",
  fails_on_both: "Fails on both revisions",
  fixed_on_head: "Fails on base, passes on head",
  not_reproduced: "Passes on both revisions",
  inconclusive: "Inconclusive",
  not_run: "Not run",
};

const RUN_BADGE: Record<RevisionRun["outcome"], { label: string; tone: "red" | "green" | "amber" }> = {
  passed: { label: "PASS", tone: "green" },
  violated: { label: "FAIL", tone: "red" },
  error: { label: "ERROR", tone: "amber" },
};

const VERDICT_STYLE = {
  issues_confirmed: "border-red-500/40 bg-red-500/10 text-red-200",
  unverified_concerns: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  no_issue_detected: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  analysis_incomplete: "border-slate-500/40 bg-slate-500/10 text-slate-200",
};

type Tab = "findings" | "checks" | "advisories" | "model";

export function Findings({
  report,
  running,
  selectedRiskId,
  onSelectRisk,
}: {
  report: Report | null;
  running: boolean;
  selectedRiskId: string | null;
  onSelectRisk: (id: string | null) => void;
}) {
  const [tab, setTab] = useState<Tab>("findings");
  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "findings", label: "Findings", count: report?.risks.length },
    { key: "checks", label: "Checks", count: report ? report.static_checks.length + (report.baseline_tests ? 1 : 0) + (report.base_existing_tests ? 1 : 0) : undefined },
    { key: "advisories", label: "Advisories", count: report?.advisories.length },
    { key: "model", label: "Model" },
  ];

  return (
    <section className="flex min-h-0 flex-col">
      <PanelHeader title="Findings & verification" />
      <div className="flex shrink-0 gap-1 border-b border-white/5 px-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-2.5 py-1.5 text-[12px] ${
              tab === t.key ? "border-sky-400 text-slate-100" : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
          >
            {t.label}
            {t.count !== undefined && <span className="ml-1 text-slate-500">{t.count}</span>}
          </button>
        ))}
      </div>
      <div className="scrollbar-thin min-h-0 flex-1 space-y-3 overflow-auto p-3">
        {!report ? (
          <Empty>Findings, evidence and real test output appear here.</Empty>
        ) : tab === "findings" ? (
          <FindingsTab report={report} running={running} selectedRiskId={selectedRiskId} onSelectRisk={onSelectRisk} />
        ) : tab === "checks" ? (
          <ChecksTab report={report} />
        ) : tab === "advisories" ? (
          <AdvisoriesTab advisories={report.advisories} />
        ) : (
          <ModelTab report={report} />
        )}
      </div>
    </section>
  );
}

function FindingsTab({
  report,
  running,
  selectedRiskId,
  onSelectRisk,
}: {
  report: Report;
  running: boolean;
  selectedRiskId: string | null;
  onSelectRisk: (id: string | null) => void;
}) {
  return (
    <>
      {report.verdict ? (
        <div className={`rounded-md border px-3 py-2.5 ${VERDICT_STYLE[report.verdict.status]}`}>
          <div className="text-[13px] font-semibold">{report.verdict.headline}</div>
          <ul className="mt-1 space-y-0.5 text-[12px] opacity-90">
            {report.verdict.details.map((d, i) => (
              <li key={i}>• {d}</li>
            ))}
          </ul>
        </div>
      ) : (
        running && <div className="text-[12px] text-slate-500">Analysis in progress…</div>
      )}

      {report.risks.length === 0 && report.verdict && (
        <div className="rounded-md border border-white/5 px-3 py-2.5 text-[12px] text-slate-400">
          No risk hypotheses were raised for this change. This reflects only the checks listed below, not a guarantee.
        </div>
      )}

      {report.risks.map((risk) => (
        <RiskCard
          key={risk.id}
          risk={risk}
          selected={risk.id === selectedRiskId}
          onSelect={() => onSelectRisk(risk.id === selectedRiskId ? null : risk.id)}
        />
      ))}

      {report.checks_not_performed.length > 0 && report.verdict && (
        <Collapsible label={`Checks not performed / limits (${report.checks_not_performed.length})`}>
          <ul className="space-y-1 text-[11.5px] text-slate-400">
            {report.checks_not_performed.map((c, i) => (
              <li key={i}>• {c}</li>
            ))}
          </ul>
        </Collapsible>
      )}
    </>
  );
}

function RiskCard({ risk, selected, onSelect }: { risk: Risk; selected: boolean; onSelect: () => void }) {
  const status = STATUS[risk.status];
  const v = risk.verification;
  return (
    <div
      className={`rounded-md border bg-white/[0.02] ${selected ? "border-sky-400/60" : "border-white/10"} transition-colors`}
    >
      <button onClick={onSelect} className="w-full px-3 pt-2.5 text-left">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={status.tone}>{status.label}</Badge>
          <Badge tone={risk.kind === "security" ? "violet" : "blue"}>{risk.kind}</Badge>
          <Badge tone={risk.severity === "high" ? "red" : risk.severity === "medium" ? "amber" : "slate"}>
            {risk.severity}
          </Badge>
          <Badge tone="slate" title={risk.source === "model" ? "Hypothesis from Nemotron" : "Raised by a deterministic rule"}>
            {risk.source === "model" ? "model hypothesis" : "deterministic rule"}
          </Badge>
        </div>
        <div className="mt-1.5 text-[13px] font-medium text-slate-100">{risk.title}</div>
        <div className="font-mono text-[11px] text-slate-500">
          {risk.file}
          {risk.line ? `:${risk.line}` : ""}
        </div>
      </button>
      <div className="space-y-2 px-3 pb-3 pt-1.5">
        <p className="text-[12px] leading-relaxed text-slate-300">{risk.explanation}</p>
        <div>
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Evidence</div>
          <Code>{risk.evidence}</Code>
        </div>
        {risk.validation_notes.length > 0 && (
          <ul className="space-y-0.5 text-[11px] text-amber-300/80">
            {risk.validation_notes.map((n, i) => (
              <li key={i}>⚠ {n}</li>
            ))}
          </ul>
        )}
        {risk.plan && (risk.plan.expected_behavior || risk.plan.reason) && (
          <div className="rounded border border-white/5 px-2 py-1.5 text-[11.5px] text-slate-400">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Verification plan ({risk.plan.source === "model" ? "proposed by model" : risk.plan.source})
            </span>
            {risk.plan.expected_behavior && <div className="mt-0.5">Expected: {risk.plan.expected_behavior}</div>}
            {risk.plan.reason && <div className="mt-0.5">Why: {risk.plan.reason}</div>}
          </div>
        )}
        {v && <VerificationBlock v={v} />}
      </div>
    </div>
  );
}

function VerificationBlock({ v }: { v: NonNullable<Risk["verification"]> }) {
  if (v.outcome === "not_run" || !v.base || !v.head) {
    return <div className="text-[11.5px] text-slate-500">Not tested: {v.note}</div>;
  }
  return (
    <div className="space-y-2 rounded border border-white/10 bg-black/20 p-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Base vs head</span>
        <Badge tone="slate">{v.template}</Badge>
        <span className="font-mono text-slate-400">{v.target}</span>
      </div>
      <div className="text-[12px] font-medium text-slate-200">{OUTCOME[v.outcome]}</div>
      <div className="text-[11.5px] text-slate-400">{v.note}</div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <RevisionCard run={v.base} />
        <RevisionCard run={v.head} />
      </div>

      <div>
        <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Requirement in the base revision
        </div>
        {v.requirements.length === 0 ? (
          <div className="text-[11.5px] text-slate-400">
            None found. Without one, a behaviour difference is not reported as a confirmed regression.
          </div>
        ) : (
          <ul className="space-y-1">
            {v.requirements.map((r, i) => (
              <li key={i} className="text-[11.5px]">
                <span className="font-mono text-sky-300">
                  {r.file}:{r.line}
                </span>
                <Code className="mt-0.5">{r.text}</Code>
                <div className="text-slate-400">{r.reason}</div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {v.caveats.length > 0 && (
        <ul className="space-y-0.5 rounded border border-amber-500/20 px-2 py-1.5 text-[11.5px] text-amber-200/90">
          {v.caveats.map((c, i) => (
            <li key={i}>Note: {c}</li>
          ))}
        </ul>
      )}

      <Code className="max-h-40">$ {v.base.command}</Code>
      <Collapsible
        label={
          <>
            Identical test on both revisions · sha256 <span className="font-mono">{v.test_sha256.slice(0, 12)}</span>
          </>
        }
      >
        <Code className="max-h-72">{v.test_code}</Code>
      </Collapsible>
    </div>
  );
}

function RevisionCard({ run }: { run: RevisionRun }) {
  const badge = RUN_BADGE[run.outcome];
  const failure = run.test_cases.find((c) => c.result !== "passed" && c.message);
  return (
    <div className="min-w-0 space-y-1 rounded border border-white/10 p-2">
      <div className="flex items-center gap-2 text-[11px]">
        <span className="font-semibold uppercase tracking-wider text-slate-300">{run.revision}</span>
        <Badge tone={badge.tone}>{badge.label}</Badge>
        <span className="ml-auto text-slate-500">
          exit {run.exit_code ?? "–"} · {run.duration_ms} ms
        </span>
      </div>
      {run.test_cases.length > 0 && (
        <ul className="space-y-0.5 font-mono text-[11px]">
          {run.test_cases.map((c) => (
            <li key={c.name} className={`truncate ${c.result === "passed" ? "text-emerald-300" : "text-red-300"}`}>
              {c.result === "passed" ? "✓" : "✗"} {c.name}
            </li>
          ))}
        </ul>
      )}
      {failure && <Code className="max-h-24 whitespace-pre-wrap text-red-200/90">{failure.message}</Code>}
      <Collapsible label="Output">
        <Code className="max-h-64">{(run.stdout + (run.stderr ? "\n" + run.stderr : "")).trim() || "(no output)"}</Code>
      </Collapsible>
    </div>
  );
}

function CommandCard({ c }: { c: CommandResult }) {
  const tone =
    c.status === "passed" ? "green" : c.status === "findings" ? "amber" : c.status === "not_run" ? "slate" : "red";
  return (
    <div className="rounded-md border border-white/10 p-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[12.5px] font-medium text-slate-100">{c.name}</span>
        <Badge tone={tone}>{c.status.replace("_", " ")}</Badge>
        <span className="ml-auto text-[11px] text-slate-500">
          {c.exit_code !== null && `exit ${c.exit_code} · `}
          {c.duration_ms} ms
        </span>
      </div>
      <div className="mt-0.5 text-[11.5px] text-slate-400">{c.summary}</div>
      {c.status !== "not_run" && (
        <div className="mt-1.5">
          <Collapsible label="Command and output">
            <Code className="max-h-64">
              $ {c.command}
              {"\n"}
              {(c.stdout + (c.stderr ? "\n" + c.stderr : "")).trim() || "(no output)"}
            </Code>
          </Collapsible>
        </div>
      )}
    </div>
  );
}

function ChecksTab({ report }: { report: Report }) {
  return (
    <>
      {report.base_existing_tests && <CommandCard c={report.base_existing_tests} />}
      {report.baseline_tests && <CommandCard c={report.baseline_tests} />}
      {report.static_checks.map((c) => (
        <CommandCard key={c.name} c={c} />
      ))}
      <div className="rounded-md border border-white/10 p-2.5">
        <div className="text-[12.5px] font-medium text-slate-100">guard-consistency rule</div>
        {report.deterministic_signals.length === 0 ? (
          <div className="mt-0.5 text-[11.5px] text-slate-400">No changed route calls an operation that other routes guard.</div>
        ) : (
          report.deterministic_signals.map((s, i) => (
            <div key={i} className="mt-1.5 space-y-1">
              <div className="text-[11.5px] text-slate-300">{s.message}</div>
              <Code>{s.evidence}</Code>
            </div>
          ))
        )}
      </div>
      <p className="text-[11px] text-slate-500">
        Passing checks are evidence, not proof of security. Bandit and Ruff do not model authorization logic.
      </p>
    </>
  );
}

function AdvisoriesTab({ advisories }: { advisories: DependencyAdvisory[] }) {
  if (advisories.length === 0) return <Empty>No dependency was added or re-pinned in this change.</Empty>;
  return (
    <>
      {advisories.map((a) => (
        <div key={a.name} className="space-y-2 rounded-md border border-white/10 p-2.5">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[12.5px] text-slate-100">
              {a.name} {a.old_version ? `${a.old_version} → ` : ""}
              {a.new_version}
            </span>
            <Badge tone="slate">{a.ecosystem}</Badge>
            {!a.old_version && <Badge tone="blue">new dependency</Badge>}
          </div>

          <div>
            <div className="mb-1 flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                OSV · affected-version database
              </span>
              <Badge tone={a.osv_status === "affected" ? "red" : a.osv_status === "no_known_vulns" ? "green" : "amber"}>
                {a.osv_status === "affected"
                  ? `version listed as affected (${a.osv_vulns.length})`
                  : a.osv_status.replace(/_/g, " ")}
              </Badge>
            </div>
            {a.osv_error && <div className="text-[11.5px] text-amber-300/80">{a.osv_error}</div>}
            <ul className="space-y-1">
              {a.osv_vulns.map((v) => (
                <li key={v.id} className="text-[11.5px]">
                  <a href={v.url} target="_blank" rel="noreferrer" className="font-mono text-sky-300 hover:underline">
                    {v.id}
                  </a>
                  {v.aliases.length > 0 && <span className="text-slate-500"> ({v.aliases.join(", ")})</span>}
                  <div className="text-slate-400">{v.summary}</div>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <div className="mb-1 flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Tavily · search leads (unverified)
              </span>
              <Badge tone={a.tavily_status === "ok" ? "blue" : "amber"}>{a.tavily_status.replace("_", " ")}</Badge>
            </div>
            {a.tavily_error && <div className="text-[11.5px] text-amber-300/80">{a.tavily_error}</div>}
            {a.tavily_query && <div className="mb-1 font-mono text-[10.5px] text-slate-500">query: {a.tavily_query}</div>}
            <ul className="space-y-1.5">
              {a.tavily_results.map((r, i) => (
                <li key={i} className="text-[11.5px]">
                  <a href={r.url ?? "#"} target="_blank" rel="noreferrer" className="text-sky-300 hover:underline">
                    {r.title || r.url}
                  </a>
                  <div className="truncate font-mono text-[10.5px] text-slate-500">{r.url}</div>
                  {r.snippet && <div className="line-clamp-3 text-slate-400">{r.snippet}</div>}
                </li>
              ))}
            </ul>
            {a.tavily_status === "ok" && (
              <p className="mt-1 text-[10.5px] text-slate-500">
                Search results are leads; only the OSV match above is a version-specific confirmation.
              </p>
            )}
          </div>
        </div>
      ))}
    </>
  );
}

function ModelTab({ report }: { report: Report }) {
  const m = report.model;
  return (
    <>
      <div className="rounded-md border border-white/10 p-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[12.5px] font-medium text-slate-100">NVIDIA Nemotron · Nebius Token Factory</span>
          <Badge tone={m.status === "ok" ? "green" : m.status === "error" ? "red" : "slate"}>{m.status.replace("_", " ")}</Badge>
        </div>
        {m.model && <div className="mt-0.5 font-mono text-[11px] text-slate-500">{m.model}</div>}
        {m.error && <div className="mt-1 text-[11.5px] text-red-300/90">{m.error}</div>}
        {m.summary && <p className="mt-1.5 text-[12px] leading-relaxed text-slate-300">{m.summary}</p>}
        {m.attempts > 1 && <div className="mt-1 text-[11px] text-amber-300/80">Valid JSON after {m.attempts} attempts.</div>}
      </div>
      {report.impacts.length > 0 && (
        <div className="rounded-md border border-white/10 p-2.5">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Impacts named by the model</div>
          <ul className="space-y-1.5">
            {report.impacts.map((imp, i) => (
              <li key={i} className="text-[11.5px]">
                <span className="font-mono text-slate-200">{imp.symbol}</span>{" "}
                <span className="text-slate-500">({imp.file})</span> <Badge tone="slate">{imp.confidence}</Badge>
                <div className="text-slate-400">{imp.relationship}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {m.rejected_items.length > 0 && (
        <div className="rounded-md border border-amber-500/20 p-2.5">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-amber-300/80">
            Rejected by backend validation
          </div>
          <ul className="space-y-0.5 text-[11.5px] text-slate-400">
            {m.rejected_items.map((r, i) => (
              <li key={i}>• {r}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
