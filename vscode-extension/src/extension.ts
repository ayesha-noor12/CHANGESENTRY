// ChangeSentry for VS Code: analyze your own change locally and prove regressions on base vs head.
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as vscode from "vscode";
import { analyze, BackendError, NEBIUS_KEY, pythonPath, setupPython, TAVILY_KEY } from "./backend";
import { configureKeys, enterKeys, hasNebiusKey, importFromEnv, setKey, testNebius } from "./keys";
import { ReportPanel } from "./reportPanel";
import type { AnalysisRun, Risk } from "./types";

const exec = promisify(execFile);
const WORKTREE = "WORKTREE";

let lastRun: { run: AnalysisRun; repo: vscode.Uri } | undefined;

export function activate(context: vscode.ExtensionContext) {
  const log = vscode.window.createOutputChannel("ChangeSentry");
  const diagnostics = vscode.languages.createDiagnosticCollection("changesentry");
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.show();
  context.subscriptions.push(log, diagnostics, status);
  const refreshStatus = () => void updateStatus(context, status);
  refreshStatus();
  context.subscriptions.push(context.secrets.onDidChange(refreshStatus));

  const register = (id: string, fn: () => unknown) => context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  register("changesentry.configureKeys", () => configureKeys(context));
  register("changesentry.enterKeys", () => enterKeys(context));
  register("changesentry.setNebiusKey", () => setKey(context, NEBIUS_KEY));
  register("changesentry.setTavilyKey", () => setKey(context, TAVILY_KEY));
  register("changesentry.importKeys", () => importFromEnv(context));
  register("changesentry.testNebiusKey", () => testNebius(context));
  register("changesentry.setupPython", () => runSetup(context, log));
  register("changesentry.showReport", () => {
    if (lastRun) ReportPanel.show(lastRun.run, lastRun.repo);
    else vscode.window.showInformationMessage("No ChangeSentry report yet. Run 'ChangeSentry: Check my changes'.");
  });
  register("changesentry.checkChanges", () => checkChanges(context, log, diagnostics, status));

  void hasNebiusKey(context).then(async (ready) => {
    if (ready) return;
    const choice = await vscode.window.showInformationMessage(
      "ChangeSentry needs your Nebius API key (and optionally a Tavily key) to run Nemotron analysis.",
      "Enter API keys", "Import from .env file…");
    if (choice === "Enter API keys") await enterKeys(context);
    else if (choice === "Import from .env file…") await importFromEnv(context);
  });
}

async function updateStatus(context: vscode.ExtensionContext, status: vscode.StatusBarItem) {
  if (await hasNebiusKey(context)) {
    status.text = "$(shield) ChangeSentry";
    status.tooltip = "Check my changes: run the same test on base and head";
    status.command = "changesentry.checkChanges";
    status.backgroundColor = undefined;
  } else {
    status.text = "$(key) ChangeSentry: key needed";
    status.tooltip = "No Nebius API key set. Click to enter the Nebius and Tavily keys.";
    status.command = "changesentry.enterKeys";
    status.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
  }
}

export function deactivate() {}

async function runSetup(context: vscode.ExtensionContext, log: vscode.OutputChannel): Promise<boolean> {
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "ChangeSentry: installing the Python backend (first run, about a minute)…" },
      () => setupPython(context, log),
    );
    vscode.window.showInformationMessage("ChangeSentry Python environment is ready.");
    return true;
  } catch (err) {
    log.show(true);
    vscode.window.showErrorMessage(`ChangeSentry setup failed: ${(err as Error).message}. Python 3.10+ must be installed.`);
    return false;
  }
}

async function git(repo: string, ...args: string[]): Promise<string> {
  const { stdout } = await exec("git", ["-C", repo, ...args]);
  return stdout.trim();
}

async function pickRepo(): Promise<vscode.WorkspaceFolder | undefined> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length <= 1) return folders[0];
  return vscode.window.showWorkspaceFolderPick({ placeHolder: "Which repository should ChangeSentry check?" });
}

async function commitOf(repo: string, ref: string): Promise<{ sha: string; text: string } | undefined> {
  try {
    const [sha, short, subject] = (await git(repo, "log", "-1", "--format=%H%x00%h%x00%s", `${ref}^{commit}`, "--")).split("\0");
    return { sha, text: `${short} ${subject}` };
  } catch {
    return undefined;
  }
}

async function pickRevisions(repo: string): Promise<{ base: string; head: string } | undefined> {
  const dirty = (await git(repo, "status", "--porcelain").catch(() => "")).length > 0;
  const last = await commitOf(repo, "HEAD");
  if (!last) return void vscode.window.showWarningMessage("This repository has no commits yet.");
  const headItems: (vscode.QuickPickItem & { ref: string })[] = [
    { label: "Last commit", description: last.text, ref: "HEAD" },
    { label: "Uncommitted changes", description: dirty ? "working tree has changes" : "working tree is clean: nothing to check", ref: WORKTREE },
  ];
  if (dirty) headItems.reverse();
  const head = await vscode.window.showQuickPick(headItems, { title: "ChangeSentry (1/2): the changed code (head)" });
  if (!head) return;
  if (head.ref === WORKTREE && !dirty) {
    return void vscode.window.showWarningMessage("There are no uncommitted changes. Pick 'Last commit' instead.");
  }

  // Offer only bases that differ from the head; comparing a commit with itself finds nothing.
  const offered = new Set<string>();
  const candidates: (vscode.QuickPickItem & { ref: string })[] = [];
  const add = async (label: string, ref: string) => {
    const commit = await commitOf(repo, ref);
    if (!commit || offered.has(commit.sha) || (head.ref === "HEAD" && commit.sha === last.sha)) return;
    offered.add(commit.sha);
    candidates.push({ label, description: `${ref} · ${commit.text}`, ref });
  };
  if (head.ref === WORKTREE) await add("Last commit", "HEAD");
  await add("Previous commit", "HEAD~1");
  for (const branch of ["main", "master", "origin/main", "origin/master"]) await add(`Branch ${branch}`, branch);
  candidates.push({ label: "Other commit or branch…", ref: "" });
  const base = await vscode.window.showQuickPick(candidates, { title: "ChangeSentry (2/2): the original code to compare against (base)" });
  if (!base) return;
  const ref = base.ref || (await vscode.window.showInputBox({ prompt: "Base commit, tag or branch", placeHolder: "e.g. v1.2.0 or a1b2c3d" }));
  if (!ref) return;
  const chosen = await commitOf(repo, ref);
  if (!chosen) return void vscode.window.showWarningMessage(`'${ref}' is not a commit in this repository.`);
  if (head.ref === "HEAD" && chosen.sha === last.sha) {
    return void vscode.window.showWarningMessage(`'${ref}' is the same commit as the head, so there is nothing to compare.`);
  }
  return { base: ref, head: head.ref };
}

async function checkChanges(
  context: vscode.ExtensionContext,
  log: vscode.OutputChannel,
  diagnostics: vscode.DiagnosticCollection,
  status: vscode.StatusBarItem,
) {
  const folder = await pickRepo();
  if (!folder) return void vscode.window.showWarningMessage("Open a folder that is a git repository first.");
  const repo = folder.uri.fsPath;
  if (!(await git(repo, "rev-parse", "--git-dir").then(() => true, () => false))) {
    return void vscode.window.showWarningMessage(`${folder.name} is not a git repository.`);
  }
  if (!pythonPath(context)) {
    const choice = await vscode.window.showInformationMessage(
      "ChangeSentry needs its Python backend installed once.", "Install now", "Use my own Python…");
    if (choice === "Use my own Python…") {
      return void vscode.commands.executeCommand("workbench.action.openSettings", "changesentry.pythonPath");
    }
    if (choice !== "Install now" || !(await runSetup(context, log))) return;
  }
  if (!(await hasNebiusKey(context))) {
    const choice = await vscode.window.showWarningMessage(
      "No Nebius API key is set, so Nemotron cannot suggest what to test. Deterministic checks still run.",
      { modal: true },
      "Enter API keys…", "Import from .env file…", "Continue without");
    if (choice === "Enter API keys…") await enterKeys(context);
    else if (choice === "Import from .env file…") await importFromEnv(context);
    else if (choice !== "Continue without") return;
  }
  const revisions = await pickRevisions(repo);
  if (!revisions) return;

  status.text = "$(sync~spin) ChangeSentry";
  try {
    const run = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "ChangeSentry", cancellable: true },
      (progress, token) => {
        let done = 0;
        return analyze(context, repo, revisions.base, revisions.head, (event) => {
          if (event.status === "running") progress.report({ message: `${event.label}…` });
          if (event.status === "done" || event.status === "skipped") progress.report({ increment: 10, message: `${event.label} ✓ (${++done}/10)` });
        }, token, log);
      },
    );
    lastRun = { run, repo: folder.uri };
    const model = run.report?.model;
    log.appendLine(`Model: ${model?.model ?? "none"} · ${model?.status ?? "no report"}${model?.error ? ` · ${model.error}` : ""}`);
    log.appendLine(`Verdict: ${run.report?.verdict?.headline ?? run.error ?? "none"}`);
    showDiagnostics(run, folder.uri, diagnostics, revisions.head);
    ReportPanel.show(run, folder.uri);
    announce(run);
  } catch (err) {
    if (err instanceof BackendError && err.message === "cancelled") return;
    log.show(true);
    vscode.window.showErrorMessage(`ChangeSentry: ${(err as Error).message}`);
  } finally {
    await updateStatus(context, status);
  }
}

function announce(run: AnalysisRun) {
  const verdict = run.report?.verdict;
  if (!verdict) return void vscode.window.showErrorMessage(`ChangeSentry analysis failed: ${run.error ?? "no report"}`);
  const show = verdict.status === "issues_confirmed" ? vscode.window.showErrorMessage
    : verdict.status === "no_issue_detected" ? vscode.window.showInformationMessage
    : vscode.window.showWarningMessage;
  show(`ChangeSentry: ${verdict.headline}`);
}

const SEVERITY: Record<Risk["status"], vscode.DiagnosticSeverity> = {
  confirmed_by_test: vscode.DiagnosticSeverity.Error,
  behavior_changed: vscode.DiagnosticSeverity.Warning,
  preexisting_issue: vscode.DiagnosticSeverity.Warning,
  test_error: vscode.DiagnosticSeverity.Warning,
  not_tested: vscode.DiagnosticSeverity.Information,
  not_reproduced: vscode.DiagnosticSeverity.Hint,
};

const STATUS_TEXT: Record<Risk["status"], string> = {
  confirmed_by_test: "Confirmed regression: the same test passes on base and fails on head",
  behavior_changed: "Behaviour changed (passes on base, fails on head) but no base requirement was found",
  preexisting_issue: "Fails on base and head",
  test_error: "Verification test could not run to a conclusion",
  not_tested: "Hypothesis not tested",
  not_reproduced: "Tested and not reproduced",
};

function showDiagnostics(run: AnalysisRun, repo: vscode.Uri, collection: vscode.DiagnosticCollection, head: string) {
  collection.clear();
  if (head !== "HEAD" && head !== WORKTREE) return; // line numbers would not match the open files
  const byFile = new Map<string, vscode.Diagnostic[]>();
  for (const risk of run.report?.risks ?? []) {
    const line = Math.max(0, (risk.line ?? 1) - 1);
    const diagnostic = new vscode.Diagnostic(
      new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER),
      `${risk.title}. ${STATUS_TEXT[risk.status]}.`,
      SEVERITY[risk.status],
    );
    diagnostic.source = "ChangeSentry";
    diagnostic.code = risk.verification?.test_sha256 ? `test ${risk.verification.test_sha256.slice(0, 12)}` : risk.status;
    byFile.set(risk.file, [...(byFile.get(risk.file) ?? []), diagnostic]);
  }
  for (const [file, items] of byFile) collection.set(vscode.Uri.joinPath(repo, file), items);
}
