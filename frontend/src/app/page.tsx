"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChangeViewer } from "@/components/ChangeViewer";
import { Findings } from "@/components/Findings";
import { ImpactGraph } from "@/components/ImpactGraph";
import { Badge } from "@/components/ui";
import { api } from "@/lib/api";
import type { AnalysisRun, Health, Scenario, Stage } from "@/lib/types";

const POLL_MS = 900;

export default function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedRiskId, setSelectedRiskId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    Promise.all([api.health(), api.scenarios()])
      .then(([h, s]) => {
        setHealth(h);
        setScenarios(s);
        setSelected((cur) => cur ?? s[0]?.id ?? null);
      })
      .catch((e: Error) => setError(`Backend unreachable: ${e.message}`));
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  const poll = useCallback((runId: string) => {
    api
      .run(runId)
      .then((r) => {
        setRun(r);
        if (r.status === "queued" || r.status === "running") {
          pollRef.current = setTimeout(() => poll(runId), POLL_MS);
        } else {
          const firstRisk = r.report?.risks.find((x) => x.status === "confirmed_by_test") ?? r.report?.risks[0];
          setSelectedRiskId(firstRisk?.id ?? null);
        }
      })
      .catch((e: Error) => setError(`Lost contact with the analysis run: ${e.message}`));
  }, []);

  const analyze = async (scenarioId: string) => {
    if (pollRef.current) clearTimeout(pollRef.current);
    setSelected(scenarioId);
    setError(null);
    setSelectedRiskId(null);
    setRun(null);
    try {
      const r = await api.analyze(scenarioId);
      setRun(r);
      poll(r.run_id);
    } catch (e) {
      setError(`Could not start analysis: ${(e as Error).message}`);
    }
  };

  const running = run?.status === "queued" || run?.status === "running";
  const report = run?.report ?? null;
  const selectedRisk = report?.risks.find((r) => r.id === selectedRiskId) ?? null;
  const scenario = scenarios.find((s) => s.id === selected);

  return (
    <div className="flex h-screen min-h-[640px] flex-col">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b border-white/5 px-4">
        <div className="flex items-center gap-2">
          <Logo />
          <span className="text-[14px] font-semibold tracking-tight text-slate-100">ChangeSentry</span>
          <span className="hidden text-[12px] text-slate-500 md:inline">
            Detect what a code change could break before it reaches production.
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {health && (
            <>
              <Badge tone={health.nemotron_configured ? "green" : "amber"} title={health.model ?? "not configured"}>
                Nemotron {health.nemotron_configured ? "ready" : "not configured"}
              </Badge>
              <Badge tone={health.tavily_configured ? "green" : "amber"}>
                Tavily {health.tavily_configured ? "ready" : "not configured"}
              </Badge>
            </>
          )}
        </div>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-white/5 px-4 py-2.5">
        <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Scenario</span>
        {scenarios.map((s) => (
          <button
            key={s.id}
            disabled={running}
            onClick={() => analyze(s.id)}
            className={`rounded-md border px-3 py-1.5 text-left text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
              s.id === selected ? "border-sky-400/50 bg-sky-400/10 text-slate-100" : "border-white/10 text-slate-300 hover:border-white/20"
            }`}
          >
            <span className="font-medium">{s.title}</span>
            <span className="ml-2 text-[10.5px] uppercase tracking-wider text-slate-500">{s.category}</span>
          </button>
        ))}
        <span className="ml-auto text-[11.5px] text-slate-500">
          {running ? "Analyzing…" : run?.status === "completed" ? `Run ${run.run_id} · ${duration(run)}` : "Click a scenario to analyze it"}
        </span>
      </div>

      {scenario && <div className="shrink-0 px-4 py-1.5 text-[12px] text-slate-400">{scenario.description}</div>}
      {run && <StageBar stages={run.stages} />}
      {(error || run?.error) && (
        <div className="mx-4 my-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12.5px] text-red-200">
          {error ?? `Analysis failed: ${run?.error}`}
        </div>
      )}

      <main className="grid min-h-0 flex-1 grid-cols-1 divide-white/5 overflow-y-auto lg:overflow-hidden [&>section]:min-h-[480px] lg:[&>section]:min-h-0 lg:grid-cols-[minmax(300px,0.9fr)_minmax(360px,1.2fr)_minmax(360px,1fr)] lg:divide-x">
        <ChangeViewer files={report?.changed_files ?? []} />
        <ImpactGraph nodes={report?.graph.nodes ?? []} edges={report?.graph.edges ?? []} selectedRisk={selectedRisk} />
        <Findings report={report} running={running} selectedRiskId={selectedRiskId} onSelectRisk={setSelectedRiskId} />
      </main>
    </div>
  );
}

function duration(run: AnalysisRun) {
  return run.finished_at ? `${(run.finished_at - run.started_at).toFixed(1)}s` : "";
}

function StageBar({ stages }: { stages: Stage[] }) {
  return (
    <ol className="scrollbar-thin flex shrink-0 gap-1 overflow-x-auto border-b border-white/5 px-4 py-2">
      {stages.map((s, i) => {
        const tone =
          s.status === "done"
            ? "border-emerald-500/30 text-emerald-300"
            : s.status === "running"
              ? "border-sky-400/50 text-sky-200 animate-pulse"
              : s.status === "error"
                ? "border-red-500/40 text-red-300"
                : s.status === "skipped"
                  ? "border-white/5 text-slate-600"
                  : "border-white/5 text-slate-500";
        return (
          <li key={s.key} title={s.detail || s.status} className={`shrink-0 rounded border px-2 py-1 text-[11px] ${tone}`}>
            <span className="mr-1 text-slate-600">{i + 1}</span>
            {s.label}
            {s.status === "skipped" && <span className="ml-1 text-slate-600">(skipped)</span>}
          </li>
        );
      })}
    </ol>
  );
}

function Logo() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z" stroke="#38bdf8" strokeWidth="1.8" />
      <path d="m8.5 12 2.5 2.5 4.5-5" stroke="#38bdf8" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
