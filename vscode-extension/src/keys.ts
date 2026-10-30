// API key setup: status, manual entry, import from a .env file, and a live Nebius check.
import { readFile } from "node:fs/promises";
import * as vscode from "vscode";
import { NEBIUS_KEY, TAVILY_KEY } from "./backend";

const LABELS: Record<string, string> = {
  [NEBIUS_KEY]: "Nebius Token Factory API key",
  [TAVILY_KEY]: "Tavily API key",
};

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
  if (value.trim()) await context.secrets.store(key, value.trim());
  else await context.secrets.delete(key);
  vscode.window.showInformationMessage(value.trim() ? `${LABELS[key]} saved.` : `${LABELS[key]} removed.`);
  return Boolean(value.trim());
}

/** Read NEBIUS_API_KEY / TAVILY_API_KEY (and the model id) from a .env file the user picks. */
export async function importFromEnv(context: vscode.ExtensionContext): Promise<boolean> {
  const picked = await vscode.window.showOpenDialog({
    title: "Pick the .env file that holds NEBIUS_API_KEY (for example backend/.env)",
    canSelectMany: false,
    openLabel: "Import keys",
    defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
  });
  if (!picked?.[0]) return false;
  let text: string;
  try {
    text = await readFile(picked[0].fsPath, "utf-8");
  } catch (err) {
    vscode.window.showErrorMessage(`Could not read ${picked[0].fsPath}: ${(err as Error).message}`);
    return false;
  }
  const values: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?([A-Z_]+)\s*=\s*(.*?)\s*$/);
    if (match) values[match[1]] = match[2].replace(/^(['"])(.*)\1$/, "$2");
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
  vscode.window.showInformationMessage(`Imported: ${imported.join(", ")}. Values are not shown or logged.`);
  return Boolean(values.NEBIUS_API_KEY);
}

/** List the models the key can use and confirm the configured Nemotron model is among them. */
export async function testNebius(context: vscode.ExtensionContext): Promise<void> {
  const key = await context.secrets.get(NEBIUS_KEY);
  if (!key) return void vscode.window.showWarningMessage("No Nebius API key is set.");
  const config = vscode.workspace.getConfiguration("changesentry");
  const base = (config.get<string>("nebiusBaseUrl") ?? "").replace(/\/+$/, "");
  const model = config.get<string>("nebiusModel") ?? "";
  try {
    const response = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "ChangeSentry: checking the Nebius key…" },
      () => fetch(`${base}/models`, { headers: { Authorization: `Bearer ${key}` }, signal: AbortSignal.timeout(20000) }),
    );
    if (response.status === 401 || response.status === 403) {
      return void vscode.window.showErrorMessage("Nebius rejected the key (unauthorized). Set it again.");
    }
    if (!response.ok) return void vscode.window.showErrorMessage(`Nebius returned HTTP ${response.status}.`);
    const ids = ((await response.json()) as { data?: { id: string }[] }).data?.map((m) => m.id) ?? [];
    if (ids.includes(model)) {
      vscode.window.showInformationMessage(`Nebius key works and ${model} is available.`);
    } else {
      const nemotron = ids.filter((id) => id.toLowerCase().includes("nemotron"));
      const choice = await vscode.window.showWarningMessage(
        `The key works, but ${model || "the configured model"} is not available to it.`,
        ...(nemotron.length ? ["Choose a Nemotron model"] : []),
      );
      if (choice) {
        const pick = await vscode.window.showQuickPick(nemotron, { title: "Nemotron models available to this key" });
        if (pick) await config.update("nebiusModel", pick, vscode.ConfigurationTarget.Global);
      }
    }
  } catch (err) {
    vscode.window.showErrorMessage(`Could not reach Nebius at ${base}: ${(err as Error).message}`);
  }
}

/** One menu for everything key-related, showing what is currently set. */
export async function configureKeys(context: vscode.ExtensionContext): Promise<void> {
  const nebius = await context.secrets.get(NEBIUS_KEY);
  const tavily = await context.secrets.get(TAVILY_KEY);
  type Item = vscode.QuickPickItem & { action: () => Promise<unknown> };
  const items: Item[] = [
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
