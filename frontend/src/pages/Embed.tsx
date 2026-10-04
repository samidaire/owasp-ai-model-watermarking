import { useState } from "react";
import type { PageProps } from "../App";
import { Icon } from "../components/icons";
import { Callout, Empty } from "../components/ui";
import { pct, short, when } from "../format";
import { RunButton } from "../panels/Shell";
import { Link } from "../router";

type Proto = "v1" | "v2";

function BitBox({ bits, hidden, T }: { bits?: number[]; hidden?: boolean; T: number }) {
  const cells = hidden ? Array.from({ length: T }, () => -1) : bits ?? [];
  return (
    <div className="bitbox" role="img" aria-label={hidden ? `${T}-bit signature, hidden` : `${cells.length}-bit signature`}
      style={{ gridTemplateColumns: "repeat(16, minmax(0, 1fr))" }}>
      {cells.map((b, i) => (
        <span key={`${hidden}-${i}`} className={b < 0 ? "hidden" : b ? "one" : "zero"}
          style={{ ["--i" as string]: (i % 16) + Math.floor(i / 16) }} title={b < 0 ? "hidden" : `bit ${i}: ${b}`} />
      ))}
    </div>
  );
}

export function Embed({ s, ctl }: PageProps) {
  const t = s.results.train;
  const f = s.results.protocol_v2;
  const [proto, setProto] = useState<Proto>("v2");
  const v2 = proto === "v2";
  const ready = v2 ? Boolean(f) : Boolean(t);

  const steps = v2 ? ["Owner key", "Committed seed", "Embed", "Register"] : ["Secret seed", "Commit", "Embed", "Publish"];
  return (
    <>
      <div className="pagehead">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <nav aria-label="Breadcrumb" className="mono muted" style={{ fontSize: 13, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link to="/app" style={{ color: "var(--text-secondary)" }}>Overview</Link><span aria-hidden>/</span>
            <span>{v2 ? "v2/watermarked_v2.pt" : "watermarked.pt"}</span><span aria-hidden>/</span>
            <span style={{ color: "var(--espresso)", fontWeight: 600 }}>Embed</span>
          </nav>
          <h1 className="display in" style={{ ["--i" as string]: 0, margin: 0, fontSize: "clamp(40px, 4.4vw, 62px)" }}>
            Embed a <span className="jw hlw">watermark.</span>
          </h1>
          <p className="muted" style={{ margin: 0, fontSize: 16, maxWidth: 720 }}>
            How the demo's models were watermarked: a secret seed decides both the key and the signature, the owner commits to it
            before release, and training hides the signature in the weights of one layer.
          </p>
        </div>
        <div className="segbar" role="group" aria-label="Protocol" style={{ flex: "0 1 420px" }}>
          <button type="button" aria-pressed={proto === "v1"} onClick={() => setProto("v1")}>Protocol v1 · demo A</button>
          <button type="button" aria-pressed={proto === "v2"} onClick={() => setProto("v2")}>Protocol v2 · demo F</button>
        </div>
      </div>

      <ol className="stepper" aria-label="Embedding steps">
        {steps.map((label, i) => (
          <li key={label}>
            {i > 0 && <span className="ln" aria-hidden />}
            <span className="c" aria-hidden><Icon name="check" size={18} /></span>
            <span>{label}</span>
          </li>
        ))}
      </ol>

      {!ready ? <Empty what={v2 ? "demo F" : "demo A"} /> : (
        <div className="cols">
          <section className="box" style={{ flex: "1 1 520px", minWidth: 0, padding: 26, display: "flex", flexDirection: "column", gap: 20 }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 14, padding: 14, border: "1.5px dashed color-mix(in oklab, var(--espresso) 30%, transparent)", borderRadius: 18, background: "var(--cream)" }}>
              <span className="ibub" style={{ background: "var(--caramel)" }}><Icon name="file" /></span>
              <div style={{ flex: "1 1 200px", minWidth: 0 }}>
                <div className="mono" style={{ fontWeight: 600, fontSize: 14.5 }}>{v2 ? "watermarked_v2.pt" : "watermarked.pt"}</div>
                <div className="muted" style={{ fontSize: 13 }}>PyTorch · MNIST CNN · watermarked layer conv2 (M = 288)</div>
              </div>
              <span className="chip good"><Icon name="check" size={14} />Embedded</span>
            </div>

            <h2 className="h-sm">Configuration</h2>
            <dl className="kv">
              {v2 && f ? <>
                <dt>Owner</dt><dd><span className="hash">{short(f.owner_public_key, 20)}</span> <span className="muted">Ed25519 public key</span></dd>
                <dt>Signature</dt><dd>{f.config.T} bits · accept with at most {f.config.max_err} wrong (θ = {f.config.max_err}/{f.config.T})</dd>
                <dt>Method</dt><dd>White-box (Uchida), layer <span className="mono">{f.config.layer}</span>, λ = 1.0</dd>
                <dt>Key X</dt><dd>{f.config.T} × {f.config.M}, entries ±1 from a Poseidon PRG of (seed, owner key)</dd>
                <dt>Fixed point</dt><dd>w × 2^{f.config.scale_bits}, |w| &lt; 2^{f.config.w_bits}: the circuit's exact arithmetic</dd>
                <dt>Accuracy</dt><dd>{pct(f.accuracy.watermarked_v2)} with the watermark</dd>
              </> : t && <>
                <dt>Owner</dt><dd className="mono">{t.owner_id}</dd>
                <dt>Signature</dt><dd>{t.signature_bits.length} bits · accept with BER ≤ {t.threshold.toFixed(3)}</dd>
                <dt>Method</dt><dd>White-box (Uchida), layer <span className="mono">conv2</span>, λ = 1.0</dd>
                <dt>Key X</dt><dd>{t.key_shape.join(" × ")} Gaussian projection from SHA-256 of the seed</dd>
                <dt>Accuracy</dt><dd>{pct(t.models.clean.accuracy)} clean → {pct(t.models.watermarked.accuracy)} watermarked</dd>
              </>}
            </dl>

            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ fontWeight: 700, fontSize: 14 }}>Secret seed</span>
              <code className="mono" style={{ minHeight: 48, display: "flex", alignItems: "center", padding: "0 16px", border: "var(--line)", borderRadius: 14, background: "var(--espresso)", color: "var(--cream)", fontSize: 14, letterSpacing: ".04em" }}>
                seed_••••••••••••••••••••••••••
              </code>
              <p className="muted" style={{ margin: 0, fontSize: 13.5, display: "flex", gap: 8, alignItems: "center" }}>
                <Icon name="lock" size={16} />Never leaves the owner's machine. Only its commitment is published.
              </p>
            </div>

            <div className="actions">
              {v2 ? <>
                <RunButton ctl={ctl} step="protocol_v2" primary />
                <Link to="/app/verify" className="btn">Verify this model <Icon name="arrow" size={18} /></Link>
              </> : <>
                <RunButton ctl={ctl} step="evaluate" primary />
                <RunButton ctl={ctl} step="retrain" />
              </>}
            </div>
          </section>

          <div style={{ flex: "1 1 400px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
            <section className="box" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16, background: "var(--sand)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                <h2 className="h-sm">Signature</h2>
                <span className="chip mono">{v2 ? f?.config.T : t?.signature_bits.length} bits</span>
              </div>
              <div style={{ padding: 16, border: "var(--line)", borderRadius: 18, background: "var(--paper)" }}>
                {v2 ? <BitBox hidden T={f?.config.T ?? 64} /> : <BitBox bits={t?.signature_bits} T={64} />}
              </div>
              <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>
                {v2 ? "Derived inside the circuit from the committed seed: never shown, not even to the verifier."
                  : "Derived from the seed with SHA-256. Shown here for the demo; protocol v2 keeps it secret."}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span className="eyebrow">Commitment (public)</span>
                <span className="hash" style={{ fontWeight: 600 }}>{v2 ? f?.commitment : t?.commitment}</span>
                <span className="muted" style={{ fontSize: 13 }}>{v2 ? `Poseidon · registry receipt ${f ? when(f.registered_at) : ""}` : `SHA-256 · published ${t ? when(t.timestamp_utc) : ""}`}</span>
              </div>
            </section>

            <section className="codebox">
              <div className="bar"><i /><i /><i /><span className="mono" style={{ marginLeft: 10, fontSize: 13, color: "var(--latte)" }}>same thing, from the command line</span></div>
              <div className="body">{v2 ? <>
                <div><span className="tk-f">sigil</span> keygen                      <span className="tk-c"># Ed25519 owner key</span></div>
                <div><span className="tk-f">sigil</span> seed --bits <span className="tk-s">64</span> --layer <span className="tk-s">conv2</span></div>
                <div><span className="tk-c"># train with sigil.embed.embed_torch(...), save the model</span></div>
                <div><span className="tk-f">sigil</span> detect <span className="tk-s">watermarked_v2.pt</span></div>
                <div><span className="tk-f">sigil</span> register <span className="tk-s">watermarked_v2.pt</span> --registry-key <span className="tk-s">registry.key</span><span className="caret" /></div>
              </> : <>
                <div><span className="tk-c"># demo A: new seed, commitment, watermarked + clean + null models</span></div>
                <div><span className="tk-f">python</span> demo/01_train.py</div>
                <div><span className="tk-c"># re-check the saved owner models (no retraining)</span></div>
                <div><span className="tk-f">python</span> demo/evaluate_owner.py<span className="caret" /></div>
              </>}</div>
            </section>
          </div>
        </div>
      )}

      {!v2 && <Callout tone="warn"><p><strong>Retrain</strong> creates a new owner seed and key, so the results of demos B–E become stale until they're re-run.</p></Callout>}
    </>
  );
}
