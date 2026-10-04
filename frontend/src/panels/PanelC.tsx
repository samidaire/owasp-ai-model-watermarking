import { isStale } from "../api";
import { BitGrid, BitLegend } from "../components/charts";
import { Callout, Card, Empty, Notes, Stat, Verdict } from "../components/ui";
import { ber3, bitsWrong } from "../format";
import { PanelShell, RunButton, type PanelProps } from "./Shell";

export function PanelC({ s, ctl, refreshing }: PanelProps) {
  const f = s.results.forgery;
  return (
    <PanelShell
      letter="C" title="Ownership forgery" reqs={["OWASP R2: avoid ambiguous ownership", "Gap G1"]}
      claim="Without a key commitment, the thief needs only the stolen weights. They choose their own signature and fit a counterfeit key to the owner's weights, one sign flip per bit."
      stale={isStale(f?.commitment, s.commitment)} refreshing={refreshing}
      actions={<RunButton ctl={ctl} step="forgery" label="Run forgery live" primary hint="~3 s" />}
      notes={<Notes
        say={[
          "The thief has the weights but not my key. They pick their own signature, 'MALLORY!', and fit a key to my weights in one line per bit.",
          "Its entries look like a real key's, and with rejection sampling even its margins match. Under ZK the verifier sees neither.",
          "The same trick 'proves' ownership of models that were never watermarked at all.",
          "The same construction satisfies the relation ZKROWNN's circuit checks. ZKROWNN assumes an honest prover, so this is outside its threat model, but in a dispute the accuser is the party with a motive to cheat (USENIX Security '24 false-claims paper).",
          "This is my analysis; the demo is the evidence.",
        ]}
        caveats={["Part 2 evaluates ZKROWNN's Algorithm 1 relation in PyTorch. It does not run ZKROWNN's code or circuit."]}
      />}
    >
      {!f ? <Empty what="demo C" /> : <>
        <div className="grid2">
          <Card title="Owner: real key" sub="Committed at embedding time" flag="good">
            <div className="grid2" style={{ marginBottom: 14 }}>
              <Stat label="Owner BER on the stolen model" value={ber3(f.owner.ber)} caption={`${bitsWrong(f.owner.ber)}/64 bits differ`} />
              <div style={{ alignSelf: "center" }}><Verdict tone="good">Ownership shown</Verdict></div>
            </div>
            <BitGrid bits={f.owner.extracted_bits} reference={f.owner.signature_bits} label="Owner key extraction" columns={16} />
          </Card>
          <Card title="Thief: counterfeit key fitted to the stolen weights" sub="Chosen after seeing the model" flag="bad">
            <div className="grid2" style={{ marginBottom: 14 }}>
              <Stat label="Thief BER on the same model" value={ber3(f.thief.ber)} caption={`${bitsWrong(f.thief.ber)}/64 bits differ`} />
              <Stat label="Extracted message" value={<span className="mono">{f.thief.message}</span>} />
            </div>
            <BitGrid bits={f.thief.extracted_bits} reference={f.thief.target_bits} label="Thief key extraction" columns={16} />
          </Card>
        </div>
        <BitLegend />
        <Callout tone="bad"><p><strong>Both parties "prove" ownership of the same model.</strong> Nothing in the extraction itself says who embedded the watermark.</p></Callout>

        <Card title="Can a judge who sees the key and the weights tell the counterfeit apart?"
          sub="Entry statistics vs the owner's key, and projection margins (in units of a random row's standard deviation)">
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Key</th><th className="num">Entry mean</th><th className="num">Entry std</th><th className="num">KS D vs owner</th>
                <th className="num">Min margin</th><th className="num">Median margin</th></tr></thead>
              <tbody>{f.key_stats.map((k) => (
                <tr key={k.key}>
                  <td>{k.key}</td>
                  <td className="num">{k.entry_mean >= 0 ? "+" : ""}{k.entry_mean.toFixed(4)}</td>
                  <td className="num">{k.entry_std.toFixed(4)}</td>
                  <td className="num">{k.ks_d.toFixed(4)}</td>
                  <td className="num">{k.min_margin.toFixed(2)}</td>
                  <td className="num">{k.median_margin.toFixed(2)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <p className="sub" style={{ marginTop: 10 }}>
            KS 5% critical value {f.ks_critical.toFixed(4)}. Entry distributions match a real key. The naive forgery has smaller margins,
            which a careful forger raises by rejection sampling (large-margin forgery BER {ber3(f.large_margin_ber)}). Under ZK the verifier sees neither.
          </p>
        </Card>

        <div className="grid2">
          <Card title="Models that were never watermarked" sub="The same sign-fit forgery, applied to each">
            <div className="tablewrap"><table className="data">
              <thead><tr><th>Model</th><th className="num">Thief BER</th><th>Outcome</th></tr></thead>
              <tbody>{f.never_watermarked.map((r) => (
                <tr key={r.model}>
                  <td className="mono">{r.model}</td>
                  <td className="num">{ber3(r.thief_ber)}</td>
                  <td>{r.thief_ber <= f.threshold ? <Verdict tone="bad">False claim works</Verdict> : <Verdict tone="good">Rejected</Verdict>}</td>
                </tr>
              ))}</tbody>
            </table></div>
          </Card>
          <Card title="Same construction vs ZKROWNN's Algorithm 1 relation"
            sub={`Private witness chosen after seeing the model: trigger key ${f.zkrownn.xkey_shape.join("×")} (thief's own images), projection A ${f.zkrownn.a_shape.join("×")} (fitted), watermark "${f.thief.target_text}"`}>
            <div className="tablewrap"><table className="data">
              <thead><tr><th>Model</th><th>Relation</th><th className="num">BER</th></tr></thead>
              <tbody>{f.zkrownn.rows.map((r) => (
                <tr key={r.model}>
                  <td className="mono">{r.model}</td>
                  <td>{r.satisfied ? <Verdict tone="bad">Satisfied</Verdict> : <Verdict tone="good">Not satisfied</Verdict>}</td>
                  <td className="num">{ber3(r.ber)}</td>
                </tr>
              ))}</tbody>
            </table></div>
            <p className="sub" style={{ marginTop: 10 }}>
              Without a prior commitment, a valid witness exists for any model, and a ZK proof of this relation would hide the fitted A.
              Evaluated in PyTorch, not ZKROWNN's code; ZKROWNN assumes a semi-honest prover.
            </p>
          </Card>
        </div>
      </>}
    </PanelShell>
  );
}
