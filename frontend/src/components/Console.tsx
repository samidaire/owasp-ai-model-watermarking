import { useEffect, useRef, useState } from "react";
import type { JobInfo } from "../api";

export interface ConsoleJob { info: JobInfo; lines: string[]; title: string }

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

/** Live output of the most recent demo run, pinned to the bottom of the page. */
export function Console({ job, open, onToggle }: { job: ConsoleJob | null; open: boolean; onToggle: () => void }) {
  const pre = useRef<HTMLPreElement>(null);
  const elapsed = useElapsed(job?.info);
  useEffect(() => {
    if (open && pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [job?.lines.length, open]);

  const info = job?.info;
  const last = job?.lines.filter((l) => l.trim()).at(-1) ?? "No demo run yet in this session. Saved results are shown.";
  let status = <span className="st">Idle</span>;
  if (info?.running) status = <span className="st run"><span className="spinner" /> Running {job!.title}</span>;
  else if (info && info.code === 0) status = <span className="st ok">✓ {job!.title} finished</span>;
  else if (info) status = <span className="st err">✕ {job!.title} failed (exit {info.code})</span>;

  return (
    <section className="console" aria-label="Demo console">
      <div className="bar" onClick={onToggle} role="button" tabIndex={0} aria-expanded={open}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}>
        {status}
        {info && <span style={{ color: "#898781" }}>{elapsed.toFixed(1)} s</span>}
        <span className="last">{last}</span>
        <span style={{ color: "#898781" }}>{open ? "▾ hide" : "▴ console"}</span>
      </div>
      {open && <pre ref={pre}>{job ? job.lines.join("\n") : "Run a demo to see its live output here."}</pre>}
    </section>
  );
}
