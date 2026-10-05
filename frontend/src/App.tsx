import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError, cancelJob, followJob, getJob, getState, getSteps, runStep, type DemoState, type JobInfo, type ServerStep,
} from "./api";
import { Console, type ConsoleJob } from "./components/Console";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Callout } from "./components/ui";
import { Demos, DEMOS } from "./pages/Demos";
import { Embed } from "./pages/Embed";
import { Landing } from "./pages/Landing";
import { Overview } from "./pages/Overview";
import { Robustness } from "./pages/Robustness";
import { Verify } from "./pages/Verify";
import { ALL_RESULTS, REVEALS, applyView, loadClearedAt, loadShown, saveClearedAt, saveShown, type ResultKey } from "./reveal";
import { navigate, usePath } from "./router";
import { Side } from "./shell/Side";
import { FALLBACK_STEPS, toCatalogue, type StepCatalogue } from "./steps";
import type { RunCtl } from "./panels/Shell";

export const TITLE_OF: Record<ServerStep, string> = {
  evaluate: "Demo A (re-verify)", retrain: "Demo A (retrain)", attacks: "Demo B (removal attacks)", forgery: "Demo C (forgery)",
  committed: "Demo D (committed seed)", zk: "Demo E1 + E2", zk_hashed: "Demo E3", protocol_v2: "Demo F (protocol v2)", all: "All demos",
  verify_honest: "Live verification", verify_replay: "Misuse: replayed proof", verify_model: "Misuse: different model",
  verify_tamper: "Misuse: tampered proof", verify_registry: "Misuse: untrusted registry",
};
const SERVER_CMD = "Double-click Start-Demo-UI.cmd in the project folder, or run: python demo/server.py";

export function readPref(key: string, fallback: string) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writePref(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* private window: preference just isn't kept */ }
}

/** What every app page receives. */
export interface PageProps { s: DemoState; ctl: RunCtl }

export default function App() {
  const path = usePath();
  const [s, setS] = useState<DemoState | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [job, setJob] = useState<ConsoleJob | null>(null);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [motion, setMotion] = useState(() => readPref("demo.motion", "on") !== "off");
  /** Step catalogue from GET /api/steps; the fallback (src/steps.ts) until it loads, or if it fails. */
  const [steps, setSteps] = useState<StepCatalogue>(FALLBACK_STEPS);
  const [stepsLoaded, setStepsLoaded] = useState(false);
  /** Id of the job a cancel was requested for (until it ends). */
  const [cancelling, setCancelling] = useState<string | null>(null);
  /** The server has no cancel endpoint (older server): hide the Cancel button. */
  const [cancelUnsupported, setCancelUnsupported] = useState(false);
  /** Results on screen: none until a run finishes (or "Show saved results"); Clear empties them again. */
  const [shown, setShown] = useState<Set<ResultKey>>(loadShown);
  const reveal = useCallback((done: JobInfo | null) => {
    const keys = done && done.code === 0 ? REVEALS[done.step] : undefined;
    if (keys) setShown((cur) => (keys.every((k) => cur.has(k)) ? cur : new Set([...cur, ...keys])));
  }, []);
  const [clearedAt, setClearedAt] = useState(loadClearedAt);
  useEffect(() => saveShown(shown), [shown]);
  useEffect(() => saveClearedAt(clearedAt), [clearedAt]);
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

  /** The server says job `id` is no longer running (or no longer exists): end it in the console. */
  const settle = useCallback(async (id: string, fromState: JobInfo | null) => {
    let final: JobInfo | null = fromState?.id === id && !fromState.running ? fromState : null;
    if (!final) {
      try {
        const d = await getJob(id);
        if (!d.running) final = d;
      } catch { /* unknown job or unreachable server: ends as "lost" */ }
    }
    unfollow(id);
    reveal(final);
    setJob((j) => {
      if (!j || j.info.id !== id || !j.info.running) return j;
      if (final) return { ...j, info: final };
      return { ...j, lost: true, info: { ...j.info, running: false, ended: j.info.ended ?? Date.now() / 1000 } };
    });
  }, [unfollow, reveal]);

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
        reveal(done);
        refresh();
      },
      onLost: async () => {
        if (follow.current?.id === id) follow.current = null;
        const st = await refresh();
        settle(id, st?.job ?? null);
      },
    });
    follow.current = { id, stop };
  }, [refresh, settle, unfollow, reveal]);

  // Initial load: saved results populate every page before anything runs; re-attach to a running job.
  useEffect(() => {
    refresh().then((st) => { if (st?.job?.running) attach(st.job); });
    return () => unfollow();
  }, [refresh, attach, unfollow]);

  useEffect(() => {
    if (stepsLoaded || offline) return;
    let live = true;
    getSteps()
      .then((r) => { if (live) { setSteps(toCatalogue(r)); setStepsLoaded(true); } })
      .catch(() => { /* keep the fallback catalogue */ });
    return () => { live = false; };
  }, [stepsLoaded, offline]);

  // The server probes the GPU in the background; poll until it reports.
  useEffect(() => {
    if (s?.env.status !== "probing" && !offline) return;
    const t = setTimeout(refresh, 2000);
    return () => clearTimeout(t);
  }, [s, offline, refresh]);

  // Safety net while anything runs: poll /api/state every 5 s.
  const runningId = job?.info.running ? job.info.id : s?.job?.running ? s.job.id : null;
  useEffect(() => {
    if (!runningId) return;
    const t = setInterval(async () => {
      const st = await refresh();
      if (!st) return;
      const sj = st.job;
      const cur = jobRef.current;
      if (cur?.info.running && (!sj || !sj.running || sj.id !== cur.info.id)) settle(cur.info.id, sj);
      if (sj?.running && sj.id !== cur?.info.id) attach(sj);
    }, 5000);
    return () => clearInterval(t);
  }, [runningId, refresh, settle, attach]);

  useEffect(() => {
    document.documentElement.classList.toggle("still", !motion);
    writePref("demo.motion", motion ? "on" : "off");
  }, [motion]);

  const run = useCallback(async (step: ServerStep, opts?: { tries?: number }) => {
    const confirmText = steps[step]?.confirm;
    if (confirmText && !window.confirm(confirmText)) return;
    setNotice(null);
    try {
      const info = await runStep(step, opts?.tries);
      attach(info);
      setConsoleOpen(true);
    } catch (e) {
      const busy = e instanceof ApiError && e.status === 409 ? e.body.job : undefined;
      if (busy) {
        if (jobRef.current?.info.id !== busy.id || !follow.current) attach(busy);
        setConsoleOpen(true);
        setNotice(`Another demo is already running (${TITLE_OF[busy.step] ?? busy.step}). Its live output is in the console; Run buttons unlock when it ends.`);
      } else {
        setNotice((e as Error).message);
      }
      refresh();
    }
  }, [attach, refresh, steps]);

  const cancel = useCallback(async () => {
    const cur = jobRef.current;
    if (!cur?.info.running) return;
    const id = cur.info.id;
    setCancelling(id);
    try {
      const r = await cancelJob(id, "cancelled" in cur.info);
      if (r.kind === "cancelling") {
        if (!r.job.running) settle(id, r.job);
        return;
      }
      setCancelling(null);
      if (r.kind === "unsupported") {
        setCancelUnsupported(true);
        setNotice("This server version can't cancel a run. It ends by itself; the other Run buttons unlock then.");
      } else {
        settle(id, r.kind === "not_running" ? r.job ?? null : null);
        refresh();
      }
    } catch (e) {
      setCancelling(null);
      setNotice(`Cancel failed: ${(e as Error).message}`);
    }
  }, [settle, refresh]);

  const running: ServerStep | null = job?.info.running ? job.info.step : s?.job?.running ? s.job.step : null;
  const ctl = useMemo<RunCtl>(() => ({ running, run, steps }), [running, run, steps]);
  const view = useMemo(() => (s ? applyView(s, shown, clearedAt) : null), [s, shown, clearedAt]);

  /** Clear: every page back to "nothing has run yet", the console emptied, ready for a new test. */
  const clear = useCallback(() => {
    setShown(new Set());
    setClearedAt(Date.now() / 1000);
    setNotice(null);
    setJob((j) => (j?.info.running ? j : null));
    setConsoleOpen(false);
  }, []);
  const showSaved = useCallback(() => setShown(new Set(ALL_RESULTS)), []);

  // ------------------------------------------------------------------ routes
  const isLanding = path === "/" || path === "/index.html";
  const demoKey = /^\/app\/demo\/([A-F])\/?$/.exec(path)?.[1] ?? null;

  // ← → (and a presentation clicker's PageUp / PageDown) move between research demos A–F.
  useEffect(() => {
    if (!demoKey) return;
    const keys: string[] = DEMOS.map((d) => d.key);
    const i = keys.indexOf(demoKey);
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      if ((t instanceof Element && t.closest("input, select, textarea, [contenteditable='true']")) || e.altKey || e.ctrlKey || e.metaKey) return;
      const to = (k: number) => navigate(`/app/demo/${keys[Math.max(0, Math.min(keys.length - 1, k))]}`);
      if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); to(i + 1); }
      if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); to(i - 1); }
      if (e.key === "Home") to(0);
      if (e.key === "End") to(keys.length - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [demoKey]);

  useEffect(() => {
    const name = isLanding ? null : demoKey ? `Demo ${demoKey}` : path.startsWith("/app/embed") ? "Embed watermark"
      : path.startsWith("/app/verify") ? "Verify ownership" : path.startsWith("/app/robustness") ? "Robustness lab" : "Overview";
    document.title = name ? `${name} · Sigil` : "Sigil · Watermark ownership";
  }, [path, isLanding, demoKey]);

  if (isLanding) return <Landing />;

  let page: React.ReactNode;
  let pageName = "This page";
  if (!view) page = !offline && <p className="muted">Loading…</p>;
  else if (path === "/app" || path === "/app/") { page = <Overview s={view} ctl={ctl} job={job} />; pageName = "Overview"; }
  else if (path.startsWith("/app/embed")) { page = <Embed s={view} ctl={ctl} />; pageName = "Embed watermark"; }
  else if (path.startsWith("/app/verify")) { page = <Verify s={view} ctl={ctl} />; pageName = "Verify ownership"; }
  else if (path.startsWith("/app/robustness")) { page = <Robustness s={view} ctl={ctl} />; pageName = "Robustness lab"; }
  else if (demoKey) { page = <Demos s={view} ctl={ctl} k={demoKey} />; pageName = `Demo ${demoKey}`; }
  else page = <Callout tone="warn"><p>No page here. <a href="/app">Go to the overview</a>.</p></Callout>;

  return (
    <div className="appwrap">
      <Side path={path} s={view} ctl={ctl} motion={motion} onMotion={() => setMotion((m) => !m)}
        shownCount={shown.size} onClear={clear} onShowSaved={showSaved} />
      <main className="page">
        {offline && (
          <Callout tone="bad">
            <p><strong>Can't reach the demo server</strong> ({offline}). Start it, then reload:</p>
            <p className="mono" style={{ marginTop: 6, wordBreak: "break-all" }}>{SERVER_CMD}</p>
          </Callout>
        )}
        {s?.mode === "simulate" && (
          <Callout tone="warn">
            <p><strong>Simulate mode.</strong> Run buttons replay recorded logs: nothing is executed, and each page then shows that demo's
              saved results. For real runs, start the server without <span className="mono">--simulate</span> (<span className="mono">Start-Demo-UI.cmd</span>).</p>
          </Callout>
        )}
        <div aria-live="polite">{notice && <Callout tone="warn"><p>{notice}</p></Callout>}</div>
        <ErrorBoundary key={path} name={pageName} onReload={refresh} resetKey={s}>{page}</ErrorBoundary>
      </main>
      <ErrorBoundary name="The console" onReload={() => setConsoleOpen(true)}>
        <Console job={job} open={consoleOpen} onToggle={() => setConsoleOpen((o) => !o)}
          timeout={job ? steps[job.info.step]?.timeout : undefined}
          onCancel={job?.info.running && !job.lost && !cancelUnsupported ? cancel : undefined}
          cancelling={Boolean(job?.info.running && cancelling === job.info.id)} />
      </ErrorBoundary>
    </div>
  );
}
