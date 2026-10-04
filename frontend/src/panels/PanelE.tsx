import { isStale, type EzklSummary } from "../api";
import { Callout, Card, Empty, Notes, Verdict } from "../components/ui";
import { bytes, secs, short } from "../format";
import { PanelShell, RunButton, type PanelProps } from "./Shell";

const HASHED_WARNING =
  "Re-run the Poseidon-committed proofs?\n\n" +
  "Takes about 3 minutes and writes a ~10 GB temporary proving key per proof (deleted afterwards). " +
  "The precomputed results are shown otherwise.\n\nContinue?";

const score = (e: EzklSummary) => e.public_outputs?.[0]?.[0] ?? "?";
const poseidon = (e: EzklSummary | null) => e?.param_commitment_poseidon?.[0]?.[0] ?? null;

function ProofCard({ title, sub, e, flag }: { title: string; sub: string; e: EzklSummary; flag: "good" | "bad" }) {
  return (
    <Card title={title} sub={sub} flag={flag}>
      <div className="actions" style={{ marginBottom: 12 }}>
        <Verdict tone={e.verified ? (flag === "good" ? "good" : "bad") : "warn"}>Proof verified: {String(e.verified)}</Verdict>
        <Verdict tone="neutral">Public score {Number(score(e)).toFixed(0)}/64</Verdict>
      </div>
      <dl className="kv">
        <dt>Prove</dt><dd>{secs(e.seconds.prove)}</dd>
        <dt>Verify</dt><dd>{secs(e.seconds.verify)}</dd>
        <dt>Proof size</dt><dd>{bytes(e.proof_bytes)}</dd>
        <dt>Proving key</dt><dd>{bytes(e.pk_bytes)}</dd>
        <dt>Peak RAM</dt><dd>{bytes(e.peak_rss_bytes)} <span style={{ color: "var(--text-muted)" }}>(sampled)</span></dd>
        <dt>Circuit</dt><dd>logrows {e.logrows} · Halo2/KZG · SRS {e.srs}</dd>
      </dl>
    </Card>
  );
}

export function PanelE({ s, ctl, refreshing }: PanelProps) {
  const z = s.results.ezkl;
  const vk = s.results.vk_crosscheck;
  const po = poseidon(z.hashed_owner);
  const staleE = [z.private_owner?.commitment, z.private_thief?.commitment, vk?.commitment, z.hashed_owner?.commitment]
    .some((c) => isStale(c, s.commitment));
  const literature = [
    { name: "ZKROWNN, CIFAR-10 CNN (128 GB machine)", prove: "11.2 s", verify: "1 ms", proof: "127 B", pk: "117 MB", ram: "n/a" },
    { name: "RoSeMary decoder", prove: "7.15 s", verify: "118.6 ms", proof: "17.1 KB", pk: "n/a", ram: "2.6 GB" },
  ];

  return (
    <PanelShell
      letter="E" title="Zero-knowledge proofs" reqs={["OWASP project objective: ZK ownership verification", "Gap G1 · RQ3"]}
      claim="EZKL (Halo2/KZG) proves the watermark-extraction statement with the key and signature kept private and the suspect model's weights public: 'I know a key and signature such that all 64 bits agree.'"
      stale={staleE} refreshing={refreshing}
      actions={<>
        <RunButton ctl={ctl} step="zk" label="Run E1 + E2 live" primary hint="Owner proof, thief proof, VK cross-check (~10 s)" />
        <RunButton ctl={ctl} step="zk_hashed" label="Re-run E3…" confirm={HASHED_WARNING} />
      </>}
      notes={<Notes
        say={[
          "This is a real zero-knowledge proof on my 32 GB machine: the key and signature are private, the suspect's weights are public.",
          "Without a commitment, the thief's forged proof verifies under my own verification key. The verifier literally cannot tell us apart. That is gap G1, demonstrated cryptographically.",
          "Commit inside the proof (Poseidon hash of the private parameters) and the thief is rejected.",
          "The cost jump from logrows 15 to 20 is the RQ3 trade-off I will optimise.",
        ]}
        caveats={[
          "E3 commits to the key and signature directly: the D1 level plus a timestamp. Deriving them from the seed inside the circuit (D2 level) is Phase 3.",
          "E3's Poseidon commitment is not yet linked to demo A's SHA-256 seed commitment, and a real commitment must also pin the circuit's quantisation settings.",
          "EZKL ships no open-source licence file (gap G5): research and demo use only.",
        ]}
      />}
    >
      {!z.private_owner || !z.private_thief ? <Empty what="demo E" /> : <>
        <h3 style={{ fontSize: 16 }}>E1 · Proofs without a commitment</h3>
        <div className="grid2">
          <ProofCard title="Owner: real key" sub="Private key + signature; public suspect weights" e={z.private_owner} flag="good" />
          <ProofCard title="Thief: forged key, same circuit" sub="Demo C's counterfeit key, margins raised by rejection sampling" e={z.private_thief} flag="bad" />
        </div>

        {vk && (
          <Card title="E2 · The thief's proof, checked against the owner's verification key" flag="bad">
            <dl className="kv">
              <dt>Owner's VK</dt><dd className="hash">{vk.owner_vk}</dd>
              <dt>Thief's VK</dt><dd className="hash">{vk.thief_vk} {vk.identical && <Verdict tone="warn">identical</Verdict>}</dd>
              <dt>Result</dt><dd>{vk.thief_verified_under_owner_vk
                ? <Verdict tone="bad">Thief's proof verified under the owner's VK</Verdict>
                : <Verdict tone="good">Rejected</Verdict>}</dd>
            </dl>
            <div style={{ marginTop: 12 }}>
              <Callout tone="bad"><p><strong>Without a published commitment, the verifier cannot tell owner and thief apart.</strong></p></Callout>
            </div>
          </Card>
        )}

        <h3 style={{ fontSize: 16, marginTop: 8 }}>E3 · Proofs with a Poseidon commitment (precomputed)</h3>
        {!z.hashed_owner || !z.hashed_thief ? <Empty what="E3 (run Re-run E3)" /> : <>
          <Card title="Commitment checked by the verifier"
            sub="Owner's Poseidon commitment: in the protocol, published at embedding time; in this demo, taken from the owner's run">
            <p className="hash" style={{ margin: "0 0 12px" }}>{po}</p>
            <div className="tablewrap">
              <table className="data">
                <thead><tr><th>Prover</th><th>Proof verifies</th><th>Public Poseidon hash of private params</th><th>Verifier decision</th></tr></thead>
                <tbody>{([["owner", z.hashed_owner], ["thief", z.hashed_thief]] as const).map(([who, e]) => {
                  const h = poseidon(e);
                  const accept = e.verified && h === po;
                  return (
                    <tr key={who} className={accept ? undefined : "hl"}>
                      <td>{who}</td>
                      <td>{String(e.verified)}</td>
                      <td className="mono">{short(h, 20)}</td>
                      <td>{accept ? <Verdict tone="good">Accept</Verdict> : <Verdict tone="bad">Reject: hash ≠ owner's commitment</Verdict>}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
            <div style={{ marginTop: 12 }}>
              <Callout tone="warn"><p><strong>Scope:</strong> this commits to the key and signature directly (D1 level). A thief who fits a key after the theft
                and publishes their own hash is stopped only by timestamp ordering. Deriving them from the seed inside the proof (D2) is Phase 3.</p></Callout>
            </div>
          </Card>

          <Card title="What committing costs (RQ3)" sub="Measured on this machine. Literature rows are orders of magnitude only: different circuits, proof systems and hardware.">
            <div className="tablewrap">
              <table className="data">
                <thead><tr><th>Workload</th><th className="num">Prove</th><th className="num">Verify</th><th className="num">Proof</th><th className="num">Proving key</th><th className="num">Peak RAM</th></tr></thead>
                <tbody>
                  {([["Uncommitted, logrows " + z.private_owner.logrows, z.private_owner], ["Poseidon-committed, logrows " + z.hashed_owner.logrows, z.hashed_owner]] as const).map(([name, e]) => (
                    <tr key={name}>
                      <td><strong>{name}</strong> <span style={{ color: "var(--text-muted)" }}>(this PC)</span></td>
                      <td className="num">{secs(e.seconds.prove)}</td><td className="num">{secs(e.seconds.verify)}</td>
                      <td className="num">{bytes(e.proof_bytes)}</td><td className="num">{bytes(e.pk_bytes)}</td>
                      <td className="num">{bytes(e.peak_rss_bytes)} <span style={{ color: "var(--text-muted)" }}>(sampled)</span></td>
                    </tr>
                  ))}
                  {literature.map((l) => (
                    <tr key={l.name} style={{ color: "var(--text-secondary)" }}>
                      <td><em>{l.name}</em></td><td className="num">{l.prove}</td><td className="num">{l.verify}</td>
                      <td className="num">{l.proof}</td><td className="num">{l.pk}</td><td className="num">{l.ram}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>}
      </>}
    </PanelShell>
  );
}
