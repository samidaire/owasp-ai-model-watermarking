import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError, cancelJob, followJob, getJob, getState, runStep, type DemoState, type JobInfo, type ServerStep,
} from "./api";
import { Console, type ConsoleJob } from "./components/Console";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Callout } from "./components/ui";
import { short } from "./format";
import { PanelA } from "./panels/PanelA";
import { PanelB } from "./panels/PanelB";
import { PanelC } from "./panels/PanelC";
import { PanelD } from "./panels/PanelD";
import { PanelE } from "./panels/PanelE";
import type { PanelProps } from "./panels/Shell";
import { panelStatus, type PanelKey as Key, type PanelStatus } from "./stale";

const STEPS: { key: Key; title: string; sub: string; Panel: (p: PanelProps) => React.JSX.Element }[] = [
  { key: "A", title: "Commit & embed", sub: "Seed, key and watermark", Panel: PanelA },
  { key: "B", title: "Removal attacks", sub: "OWASP R1 · gap G2", Panel: PanelB },
  { key: "C", title: "Ownership forgery", sub: "OWASP R2 · gap G1", Panel: PanelC },
  { key: "D", title: "Committed seed", sub: "The fix, without ZK", Panel: PanelD },
  { key: "E", title: "Zero-knowledge proofs", sub: "EZKL on this machine", Panel: PanelE },
];
const PANEL_OF: Record<ServerStep, Key | "*"> = {
  evaluate: "A", retrain: "A", attacks: "B", forgery: "C", committed: "D", zk: "E", zk_hashed: "E", all: "*",
};
const TITLE_OF: Record<ServerStep, string> = {
  evaluate: "Demo A (re-verify)", retrain: "Demo A (retrain)", attacks: "Demo B", forgery: "Demo C",
  committed: "Demo D", zk: "Demo E1 + E2", zk_hashed: "Demo E3", all: "All demos",
};
const SERVER_CMD = "Double-click Start-Demo-UI.cmd in the project folder, or run: python demo/server.py";

function readPref(key: string, fallback: string) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writePref(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* private window: preference just isn't kept */ }
}

/** Sidebar marker per panel status (stale.ts decides the status for the sidebar and the panels alike). */
const MARK: Record<PanelStatus, { say: string; title: string; icon: string; color: string }> = {
  fresh: { say: "up to date", title: "Results up to date", icon: "✓", color: "var(--good-text)" },
  stale: { say: "stale", title: "Stale: made with an older owner key", icon: "!", color: "var(--warning-text)" },
  unknown: { say: "freshness unknown", title: "Results shown; freshness unknown (no current owner commitment to compare)", icon: "–", color: "var(--text-secondary)" },
  missing: { say: "no results", title: "No results yet", icon: "○", color: "var(--text-muted)" },
};

export default function App() {
  const [s, setS] = useState<DemoState | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [idx, setIdx] = useState(() => Math.max(0, STEPS.findIndex((x) => x.key === readPref("demo.step", "A"))));
  const [job, setJob] = useState<ConsoleJob | null>(null);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [theme, setTheme] = useState(() => readPref("demo.theme", "auto"));
  /** Id of the job a cancel was requested for (until it ends). */
  const [cancelling, setCancelling] = useState<string | null>(null);
  /** The server has no cancel endpoint (older server): hide the Cancel button. */
  const [cancelUnsupported, setCancelUnsupported] = useState(false);
  /** The job whose output the console follows, and how to stop following it. */
  const follow = useRef<{ id: string; stop: () => void } | null>(null);
  const jobRef = useRef<ConsoleJob | null>(null);
  jobRef.current = job;

  const refresh = useCallback(async () => {
    try {
      const st = await getState();
      setS(st);
      setOffline(null);
      return st;
    } catch (e) {
      setOffline((e as Error).message);
      return null;
    }
  }, []);

  const unfollow = useCallback((id?: string) => {
    if (follow.current && (id === undefined || follow.current.id === id)) {
      follow.current.stop();
      follow.current = null;
    }
  }, []);

  /**
   * The server says job `id` is no longer running (or no longer exists): end it in the console, with its final
   * JobInfo when the server still has it, otherwise as "lost" (e.g. the server was restarted mid-run).
   */
  const settle = useCallback(async (id: string, fromState: JobInfo | null) => {
    let final: JobInfo | null = fromState?.id === id && !fromState.running ? fromState : null;
    if (!final) {
      try {
        const d = await getJob(id);
        if (!d.running) final = d;
      } catch { /* unknown job or unreachable server: ends as "lost" */ }
    }
    unfollow(id);
    setJob((j) => {
      if (!j || j.info.id !== id || !j.info.running) return j;
      if (final) return { ...j, info: final };
      return { ...j, lost: true, info: { ...j.info, running: false, ended: j.info.ended ?? Date.now() / 1000 } };
    });
  }, [unfollow]);

  const attach = useCallback((info: JobInfo) => {
    unfollow();
    const id = info.id;
    const update = (f: (j: ConsoleJob) => ConsoleJob) => setJob((j) => (j && j.info.id === id ? f(j) : j));
    setJob({ info, lines: [], title: TITLE_OF[info.step] ?? info.step });
    const stop = followJob(id, {
      onLine: (line) => update((j) => ({ ...j, lines: [...j.lines, line] })),
      onOutput: (lines) => update((j) => ({ ...j, lines })),
      onDone: (done) => {
        if (follow.current?.id === id) follow.current = null;
        update((j) => ({ ...j, info: done }));
        setNotice(null);
        refresh();
      },
      onLost: async () => {
        // The server no longer knows this job (restarted): trust /api/state from now on. If another job runs
        // there, the safety-net poll below attaches to it.
        if (follow.current?.id === id) follow.current = null;
        const st = await refresh();
        settle(id, st?.job ?? null);
      },
    });
    follow.current = { id, stop };
  }, [refresh, settle, unfollow]);

  // Initial load: saved results populate every panel before anything runs; re-attach to a running job.
  useEffect(() => {
    refresh().then((st) => { if (st?.job?.running) attach(st.job); });
    return () => unfollow();
  }, [refresh, attach, unfollow]);

  // The server probes the GPU in the background; poll until it reports.
  useEffect(() => {
    if (s?.env.status !== "probing" && !offline) return;
    const t = setTimeout(refresh, 2000);
    return () => clearTimeout(t);
  }, [s, offline, refresh]);

  // Safety net while anything runs (the stream can drop behind a proxy, or the server can restart):
  // poll /api/state every 5 s. Whenever no job is running there, nothing is running here either.
  const runningId = job?.info.running ? job.info.id : s?.job?.running ? s.job.id : null;
  useEffect(() => {
    if (!runningId) return;
    const t = setInterval(async () => {
      const st = await refresh();
      if (!st) return; // server unreachable: the offline banner shows; keep polling
      const sj = st.job;
      const cur = jobRef.current;
      if (cur?.info.running && (!sj || !sj.running || sj.id !== cur.info.id)) settle(cur.info.id, sj);
      // A run this tab isn't following (started elsewhere, or after a missed "done"): follow it.
      if (sj?.running && sj.id !== cur?.info.id) attach(sj);
    }, 5000);
    return () => clearInterval(t);
  }, [runningId, refresh, settle, attach]);

  useEffect(() => {
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    writePref("demo.theme", theme);
  }, [theme]);

  const go = useCallback((i: number) => {
    const n = Math.max(0, Math.min(STEPS.length - 1, i));
    setIdx(n);
    writePref("demo.step", STEPS[n].key);
    window.scrollTo({ top: 0 });
  }, []);

  // Arrow keys / PageUp / PageDown (presentation clickers) move between demos.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, select, textarea, [contenteditable='true']") || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); go(idx + 1); }
      if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(idx - 1); }
      if (e.key === "Home") go(0);
      if (e.key === "End") go(STEPS.length - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, go]);

  const run = useCallback(async (step: ServerStep, opts?: { tries?: number; confirm?: string }) => {
    if (opts?.confirm && !window.confirm(opts.confirm)) return;
    setNotice(null);
    try {
      const info = await runStep(step, opts?.tries);
      attach(info);
      setConsoleOpen(true);
    } catch (e) {
      const busy = e instanceof ApiError && e.status === 409 ? e.body.job : undefined;
      if (busy) {
        // Only one job runs at a time: show the one that is running instead of just an error.
        if (jobRef.current?.info.id !== busy.id || !follow.current) attach(busy);
        setConsoleOpen(true);
        setNotice(`Another demo is already running (${TITLE_OF[busy.step] ?? busy.step}). Its live output is in the console; Run buttons unlock when it ends.`);
      } else {
        setNotice((e as Error).message);
      }
      refresh();
    }
  }, [attach, refresh]);

  const cancel = useCallback(async () => {
    const cur = jobRef.current;
    if (!cur?.info.running) return;
    const id = cur.info.id;
    setCancelling(id);
    try {
      const r = await cancelJob(id, "cancelled" in cur.info);
      if (r.kind === "cancelling") {
        // The "done" event (code -2, cancelled) ends it; if the server already stopped it, end it now.
        if (!r.job.running) settle(id, r.job);
        return;
      }
      setCancelling(null);
      if (r.kind === "unsupported") {
        setCancelUnsupported(true);
        setNotice("This server version can't cancel a run. It ends by itself; the other Run buttons unlock then.");
      } else {
        // Already ended (409) or unknown to the server (404): settle it from what the server says.
        settle(id, r.kind === "not_running" ? r.job ?? null : null);
        refresh();
      }
    } catch (e) {
      setCancelling(null);
      setNotice(`Cancel failed: ${(e as Error).message}`);
    }
  }, [settle, refresh]);

  const running: ServerStep | null = job?.info.running ? job.info.step : s?.job?.running ? s.job.step : null;
  const step = STEPS[idx];
  const env = s?.env;
  let envLabel = "Connecting…";
  if (env?.status === "probing") envLabel = "Probing GPU…";
  else if (env?.status === "error") envLabel = "Environment probe failed";
  else if (env?.status === "ok") envLabel = env.gpu
    ? `${env.gpu.replace("NVIDIA GeForce ", "")} · ${env.sm} · torch ${env.torch}`
    : `CPU only · torch ${env.torch}`;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Committed-seed ZK ownership verification</h1>
          <span>OWASP AI Model Watermarking · final-year project demo</span>
        </div>
        <div className="group">
          <span className={`chip${env?.status === "ok" && env.gpu ? " good" : env?.status === "error" ? " warn" : ""}`} title={env?.error}>
            {env?.status === "ok" && <span className="ic" aria-hidden>{env.gpu ? "✓" : "!"}</span>}{envLabel}
          </span>
          <span className="chip" title={s?.commitment ?? ""}>Owner commitment <span className="mono">{short(s?.commitment)}</span></span>
          <button className="btn primary" disabled={running !== null || !s} onClick={() => run("all")} aria-label="Run all demos live"
            title="Re-verify A, then run B, C, D and E1 + E2 live (~30 s). E3 stays precomputed.">
            {running === "all" ? <span className="spinner" aria-hidden /> : <span aria-hidden>▶</span>}
            {running === "all" ? "Running all…" : "Run all live"}
          </button>
          <select className="sel" value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Colour theme">
            <option value="auto">Theme: auto</option>
            <option value="light">Theme: light</option>
            <option value="dark">Theme: dark</option>
          </select>
        </div>
      </header>

      {offline && (
        <div className="banner">
          <Callout tone="bad">
            <p><strong>Can't reach the demo server</strong> ({offline}). Start it, then reload:</p>
            <p className="mono" style={{ marginTop: 6, wordBreak: "break-all" }}>{SERVER_CMD}</p>
          </Callout>
        </div>
      )}
      {s?.mode === "simulate" && (
        <div className="banner">
          <Callout tone="warn">
            <p><strong>Simulate mode.</strong> Run buttons replay recorded logs; nothing is executed and the results shown are the saved ones.
              For real runs, restart the server without <span className="mono">--simulate</span>.</p>
          </Callout>
        </div>
      )}
      {notice && <div className="banner"><Callout tone="warn"><p>{notice}</p></Callout></div>}

      <div className="layout">
        <nav className="sidenav" aria-label="Demo steps">
          <div className="navlabel">Demo storyline</div>
          {STEPS.map((x, i) => {
            const mark = MARK[panelStatus(x.key, s)];
            const busy = running && (PANEL_OF[running] === x.key || PANEL_OF[running] === "*");
            return (
              <button key={x.key} className="navitem" aria-current={i === idx ? "step" : undefined} onClick={() => go(i)}
                aria-label={`Demo ${x.key}: ${x.title} (${busy ? "running" : mark.say})`}>
                <span className="letter">{x.key}</span>
                <span className="t">{x.title}<span className="s">{x.sub}</span></span>
                <span aria-hidden title={busy ? "Running" : mark.title}>
                  {busy ? <span className="spinner" style={{ color: "var(--series-1)" }} />
                    : <span style={{ color: mark.color, fontWeight: 800 }}>{mark.icon}</span>}
                </span>
              </button>
            );
          })}
          <div className="navhint">← → or PageUp / PageDown to move between demos.</div>
        </nav>
        <main>
          {s ? (
            // One boundary per panel (keyed, so moving to another panel starts clean): a render error in one
            // panel shows an error card there, and the other panels, the sidebar and the console keep working.
            <ErrorBoundary key={step.key} name={`Demo ${step.key} (${step.title})`} onReload={refresh} resetKey={s}>
              <step.Panel s={s} ctl={{ running, run }}
                refreshing={Boolean(running && (PANEL_OF[running] === step.key || PANEL_OF[running] === "*"))} />
            </ErrorBoundary>
          ) : !offline && <p style={{ color: "var(--text-secondary)" }}>Loading saved results…</p>}
        </main>
      </div>

      <ErrorBoundary name="The console" onReload={() => setConsoleOpen(true)}>
        <Console job={job} open={consoleOpen} onToggle={() => setConsoleOpen((o) => !o)}
          onCancel={job?.info.running && !job.lost && !cancelUnsupported ? cancel : undefined}
          cancelling={Boolean(job?.info.running && cancelling === job.info.id)} />
      </ErrorBoundary>
    </div>
  );
}
