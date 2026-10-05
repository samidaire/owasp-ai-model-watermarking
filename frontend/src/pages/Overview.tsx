import type { PageProps } from "../App";
import { TITLE_OF } from "../App";
import type { ConsoleJob } from "../components/Console";
import { Icon } from "../components/icons";
import { Verdict } from "../components/ui";
import { RunButton } from "../panels/Shell";
import { bytes, pct, secs, short, when } from "../format";
import { Link } from "../router";
import { panelStatus } from "../stale";
import { DEMOS } from "./Demos";

interface Event { at: string; title: string; detail: string; icon: string; tone: "accent" | "plain" | "bad" }

export function Overview({ s, ctl, job }: PageProps & { job: ConsoleJob | null }) {
  const r = s.results;
  const t = r.train;
  const f = r.protocol_v2;
  const d2 = r.committed_seed?.d2;
  const attacks = (r.attacks?.rows ?? []).filter((x) => x.family !== "baseline");
  const survived = attacks.filter((x) => x.survives).length;
  const fresh = DEMOS.filter((d) => panelStatus(d.key, s) === "fresh").length;
  const theta = t?.threshold ?? 0.125;
  const nullsOk = (t?.nulls ?? []).every((n) => n.owner_ber > theta);

  const events: Event[] = [];
  if (f) {
    events.push({ at: f.registered_at, title: "Registry receipt issued (protocol v2)", detail: `owner ${short(f.owner_public_key, 10)} · commitment ${short(f.commitment, 10)}`, icon: "key", tone: "plain" });
    const thief = f.overwrite_dispute.parties.find((p) => p.party === "thief");
    if (thief) events.push({ at: thief.registered_at, title: "Later registration on an overwritten copy", detail: `dispute rule: earliest valid registration wins → ${f.overwrite_dispute.winner}`, icon: "x", tone: "bad" });
  }
  if (t) events.push({ at: t.timestamp_utc, title: "Commitment published (protocol v1)", detail: `SHA-256 ${short(t.commitment, 14)} · ${t.owner_id}`, icon: "lock", tone: "plain" });
  if (s.job) {
    const j = s.job;
    events.push({ at: new Date(j.started * 1000).toISOString(), title: `${TITLE_OF[j.step] ?? j.step} ${j.running ? "running" : j.code === 0 ? "finished" : j.cancelled ? "cancelled" : "failed"}`,
      detail: `${j.lines} console lines${s.mode === "simulate" ? " · replayed" : ""}`, icon: "play", tone: j.code === 0 || j.running ? "accent" : "bad" });
  }
  events.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));

  const runningName = ctl.running ? TITLE_OF[ctl.running] : null;
  const shownCount = DEMOS.filter((d) => panelStatus(d.key, s) !== "missing").length;
  const nothing = shownCount === 0;

  return (
    <>
      <div className="pagehead">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span className="chip in" style={{ ["--i" as string]: 0, alignSelf: "flex-start" }}>Overview</span>
          <h1 className="display in" style={{ ["--i" as string]: 1, margin: 0, fontSize: "clamp(40px, 4.4vw, 62px)" }}>
            Welcome back, <span className="jw hlw">Team Sigil.</span>
          </h1>
          <p className="muted in" style={{ ["--i" as string]: 2, margin: 0, fontSize: 16, maxWidth: 640 }}>
            {nothing
              ? <>Nothing has run yet. Press <strong>Run all live</strong> for demos A–E, then <strong>Run demo F live</strong> for the zero-knowledge proof. Each page fills in as its run finishes.</>
              : <>{shownCount} of {DEMOS.length} demos have run; {fresh} up to date.</>}
          </p>
        </div>
        <div className="actions">
          {nothing ? <>
            <RunButton ctl={ctl} step="all" primary />
            <RunButton ctl={ctl} step="protocol_v2" />
          </> : <>
            <Link to="/app/embed" className="btn">Embed watermark</Link>
            <Link to="/app/verify" className="btn primary">Verify ownership <Icon name="arrow" size={18} /></Link>
          </>}
        </div>
      </div>

      <div className="statgrid">
        <div className="box lift pop wig stile" style={{ ["--i" as string]: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span className="eyebrow">Groth16 proof</span><span className="ibub"><Icon name="code" /></span></div>
          <div className="big">{f ? secs(f.owner_proof.timing.prove_s) : "—"}</div>
          <div className="muted" style={{ fontSize: 14 }}>{f ? `to prove · ${bytes(f.owner_proof.proof_json_bytes)} proof · ${f.owner_proof.accepted ? "verified" : "rejected"}` : "run demo F"}</div>
        </div>
        <div className="box lift pop wig stile" style={{ ["--i" as string]: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span className="eyebrow">Accuracy cost</span><span className="ibub"><Icon name="models" /></span></div>
          <div className="big">{t ? ((t.models.watermarked.accuracy - t.models.clean.accuracy) * 100).toFixed(2) : "—"}<small> pp</small></div>
          <div className="muted" style={{ fontSize: 14 }}>{t ? `${pct(t.models.clean.accuracy)} → ${pct(t.models.watermarked.accuracy)} with the watermark` : "run demo A"}</div>
        </div>
        <div className="box lift pop wig stile" style={{ ["--i" as string]: 2, background: "var(--caramel)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span className="eyebrow" style={{ color: "var(--espresso)" }}>Forgeries accepted</span><span className="ibub" style={{ background: "var(--paper)" }}><Icon name="verify" /></span></div>
          <div className="big">{d2 ? d2.accepted : "—"}<small>/{d2 ? d2.tries.toLocaleString("en-US") : "—"}</small></div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>thief's seed search against the committed seed</div>
        </div>
        <div className="box lift pop wig stile" style={{ ["--i" as string]: 3, background: "var(--espresso)", color: "var(--paper)", boxShadow: "5px 5px 0 var(--caramel)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span className="eyebrow" style={{ color: "var(--sand)" }}>Attacks survived</span><span className="ibub" style={{ background: "var(--caramel)", color: "var(--espresso)" }}><Icon name="bolt" /></span></div>
          <div className="big">{attacks.length ? survived : "—"}<small>/{attacks.length || "—"}</small></div>
          <div style={{ height: 12, border: "2px solid var(--paper)", borderRadius: 999, overflow: "hidden" }}>
            <div style={{ width: `${attacks.length ? (survived / attacks.length) * 100 : 0}%`, height: "100%", background: "var(--caramel)", transformOrigin: "left", animation: "fillx 1.1s var(--spring) backwards .3s" }} />
          </div>
        </div>
      </div>

      <div className="cols">
        <section className="box" style={{ flex: "2 1 620px", minWidth: 0, padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <h2 className="h-sm">Models</h2>
            <span className="muted" style={{ fontSize: 13 }}>Checkpoints in demo/ckpt · threshold θ = {theta.toFixed(3)}</span>
          </div>
          <div className="tablewrap">
            <table className="tbl">
              <thead><tr><th>Model</th><th>Protocol</th><th>Bits</th><th>Accuracy</th><th>Owner BER</th><th>Status</th><th><span className="sr-only">Open</span></th></tr></thead>
              <tbody>
                {t && <tr>
                  <td><ModelName name="watermarked" file="watermarked.pt" /></td>
                  <td className="muted">v1 · SHA-256 seed</td><td className="mono">64</td>
                  <td className="mono">{pct(t.models.watermarked.accuracy)}</td><td className="mono">{t.models.watermarked.owner_ber.toFixed(3)}</td>
                  <td>{t.models.watermarked.owner_ber <= theta ? <Verdict tone="good">Ownership shown</Verdict> : <Verdict tone="bad">No match</Verdict>}</td>
                  <td><Link to="/app/demo/A" className="rowgo">Demo A <Icon name="arrow" size={16} /></Link></td>
                </tr>}
                {f && <tr>
                  <td><ModelName name="watermarked_v2" file="v2/watermarked_v2.pt" tint /></td>
                  <td className="muted">v2 · Poseidon + Groth16</td><td className="mono">{f.config.T}</td>
                  <td className="mono">{pct(f.accuracy.watermarked_v2)}</td><td className="mono">{f.owner_detection.ber.toFixed(3)}</td>
                  <td>{f.owner_proof.accepted ? <Verdict tone="good">ZK-verified</Verdict> : <Verdict tone="bad">Rejected</Verdict>}</td>
                  <td><Link to="/app/verify" className="rowgo">Verify <Icon name="arrow" size={16} /></Link></td>
                </tr>}
                {t && <tr>
                  <td><ModelName name="clean" file="clean.pt" /></td>
                  <td className="muted">never watermarked</td><td className="mono">—</td>
                  <td className="mono">{pct(t.models.clean.accuracy)}</td><td className="mono">{t.models.clean.owner_ber.toFixed(3)}</td>
                  <td><Verdict tone="neutral">Not claimed (correct)</Verdict></td>
                  <td><Link to="/app/demo/A" className="rowgo">Demo A <Icon name="arrow" size={16} /></Link></td>
                </tr>}
                {!t && !f && <tr><td colSpan={7} className="muted" style={{ fontWeight: 400 }}>No models checked yet: run demo A (<strong>Run all live</strong>) or demo F.</td></tr>}
                {t && t.nulls.length > 0 && <tr>
                  <td><ModelName name={`null models ×${t.nulls.length}`} file="null_0 … null_3.pt" tint /></td>
                  <td className="muted">never watermarked</td><td className="mono">—</td>
                  <td className="mono">{pct(Math.min(...t.nulls.map((n) => n.accuracy)))}+</td>
                  <td className="mono">{Math.min(...t.nulls.map((n) => n.owner_ber)).toFixed(3)}–{Math.max(...t.nulls.map((n) => n.owner_ber)).toFixed(3)}</td>
                  <td>{nullsOk ? <Verdict tone="neutral">Not claimed (correct)</Verdict> : <Verdict tone="bad">False claim</Verdict>}</td>
                  <td><Link to="/app/demo/A" className="rowgo">Demo A <Icon name="arrow" size={16} /></Link></td>
                </tr>}
              </tbody>
            </table>
          </div>
        </section>

        <div style={{ flex: "1 1 320px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
          <section className="box" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 20, background: "var(--sand)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2 className="h-sm">Proof pipeline</h2>
              <span className="chip"><span className="dot pulse" style={{ color: "var(--caramel)" }} />{runningName ? "Running" : "Protocol v2"}</span>
            </div>
            <div style={{ position: "relative" }}>
              <div className="track" style={{ position: "absolute", left: 32, right: 32, top: 20 }}><span className="traveler" /></div>
              <div style={{ position: "relative", display: "flex", justifyContent: "space-between" }}>
                {(["Embed", "Commit", "Prove", "Verify"] as const).map((n, i) => {
                  const done = i < 3 ? Boolean(f) : Boolean(f?.owner_proof.accepted);
                  return (
                    <div key={n} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, width: 64 }}>
                      <span className="ibub" style={{ borderRadius: "50%", background: done ? "var(--espresso)" : "var(--paper)", color: done ? "var(--paper)" : "var(--espresso)" }}>
                        <Icon name={done ? "check" : "play"} />
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 700 }}>{n}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13 }}>
                <span className="mono" style={{ fontWeight: 600 }}>{runningName ?? "watermarked_v2 · Groth16"}</span>
                <span className="mono">{runningName ? "…" : f?.owner_proof.accepted ? "verified" : "—"}</span>
              </div>
              <div style={{ height: 16, border: "var(--line)", borderRadius: 999, overflow: "hidden", background: "var(--paper)" }}>
                <div className={runningName ? "stripes" : undefined} style={{ width: runningName ? "60%" : f ? "100%" : "0%", height: "100%", backgroundColor: "var(--caramel)", borderRight: "var(--line)", transition: "width .6s var(--spring)" }} />
              </div>
              <span className="muted" style={{ fontSize: 13 }}>{runningName ? `${runningName}: live output in the console below` : f ? "Verified off-chain with SnarkJS; also verifies on a local EVM" : "Run demo F to generate and verify a proof"}</span>
            </div>
          </section>

          <section className="box" style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
            <h2 className="h-sm">Audit log</h2>
            {events.length === 0 && <p className="muted" style={{ margin: 0 }}>Nothing yet.</p>}
            <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 14 }}>
              {events.map((e, i) => (
                <li key={i} className="in wig" style={{ ["--i" as string]: i + 1, display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <span className="ibub" style={{ width: 38, height: 38, borderRadius: 12, background: e.tone === "bad" ? "var(--rust)" : e.tone === "accent" ? "var(--caramel)" : "var(--sand)", color: e.tone === "bad" ? "#fff" : "var(--espresso)" }}>
                    <Icon name={e.icon} size={18} />
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 14.5 }}>{e.title}</div>
                    <div className="muted mono" style={{ fontSize: 12, wordBreak: "break-word" }}>{e.detail}</div>
                  </div>
                  <span className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{when(e.at)}</span>
                </li>
              ))}
            </ol>
            {job && !job.info.running && <p className="muted" style={{ margin: 0, fontSize: 13 }}>Last run this session: {job.title}.</p>}
          </section>
        </div>
      </div>
    </>
  );
}

function ModelName({ name, file, tint }: { name: string; file: string; tint?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span className="ibub" style={{ width: 38, height: 38, borderRadius: 12, background: tint ? "var(--sand)" : "var(--caramel-soft)" }}><Icon name="file" size={18} /></span>
      <div><div className="mono" style={{ fontWeight: 600, fontSize: 14 }}>{name}</div><div className="muted" style={{ fontSize: 12.5 }}>{file}</div></div>
    </div>
  );
}
