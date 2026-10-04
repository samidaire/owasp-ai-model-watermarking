import type { ServerStep } from "../api";
import type { PageProps } from "../App";
import { Icon } from "../components/icons";
import { PanelA } from "../panels/PanelA";
import { PanelB } from "../panels/PanelB";
import { PanelC } from "../panels/PanelC";
import { PanelD } from "../panels/PanelD";
import { PanelE } from "../panels/PanelE";
import { PanelF } from "../panels/PanelF";
import type { PanelProps } from "../panels/Shell";
import { Link } from "../router";
import type { PanelKey } from "../stale";

/** The research storyline, in presentation order. `steps` = the server steps that refresh the panel. */
export const DEMOS: { key: PanelKey; title: string; sub: string; steps: ServerStep[]; Panel: (p: PanelProps) => React.JSX.Element }[] = [
  { key: "A", title: "Commit & embed", sub: "Seed, key and watermark", steps: ["evaluate", "retrain"], Panel: PanelA },
  { key: "B", title: "Removal attacks", sub: "OWASP R1 · gap G2", steps: ["attacks"], Panel: PanelB },
  { key: "C", title: "Ownership forgery", sub: "OWASP R2 · gap G1", steps: ["forgery"], Panel: PanelC },
  { key: "D", title: "Committed seed", sub: "The fix, without ZK", steps: ["committed"], Panel: PanelD },
  { key: "E", title: "Zero-knowledge proofs", sub: "EZKL on this machine", steps: ["zk", "zk_hashed"], Panel: PanelE },
  { key: "F", title: "Protocol v2", sub: "Circom + Groth16, end to end", steps: ["protocol_v2"], Panel: PanelF },
];

/** The steps "Run all live" chains (mirrors STEPS["all"] in demo/server.py): demo F isn't part of it. */
const IN_RUN_ALL: ServerStep[] = ["evaluate", "attacks", "forgery", "committed", "zk"];

/** Is this demo's panel being refreshed by the current run? */
export function demoBusy(d: (typeof DEMOS)[number], running: ServerStep | null): boolean {
  if (!running) return false;
  return d.steps.includes(running) || (running === "all" && d.steps.some((st) => IN_RUN_ALL.includes(st)));
}

export function Demos({ s, ctl, k }: PageProps & { k: string }) {
  const i = Math.max(0, DEMOS.findIndex((d) => d.key === k));
  const d = DEMOS[i];
  const prev = DEMOS[i - 1];
  const next = DEMOS[i + 1];
  const refreshing = demoBusy(d, ctl.running);
  return (
    <>
      <d.Panel s={s} ctl={ctl} refreshing={refreshing} />
      <nav aria-label="Demo navigation" style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 12, maxWidth: 1140 }}>
        {prev ? <Link to={`/app/demo/${prev.key}`} className="btn"><span aria-hidden>←</span> Demo {prev.key}: {prev.title}</Link> : <span />}
        {next ? <Link to={`/app/demo/${next.key}`} className="btn primary">Demo {next.key}: {next.title} <Icon name="arrow" size={18} /></Link>
          : <Link to="/app/verify" className="btn primary">Verify ownership <Icon name="arrow" size={18} /></Link>}
      </nav>
    </>
  );
}
