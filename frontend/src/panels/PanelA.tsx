import { isStale } from "../api";
import { BitGrid, BitLegend } from "../components/charts";
import { Card, Empty, Notes, Stat, Verdict } from "../components/ui";
import { ber3, bitsWrong, pct, when } from "../format";
import { PanelShell, RunButton, type PanelProps } from "./Shell";

const RETRAIN_WARNING =
  "Retraining creates a NEW owner seed and key.\n\n" +
  "Every other result (B–E) becomes stale, and E3's precomputed Poseidon proofs must be re-run " +
  "(about 3 minutes and ~10 GB of temporary disk).\n\nContinue?";

export function PanelA({ s, ctl, refreshing }: PanelProps) {
  const t = s.results.train;
  return (
    <PanelShell
      letter="A" title="Commit & embed" reqs={["OWASP: post-theft ownership verification"]}
      claim="Before release, the owner publishes a hash of a secret seed. The watermark key and the 64-bit signature are both derived from that seed, then embedded into the model's weights (Uchida-style). The watermark costs essentially no accuracy."
      stale={isStale(t?.commitment, s.commitment)} refreshing={refreshing}
      actions={<>
        <RunButton ctl={ctl} step="evaluate" label="Re-verify live" primary hint="Re-checks the saved models (~5 s). Does not retrain." />
        <RunButton ctl={ctl} step="retrain" label="Retrain with a new seed…" confirm={RETRAIN_WARNING} />
      </>}
      notes={<Notes
        say={[
          "Before anything is released, I publish a hash of a secret seed. The key and the signature are both derived from that seed.",
          "The watermarked model is essentially as accurate as the clean one (a few hundredths of a percentage point), and my key reads back all 64 bits from it.",
          "On a clean model, or on models I never watermarked, the same key gives roughly coin-flip bits.",
        ]}
        caveats={[
          "The demo stores the commitment locally. In production it would go to a transparency log (e.g. Sigstore) for an independent timestamp.",
          "The acceptance threshold θ = 8/64 is indicative only; a handful of null models cannot give a false-positive rate.",
        ]}
      />}
    >
      {!t ? <Empty what="demo A" /> : <>
        <div className="grid2">
          <Card title="Published commitment" sub="Made at embedding time, before the model is released">
            <dl className="kv">
              <dt>SHA-256</dt><dd className="hash">{t.commitment}</dd>
              <dt>Timestamp</dt><dd>{when(t.timestamp_utc)} <span style={{ color: "var(--text-muted)" }}>({t.timestamp_utc})</span></dd>
              <dt>Owner</dt><dd className="mono">{t.owner_id}</dd>
              <dt>Key X</dt><dd>{t.key_shape.join(" × ")} Gaussian projection, derived from the seed</dd>
            </dl>
          </Card>
          <Card title="Accuracy cost of the watermark" sub="MNIST test set, 10,000 images">
            <div className="grid2">
              <Stat label="Clean model" value={pct(t.models.clean.accuracy)} />
              <Stat label="Watermarked model" value={pct(t.models.watermarked.accuracy)}
                caption={`${((t.models.watermarked.accuracy - t.models.clean.accuracy) * 100).toFixed(2)} percentage points vs clean`} />
            </div>
          </Card>
        </div>

        <Card title="Reading the watermark with the owner's key" sub="Each square is one bit of the 64-bit signature">
          <div className="bitrow">
            <div className="name">Signature b<small>derived from the committed seed</small></div>
            <BitGrid bits={t.signature_bits} label="Owner signature" />
            <div className="verdict"><Verdict tone="neutral">64 bits</Verdict></div>
          </div>
          {([["watermarked", "Extracted from watermarked model"], ["clean", "Extracted from clean model"]] as const).map(([k, name]) => {
            const m = t.models[k];
            const ok = m.owner_ber <= t.threshold;
            return (
              <div className="bitrow" key={k}>
                <div className="name">{name}<small>BER {ber3(m.owner_ber)}</small></div>
                <BitGrid bits={m.extracted_bits} reference={t.signature_bits} label={name} />
                <div className="verdict">
                  <Verdict tone={ok ? "good" : "bad"}>{bitsWrong(m.owner_ber)}/64 differ · {ok ? "ownership shown" : "no match"}</Verdict>
                </div>
              </div>
            );
          })}
          <BitLegend />
        </Card>

        <Card title="Null models: independently trained, never watermarked" sub="The owner's key should NOT find its signature here (indicative check, not a calibrated false-positive rate)">
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Model</th><th className="num">Test accuracy</th><th className="num">Owner BER</th><th>Outcome</th></tr></thead>
              <tbody>{t.nulls.map((n) => (
                <tr key={n.name}>
                  <td className="mono">{n.name}</td>
                  <td className="num">{pct(n.accuracy)}</td>
                  <td className="num">{ber3(n.owner_ber)}</td>
                  <td>{n.owner_ber > t.threshold
                    ? <Verdict tone="good">Correctly not claimed</Verdict>
                    : <Verdict tone="bad">False claim</Verdict>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Card>
      </>}
    </PanelShell>
  );
}
