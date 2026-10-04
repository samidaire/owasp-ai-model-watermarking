import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { jobOutcome, type JobInfo } from "../api";

export interface ConsoleJob {
  info: JobInfo;
  lines: string[];
  title: string;
  /** The server no longer knows this job (e.g. it was restarted mid-run), so how it ended is unknown. */
  lost?: boolean;
}

function useElapsed(info: JobInfo | undefined) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    if (!info?.running) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 250);
    return () => clearInterval(t);
  }, [info?.running]);
  if (!info) return 0;
  return (info.ended ?? now) - info.started;
}

function statusOf(job: ConsoleJob | null, cancelling: boolean): ReactNode {
  if (!job) return <span className="st">Idle</span>;
  const { info, title } = job;
  if (job.lost) return <span className="st warn">? {title}: the server no longer knows this run (restarted?). Saved results reloaded.</span>;
  switch (jobOutcome(info)) {
    case "running":
      return <span className="st run"><span className="spinner" aria-hidden /> {cancelling ? `Cancelling ${title}…` : `Running ${title}`}</span>;
    case "ok":
      return <span className="st ok">✓ {title} finished</span>;
    case "cancelled":
      return <span className="st cancel">■ {title} cancelled. Results from before the run are kept.</span>;
    case "timed_out":
      return <span className="st warn">⏱ {title} timed out: stopped by the server's time limit. Results from before the run are kept.</span>;
    default:
      return <span className="st err">✕ {title} failed (exit {info.code})</span>;
  }
}

/**
 * Live output of the most recent demo run, pinned to the bottom of the page.
 * `onCancel` is set only while a job runs on a server that supports cancelling.
 */
export function Console({ job, open, onToggle, onCancel, cancelling }: {
  job: ConsoleJob | null; open: boolean; onToggle: () => void; onCancel?: () => void; cancelling: boolean;
}) {
  const root = useRef<HTMLElement>(null);
  const pre = useRef<HTMLPreElement>(null);
  const elapsed = useElapsed(job?.info);
  useEffect(() => {
    if (open && pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [job?.lines.length, open]);

  // The console is fixed over the bottom of the page. Publish its real height (open or closed, wrapped bar or
  // not) as --console-h, so the page reserves exactly that much space and no panel content is ever hidden.
  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    const set = () => document.documentElement.style.setProperty("--console-h", `${Math.ceil(el.getBoundingClientRect().height)}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => {
      ro.disconnect();
      document.documentElement.style.removeProperty("--console-h");
    };
  }, []);

  const info = job?.info;
  const last = job?.lines.filter((l) => l.trim()).at(-1) ?? "No demo run yet in this session. Saved results are shown.";

  return (
    <section className="console" aria-label="Demo console" ref={root}>
      {/* The whole bar toggles on click (a big target for a presenter); the buttons are the keyboard path. */}
      <div className="bar" onClick={(e) => { if (!(e.target as HTMLElement).closest("button")) onToggle(); }}>
        {statusOf(job, cancelling)}
        {info && <span className="dim">{elapsed.toFixed(1)} s</span>}
        <span className="last">{last}</span>
        {onCancel && (
          <button type="button" className="cbtn stop" onClick={onCancel} disabled={cancelling}>
            {cancelling ? "Cancelling…" : "■ Cancel run"}
          </button>
        )}
        <button type="button" className="cbtn" onClick={onToggle} aria-expanded={open} aria-controls="console-output">
          {open ? "▾ Hide console" : "▴ Console"}
        </button>
      </div>
      {open && <pre id="console-output" ref={pre}>{job ? job.lines.join("\n") : "Run a demo to see its live output here."}</pre>}
    </section>
  );
}
