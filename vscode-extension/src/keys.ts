// API key setup: status, manual entry, import from a .env file, and a live Nebius check.
import { readdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import * as vscode from "vscode";
import { NEBIUS_KEY, TAVILY_KEY } from "./backend";

const LABELS: Record<string, string> = {
  [NEBIUS_KEY]: "Nebius Token Factory API key",
  [TAVILY_KEY]: "Tavily API key",
};

/** Undo common paste mistakes: a NAME= prefix, surrounding quotes, spaces and line breaks. */
export function cleanKey(raw: string): string {
  return raw
    .trim()
    .replace(/^(?:export\s+)?[A-Z_]+\s*=\s*/, "")
    .replace(/^(['"])(.*)\1$/s, "$2")
    .replace(/\s+/g, "");
}

export async function hasNebiusKey(context: vscode.ExtensionContext): Promise<boolean> {
  return Boolean(await context.secrets.get(NEBIUS_KEY));
}

export async function setKey(context: vscode.ExtensionContext, key: string): Promise<boolean> {
  const value = await vscode.window.showInputBox({
    title: LABELS[key],
    prompt: "Stored in VS Code's encrypted secret storage. Leave empty to remove it.",
    password: true,
    ignoreFocusOut: true,
  });
  if (value === undefined) return false;
  const cleaned = cleanKey(value);
  if (cleaned) await context.secrets.store(key, cleaned);
  else await context.secrets.delete(key);
  vscode.window.showInformationMessage(cleaned ? `${LABELS[key]} saved.` : `${LABELS[key]} removed.`);
  return Boolean(cleaned);
}

/** Ask for the Nebius key, then the Tavily key; an empty answer keeps the current value. Then test Nebius. */
export async function enterKeys(context: vscode.ExtensionContext): Promise<boolean> {
  const steps: { key: string; required: boolean }[] = [
    { key: NEBIUS_KEY, required: true },
    { key: TAVILY_KEY, required: false },
  ];
  const saved: string[] = [];
  for (const [i, step] of steps.entries()) {
    const current = await context.secrets.get(step.key);
    const value = await vscode.window.showInputBox({
      title: `ChangeSentry API keys (${i + 1}/${steps.length}): ${LABELS[step.key]}`,
      prompt: current
        ? "A key is already saved. Paste a new one to replace it, or press Enter to keep it."
        : step.required
          ? "Required for Nemotron analysis. Stored in VS Code's encrypted secret storage."
          : "Optional: used to search dependency advisories. Press Enter to skip.",
      placeHolder: current ? "•••••••• (saved)" : step.required ? "Paste your Nebius Token Factory key" : "Paste your Tavily key, or leave empty",
      password: true,
      ignoreFocusOut: true,
      validateInput: (v) => (step.required && !current && !cleanKey(v) ? "The Nebius key is required." : undefined),
    });
    if (value === undefined) break; // Escape stops the flow; keys entered so far stay saved
    if (cleanKey(value)) {
      await context.secrets.store(step.key, cleanKey(value));
      saved.push(LABELS[step.key]);
    }
  }
  if (saved.length) vscode.window.showInformationMessage(`Saved: ${saved.join(", ")}.`);
  const ready = await hasNebiusKey(context);
  if (ready) await testNebius(context);
  return ready;
}

const LAST_ENV_FILE = "changesentry.lastEnvFile";

/** .env files that mention NEBIUS_API_KEY: the last one imported, then the open folders and their subfolders. */
async function findEnvFiles(context: vscode.ExtensionContext): Promise<string[]> {
  const candidates: string[] = [];
  const last = context.globalState.get<string>(LAST_ENV_FILE);
  if (last) candidates.push(last);
  const backend = vscode.workspace.getConfiguration("changesentry").get<string>("backendPath");
  if (backend) candidates.push(join(backend, ".env"));
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const root = folder.uri.fsPath;
    candidates.push(join(root, ".env"));
    const children = await readdir(root, { withFileTypes: true }).catch(() => []);
    for (const child of children) {
      if (child.isDirectory() && !child.name.startsWith(".") && child.name !== "node_modules") {
        candidates.push(join(root, child.name, ".env"));
      }
    }
  }
  const found: string[] = [];
  for (const path of new Set(candidates)) {
    const text = await readFile(path, "utf-8").catch(() => "");
    if (/^\s*(?:export\s+)?NEBIUS_API_KEY\s*=\s*\S/m.test(text)) found.push(path);
  }
  return found;
}

/** Read NEBIUS_API_KEY / TAVILY_API_KEY (and the model id) from a .env file, found automatically or picked. */
export async function importFromEnv(context: vscode.ExtensionContext): Promise<boolean> {
  const found = await findEnvFiles(context);
  const browse = "$(folder-opened) Browse for a .env file…";
  const choice = await vscode.window.showQuickPick(
    [...found.map((path) => ({ label: `$(file) ${path}`, path })), { label: browse, path: "" }],
    {
      title: "Import API keys from a .env file",
      placeHolder: found.length
        ? "Files that contain NEBIUS_API_KEY"
        : "No .env with NEBIUS_API_KEY in the open folders. Open the CHANGESENTRY folder, or browse.",
    },
  );
  if (!choice) return false;
  let path = choice.path;
  if (!path) {
    vscode.window.showInformationMessage("In the file dialog, press Cmd+Shift+. to show hidden files such as .env.");
    const picked = await vscode.window.showOpenDialog({
      title: "Pick the .env file that holds NEBIUS_API_KEY (for example CHANGESENTRY/backend/.env)",
      canSelectMany: false,
      openLabel: "Import keys",
      defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri ?? vscode.Uri.file(homedir()),
    });
    if (!picked?.[0]) return false;
    path = picked[0].fsPath;
  }
  let text: string;
  try {
    text = await readFile(path, "utf-8");
  } catch (err) {
    vscode.window.showErrorMessage(`Could not read ${path}: ${(err as Error).message}`);
    return false;
  }
  await context.globalState.update(LAST_ENV_FILE, path);
  const values: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?([A-Z_]+)\s*=\s*(.*?)\s*$/);
    if (match) values[match[1]] = cleanKey(match[2]);
  }
  const imported: string[] = [];
  if (values.NEBIUS_API_KEY) {
    await context.secrets.store(NEBIUS_KEY, values.NEBIUS_API_KEY);
    imported.push("Nebius key");
  }
  if (values.TAVILY_API_KEY) {
    await context.secrets.store(TAVILY_KEY, values.TAVILY_API_KEY);
    imported.push("Tavily key");
  }
  const config = vscode.workspace.getConfiguration("changesentry");
  if (values.NEBIUS_MODEL) {
    await config.update("nebiusModel", values.NEBIUS_MODEL, vscode.ConfigurationTarget.Global);
    imported.push(`model ${values.NEBIUS_MODEL}`);
  }
  if (!imported.length) {
    vscode.window.showWarningMessage("No NEBIUS_API_KEY or TAVILY_API_KEY found in that file.");
    return false;
  }
  if (!values.NEBIUS_API_KEY) {
    vscode.window.showInformationMessage(`Imported: ${imported.join(", ")}. Values are not shown or logged.`);
    return false;
  }
  const check = await checkNebius(context);
  if (check.state === "ok") {
    vscode.window.showInformationMessage(`Imported ${imported.join(", ")}. Nebius accepted the key.`);
    return true;
  }
  vscode.window.showErrorMessage(check.state === "unauthorized"
    ? `Imported from ${path}, but Nebius rejects this key too (401). Create a new key in the Nebius Token Factory console.`
    : `Imported from ${path}, but the key could not be verified: ${check.state === "error" ? check.message : check.state}.`);
  return false;
}

export type NebiusCheck =
  | { state: "ok"; models: string[] }
  | { state: "no_key" }
  | { state: "unauthorized" }
  | { state: "error"; message: string };

/** Ask Nebius which models the saved key can use. No UI, so it can run before every check. */
export async function checkNebius(context: vscode.ExtensionContext): Promise<NebiusCheck> {
  const key = await context.secrets.get(NEBIUS_KEY);
  if (!key) return { state: "no_key" };
  const base = (vscode.workspace.getConfiguration("changesentry").get<string>("nebiusBaseUrl") ?? "").replace(/\/+$/, "");
  try {
    const response = await fetch(`${base}/models`, {
      headers: { Authorization: `Bearer ${key}` },
      signal: AbortSignal.timeout(20000),
    });
    if (response.status === 401 || response.status === 403) return { state: "unauthorized" };
    if (!response.ok) return { state: "error", message: `Nebius returned HTTP ${response.status}` };
    const models = ((await response.json()) as { data?: { id: string }[] }).data?.map((m) => m.id) ?? [];
    return { state: "ok", models };
  } catch (err) {
    return { state: "error", message: `could not reach Nebius at ${base}: ${(err as Error).message}` };
  }
}

/** Offer to replace a key that Nebius rejected. Returns true when a new key was saved. */
export async function fixRejectedKey(context: vscode.ExtensionContext, message: string): Promise<boolean> {
  const choice = await vscode.window.showErrorMessage(message, { modal: true }, "Enter API keys…", "Import from .env file…");
  if (choice === "Enter API keys…") return enterKeys(context);
  if (choice === "Import from .env file…") return importFromEnv(context);
  return false;
}

/** List the models the key can use and confirm the configured Nemotron model is among them. */
export async function testNebius(context: vscode.ExtensionContext): Promise<boolean> {
  const config = vscode.workspace.getConfiguration("changesentry");
  const model = config.get<string>("nebiusModel") ?? "";
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "ChangeSentry: checking the Nebius key…" },
    () => checkNebius(context),
  );
  if (result.state === "no_key") {
    vscode.window.showWarningMessage("No Nebius API key is set.");
    return false;
  }
  if (result.state === "unauthorized") {
    await fixRejectedKey(context, "Nebius rejected the saved key (401 unauthorized). It may be incomplete or have extra characters. "
      + "Importing it from your .env file avoids copy-paste mistakes.");
    return false;
  }
  if (result.state === "error") {
    vscode.window.showErrorMessage(`ChangeSentry: ${result.message}.`);
    return false;
  }
  if (result.models.includes(model)) {
    vscode.window.showInformationMessage(`Nebius key works and ${model} is available.`);
    return true;
  }
  const nemotron = result.models.filter((id) => id.toLowerCase().includes("nemotron"));
  const choice = await vscode.window.showWarningMessage(
    `The key works, but ${model || "the configured model"} is not available to it.`,
    ...(nemotron.length ? ["Choose a Nemotron model"] : []),
  );
  if (choice) {
    const pick = await vscode.window.showQuickPick(nemotron, { title: "Nemotron models available to this key" });
    if (pick) await config.update("nebiusModel", pick, vscode.ConfigurationTarget.Global);
    return Boolean(pick);
  }
  return false;
}

/** One menu for everything key-related, showing what is currently set. */
export async function configureKeys(context: vscode.ExtensionContext): Promise<void> {
  const nebius = await context.secrets.get(NEBIUS_KEY);
  const tavily = await context.secrets.get(TAVILY_KEY);
  type Item = vscode.QuickPickItem & { action: () => Promise<unknown> };
  const items: Item[] = [
    { label: "$(key) Enter API keys…", description: "asks for the Nebius key, then the Tavily key", action: () => enterKeys(context) },
    { label: "$(file) Import keys from a .env file…", description: "e.g. CHANGESENTRY/backend/.env", action: () => importFromEnv(context) },
    { label: `$(key) Set Nebius API key`, description: nebius ? "set ✓" : "not set (required for Nemotron)", action: () => setKey(context, NEBIUS_KEY) },
    { label: `$(key) Set Tavily API key`, description: tavily ? "set ✓" : "not set (optional)", action: () => setKey(context, TAVILY_KEY) },
    { label: "$(plug) Test the Nebius key", description: "lists your models and checks the configured one", action: () => testNebius(context) },
    {
      label: "$(trash) Remove both keys",
      action: async () => {
        await context.secrets.delete(NEBIUS_KEY);
        await context.secrets.delete(TAVILY_KEY);
        vscode.window.showInformationMessage("ChangeSentry keys removed.");
      },
    },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    title: `ChangeSentry API keys · Nebius ${nebius ? "✓" : "✗"} · Tavily ${tavily ? "✓" : "✗"}`,
  });
  await pick?.action();
}
