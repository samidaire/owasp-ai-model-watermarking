import { useEffect, useState } from "react";
import type { ServerStep } from "../api";
import type { PageProps } from "../App";
import { Icon } from "../components/icons";
import { Callout, Empty, Verdict } from "../components/ui";
import { bytes, pct, secs, short, when } from "../format";
import { Stamp } from "../panels/PanelF";
import { RunButton } from "../panels/Shell";
import { modelVerdict, TestButton } from "../shell/ModelBar";
import { Link } from "../router";

/** The verifier's checks, in order (sdk/src/sigil/verify.py). */
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
/** Which check a recorded misuse trips, judged from its reason text. */
function failedCheck(reason: string): string | null {
  if (/nonce/i.test(reason)) return "public_nonce";
  if (/w_hash|different model/i.test(reason)) return "public_w_hash";
  if (/snark/i.test(reason)) return "snark_valid";
  if (/registry|receipt/i.test(reason)) return "receipt_valid";
  return null;
}

/** The live re-check behind each misuse button (demo/09_verify_live.py): same proof, one thing changed. */
const MISUSE_STEP: Record<string, ServerStep> = {
  "replayed for another claim": "verify_replay",
  "checked against a different model": "verify_model",
  "tampered proof bytes": "verify_tamper",
  "receipt from an untrusted registry": "verify_registry",
};

interface Proof { pi_a: string[]; pi_b: string[][]; pi_c: string[]; protocol: string; curve: string }
interface Onchain { verified: boolean; tampered_public_signal_verified: boolean; verify_gas: string; deploy_gas: string; chain_id: number; proof_pi_a0?: string }
const SIGNALS = ["pk_hash", "config_hash", "commitment", "w_hash", "nonce"];
const cut = (v: string) => (v.length > 16 ? `${v.slice(0, 7)}…${v.slice(-6)}` : v);

/** The selected model's test: verdict stamp, the numbers, and every check the verifier ran. */
function ModelVerdict({ s, ctl }: PageProps) {
  const m = ctl.models.find((x) => x.id === ctl.model);
  if (!m) return null;
  const r = s.results.model_tests?.[ctl.model];
  if (!r) return (
    <section className="box" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
      <h2 className="h-sm">Verdict for {m.label}</h2>
      <Empty what={m.label} action={<TestButton ctl={ctl} />} />
    </section>
  );
  const v = modelVerdict(r);
  const ok = r.verdict === "proven";
  const text = r.verdict === "proven"
    ? `The owner proved in zero knowledge that ${r.label} carries their watermark. The verifier learned 0 of the 64 watermark bits.`
    : r.verdict === "no_proof"
      ? `The owner's watermark isn't in ${r.label}: ${r.v2?.errors ?? "?"} of 64 bits read wrong (more than ${r.v2?.max_err ?? 8}). No valid proof can exist, so none was made.`
      : r.verdict === "unreadable" ? `This file can't be tested: ${r.error}.` : `The proof was rejected: ${r.proof?.reasons.join("; ")}.`;
  const rows: [string, boolean, string?][] = [];
  rows.push(["Watermarked layer readable (conv2, 288 values)", r.readable, r.readable ? undefined : r.error ?? undefined]);
  if (r.v2) rows.push([`Owner's mark present (at most ${r.v2.max_err} of 64 bits wrong)`, r.v2.accepted, `${r.v2.errors}/64`]);
  if (r.proof?.made) for (const [k, label] of CHECKS) { if (k in r.proof.checks) rows.push([label, r.proof.checks[k]]); }
  else if (r.v2) rows.push(["Zero-knowledge proof", false, "not possible"]);
  return (
    <div className="cols">
      <section className="box" aria-live="polite" style={{ flex: "1 1 440px", minWidth: 0, padding: 26, display: "flex", flexDirection: "column", alignItems: "center", gap: 12, textAlign: "center",
        background: ok ? "var(--caramel-soft)" : "color-mix(in oklab, var(--rust) 10%, var(--paper))" }}>
        <span className="eyebrow">Verdict for the model under test</span>
        <div key={r.tested_at + r.model} className={ok ? undefined : "shake"}><Stamp ok={ok} /></div>
        <h2 className="h-lg" style={{ fontSize: "clamp(28px, 2.8vw, 40px)" }}>{v.text}</h2>
        <p className="muted" style={{ margin: 0, maxWidth: 460 }}>{text}</p>
        <div className="actions" style={{ justifyContent: "center" }}>
          <span className="chip mono">{r.label}</span>
          <span className="chip mono">{r.accuracy === null ? "accuracy n/a" : `${pct(r.accuracy)} accuracy`}</span>
          {r.v1 && <span className="chip mono">v1 owner BER {r.v1.ber.toFixed(3)}</span>}
          {r.proof?.made && r.proof.timing && <span className="chip mono">prove {secs(r.proof.timing.prove_s)} · {bytes(r.proof.proof_bytes ?? 0)}</span>}
        </div>
        <div className="actions" style={{ justifyContent: "center", paddingTop: 4 }}><TestButton ctl={ctl} label="Test it again" /></div>
        <span className="muted" style={{ fontSize: 12 }}>Tested {when(r.tested_at)}</span>
      </section>
      <section className="box" style={{ flex: "1 1 380px", minWidth: 0, padding: 22, display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 className="h-sm">What was checked</h2>
        <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {rows.map(([label, pass, note]) => (
            <li key={label} style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <span className={`stp ${pass ? "ok" : "fail"}`} aria-hidden><Icon name={pass ? "check" : "x"} size={16} /></span>
              <span style={{ fontWeight: 600, fontSize: 14.5, flex: 1 }}>{label}<span className="sr-only">: {pass ? "passed" : "failed"}</span></span>
              {note && <span className="mono muted" style={{ fontSize: 12.5 }}>{note}</span>}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

export function Verify({ s, ctl }: PageProps) {
  const f = s.results.protocol_v2;
  const [proof, setProof] = useState<Proof | null>(null);
  const [pub, setPub] = useState<string[] | null>(null);
  const [onchain, setOnchain] = useState<Onchain | null>(null);
  const [mode, setMode] = useState<"off" | "on">("off");
  const [misuse, setMisuse] = useState<string | null>(null);

  // The real proof files from the last demo F run (served by the demo server under /results).
  const stamp = f?.registered_at + (f?.owner_proof.public_signals.nonce ?? "");
  useEffect(() => {
    let live = true;
    const get = (p: string) => fetch(`/results/protocol_v2/${p}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    Promise.all([get("proof.json"), get("public.json"), get("onchain.json")]).then(([a, b, c]) => {
      if (live) { setProof(a); setPub(b); setOnchain(c); }
    });
    return () => { live = false; };
  }, [stamp]);

  if (!f) return (
    <>
      <div className="pagehead"><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <span className="chip" style={{ alignSelf: "flex-start" }}>Verify ownership</span>
        <h1 className="display" style={{ margin: 0, fontSize: "clamp(40px, 4.4vw, 62px)" }}>Check the <span className="jw hlw">claim.</span></h1>
        <p className="muted" style={{ margin: 0, fontSize: 16, maxWidth: 640 }}>Pick a model above and test it: the owner proves ownership in zero knowledge and the verifier runs every check.</p>
      </div></div>
      <ModelVerdict s={s} ctl={ctl} />
      <div><span className="eyebrow">Demo F</span><h2 className="h-lg" style={{ fontSize: "clamp(26px, 2.6vw, 36px)", marginTop: 4 }}>The recorded claim, in detail</h2></div>
      <Empty what="demo F's claim" action={<RunButton ctl={ctl} step="protocol_v2" primary />} />
    </>
  );
  const shown = misuse ? f.misuse[misuse] : null;
  /** Show the verdict demo F recorded, and re-run that verification live so the console shows every check. */
  const pick = (k: string | null) => {
    setMisuse(k);
    const step: ServerStep = k ? MISUSE_STEP[k] ?? "verify_honest" : "verify_honest";
    if (!ctl.running && ctl.steps[step]) void ctl.run(step, {});
  };
  const ok = shown ? shown.accepted : f.owner_proof.accepted;
  const tripped = shown ? failedCheck(shown.reasons[0] ?? "") : null;
  const onchainCurrent = onchain && proof && onchain.proof_pi_a0 === proof.pi_a[0];

  return (
    <>
      <div className="pagehead">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span className="chip in" style={{ ["--i" as string]: 0, alignSelf: "flex-start" }}>Verify ownership</span>
          <h1 className="display in" style={{ ["--i" as string]: 1, margin: 0, fontSize: "clamp(40px, 4.4vw, 62px)" }}>
            Check the <span className="jw hlw">claim.</span>
          </h1>
          <p className="muted in" style={{ ["--i" as string]: 2, margin: 0, fontSize: 16, maxWidth: 640 }}>
            Pick a model above and test it: the owner proves ownership in zero knowledge and the verifier runs every check.
            Anyone can run this check with the public verification key; the watermark itself never leaves the owner.
          </p>
        </div>
      </div>

      <ModelVerdict s={s} ctl={ctl} />

      <div className="pagehead">
        <div><span className="eyebrow">Demo F</span><h2 className="h-lg" style={{ fontSize: "clamp(26px, 2.6vw, 36px)", marginTop: 4 }}>The recorded claim, in detail</h2></div>
        <div className="segbar" role="group" aria-label="Where to verify" style={{ flex: "0 1 320px" }}>
          <button type="button" aria-pressed={mode === "off"} onClick={() => setMode("off")}>Off-chain</button>
          <button type="button" aria-pressed={mode === "on"} onClick={() => setMode("on")}>On-chain</button>
        </div>
      </div>

      <div className="cols">
        <div style={{ flex: "1 1 520px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
          <section className="box" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
            <h2 className="h-sm">The claim</h2>
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(220px, 100%), 1fr))", gap: 14 }}>
              {[
                ["Model", "watermarked_v2.pt", "PyTorch · MNIST CNN"],
                ["Claimed owner", short(f.owner_public_key, 14), "Ed25519 public key"],
                ["Watermark commitment", short(f.commitment, 14), "Poseidon hash of the seed"],
                ["Registered", when(f.registered_at), "registry receipt"],
              ].map(([k, v, sub]) => (
                <div key={k} style={{ display: "flex", flexDirection: "column", gap: 5, padding: 14, border: "1.5px dashed color-mix(in oklab, var(--espresso) 28%, transparent)", borderRadius: 16 }}>
                  <dt className="eyebrow">{k}</dt>
                  <dd className="mono" style={{ margin: 0, fontWeight: 600, fontSize: 13.5, wordBreak: "break-all" }}>{v}</dd>
                  <dd className="muted" style={{ margin: 0, fontSize: 12.5 }}>{sub}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="codebox">
            <div className="bar"><i /><i /><i /><span className="mono" style={{ marginLeft: 10, fontSize: 13, color: "var(--latte)" }}>proof.json · public.json</span>
              <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}><span className="chip" style={{ minHeight: 26, background: "var(--caramel)" }}>groth16</span><span className="chip" style={{ minHeight: 26 }}>bn128</span></span>
            </div>
            <div className="body" style={{ fontSize: 12.5 }}>
              {proof ? <>
                <div>{"{"}</div>
                <div>  <span className="tk-s">"pi_a"</span>: [<span className="tk-k">"{cut(proof.pi_a[0])}"</span>, <span className="tk-k">"{cut(proof.pi_a[1])}"</span>],</div>
                <div>  <span className="tk-s">"pi_b"</span>: [[<span className="tk-k">"{cut(proof.pi_b[0][0])}"</span>, <span className="tk-k">"{cut(proof.pi_b[0][1])}"</span>], …],</div>
                <div>  <span className="tk-s">"pi_c"</span>: [<span className="tk-k">"{cut(proof.pi_c[0])}"</span>, <span className="tk-k">"{cut(proof.pi_c[1])}"</span>],</div>
                <div>  <span className="tk-s">"publicSignals"</span>: [</div>
                {(pub ?? []).map((v, i) => (
                  <div key={i}>    <span className="tk-k">"{cut(String(v))}"</span>{i < (pub?.length ?? 0) - 1 ? "," : " "}  <span className="tk-c">// {SIGNALS[i]}</span></div>
                ))}
                <div>  ]</div>
                <div>{"}"}</div>
              </> : <div className="tk-c">// loading the proof files…</div>}
            </div>
          </section>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            Proof {bytes(f.owner_proof.proof_json_bytes)} as JSON (3 curve points) · witness {secs(f.owner_proof.timing.witness_s)} · prove {secs(f.owner_proof.timing.prove_s)} · circuit <span className="mono">{f.circuit}</span>
          </p>
          <section className="box" style={{ padding: 22, display: "flex", flexDirection: "column", gap: 12 }}>
            <h2 className="h-sm">What gets checked</h2>
            <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
              {CHECKS.filter(([k]) => k in f.owner_proof.checks).map(([k, label]) => {
                const pass = tripped ? k !== tripped : f.owner_proof.checks[k];
                return (
                  <li key={k} style={{ display: "flex", gap: 12, alignItems: "center" }}>
                    <span className={`stp ${pass ? "ok" : "fail"}`} aria-hidden><Icon name={pass ? "check" : "x"} size={16} /></span>
                    <span style={{ fontWeight: 600, fontSize: 14.5 }}>{label}<span className="sr-only">: {pass ? "passed" : "failed"}</span></span>
                  </li>
                );
              })}
            </ol>
          </section>
        </div>

        <div style={{ flex: "1 1 440px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
          <section className="box" aria-live="polite" style={{ padding: 26, display: "flex", flexDirection: "column", alignItems: "center", gap: 14, textAlign: "center",
            background: ok ? "var(--caramel-soft)" : "color-mix(in oklab, var(--rust) 10%, var(--paper))" }}>
            <div key={misuse ?? "honest"} className={ok ? undefined : "shake"}><Stamp ok={ok} /></div>
            <h2 className="h-lg" style={{ fontSize: "clamp(30px, 3vw, 42px)" }}>{ok ? "Ownership verified" : "Proof rejected"}</h2>
            <p className="muted" style={{ margin: 0, maxWidth: 440 }}>
              {ok ? "The owner of watermarked_v2.pt is proven without revealing a single watermark bit."
                : `${misuse}: ${shown?.reasons[0] ?? ""}.`}
            </p>
            {ok && (mode === "off"
              ? <div className="actions" style={{ justifyContent: "center" }}><Verdict tone="good">0 of {f.config.T} bits revealed</Verdict><Verdict tone="neutral">SnarkJS, off-chain</Verdict></div>
              : onchain && <div className="actions" style={{ justifyContent: "center" }}>
                  <Verdict tone={onchain.verified ? "good" : "bad"}>{onchain.verified ? "Verified on a local EVM" : "Not verified on-chain"}</Verdict>
                  <Verdict tone="neutral">{Number(onchain.verify_gas).toLocaleString("en-US")} gas</Verdict>
                </div>)}
            {!ok && <div className="actions" style={{ justifyContent: "center" }}><Verdict tone="neutral">Recorded by demo F's verifier (SnarkJS, off-chain)</Verdict></div>}
            {ok && mode === "on" && onchain && (
              <p className="muted" style={{ margin: 0, fontSize: 13 }}>
                Solidity verifier exported by SnarkJS, deployed on Hardhat's in-process chain {onchain.chain_id}: deploy {Number(onchain.deploy_gas).toLocaleString("en-US")} gas;
                a tampered public signal {onchain.tampered_public_signal_verified ? "verified (!)" : "is rejected"}.
                {!onchainCurrent && " This on-chain check was made for an earlier proof; re-run it after demo F."}
              </p>
            )}
            <div className="actions" style={{ justifyContent: "center", paddingTop: 4 }}>
              {misuse
                ? <button type="button" className="btn primary" onClick={() => pick(null)}>Back to the honest proof</button>
                : <RunButton ctl={ctl} step="verify_honest" primary />}
              <RunButton ctl={ctl} step="protocol_v2" hint="Re-run demo F: a fresh claim, proof and verification" />
            </div>
          </section>

          <section className="box" style={{ padding: 22, display: "flex", flexDirection: "column", gap: 14 }}>
            <h2 className="h-sm">Try a misuse</h2>
            <p className="muted" style={{ margin: "-6px 0 0", fontSize: 13.5 }}>Each button changes one thing about the saved proof and runs the verifier on it again: the console shows every check.</p>
            <div className="actions">
              {Object.keys(f.misuse).map((k) => (
                <button key={k} type="button" className="btn" aria-pressed={misuse === k}
                  style={misuse === k ? { background: "var(--espresso)", color: "var(--paper)" } : undefined}
                  onClick={() => pick(misuse === k ? null : k)}>{k}</button>
              ))}
            </div>
          </section>
        </div>
      </div>

      <Callout tone="good">
        <p><strong>A valid zk-SNARK alone is never enough.</strong> The verifier recomputes the suspect model's hash from its own copy of the file,
          checks the owner's signature and the registry timestamp, and insists on its own fresh nonce. <Link to="/app/demo/F">See demo F</Link> for the thief and the overwrite dispute.</p>
      </Callout>
    </>
  );
}
