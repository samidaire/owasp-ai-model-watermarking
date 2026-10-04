import type { ReactNode } from "react";
import type { DemoState, ServerStep } from "../api";
import { ReqChip, StaleBadge } from "../components/ui";

export interface RunCtl {
  /** Server step currently running, if any (one job at a time). */
  running: ServerStep | null;
  run: (step: ServerStep, opts?: { tries?: number; confirm?: string }) => void;
}

export interface PanelProps { s: DemoState; ctl: RunCtl; refreshing: boolean }

export function RunButton({ ctl, step, label, primary, confirm, tries, hint }: {
  ctl: RunCtl; step: ServerStep; label: string; primary?: boolean; confirm?: string; tries?: number; hint?: string;
}) {
  const busy = ctl.running !== null;
  const mine = ctl.running === step;
  return (
    <button className={`btn${primary ? " primary" : ""}`} disabled={busy} title={hint} aria-label={label}
      onClick={() => ctl.run(step, { confirm, tries })}>
      {mine ? <span className="spinner" aria-hidden /> : <span aria-hidden>▶</span>}
      {mine ? "Running…" : label}
    </button>
  );
}

export function PanelShell({ letter, title, reqs, claim, actions, stale, refreshing, notes, children }: {
  letter: string; title: string; reqs: string[]; claim: ReactNode; actions: ReactNode; stale: boolean;
  refreshing: boolean; notes: ReactNode; children: ReactNode;
}) {
  return (
    <article className={`panel${refreshing ? " refreshing" : ""}`} aria-labelledby={`h-${letter}`}>
      <header className="panelhead">
        <div className="titles">
          <div className="kicker">Demo {letter}</div>
          <h2 id={`h-${letter}`}>{title}</h2>
          <div className="actions" style={{ margin: "6px 0 10px" }}>
            {reqs.map((r) => <ReqChip key={r}>{r}</ReqChip>)}
            <StaleBadge stale={stale} />
          </div>
          <p>{claim}</p>
        </div>
        <div className="actions">{actions}</div>
      </header>
      <div className="results">{children}</div>
      {notes}
    </article>
  );
}
