import type { DemoState } from "../api";
import { Icon, Logo } from "../components/icons";
import { DEMOS, demoBusy } from "../pages/Demos";
import { RunButton, type RunCtl } from "../panels/Shell";
import { Link } from "../router";
import { panelStatus, type PanelStatus } from "../stale";

const PAGES = [
  { to: "/app", label: "Overview", icon: "overview" },
  { to: "/app/embed", label: "Embed watermark", icon: "embed" },
  { to: "/app/verify", label: "Verify ownership", icon: "verify" },
  { to: "/app/robustness", label: "Robustness lab", icon: "bolt" },
];

const MARK: Record<PanelStatus, { icon: string; say: string }> = {
  fresh: { icon: "✓", say: "up to date" },
  stale: { icon: "!", say: "stale: made with an older owner key" },
  unknown: { icon: "–", say: "freshness unknown" },
  missing: { icon: "○", say: "no results yet" },
};

export function Side({ path, s, ctl, motion, onMotion }: {
  path: string; s: DemoState | null; ctl: RunCtl; motion: boolean; onMotion: () => void;
}) {
  const env = s?.env;
  let envLabel = "Connecting…";
  if (env?.status === "probing") envLabel = "Probing GPU…";
  else if (env?.status === "error") envLabel = "No ML stack: replay only";
  else if (env?.status === "ok") envLabel = env.gpu ? `${env.gpu.replace("NVIDIA GeForce ", "")}` : "CPU only";
  const current = (to: string) => (to === "/app" ? path === "/app" || path === "/app/" : path.startsWith(to)) ? "page" : undefined;

  return (
    <nav className="side" aria-label="App">
      <Link to="/" className="brandlink" style={{ padding: "0 6px" }} aria-label="sigil home">
        <Logo size={36} />
        <span className="display" style={{ fontSize: 28 }}>sigil</span>
      </Link>

      <div className="ws">
        <span className="dot pulse" style={{ color: "var(--caramel)", width: 10, height: 10 }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14 }}>Team Sigil</div>
          <div className="muted" style={{ fontSize: 12.5 }}>Final-year demo · {s?.mode === "simulate" ? "replay mode" : "live mode"}</div>
        </div>
      </div>

      <div className="group">
        {PAGES.map((p) => (
          <Link key={p.to} to={p.to} className="side-link" aria-current={current(p.to)}>
            <Icon name={p.icon} />{p.label}
          </Link>
        ))}
      </div>

      <div className="group">
        <div className="sectlabel">Research demos</div>
        {DEMOS.map((d) => {
          const st = panelStatus(d.key, s);
          const busy = demoBusy(d, ctl.running);
          return (
            <Link key={d.key} to={`/app/demo/${d.key}`} className="side-link" aria-current={current(`/app/demo/${d.key}`)}
              aria-label={`Demo ${d.key}: ${d.title} (${busy ? "running" : MARK[st].say})`}>
              <span className="lt" aria-hidden>{d.key}</span>
              <span style={{ lineHeight: 1.2 }}>{d.title}</span>
              <span className="mk" aria-hidden>{busy ? <span className="spinner" /> : MARK[st].icon}</span>
            </Link>
          );
        })}
        <p className="muted" style={{ fontSize: 12, padding: "4px 12px 0", margin: 0 }}>In a demo, ← → move between A–F.</p>
      </div>

      <div className="group" style={{ gap: 10, paddingTop: 4 }}>
        <span className={`chip${env?.status === "ok" ? " good" : env?.status === "error" ? " warn" : ""}`} title={env?.error}
          style={{ justifyContent: "center" }}>
          {env?.status === "ok" && <Icon name="check" size={14} />}{envLabel}
        </span>
        <RunButton ctl={ctl} step="all" primary disabled={!s} hint="Re-verify A, then run B, C, D and E1 + E2 live. E3 stays precomputed." />
        <button type="button" className="toggle" aria-pressed={motion} onClick={onMotion} style={{ justifyContent: "center" }}>
          <span className="knob" aria-hidden />Motion
        </button>
      </div>
    </nav>
  );
}
