// Client for the demo backend (demo/server.py). The response types are the shared contract in
// ../../contract/types.ts; see ../../UI_INTEGRATION.md for every endpoint.
import type { DemoState, ErrorBody, JobDetail, JobInfo, ServerStep, StepsResponse } from "../../contract/types";

export type * from "../../contract/types";

/** Base URL of the backend. Empty = same origin (built UI served by server.py, or the Vite dev proxy). */
const API = (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_API_BASE ?? "";

/** A non-2xx answer from the server. `body` is the parsed JSON error body when there is one. */
export class ApiError extends Error {
  constructor(readonly status: number, readonly body: Partial<ErrorBody>, fallback: string) {
    super(body.error ?? fallback);
  }
}

async function getJson<T>(path: string, what: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, body, `${what}: HTTP ${r.status}`);
  return body as T;
}

export const getState = () => getJson<DemoState>("/api/state", "state");
export const getSteps = () => getJson<StepsResponse>("/api/steps", "steps");
export const getJob = (id: string) => getJson<JobDetail>(`/api/jobs/${encodeURIComponent(id)}`, "job");

/** Starts a step. A 409 throws an ApiError whose `body.job` is the job that is already running. */
export async function runStep(step: ServerStep, tries?: number): Promise<JobInfo> {
  const r = await fetch(`${API}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step, ...(tries ? { tries } : {}) }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, body, `run: HTTP ${r.status}`);
  return body as JobInfo;
}

export type CancelResult =
  /** 202: the server is stopping the job; its "done" event follows (code -2, cancelled: true). */
  | { kind: "cancelling"; job: JobInfo }
  /** 409: the job had already ended; `job` is its final JobInfo. */
  | { kind: "not_running"; job?: JobInfo }
  /** 404 from a server that has the endpoint: it doesn't know the job (restarted). */
  | { kind: "unknown_job" }
  /** 404/405 from an older server without POST /api/jobs/{id}/cancel. */
  | { kind: "unsupported" };

/**
 * Asks the server to stop a job. Older servers have no cancel endpoint and answer 404 ("not found") or 405.
 * A server that has it always sends `cancelled` in its JobInfo, so `serverHasCancel` tells a 404 for an unknown
 * job apart from a missing endpoint.
 */
export async function cancelJob(id: string, serverHasCancel: boolean): Promise<CancelResult> {
  const r = await fetch(`${API}/api/jobs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const body = await r.json().catch(() => ({}));
  if (r.ok) return { kind: "cancelling", job: body as JobInfo };
  if (r.status === 409) return { kind: "not_running", job: body.job };
  if (r.status === 405) return { kind: "unsupported" };
  if (r.status === 404) return serverHasCancel || body.error === "unknown job" ? { kind: "unknown_job" } : { kind: "unsupported" };
  throw new ApiError(r.status, body, `cancel: HTTP ${r.status}`);
}

export type JobOutcome = "running" | "ok" | "cancelled" | "timed_out" | "failed";

/** How a job ended. Older servers send no `cancelled` / `timed_out`; then the exit codes -2 / -3 decide. */
export function jobOutcome(info: JobInfo): JobOutcome {
  if (info.running) return "running";
  if (info.cancelled ?? info.code === -2) return "cancelled";
  if (info.timed_out ?? info.code === -3) return "timed_out";
  return info.code === 0 ? "ok" : "failed";
}

export interface JobFollower {
  /** One new output line from the live stream. */
  onLine: (line: string) => void;
  /** The full output so far (from GET /api/jobs/{id}); replaces what was streamed. Used after the stream broke. */
  onOutput: (lines: string[]) => void;
  /** The job ended; `info` is its final JobInfo. */
  onDone: (info: JobInfo) => void;
  /** The server no longer knows the job (404: it was restarted). The caller should reload /api/state. */
  onLost: () => void;
}

/**
 * Follows a job's output until it ends. Returns a function that stops listening (the job keeps running).
 *
 * The SSE stream is the normal path; on a dropped connection EventSource reconnects by itself and sends
 * Last-Event-ID, so the server resumes after the last line received. When the browser gives up on the stream
 * (e.g. a 404 after a server restart), this falls back to polling GET /api/jobs/{id} until the job ends, and
 * reports a job the server no longer knows through `onLost`, so the UI never stays on "Running".
 */
export function followJob(id: string, h: JobFollower): () => void {
  let stopped = false;
  let polling = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const es = new EventSource(`${API}/api/jobs/${encodeURIComponent(id)}/stream`);

  const stop = () => {
    stopped = true;
    es.close();
    clearTimeout(timer);
  };
  const finish = (info: JobInfo) => {
    if (stopped) return;
    stop();
    h.onDone(info);
  };

  /** Asks the server directly. Returns true when it settled the job (ended or unknown). */
  const check = async (): Promise<boolean> => {
    try {
      const d = await getJob(id);
      if (stopped) return true;
      if (!d.running) {
        h.onOutput(d.output);
        finish(d);
        return true;
      }
      if (polling) h.onOutput(d.output);
      return false;
    } catch (e) {
      if (stopped) return true;
      if (e instanceof ApiError && e.status === 404) {
        stop();
        h.onLost();
        return true;
      }
      return false; // server unreachable: keep trying
    }
  };
  const poll = async () => {
    if (stopped || (await check())) return;
    timer = setTimeout(poll, 2000);
  };

  es.onmessage = (e) => { if (!stopped) h.onLine(JSON.parse(e.data)); };
  es.addEventListener("done", (e) => finish(JSON.parse((e as MessageEvent).data)));
  es.onerror = () => {
    if (stopped) return;
    if (es.readyState === EventSource.CLOSED) {
      // The browser will not reconnect (non-200 answer, e.g. unknown job): poll instead.
      if (!polling) {
        polling = true;
        poll();
      }
    } else {
      // EventSource is reconnecting by itself. Check once that the job still exists on this server.
      check();
    }
  };
  return stop;
}
