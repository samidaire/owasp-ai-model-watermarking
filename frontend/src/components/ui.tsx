import type { ReactNode } from "react";

type Tone = "good" | "bad" | "warn" | "neutral";
const ICON: Record<Tone, string> = { good: "✓", bad: "✕", warn: "!", neutral: "•" };

/** Status chip: always icon + label, never colour alone. */
export function Verdict({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`chip ${tone === "neutral" ? "" : tone}`}>
      <span className="ic" aria-hidden>{ICON[tone]}</span>
      {children}
    </span>
  );
}

export function ReqChip({ children }: { children: ReactNode }) {
  return <span className="chip req">{children}</span>;
}

export function Stat({ label, value, unit, caption, hero }: {
  label: string; value: ReactNode; unit?: string; caption?: ReactNode; hero?: boolean;
}) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className={`value${hero ? " hero" : ""}`}>
        {value}
        {unit && <span className="unit">{unit}</span>}
      </span>
      {caption && <span className="caption">{caption}</span>}
    </div>
  );
}

export function Card({ title, sub, children, flag, className }: {
  title?: ReactNode; sub?: ReactNode; children: ReactNode; flag?: "good" | "bad"; className?: string;
}) {
  return (
    <section className={`card${flag ? ` flag-${flag}` : ""}${className ? ` ${className}` : ""}`}>
      {title && <h3>{title}</h3>}
      {sub && <p className="sub">{sub}</p>}
      {children}
    </section>
  );
}

export function Callout({ tone, children }: { tone: "good" | "bad" | "warn"; children: ReactNode }) {
  return (
    <div className={`callout ${tone}`} role="note">
      <span className="ic" aria-hidden>{ICON[tone]}</span>
      <div>{children}</div>
    </div>
  );
}

/** What to say at this point of the demo, plus the honest caveats. */
export function Notes({ say, caveats }: { say: ReactNode[]; caveats?: ReactNode[] }) {
  return (
    <details className="notes">
      <summary>Presenter notes</summary>
      <ul>{say.map((s, i) => <li key={i}>{s}</li>)}</ul>
      {caveats && caveats.length > 0 && (
        <div className="cav">
          <strong>Caveats to say out loud:</strong>
          <ul>{caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      )}
    </details>
  );
}

export function StaleBadge({ stale }: { stale: boolean }) {
  if (!stale) return null;
  return (
    <span className="stale" title="Made with an older owner key. Re-run this step.">
      <Verdict tone="warn">Stale: older owner key</Verdict>
    </span>
  );
}

/** Inline bar for table cells: value in [0, 1], optional threshold tick. Text stays in ink. */
export function Meter({ value, color, threshold, label }: {
  value: number; color: string; threshold?: number; label: string;
}) {
  const w = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="meter">
      <svg viewBox="0 0 100 10" preserveAspectRatio="none" role="img" aria-label={label}>
        <rect x="0" y="3" width="100" height="4" rx="2" fill="var(--grid)" />
        {w > 0 && <rect x="0" y="2" width={Math.max(w, 1.5)} height="6" rx="3" fill={color} />}
        {threshold !== undefined && (
          <line x1={threshold * 100} x2={threshold * 100} y1="0" y2="10" stroke="var(--text-secondary)" strokeWidth="1"
            vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      <span className="v">{label}</span>
    </div>
  );
}

export function Empty({ what }: { what: string }) {
  return (
    <Callout tone="warn">
      <p>No saved results for {what} yet. Press <strong>Run live</strong> above.</p>
    </Callout>
  );
}
