// Locates the Python backend and runs `python -m app.cli` on the developer's own repository.
import { execFile, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import * as vscode from "vscode";
import type { AnalysisRun } from "./types";

export const NEBIUS_KEY = "changesentry.nebiusApiKey";
export const TAVILY_KEY = "changesentry.tavilyApiKey";

type StageEvent = { event: "stage"; key: string; label: string; status: string; detail: string };
type ErrorEvent = { event: "error"; message: string };

export class BackendError extends Error {}

function settings() {
  return vscode.workspace.getConfiguration("changesentry");
}

export function backendPath(context: vscode.ExtensionContext): string {
  return settings().get<string>("backendPath") || join(context.extensionPath, "backend");
}

function managedPython(context: vscode.ExtensionContext): string {
  const bin = process.platform === "win32" ? join("Scripts", "python.exe") : join("bin", "python");
  return join(context.globalStorageUri.fsPath, "venv", bin);
}

export function pythonPath(context: vscode.ExtensionContext): string | undefined {
  const configured = settings().get<string>("pythonPath");
  if (configured) return configured;
  const managed = managedPython(context);
  return existsSync(managed) ? managed : undefined;
}

function run(command: string, args: string[], options: { cwd?: string; env?: NodeJS.ProcessEnv }, log: vscode.OutputChannel) {
  return new Promise<void>((resolve, reject) => {
    log.appendLine(`$ ${command} ${args.join(" ")}`);
    const child = spawn(command, args, { cwd: options.cwd, env: options.env ?? process.env });
    child.stdout.on("data", (d) => log.append(d.toString()));
    child.stderr.on("data", (d) => log.append(d.toString()));
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve() : reject(new BackendError(`${command} exited with ${code}`))));
  });
}

const MIN_PYTHON: [number, number] = [3, 10];

/** The first Python 3.10+ found, newest names first; macOS's built-in python3 is often 3.9 and is skipped. */
async function findPython(log: vscode.OutputChannel): Promise<string> {
  const names = process.platform === "win32"
    ? ["python", "python3", "py"]
    : ["python3.13", "python3.12", "python3.11", "python3.10", "python3",
       "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"];
  const seen: string[] = [];
  for (const name of names) {
    const version = await new Promise<string | undefined>((resolve) => {
      execFile(name, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], { timeout: 10000 },
        (err, stdout) => resolve(err ? undefined : stdout.trim()));
    });
    if (!version) continue;
    seen.push(`${name} (${version})`);
    const [major, minor] = version.split(".").map(Number);
    if (major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])) {
      log.appendLine(`Using ${name} (Python ${version}) for the ChangeSentry environment`);
      return name;
    }
  }
  throw new BackendError(
    `ChangeSentry needs Python 3.10 or newer. Found: ${seen.join(", ") || "no Python"}. `
    + "Install it from https://www.python.org/downloads/ (or 'brew install python'), then run 'ChangeSentry: Set up Python environment'.");
}

/** Create a private virtual environment in the extension's storage and install the backend requirements. */
export async function setupPython(context: vscode.ExtensionContext, log: vscode.OutputChannel): Promise<string> {
  const venv = join(context.globalStorageUri.fsPath, "venv");
  const requirements = join(backendPath(context), "requirements.txt");
  if (!existsSync(requirements)) throw new BackendError(`requirements.txt not found in ${backendPath(context)}`);
  await vscode.workspace.fs.createDirectory(context.globalStorageUri);
  const base = await findPython(log);
  await run(base, ["-m", "venv", "--clear", venv], {}, log);
  const python = managedPython(context);
  await run(python, ["-m", "pip", "install", "--disable-pip-version-check", "-r", requirements], {}, log);
  return python;
}

/** Run the analysis; stage events stream to onStage, the finished run is returned. */
export async function analyze(
  context: vscode.ExtensionContext,
  repo: string,
  base: string,
  head: string,
  onStage: (event: StageEvent) => void,
  token: vscode.CancellationToken,
  log: vscode.OutputChannel,
): Promise<AnalysisRun> {
  const python = pythonPath(context);
  if (!python) throw new BackendError("NO_PYTHON");
  const cwd = backendPath(context);
  if (!existsSync(join(cwd, "app", "cli.py"))) throw new BackendError(`ChangeSentry backend not found in ${cwd}`);

  const env: NodeJS.ProcessEnv = { ...process.env, PYTHONPATH: cwd, PYTHONDONTWRITEBYTECODE: "1" };
  const nebiusKey = await context.secrets.get(NEBIUS_KEY);
  const tavilyKey = await context.secrets.get(TAVILY_KEY);
  if (nebiusKey) {
    env.NEBIUS_API_KEY = nebiusKey;
    env.NEBIUS_BASE_URL = settings().get<string>("nebiusBaseUrl");
    env.NEBIUS_MODEL = settings().get<string>("nebiusModel");
  }
  if (tavilyKey) env.TAVILY_API_KEY = tavilyKey;
  log.appendLine(`Nebius key: ${nebiusKey ? "passed to the backend" : "NOT SET (Nemotron will be skipped)"} · ` +
    `Tavily key: ${tavilyKey ? "passed to the backend" : "not set"} · model: ${settings().get<string>("nebiusModel")}`);

  const args = ["-m", "app.cli", "--repo", repo, "--base", base, "--head", head];
  log.appendLine(`$ ${python} ${args.join(" ")}`);
  return new Promise<AnalysisRun>((resolve, reject) => {
    const child = spawn(python, args, { cwd, env });
    token.onCancellationRequested(() => child.kill());
    let stdout = "";
    let pending = "";
    let failure: string | undefined;
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => {
      pending += d.toString();
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) {
        try {
          const event = JSON.parse(line) as StageEvent | ErrorEvent;
          if (event.event === "stage") onStage(event);
          else if (event.event === "error") failure = event.message;
          continue;
        } catch {
          // not one of our events: tracebacks and tool output go to the log
        }
        log.appendLine(line);
      }
    });
    child.on("error", (err) => reject(new BackendError(`could not start ${python}: ${err.message}`)));
    child.on("close", (code) => {
      if (token.isCancellationRequested) return reject(new BackendError("cancelled"));
      if (failure) return reject(new BackendError(failure));
      const last = stdout.trim().split("\n").pop();
      if (!last) return reject(new BackendError(`analysis exited with code ${code}; see the ChangeSentry output`));
      try {
        resolve(JSON.parse(last) as AnalysisRun);
      } catch {
        reject(new BackendError("analysis output was not valid JSON; see the ChangeSentry output"));
      }
    });
  });
}
