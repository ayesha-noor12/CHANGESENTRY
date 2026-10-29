// Webview that renders a ChangeSentry report: verdict, base/head results, requirements and logs.
import { randomBytes } from "node:crypto";
import * as vscode from "vscode";
import type { AnalysisRun, CommandResult, Report, RevisionRun, Risk, RiskStatus, Verification } from "./types";

const STATUS: Record<RiskStatus, { label: string; tone: string }> = {
  confirmed_by_test: { label: "Confirmed regression", tone: "red" },
  behavior_changed: { label: "Behaviour changed", tone: "amber" },
  preexisting_issue: { label: "Fails on base too", tone: "amber" },
  not_reproduced: { label: "Not reproduced", tone: "green" },
  not_tested: { label: "Not tested", tone: "grey" },
  test_error: { label: "Test error", tone: "amber" },
};

const OUTCOME: Record<Verification["outcome"], string> = {
  regression_confirmed: "Regression confirmed",
  behavior_changed: "Possible regression: no base requirement found",
  fails_on_both: "Fails on both revisions",
  fixed_on_head: "Fails on base, passes on head",
  not_reproduced: "Passes on both revisions",
  inconclusive: "Inconclusive",
  not_run: "Not run",
};

const VERDICT_TONE = {
  issues_confirmed: "red",
  unverified_concerns: "amber",
  no_issue_detected: "green",
  analysis_incomplete: "grey",
} as const;

function esc(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function badge(text: string, tone: string): string {
  return `<span class="badge ${tone}">${esc(text)}</span>`;
}

function fileLink(file: string, line?: number | null): string {
  const label = line ? `${file}:${line}` : file;
  return `<a href="#" class="file" data-file="${esc(file)}" data-line="${line ?? 1}">${esc(label)}</a>`;
}

function suiteBadge(c: CommandResult): string {
  if (c.status === "passed") return badge("PASS", "green");
  if (c.status === "failed") return badge("FAIL", "red");
  return badge(c.status.replace("_", " ").toUpperCase(), "amber");
}

function revisionCard(run: RevisionRun): string {
  const tone = run.outcome === "passed" ? "green" : run.outcome === "violated" ? "red" : "amber";
  const label = run.outcome === "passed" ? "PASS" : run.outcome === "violated" ? "FAIL" : "ERROR";
  const printed = run.test_cases.map((c) => c.stdout).filter(Boolean).join("\n");
  const failure = run.test_cases.find((c) => c.result !== "passed" && c.message);
  const cases = run.test_cases
    .map((c) => `<li class="${c.result === "passed" ? "ok" : "bad"}">${c.result === "passed" ? "✓" : "✗"} ${esc(c.name)}</li>`)
    .join("");
  return `<div class="rev">
    <div class="rev-head"><strong>${run.revision.toUpperCase()}</strong> ${badge(label, tone)}
      <span class="muted">exit ${run.exit_code ?? "–"} · ${run.duration_ms} ms</span></div>
    <ul class="cases">${cases}</ul>
    ${printed ? `<pre class="wrap">${esc(printed)}</pre>` : ""}
    ${failure ? `<div class="label red-text">Failed assertion</div><pre class="wrap red-text">${esc(failure.message.split(/\nassert /)[0])}</pre>` : ""}
    <details><summary>Full output</summary><pre>${esc((run.stdout + (run.stderr ? "\n" + run.stderr : "")).trim() || "(no output)")}</pre></details>
  </div>`;
}

function verification(v: Verification): string {
  if (v.outcome === "not_run" || !v.base || !v.head) return `<p class="muted">Not tested: ${esc(v.note)}</p>`;
  const requirements = v.requirements.length
    ? v.requirements
        .map((r) => `<li>${fileLink(r.file, r.line)}<pre>${esc(r.text)}</pre><div class="muted">${esc(r.reason)}</div></li>`)
        .join("")
    : `<li class="muted">None found. Without one, a behaviour difference is not reported as a confirmed regression.</li>`;
  const caveats = v.caveats.map((c) => `<div class="caveat">Note: ${esc(c)}</div>`).join("");
  return `<div class="box">
    <div class="label">Base vs head · ${esc(v.template)} · <code>${esc(v.target)}</code></div>
    <div class="outcome">${esc(OUTCOME[v.outcome])}</div>
    <div class="muted">${esc(v.note)}</div>
    <div class="revs">${revisionCard(v.base)}${revisionCard(v.head)}</div>
    <div class="label">Requirement in the base revision</div>
    <ul class="reqs">${requirements}</ul>
    ${caveats}
    <pre>$ ${esc(v.base.command)}</pre>
    <details><summary>Identical test on both revisions · sha256 <code>${esc(v.test_sha256.slice(0, 12))}</code></summary>
      <pre>${esc(v.test_code)}</pre></details>
  </div>`;
}

function riskCard(risk: Risk): string {
  const status = STATUS[risk.status];
  const notes = risk.validation_notes.map((n) => `<li>⚠ ${esc(n)}</li>`).join("");
  const plan = risk.plan && (risk.plan.expected_behavior || risk.plan.reason)
    ? `<div class="box muted"><div class="label">Verification plan (${risk.plan.source === "model" ? "proposed by model" : esc(risk.plan.source)})</div>
        ${risk.plan.expected_behavior ? `<div>Expected: ${esc(risk.plan.expected_behavior)}</div>` : ""}
        ${risk.plan.reason ? `<div>Why: ${esc(risk.plan.reason)}</div>` : ""}</div>`
    : "";
  return `<section class="card">
    <div>${badge(status.label, status.tone)} ${badge(risk.kind, "blue")} ${badge(risk.severity, risk.severity === "high" ? "red" : "grey")}
      ${badge(risk.source === "model" ? "model hypothesis" : "deterministic rule", "grey")}</div>
    <h3>${esc(risk.title)}</h3>
    <div>${fileLink(risk.file, risk.line)}</div>
    <p>${esc(risk.explanation)}</p>
    <div class="label">Evidence</div><pre>${esc(risk.evidence)}</pre>
    ${notes ? `<ul class="notes">${notes}</ul>` : ""}
    ${plan}
    ${risk.verification ? verification(risk.verification) : ""}
  </section>`;
}

function body(run: AnalysisRun): string {
  if (run.status === "failed" || !run.report) {
    return `<div class="verdict red"><strong>Analysis failed</strong><div>${esc(run.error ?? "no report")}</div></div>`;
  }
  const r: Report = run.report;
  const verdict = r.verdict
    ? `<div class="verdict ${VERDICT_TONE[r.verdict.status]}"><strong>${esc(r.verdict.headline)}</strong>
        <ul>${r.verdict.details.map((d) => `<li>${esc(d)}</li>`).join("")}</ul></div>`
    : "";
  const suite = r.base_existing_tests && r.baseline_tests
    ? `<div class="box"><div class="label">Existing test suite on both revisions</div>
        <div>base ${suiteBadge(r.base_existing_tests)} <span class="muted">${esc(r.base_existing_tests.summary)}</span></div>
        <div>head ${suiteBadge(r.baseline_tests)} <span class="muted">${esc(r.baseline_tests.summary)}</span></div></div>`
    : "";
  const changed = r.changed_files
    .map((c) => `<li>${badge(c.change_type, "grey")} ${fileLink(c.path)} <span class="muted">+${c.additions} −${c.deletions}</span></li>`)
    .join("");
  const risks = r.risks.length
    ? r.risks.map(riskCard).join("")
    : `<p class="muted">No risk hypotheses were raised for this change. This reflects only the checks listed below, not a guarantee.</p>`;
  const advisories = r.advisories
    .map((a) => `<li><code>${esc(a.name)} ${esc(a.old_version ? a.old_version + " → " : "")}${esc(a.new_version)}</code>
        ${a.osv_status === "affected" ? badge(`OSV: affected (${a.osv_vulns.length})`, "red") : badge(`OSV: ${a.osv_status.replace(/_/g, " ")}`, "grey")}
        ${a.osv_vulns.slice(0, 5).map((v) => `<a href="${esc(v.url)}">${esc(v.id)}</a>`).join(" ")}</li>`)
    .join("");
  const model = r.model;
  return `
    <h2>${esc(r.scenario.title)}</h2>
    ${verdict}
    ${suite}
    <div class="label">Changed files</div><ul class="plain">${changed || "<li class='muted'>none</li>"}</ul>
    ${risks}
    ${advisories ? `<div class="label">Dependency advisories</div><ul class="plain">${advisories}</ul>` : ""}
    <details><summary>Model: ${esc(model.model ?? "not configured")} · ${esc(model.status.replace("_", " "))}</summary>
      ${model.error ? `<p class="red-text">${esc(model.error)}</p>` : ""}
      ${model.summary ? `<p>${esc(model.summary)}</p>` : ""}
      ${model.rejected_items.length ? `<div class="label">Rejected by backend validation</div><ul>${model.rejected_items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    </details>
    <details><summary>Checks not performed / limits (${r.checks_not_performed.length})</summary>
      <ul>${r.checks_not_performed.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>`;
}

export function page(run: AnalysisRun, nonce: string, cspSource: string): string {
  return `<!doctype html><html><head><meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style nonce="${nonce}">
    body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground);
           background: var(--vscode-editor-background); padding: 12px 16px; line-height: 1.45; }
    h2 { font-size: 1.15em; margin: 0 0 10px; } h3 { font-size: 1.05em; margin: 8px 0 2px; }
    pre { font-family: var(--vscode-editor-font-family); font-size: 0.9em; background: var(--vscode-textCodeBlock-background);
          padding: 6px 8px; border-radius: 4px; overflow-x: auto; margin: 4px 0; }
    pre.wrap { white-space: pre-wrap; word-break: break-word; }
    code { font-family: var(--vscode-editor-font-family); }
    .card, .box, .verdict { border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 8px 10px; margin: 10px 0; }
    .verdict.red { border-color: var(--vscode-errorForeground); }
    .verdict.amber { border-color: var(--vscode-editorWarning-foreground); }
    .verdict.green { border-color: var(--vscode-testing-iconPassed); }
    .verdict ul, .notes, .reqs, .cases, .plain { margin: 4px 0; padding-left: 18px; }
    .plain, .cases { list-style: none; padding-left: 0; }
    .badge { display: inline-block; padding: 0 6px; border-radius: 3px; font-size: 0.85em; border: 1px solid; margin-right: 2px; }
    .badge.red { color: var(--vscode-errorForeground); }
    .badge.amber { color: var(--vscode-editorWarning-foreground); }
    .badge.green { color: var(--vscode-testing-iconPassed); }
    .badge.blue { color: var(--vscode-textLink-foreground); }
    .badge.grey { color: var(--vscode-descriptionForeground); }
    .red-text { color: var(--vscode-errorForeground); }
    .ok { color: var(--vscode-testing-iconPassed); } .bad { color: var(--vscode-errorForeground); }
    .muted { color: var(--vscode-descriptionForeground); }
    .label { font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.05em; color: var(--vscode-descriptionForeground); margin-top: 8px; }
    .outcome { font-weight: 600; margin-top: 2px; }
    .revs { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px; margin: 8px 0; }
    .rev { border: 1px solid var(--vscode-panel-border); border-radius: 4px; padding: 6px 8px; min-width: 0; }
    .rev-head { display: flex; gap: 6px; align-items: center; } .rev-head .muted { margin-left: auto; }
    .caveat { border: 1px solid var(--vscode-editorWarning-foreground); border-radius: 4px; padding: 6px 8px; margin: 8px 0; }
    a { color: var(--vscode-textLink-foreground); } summary { cursor: pointer; margin: 6px 0; }
  </style></head><body>${body(run)}
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    document.addEventListener("click", (event) => {
      const link = event.target.closest("a.file");
      if (!link) return;
      event.preventDefault();
      vscode.postMessage({ type: "open", file: link.dataset.file, line: Number(link.dataset.line) });
    });
  </script></body></html>`;
}

export class ReportPanel {
  private static current: ReportPanel | undefined;

  private constructor(private readonly panel: vscode.WebviewPanel, private repo: vscode.Uri) {
    panel.onDidDispose(() => (ReportPanel.current = undefined));
    panel.webview.onDidReceiveMessage(async (message: { type: string; file: string; line: number }) => {
      if (message.type !== "open") return;
      const uri = vscode.Uri.joinPath(this.repo, message.file);
      try {
        const doc = await vscode.workspace.openTextDocument(uri);
        const line = Math.max(0, message.line - 1);
        await vscode.window.showTextDocument(doc, {
          viewColumn: vscode.ViewColumn.One,
          selection: new vscode.Range(line, 0, line, 0),
        });
      } catch {
        vscode.window.showWarningMessage(`${message.file} is not in the working tree (it may exist only in the base revision).`);
      }
    });
  }

  static show(run: AnalysisRun, repo: vscode.Uri): void {
    if (!ReportPanel.current) {
      const panel = vscode.window.createWebviewPanel("changesentry.report", "ChangeSentry", vscode.ViewColumn.Beside, {
        enableScripts: true,
        localResourceRoots: [],
      });
      ReportPanel.current = new ReportPanel(panel, repo);
    }
    const current = ReportPanel.current;
    current.repo = repo;
    current.panel.title = `ChangeSentry: ${run.report?.verdict?.status === "issues_confirmed" ? "regression confirmed" : "report"}`;
    current.panel.webview.html = page(run, randomBytes(16).toString("hex"), current.panel.webview.cspSource);
    current.panel.reveal(vscode.ViewColumn.Beside);
  }
}
