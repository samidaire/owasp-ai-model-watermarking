import { useState } from "react";
import { isStale } from "../api";
import { Histogram } from "../components/charts";
import { Callout, Card, Empty, Notes, Stat, Verdict } from "../components/ui";
import { ber3, bitsWrong, int, sci, secs } from "../format";
import { PanelShell, RunButton, type PanelProps } from "./Shell";

export function PanelD({ s, ctl, refreshing }: PanelProps) {
  const c = s.results.committed_seed;
  const [tries, setTries] = useState(20000);
  const T = c?.signature_bits_T ?? 64;
  return (
    <PanelShell
      letter="D" title="Committed seed" reqs={["OWASP R2: the fix", "RQ1"]}
      claim="Commit at embedding time to a secret seed, and derive both the key and the signature from it. Then the thief can no longer choose a signature after seeing the model."
      stale={isStale(c?.commitment, s.commitment)} refreshing={refreshing}
      actions={<>
        <label className="actions" style={{ gap: 6, color: "var(--text-secondary)", fontSize: 13 }}>
          Thief's budget
          <select className="sel" value={tries} onChange={(e) => setTries(Number(e.target.value))} disabled={ctl.running !== null}>
            <option value={20000}>20,000 seeds (~2 s)</option>
            <option value={100000}>100,000 seeds (~10 s)</option>
          </select>
        </label>
        <RunButton ctl={ctl} step="committed" label="Run live" primary tries={tries} />
      </>}
      notes={<Notes
        say={[
          "If only the key is derived, the thief just sets the signature to whatever their key extracts. That wins by construction, not by luck.",
          "Derive the signature from the seed too, and the thief has to search seeds blindly.",
          "But at 64 bits that is only about 2³² work, feasible on a GPU. That is why timestamp ordering still matters, and why RQ1 sets T and θ. At Uchida's 256 bits it would be about 2¹²⁰.",
        ]}
        caveats={["The null models are an indicative check, not a calibrated false-positive rate."]}
      />}
    >
      {!c ? <Empty what="demo D" /> : <>
        <div className="grid3">
          <Card title="D0 · Owner opens the commitment" flag="good">
            <div className="actions" style={{ marginBottom: 12 }}>
              <Verdict tone={c.d0.commitment_matches ? "good" : "bad"}>H(seed ‖ owner) {c.d0.commitment_matches ? "matches" : "mismatch"}</Verdict>
            </div>
            <Stat label="Owner BER on the stolen model" value={ber3(c.d0.owner_ber)}
              caption={c.d0.verified ? "Ownership verified" : "Not verified"} />
          </Card>
          <Card title="D1 · Naive fix: free signature" flag="bad">
            <Stat label="Thief forgeries accepted" value={`${int(c.d1.wins)}/${int(c.d1.trials)}`} hero
              caption="True by construction: the thief sets the signature to whatever their key extracts, then commits after the theft" />
          </Card>
          <Card title="D2 · Real fix: derived signature" flag="good">
            <Stat label="Thief forgeries accepted" value={`${int(c.d2.accepted)}/${int(c.d2.tries)}`} hero
              caption={`Best thief BER ${ber3(c.d2.min_ber)} (${bitsWrong(c.d2.min_ber, T)}/${T} bits wrong); searched in ${secs(c.d2.seconds)}`} />
          </Card>
        </div>

        <Card title="D2: the thief's seed search" sub={`BER of each of ${int(c.d2.tries)} attempts. A forgery is accepted only at BER ≤ ${ber3(c.threshold)}.`}>
          <Histogram
            bins={c.d2.histogram.map((h) => ({ x: h.ber, count: h.count }))}
            markers={[
              { x: c.threshold, label: `accept ≤ ${ber3(c.threshold)}`, tone: "neutral" },
              { x: c.d0.owner_ber, label: `✓ owner ${ber3(c.d0.owner_ber)}`, tone: "good" },
            ]}
            xLabel="BER of extracted vs seed-derived signature"
            ariaLabel={`Histogram of ${c.d2.tries} thief attempts, centred near BER 0.5, none at or below the threshold`}
            tip={(b) => ({ value: `${int(b.count)} seeds`, label: `BER ${b.x.toFixed(3)} (${bitsWrong(b.x, T)}/${T} bits wrong)` })}
          />
        </Card>

        <div className="grid4">
          <Card><Stat label="Success chance per try" value={sci(c.d2.p_per_try)} caption={`P[Bin(${T}, 0.5) ≤ ${Math.floor(c.threshold * T)}]`} /></Card>
          <Card><Stat label="Work factor" value={<>2<sup>{c.d2.log2_work.toFixed(1)}</sup></>} caption={`${sci(c.d2.seeds_for_half)} seeds for a 50% chance`} /></Card>
          <Card><Stat label="At this machine's rate" value={int(c.d2.single_core_hours)} unit="core-hours" caption={`${int(c.d2.seeds_per_s)} seeds/s on one core`} /></Card>
          <Card><Stat label="Target at T = 256 bits" value={<>2<sup>{Math.round(c.d2.log2_work_T256)}</sup></>} caption="Uchida's signature length, same θ = 1/8" /></Card>
        </div>
        <Callout tone="warn">
          <p><strong>At {T} bits this is only ~2<sup>{Math.round(c.d2.log2_work)}</sup> work, feasible on a GPU or cluster.</strong> Timestamp ordering
            (the earliest commitment wins) stays necessary, and RQ1 must set the signature length T and threshold θ.</p>
        </Callout>

        <Card title="Null check: owner's key on models that were never watermarked" sub="Indicative only; too few models to state a false-positive rate (Phase 1 work)">
          <table className="data">
            <thead><tr><th>Model</th><th className="num">Owner BER</th><th>Outcome</th></tr></thead>
            <tbody>{c.nulls.map((n) => (
              <tr key={n.model}>
                <td className="mono">{n.model}</td>
                <td className="num">{ber3(n.owner_ber)}</td>
                <td>{n.owner_ber > c.threshold ? <Verdict tone="good">Correctly not claimed</Verdict> : <Verdict tone="bad">False claim</Verdict>}</td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      </>}
    </PanelShell>
  );
}
