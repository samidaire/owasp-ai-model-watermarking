// Client for the demo backend (demo/server.py). The response types are the shared contract in
// ../../contract/types.ts; see ../../UI_INTEGRATION.md for every endpoint.
import type { DemoState, JobInfo, ServerStep } from "../../contract/types";

export type * from "../../contract/types";

/** Base URL of the backend. Empty = same origin (built UI served by server.py, or the Vite dev proxy). */
const API = (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_API_BASE ?? "";

export async function getState(): Promise<DemoState> {
  const r = await fetch(`${API}/api/state`, { cache: "no-store" });
  if (!r.ok) throw new Error(`state: HTTP ${r.status}`);
  return r.json();
}

export async function runStep(step: ServerStep, tries?: number): Promise<JobInfo> {
  const r = await fetch(`${API}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step, ...(tries ? { tries } : {}) }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? `run: HTTP ${r.status}`);
  return body as JobInfo;
}

/** Follows a job's output. Returns a function that stops listening (the job keeps running). */
export function streamJob(id: string, onLine: (line: string) => void, onDone: (info: JobInfo) => void): () => void {
  const es = new EventSource(`${API}/api/jobs/${id}/stream`);
  es.onmessage = (e) => onLine(JSON.parse(e.data));
  es.addEventListener("done", (e) => {
    es.close();
    onDone(JSON.parse((e as MessageEvent).data));
  });
  // On a dropped connection EventSource reconnects by itself and sends Last-Event-ID,
  // so the server resumes after the last line received (no duplicates).
  return () => es.close();
}

/** True when a result was produced with an older owner key than the one currently published. */
export function isStale(resultCommitment: string | undefined | null, current: string | null): boolean {
  return Boolean(resultCommitment && current && resultCommitment !== current);
}
