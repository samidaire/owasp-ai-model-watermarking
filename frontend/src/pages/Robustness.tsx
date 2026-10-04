import type { PageProps } from "../App";
import { Icon } from "../components/icons";
import { Callout, Empty, Verdict } from "../components/ui";
import { ber3, pct } from "../format";
import { RunButton } from "../panels/Shell";
import { Link } from "../router";
import { panelStale } from "../stale";

const FAMILY: Record<string, { label: string; icon: string }> = {
  baseline: { label: "none", icon: "check" }, prune: { label: "pruning", icon: "scissors" }, quantise: { label: "quantisation", icon: "stairs" },
  finetune: { label: "fine-tuning", icon: "sliders" }, overwrite: { label: "overwriting", icon: "copy" }, permute: { label: "permutation", icon: "refresh" },
};

export function Robustness({ s, ctl }: PageProps) {
  const a = s.results.attacks;
  const t = s.results.train;
  if (!a) return <Empty what="the robustness lab (demo B)" />;
  const theta = a.threshold;
  const pruning = a.rows
    .filter((r) => r.family === "baseline" || r.family === "prune")
    .map((r) => ({ x: r.family === "baseline" ? 0 : Number(/(\d+)%/.exec(r.attack)?.[1] ?? 0), acc: r.accuracy, ber: r.owner_ber }))
    .sort((p, q) => p.x - q.x);
  const others = a.rows.filter((r) => r.family !== "prune" && r.family !== "baseline");
  const breakAt = pruning.find((p) => p.acc < 0.9);
  const stale = panelStale("B", s);

  return (
    <>
      <div className="pagehead">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="actions"><span className="chip in" style={{ ["--i" as string]: 0 }}>Robustness lab · demo B</span>{stale && <Verdict tone="warn">Stale: older owner key</Verdict>}</div>
          <h1 className="display in" style={{ ["--i" as string]: 1, margin: 0, fontSize: "clamp(40px, 4.4vw, 62px)" }}>
            Robustness <span className="jw hlw">lab.</span>
          </h1>
          <p className="muted in" style={{ ["--i" as string]: 2, margin: 0, fontSize: 16, maxWidth: 640 }}>
            Attack the stolen model the way a thief would, then check whether the owner's watermark survives.
            {t && <> Clean model accuracy: {pct(t.models.clean.accuracy)}.</>} The thief uses 10,000 samples of their own.
          </p>
        </div>
        <RunButton ctl={ctl} step="attacks" primary />
      </div>

      <div className="statgrid">
        {others.map((r, i) => {
          const fam = FAMILY[r.family] ?? { label: r.family, icon: "bolt" };
          return (
            <article key={r.attack} className="box lift pop wig" style={{ ["--i" as string]: i, padding: 20, display: "flex", flexDirection: "column", gap: 10,
              ...(r.survives ? {} : { borderColor: "var(--rust)", boxShadow: "5px 5px 0 var(--rust)", background: "color-mix(in oklab, var(--rust) 6%, var(--paper))" }) }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span className="ibub" style={{ width: 38, height: 38, borderRadius: 12 }}><Icon name={fam.icon} size={18} /></span>
                {r.survives ? <Verdict tone="good">Survives</Verdict> : <Verdict tone="bad">Removed</Verdict>}
              </div>
              <span style={{ fontWeight: 700, fontSize: 16 }}>{r.attack}</span>
              <span className="muted" style={{ fontSize: 12.5, marginTop: -6 }}>{fam.label}</span>
              <div className="display" style={{ fontSize: 40 }}>{pct(1 - r.owner_ber, 1)}</div>
              <span className="eyebrow" style={{ marginTop: -6 }}>bits recovered (BER {ber3(r.owner_ber)})</span>
              <div style={{ height: 12, border: "var(--line)", borderRadius: 999, overflow: "hidden", background: "var(--paper)" }}>
                <div style={{ width: `${(1 - r.owner_ber) * 100}%`, height: "100%", background: r.survives ? "var(--espresso)" : "var(--rust)", transformOrigin: "left", animation: `fillx 1.1s var(--spring) backwards ${0.2 + i * 0.08}s` }} />
              </div>
              <span className="muted" style={{ fontSize: 13.5 }}>Model accuracy <strong style={{ color: "var(--espresso)" }}>{pct(r.accuracy)}</strong></span>
            </article>
          );
        })}
      </div>

      <section className="box" style={{ padding: 26, display: "flex", flexDirection: "column", gap: 20 }}>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 14 }}>
          <div><h2 className="h-sm">Pruning sweep</h2><span className="muted" style={{ fontSize: 14 }}>Per-layer magnitude pruning of every weight tensor</span></div>
          <div className="actions" style={{ fontSize: 13.5, fontWeight: 600, gap: 14 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span style={{ width: 16, height: 16, border: "var(--line)", borderRadius: 5, background: "var(--espresso)" }} />Watermark bits recovered</span>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span style={{ width: 16, height: 16, border: "var(--line)", borderRadius: 5, background: "var(--caramel)" }} />Model accuracy</span>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}><span style={{ width: 22, borderTop: "3px dashed var(--rust)" }} />Acceptance threshold</span>
          </div>
        </div>
        <div role="img" aria-label={`Pruning from 0% to ${pruning.at(-1)?.x}%: bits recovered stay at or above ${pct(1 - Math.max(...pruning.map((p) => p.ber)), 0)} while accuracy falls to ${pct(Math.min(...pruning.map((p) => p.acc)), 0)}`}>
          <div className="vbars">
            {[25, 50, 75, 100].map((y) => <div key={y} className="gl" style={{ bottom: `${y}%` }} />)}
            {[0, 25, 50, 75, 100].map((y) => <span key={y} className="yl" style={{ bottom: `${y}%` }}>{y}%</span>)}
            <div className="row">
              {pruning.map((p, i) => (
                <div key={p.x} className="grp">
                  <div className="b" title={`${p.x}% pruned: ${pct(1 - p.ber, 1)} bits recovered`} style={{ height: `${(1 - p.ber) * 100}%`, background: "var(--espresso)", ["--i" as string]: i * 2 }} />
                  <div className="b" title={`${p.x}% pruned: accuracy ${pct(p.acc, 1)}`} style={{ height: `${p.acc * 100}%`, background: "var(--caramel)", ["--i" as string]: i * 2 + 1 }} />
                </div>
              ))}
            </div>
            <div style={{ position: "absolute", left: 0, right: 0, bottom: `${(1 - theta) * 100}%`, borderTop: "3px dashed var(--rust)", pointerEvents: "none" }} />
            <span className="mono" style={{ position: "absolute", right: 8, bottom: `calc(${(1 - theta) * 100}% + 6px)`, padding: "3px 8px", border: "1.5px solid var(--rust)", borderRadius: 8, background: "var(--paper)", color: "var(--rust)", fontSize: 11.5, fontWeight: 600 }}>
              accept ≥ {pct(1 - theta, 1)} bits
            </span>
          </div>
          <div className="xlabels">{pruning.map((p) => <span key={p.x}>{p.x}%</span>)}</div>
          <p className="eyebrow" style={{ textAlign: "center", margin: "6px 0 0" }}>weights pruned per layer</p>
        </div>
        {breakAt && (
          <p style={{ margin: 0, padding: "14px 16px", border: "2px dashed var(--espresso)", borderRadius: 16, background: "var(--cream)", fontSize: 15 }}>
            <strong>The mark outlives the model.</strong> At {breakAt.x}% pruning, accuracy has already fallen to {pct(breakAt.acc, 1)} while
            {" "}{pct(1 - breakAt.ber, 1)} of the watermark bits are still recovered. A thief ruins the model before erasing the mark.
          </p>
        )}
      </section>

      <section className="box" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <h2 className="h-sm">All results</h2>
          <Link to="/app/demo/B" className="rowgo">Present as demo B <Icon name="arrow" size={16} /></Link>
        </div>
        <div className="tablewrap">
          <table className="tbl">
            <thead><tr><th>Attack</th><th>Type</th><th>Model accuracy</th><th>Owner BER</th><th>Verdict</th></tr></thead>
            <tbody>{a.rows.map((r) => (
              <tr key={r.attack}>
                <td style={{ fontWeight: 600 }}>{r.attack}</td>
                <td className="muted">{FAMILY[r.family]?.label ?? r.family}</td>
                <td className="mono">{pct(r.accuracy)}</td>
                <td className="mono">{ber3(r.owner_ber)}</td>
                <td>{r.survives ? <Verdict tone="good">Survives</Verdict> : <Verdict tone="bad">Removed</Verdict>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <Callout tone="warn">
        <p><strong>Honest limits.</strong> Feature permutation erases this white-box mark at no accuracy cost unless the owner realigns first, and
          a copy trained only from the model's outputs (extraction) isn't covered by a white-box mark at all (OWASP limitation L1).</p>
      </Callout>
    </>
  );
}
