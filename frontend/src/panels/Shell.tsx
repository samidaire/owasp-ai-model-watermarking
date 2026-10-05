import type { ReactNode } from "react";
import type { DemoState, ModelInfo, ServerStep } from "../api";
import { ReqChip, StaleBadge } from "../components/ui";
import { about, RUNNING_NAME, type StepCatalogue } from "../steps";

export interface RunCtl {
  /** Server step currently running, if any (one job at a time). */
  running: ServerStep | null;
  /** Labels, durations and confirmation texts from GET /api/steps (fallback catalogue if that failed). */
  steps: StepCatalogue;
  /** Starts a step; asks for confirmation first when the step's catalogue entry has a `confirm` text. */
  run: (step: ServerStep, opts?: { tries?: number; model?: string }) => void;
  /** "Model under test": the menu's choices (GET /api/models), the selected id and its setter. */
  models: ModelInfo[];
  model: string;
  setModel: (id: string) => void;
  /** The model a running model_test job is testing, if any. */
  runningModel: string | null;
}

export interface PanelProps { s: DemoState; ctl: RunCtl; refreshing: boolean }

/** Run button: label, duration hint and confirmation all come from the step catalogue. */
export function RunButton({ ctl, step, primary, tries, hint, disabled }: {
  ctl: RunCtl; step: ServerStep; primary?: boolean; tries?: number; disabled?: boolean;
  /** Tooltip text; defaults to the step's description. The duration is appended. */
  hint?: string;
}) {
  const info = ctl.steps[step];
  const busy = ctl.running !== null;
  const mine = ctl.running === step;
  const label = info.confirm ? `${info.label}…` : info.label;   // "…" = a confirmation follows
  // The visible text is the accessible name, so it says what is running ("Running forgery…"), not just "Running…".
  return (
    <button className={`btn${primary ? " primary" : ""}`} disabled={busy || disabled}
      title={`${hint ?? info.description} (${about(info.seconds)})`}
      onClick={() => ctl.run(step, { tries })}>
      {mine ? <span className="spinner" aria-hidden /> : <span aria-hidden>▶</span>}
      {mine ? `Running ${RUNNING_NAME[step]}…` : label}
    </button>
  );
}

export function PanelShell({ letter, title, reqs, claim, actions, stale, refreshing, notes, children }: {
  letter: string; title: string; reqs: string[]; claim: ReactNode; actions: ReactNode; stale: boolean;
  refreshing: boolean; notes: ReactNode; children: ReactNode;
}) {
  return (
    <article className={`panel${refreshing ? " refreshing" : ""}`} aria-labelledby={`h-${letter}`} aria-busy={refreshing}>
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
