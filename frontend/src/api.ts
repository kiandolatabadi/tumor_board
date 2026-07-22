import type { CaseDetail, CaseSummary, PanelResult } from "./types";

// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.ts).
// In a deployed build there is no proxy, so point at the hosted backend with
// VITE_API_BASE (e.g. https://your-app.onrender.com). Falls back to the proxy.
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** Convene the specialist panel over a case and return the board output. */
export async function runBoard(caseId: string): Promise<PanelResult> {
  const res = await fetch(`${BASE}/board`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId }),
  });
  if (!res.ok) {
    // Surface the backend's reason (e.g. missing API key) instead of just the code.
    let detail = "";
    try {
      detail = (await res.json()).detail || "";
    } catch {
      /* noop */
    }
    throw new Error(`POST /board failed: ${res.status}${detail ? ` — ${detail}` : ""}`);
  }
  return res.json();
}

export async function fetchCases(): Promise<CaseSummary[]> {
  const res = await fetch(`${BASE}/cases`);
  if (!res.ok) throw new Error(`GET /cases failed: ${res.status}`);
  return res.json();
}

export async function fetchCaseDetail(caseId: string): Promise<CaseDetail> {
  const res = await fetch(`${BASE}/cases/${encodeURIComponent(caseId)}`);
  if (!res.ok) throw new Error(`GET /cases/${caseId} failed: ${res.status}`);
  return res.json();
}
