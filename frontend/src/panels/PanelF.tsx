import { Callout, Card, Empty, Notes, Stat, Verdict } from "../components/ui";
import { bytes, secs, short, when } from "../format";
import { PanelShell, RunButton, type PanelProps } from "./Shell";

/** What each verifier check means, in the order the verifier runs them (sdk/src/sigil/verify.py). */
const CHECKS: [string, string][] = [
  ["registration_valid", "Registration signed by the owner"],
  ["receipt_valid", "Registry receipt from a trusted registry"],
  ["registered_before_claim", "Registered before the claim"],
  ["claim_matches_registration", "Claim refers to this registration"],
  ["claim_matches_suspect", "Claim refers to this suspect file"],
  ["public_pk_hash", "Proof is for the owner's key"],
  ["public_config_hash", "Same watermark configuration"],
  ["public_commitment", "Opens the published commitment"],
  ["public_w_hash", "About this exact model (w_hash)"],
  ["public_nonce", "Made for this claim (nonce)"],
  ["snark_valid", "Groth16 proof verifies"],
];

function Stamp({ ok }: { ok: boolean }) {
  const id = ok ? "f-ring-ok" : "f-ring-bad";
  const text = ok ? "ownership verified · zero bits revealed · groth16 · " : "proof rejected · checks failed · rejected · ";
  return (
    <div className="stampwrap" aria-hidden>
      <div className={`stamp${ok ? "" : " bad"}`}>
        <svg viewBox="0 0 240 240">
          <defs><path id={id} d="M120,120 m-100,0 a100,100 0 1,1 200,0 a100,100 0 1,1 -200,0" /></defs>
          <circle cx="120" cy="120" r="116" fill="var(--paper)" stroke={ok ? "var(--espresso)" : "var(--rust)"} strokeWidth="4" />
          <circle cx="120" cy="120" r="84" fill="none" stroke={ok ? "var(--espresso)" : "var(--rust)"} strokeWidth="2" strokeDasharray="6 6" />
          <text className="ring"><textPath href={`#${id}`}>{text}</textPath></text>
        </svg>
        <div className="core">
          <svg viewBox="0 0 24 24" width="46" height="46" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
            {ok ? <path d="M5 12.5l4.5 4.5L19 7" /> : <path d="M6 6l12 12M18 6L6 18" />}
          </svg>
        </div>
      </div>
    </div>
  );
}

export function PanelF({ s, ctl, refreshing }: PanelProps) {
  const f = s.results.protocol_v2;
  return (
    <PanelShell
      letter="F" title="Protocol v2: prove it's yours, reveal nothing"
      reqs={["SOP: zk-SNARK via Circom + SnarkJS", "Owner identity: Ed25519 (ECC)", "Fix for gap G1"]}
      claim="The full fix, end to end. The watermark key and signature are derived inside the circuit from a seed committed with Poseidon and bound to the owner's Ed25519 key. The threshold is enforced in-circuit, and the proof is bound to the suspect model and to the verifier's fresh nonce."
      stale={false} refreshing={refreshing}
      actions={<RunButton ctl={ctl} step="protocol_v2" primary />}
      notes={<Notes
        say={[
          "This is the protocol the project proposes, running for real: Circom circuit, Groth16 proof with SnarkJS, verified by our SDK.",
          "The verifier recomputes everything it can: the owner's signature, the registry timestamp, the claim's nonce, and the hash of the suspect model from its own copy of the file. A valid SNARK alone is never enough.",
          "The thief has the weights but not the seed: with their own seed the derived signature doesn't match, and they can't open my commitment.",
          "Overwriting is the honest limit: the thief can embed and register their own mark later, both proofs verify, and the earlier registry timestamp decides.",
        ]}
        caveats={[
          "Groth16 needs a trusted setup: we use the public PSE Perpetual Powers of Tau plus our own phase-2 contribution.",
          "Feature permutation removes the white-box mark unless the owner realigns first; model extraction (training a copy from outputs) is out of scope for a white-box mark (OWASP limitation L1).",
          "θ = 8/64 is indicative, not a calibrated false-positive rate.",
        ]}
      />}
    >
      {!f ? <Empty what="demo F" /> : <>
        <Card className="flag-good">
          <div className="hero-verdict">
            <Stamp ok={f.owner_proof.accepted} />
            <div className="copy">
              <div className="actions">
                <Verdict tone={f.owner_proof.accepted ? "good" : "bad"}>{f.owner_proof.accepted ? "Ownership verified" : "Rejected"}</Verdict>
                <Verdict tone="neutral">0 of {f.config.T} watermark bits revealed</Verdict>
              </div>
              <h3>The owner proves ownership in zero knowledge</h3>
              <p style={{ margin: 0, color: "var(--text-secondary)" }}>
                Circuit <span className="mono">{f.circuit}</span>: {f.config.T}-bit signature, accept with at most {f.config.max_err} bits wrong.
              </p>
              <div className="grid4" style={{ marginTop: 6 }}>
                <Stat label="Witness" value={secs(f.owner_proof.timing.witness_s)} />
                <Stat label="Prove" value={secs(f.owner_proof.timing.prove_s)} />
                <Stat label="Proof" value={bytes(f.owner_proof.proof_json_bytes)} caption="JSON; 3 curve points" />
                <Stat label="Owner's errors" value={`${f.owner_detection.errors}/${f.config.T}`} />
              </div>
            </div>
          </div>
          <h4 style={{ margin: "18px 0 10px", fontSize: 13, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-secondary)" }}>
            Every check the verifier ran
          </h4>
          <ul className="checks">
            {CHECKS.filter(([k]) => k in f.owner_proof.checks).map(([k, label]) => {
              const ok = f.owner_proof.checks[k];
              return (
                <li key={k}>
                  <span className={`tick ${ok ? "ok" : "no"}`} aria-hidden>{ok ? "✓" : "✕"}</span>
                  <span>{label}<span className="sr-only">: {ok ? "passed" : "failed"}</span></span>
                </li>
              );
            })}
          </ul>
        </Card>

        <div className="grid2">
          <Card title="F1 · The public registration" sub="Published at embedding time. It contains no secret.">
            <dl className="kv">
              <dt>Owner key</dt><dd className="hash">{short(f.owner_public_key, 24)} <span style={{ color: "var(--text-secondary)" }}>(Ed25519)</span></dd>
              <dt>Commitment</dt><dd className="hash">{short(f.commitment, 24)} <span style={{ color: "var(--text-secondary)" }}>(Poseidon)</span></dd>
              <dt>Registered</dt><dd>{when(f.registered_at)}</dd>
              <dt>Registry</dt><dd className="hash">{short(f.registry_public_key, 24)}</dd>
              <dt>Accuracy</dt><dd>{(f.accuracy.watermarked_v2 * 100).toFixed(2)}% with the watermark</dd>
            </dl>
          </Card>
          <Card title="F3 · The thief, with the stolen weights" sub="No seed, so no proof" flag="bad">
            <dl className="kv">
              <dt>Own seed + key</dt><dd>{f.thief.own_key}</dd>
              <dt>Owner's commitment</dt><dd>{f.thief.owner_commitment}</dd>
            </dl>
            <div style={{ marginTop: 12 }}>
              <Callout tone="good"><p><strong>No proof exists</strong> for someone who doesn't know the seed: the circuit derives the signature itself.</p></Callout>
            </div>
          </Card>
        </div>

        <Card title="F4 · A valid proof, used the wrong way" sub="Each misuse is rejected with its own reason">
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Misuse</th><th>Verdict</th><th>Reason</th></tr></thead>
              <tbody>{Object.entries(f.misuse).map(([name, v]) => (
                <tr key={name}>
                  <td><strong>{name}</strong></td>
                  <td>{v.accepted ? <Verdict tone="bad">Accepted</Verdict> : <Verdict tone="good">Rejected</Verdict>}</td>
                  <td style={{ color: "var(--text-secondary)" }}>{v.reasons[0] ?? ""}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Card>

        <div className="results">
          <Card title="F5 · Robustness, in zero knowledge" sub="Attack the model, then try to prove ownership">
            <div className="tablewrap">
              <table className="data">
                <thead><tr><th>Attack</th><th className="num">Accuracy</th><th className="num">Bits wrong</th><th>Proof</th></tr></thead>
                <tbody>{f.robustness.map((r) => (
                  <tr key={r.attack} className={r.proof_accepted ? undefined : "hl"}>
                    <td>{r.attack}</td>
                    <td className="num">{(r.accuracy * 100).toFixed(1)}%</td>
                    <td className="num">{r.errors}/{f.config.T}</td>
                    <td>{r.proof_accepted ? <Verdict tone="good">Verified</Verdict> : <Verdict tone="bad">No proof</Verdict>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </Card>
          <Card title="F6 · Overwriting and the dispute rule" sub="The thief embeds and registers their own mark later">
            <div className="tablewrap">
              <table className="data">
                <thead><tr><th>Party</th><th>Registered</th><th className="num">Bits wrong</th><th>Proof</th></tr></thead>
                <tbody>{f.overwrite_dispute.parties.map((p) => (
                  <tr key={p.party}>
                    <td><strong>{p.party}</strong></td>
                    <td className="mono">{when(p.registered_at)}</td>
                    <td className="num">{p.errors}/{f.config.T}</td>
                    <td>{p.proof_accepted ? <Verdict tone="good">Verified</Verdict> : <Verdict tone="bad">No proof</Verdict>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <div style={{ marginTop: 12 }}>
              <Callout tone="warn"><p>Both can prove on the overwritten copy, so the watermark alone can't settle it.
                <strong> The earliest valid registration wins: {f.overwrite_dispute.winner ?? "nobody"}.</strong></p></Callout>
            </div>
          </Card>
        </div>
      </>}
    </PanelShell>
  );
}
