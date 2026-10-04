import { useCallback, useEffect, useRef, useState } from "react";
import { getState, isStale, runStep, streamJob, type DemoState, type JobInfo, type ServerStep } from "./api";
import { Console, type ConsoleJob } from "./components/Console";
import { Callout } from "./components/ui";
import { short } from "./format";
import { PanelA } from "./panels/PanelA";
import { PanelB } from "./panels/PanelB";
import { PanelC } from "./panels/PanelC";
import { PanelD } from "./panels/PanelD";
import { PanelE } from "./panels/PanelE";
import type { PanelProps } from "./panels/Shell";

type Key = "A" | "B" | "C" | "D" | "E";
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

function stepStatus(k: Key, s: DemoState | null): "ok" | "stale" | "missing" {
  if (!s) return "missing";
  const r = s.results;
  const c = { A: r.train?.commitment, B: r.attacks?.commitment, C: r.forgery?.commitment,
    D: r.committed_seed?.commitment, E: r.ezkl.private_owner?.commitment }[k];
  const present = { A: r.train, B: r.attacks, C: r.forgery, D: r.committed_seed, E: r.ezkl.private_owner }[k];
  if (!present) return "missing";
  return isStale(c, s.commitment) ? "stale" : "ok";
}

export default function App() {
  const [s, setS] = useState<DemoState | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [idx, setIdx] = useState(() => Math.max(0, STEPS.findIndex((x) => x.key === readPref("demo.step", "A"))));
  const [job, setJob] = useState<ConsoleJob | null>(null);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [theme, setTheme] = useState(() => readPref("demo.theme", "auto"));
  const stop = useRef<(() => void) | null>(null);

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

  const attach = useCallback((info: JobInfo) => {
    stop.current?.();
    setJob({ info, lines: [], title: TITLE_OF[info.step] });
    stop.current = streamJob(
      info.id,
      (line) => setJob((j) => (j && j.info.id === info.id ? { ...j, lines: [...j.lines, line] } : j)),
      (done) => {
        setJob((j) => (j && j.info.id === info.id ? { ...j, info: done } : j));
        refresh();
      },
    );
  }, [refresh]);

  // Initial load: saved results populate every panel before anything runs; re-attach to a running job.
  useEffect(() => {
    refresh().then((st) => { if (st?.job?.running) attach(st.job); });
    return () => stop.current?.();
  }, [refresh, attach]);

  // The server probes the GPU in the background; poll until it reports.
  useEffect(() => {
    if (s?.env.status !== "probing" && !offline) return;
    const t = setTimeout(refresh, 2000);
    return () => clearTimeout(t);
  }, [s, offline, refresh]);

  // Safety net if the event stream drops: keep job state fresh while running.
  useEffect(() => {
    if (!job?.info.running) return;
    const t = setInterval(async () => {
      const st = await refresh();
      if (st?.job && st.job.id === job.info.id && !st.job.running) {
        setJob((j) => (j && j.info.id === st.job!.id ? { ...j, info: st.job! } : j));
      }
    }, 5000);
    return () => clearInterval(t);
  }, [job?.info.running, job?.info.id, refresh]);

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
      setNotice((e as Error).message);
      refresh();
    }
  }, [attach, refresh]);

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
            const st = stepStatus(x.key, s);
            const busy = running && (PANEL_OF[running] === x.key || PANEL_OF[running] === "*");
            return (
              <button key={x.key} className="navitem" aria-current={i === idx ? "step" : undefined} onClick={() => go(i)}
                aria-label={`Demo ${x.key}: ${x.title} (${busy ? "running" : { ok: "up to date", stale: "stale", missing: "no results" }[st]})`}>
                <span className="letter">{x.key}</span>
                <span className="t">{x.title}<span className="s">{x.sub}</span></span>
                <span aria-label={busy ? "running" : st} title={busy ? "Running" : { ok: "Results up to date", stale: "Stale: older owner key", missing: "No results yet" }[st]}>
                  {busy ? <span className="spinner" style={{ color: "var(--series-1)" }} />
                    : st === "ok" ? <span style={{ color: "var(--good-text)", fontWeight: 800 }}>✓</span>
                      : st === "stale" ? <span style={{ color: "var(--warning-text)", fontWeight: 800 }}>!</span>
                        : <span style={{ color: "var(--text-muted)" }}>○</span>}
                </span>
              </button>
            );
          })}
          <div className="navhint">← → or PageUp / PageDown to move between demos.</div>
        </nav>
        <main>
          {s ? <step.Panel s={s} ctl={{ running, run }}
            refreshing={Boolean(running && (PANEL_OF[running] === step.key || PANEL_OF[running] === "*"))} />
            : !offline && <p style={{ color: "var(--text-secondary)" }}>Loading saved results…</p>}
        </main>
      </div>

      <Console job={job} open={consoleOpen} onToggle={() => setConsoleOpen((o) => !o)} />
    </div>
  );
}
