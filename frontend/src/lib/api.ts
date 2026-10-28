import type { AnalysisRun, Health, Scenario } from "./types";

// Same-origin: next.config.mjs proxies /api/* to the FastAPI backend.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, cache: "no-store" });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  scenarios: () => request<{ scenarios: Scenario[] }>("/api/scenarios").then((r) => r.scenarios),
  analyze: (scenario_id: string) =>
    request<AnalysisRun>("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id }),
    }),
  run: (runId: string) => request<AnalysisRun>(`/api/analysis/${runId}`),
};
