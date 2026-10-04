import { Icon, Logo } from "../components/icons";
import { Link } from "../router";

const SPARK = "M12 1.5l2.6 7.9 7.9 2.6-7.9 2.6L12 22.5l-2.6-7.9L1.5 12l7.9-2.6z";
const MARQUEE = ["Embed", "Commit", "Prove", "Verify", "Survive pruning", "Survive quantization", "Survive fine-tuning"];

/** The hero's weight grid: deterministic shades, with the watermark-carrying cells pulsing. */
const CELLS = (() => {
  const shades = ["#EFE3D3", "#E3D0B9", "#D4B999", "#C2A07E", "#A98466", "#8E6A52"];
  let seed = 11;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const marks = new Set([4, 15, 21, 30, 38, 45, 52, 59, 67, 74, 80, 89, 95, 102]);
  return Array.from({ length: 108 }, (_, i) => {
    const shade = shades[Math.floor(rnd() * shades.length)];
    return { mark: marks.has(i), bg: marks.has(i) ? "var(--caramel)" : shade, i: (i % 12) + Math.floor(i / 12) };
  });
})();

const STEPS = [
  { n: "01", title: "Embed", icon: "embed", rot: "-1.4deg", bg: "var(--paper)", chips: ["PyTorch", "TensorFlow", "ONNX"],
    text: "A secret seed picks the key and the signature. Training nudges one layer's weights until they spell the signature out. Accuracy barely moves." },
  { n: "02", title: "Commit", icon: "key", rot: "1.2deg", bg: "var(--sand)", chips: ["Poseidon", "Ed25519"],
    text: "The seed is committed with Poseidon and bound to the owner's Ed25519 key, then timestamped by a registry. The seed never leaves the owner." },
  { n: "03", title: "Prove", icon: "code", rot: "-0.8deg", bg: "var(--caramel-soft)", chips: ["Circom", "SnarkJS"],
    text: "A Circom circuit re-derives the key and signature from the seed and checks the suspect's weights. SnarkJS turns that into a Groth16 proof." },
  { n: "04", title: "Verify", icon: "verify", rot: "1.6deg", bg: "var(--espresso)", chips: ["Off-chain", "On-chain"],
    text: "Anyone with the public verification key checks the proof in milliseconds, off-chain or on an EVM. Zero watermark bits are revealed." },
];

const ATTACKS = [
  { name: "Pruning", icon: "scissors", text: "Zeroes out the smallest weights to slim the model down.", chip: "20–95% sparsity", indent: "0px" },
  { name: "Quantization", icon: "stairs", text: "Rounds every weight down to 8 or 4 bits.", chip: "int8 · int4", indent: "clamp(0px, 3vw, 36px)" },
  { name: "Fine-tuning", icon: "sliders", text: "Keeps training on new data, hoping the mark washes out.", chip: "FTAL · RTAL", indent: "clamp(0px, 1vw, 12px)" },
  { name: "Overwriting", icon: "copy", text: "Embeds the thief's own mark on top. The registry timestamp settles who was first.", chip: "earliest wins", indent: "clamp(0px, 4vw, 48px)" },
  { name: "Permutation", icon: "refresh", text: "Reorders channels for free. The honest limit: the owner must realign first.", chip: "known gap", indent: "clamp(0px, 2vw, 20px)", warn: true },
];

const TEAM = [
  { initials: "SD", name: "Sami Daire", roll: "231813", role: "Project lead · ZK & verification", bg: "var(--caramel)", delay: "0s",
    text: "Designs the Circom circuits, sets up SnarkJS verification and holds the whole system together." },
  { initials: "MA", name: "Mohamed Ansari", roll: "231803", role: "AI & watermarking", bg: "var(--latte)", delay: "-3s",
    text: "Builds the embedding and detection algorithms in PyTorch and TensorFlow, then attacks them in the Robustness lab." },
  { initials: "AS", name: "Arfat Shaikh", roll: "231846", role: "Frontend & integration", bg: "var(--sand)", delay: "-6s",
    text: "Builds this React dashboard, wires it to the backend APIs and packages the Python SDK." },
  { initials: "YB", name: "Yash Bandiwadekar", roll: "231810", role: "Backend developer", bg: "var(--cocoa)", delay: "-4.5s", light: true,
    text: "Builds the backend services, the demo server and the APIs for watermark tracking and verification history." },
];

export function Landing() {
  return (
    <div className="landing">
      <header className="lnav">
        <a className="brandlink" href="#top"><Logo size={38} /><span className="display" style={{ fontSize: 30, letterSpacing: "-0.04em" }}>sigil</span></a>
        <nav aria-label="Primary" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 28 }}>
          <a className="nlink" href="#how">How it works</a>
          <a className="nlink" href="#robust">Robustness</a>
          <a className="nlink" href="#sdk">SDK</a>
          <a className="nlink" href="#team">Team</a>
        </nav>
        <Link to="/app" className="btn dark">Open dashboard <Icon name="arrow" size={18} /></Link>
      </header>

      {/* HERO */}
      <section id="top" style={{ maxWidth: 1240, margin: "0 auto", padding: "36px clamp(16px, 4vw, 40px) 104px", display: "flex", flexWrap: "wrap", alignItems: "center", gap: 56 }}>
        <div style={{ flex: "1 1 520px", minWidth: 0, display: "flex", flexDirection: "column", gap: 28 }}>
          <span className="chip in" style={{ ["--i" as string]: 0, alignSelf: "flex-start" }}><span className="dot pulse" style={{ color: "var(--caramel)" }} />Final-year project · Cybersecurity × AI</span>
          <h1 className="display" style={{ margin: 0, fontSize: "clamp(54px, 7.6vw, 112px)" }}>
            <span>Prove</span> <span>it's</span>{" "}
            <span className="word-in"><span className="jw hlw">yours.</span></span>{" "}
            <span>Reveal</span>{" "}
            <span style={{ position: "relative", display: "inline-block" }}>nothing.
              <svg className="squiggle" viewBox="0 0 300 30" preserveAspectRatio="none" aria-hidden><path d="M4 18 Q 22 4 40 18 T 76 18 T 112 18 T 148 18 T 184 18 T 220 18 T 256 18 T 296 16" /></svg>
            </span>
          </h1>
          <p className="in" style={{ ["--i" as string]: 3, margin: 0, maxWidth: 560, fontSize: 19, lineHeight: 1.55, color: "var(--text-secondary)" }}>
            Sigil hides a cryptographic watermark inside your neural network's weights, then proves you own it with a zk-SNARK.
            Anyone can check the proof. Nobody learns the mark.
          </p>
          <div className="in actions" style={{ ["--i" as string]: 4, gap: 14 }}>
            <Link to="/app/embed" className="btn primary lg">Watermark a model <Icon name="arrow" size={18} /></Link>
            <a className="btn lg" href="#how">See how the proof works</a>
          </div>
          <div className="in actions" style={{ ["--i" as string]: 5 }}>
            <span className="muted" style={{ fontSize: 14, fontWeight: 600 }}>Works with</span>
            <span className="chip mono">.pt</span><span className="chip mono">.h5</span><span className="chip mono">.onnx</span>
          </div>
        </div>

        <div style={{ flex: "1 1 440px", minWidth: 0, position: "relative", minHeight: 560, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="blob" style={{ position: "absolute", width: 470, maxWidth: "94%", aspectRatio: "1", background: "var(--caramel-soft)" }} />
          <div className="floaty" style={{ position: "relative", width: 392, maxWidth: "100%" }}>
            <div className="box pop" style={{ ["--i" as string]: 2, padding: 22, display: "flex", flexDirection: "column", gap: 18, boxShadow: "var(--sh-3)" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                  <span className="ibub"><Icon name="file" /></span>
                  <div><div className="mono" style={{ fontWeight: 600, fontSize: 14 }}>watermarked_v2.pt</div><div className="muted" style={{ fontSize: 13 }}>conv2 · weights</div></div>
                </div>
                <span className="chip good">Marked</span>
              </div>
              <div className="wgrid" aria-hidden>
                {CELLS.map((c, i) => <span key={i} className={`wcell${c.mark ? " wmark" : ""}`} style={{ background: c.bg, ["--i" as string]: c.i }} />)}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 10, fontSize: 13 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600 }}>
                  <span style={{ width: 14, height: 14, borderRadius: 4, background: "var(--caramel)", outline: "2px solid var(--espresso)", outlineOffset: -1 }} />Carries a signature bit
                </span>
                <span className="mono muted">key: kept private</span>
              </div>
            </div>
          </div>
          <span className="sticker" style={{ position: "absolute", left: 0, top: 64, ["--rot" as string]: "-8deg", background: "var(--espresso)", color: "var(--paper)" }}><Icon name="verify" />zk-verified</span>
          <span className="sticker" style={{ position: "absolute", right: 0, bottom: 56, ["--rot" as string]: "6deg", background: "var(--caramel)", animationDelay: "-2s" }}><Icon name="eyeoff" />0 bits revealed</span>
          <div style={{ position: "absolute", top: -6, right: "4%", width: 140, height: 140 }} aria-hidden>
            <div className="spin-slow" style={{ position: "absolute", inset: 0 }}>
              <svg viewBox="0 0 140 140" style={{ width: "100%", height: "100%", overflow: "visible" }}>
                <defs><path id="badge-ring" d="M70,70 m-52,0 a52,52 0 1,1 104,0 a52,52 0 1,1 -104,0" /></defs>
                <circle cx="70" cy="70" r="68" fill="var(--paper)" stroke="var(--espresso)" strokeWidth="2" />
                <text className="ring-text"><textPath href="#badge-ring">zero knowledge · zero leakage · </textPath></text>
              </svg>
            </div>
            <div style={{ position: "absolute", inset: 42, display: "flex", alignItems: "center", justifyContent: "center", border: "var(--line)", borderRadius: "50%", background: "var(--caramel)" }}>
              <Icon name="lock" size={24} />
            </div>
          </div>
        </div>
      </section>

      {/* MARQUEE */}
      <div className="marquee" aria-hidden>
        <div className="marquee-track">
          {[0, 1].map((k) => (
            <div key={k} className="marquee-item">
              {MARQUEE.map((m) => <span key={m} style={{ display: "contents" }}><span>{m}</span><svg viewBox="0 0 24 24"><path d={SPARK} /></svg></span>)}
            </div>
          ))}
        </div>
      </div>

      {/* HOW */}
      <section id="how" className="section" style={{ display: "flex", flexDirection: "column", gap: 48 }}>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 24 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 720 }}>
            <span className="eyebrow">How it works</span>
            <h2 className="h-xl">Four moves from <span className="jw hlw">model</span> to proof.</h2>
          </div>
          <p className="muted" style={{ margin: 0, maxWidth: 400, fontSize: 17 }}>The watermark stays secret the whole way. What travels is a commitment and a proof, never the key.</p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(250px, 100%), 1fr))", gap: 28 }}>
          {STEPS.map((st) => {
            const dark = st.bg === "var(--espresso)";
            return (
              <article key={st.n} className="box tilt" style={{ ["--rot" as string]: st.rot, padding: 28, display: "flex", flexDirection: "column", gap: 18, minHeight: 340, background: st.bg, color: dark ? "var(--paper)" : undefined, boxShadow: dark ? "5px 5px 0 var(--caramel)" : undefined }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <span className="bignum" style={dark ? { WebkitTextStrokeColor: "var(--paper)" } : undefined}>{st.n}</span>
                  <span className="ibub" style={{ background: dark ? "var(--caramel)" : "var(--paper)", color: "var(--espresso)" }}><Icon name={st.icon} /></span>
                </div>
                <h3 className="h-sm" style={{ fontSize: 24 }}>{st.title}</h3>
                <p style={{ margin: 0, color: dark ? "var(--sand)" : "var(--text-secondary)" }}>{st.text}</p>
                <div style={{ marginTop: "auto", display: "flex", flexWrap: "wrap", gap: 8 }}>{st.chips.map((c) => <span key={c} className="chip">{c}</span>)}</div>
              </article>
            );
          })}
        </div>
      </section>

      {/* ROBUSTNESS */}
      <section id="robust" className="section" style={{ display: "flex", flexWrap: "wrap", gap: 56, alignItems: "center" }}>
        <div style={{ flex: "1 1 380px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
          <span className="eyebrow">Robustness</span>
          <h2 className="h-xl">Built to take a <span className="jw hlw">beating.</span></h2>
          <p className="muted" style={{ margin: 0, fontSize: 17, maxWidth: 460 }}>
            Thieves rarely copy a model as-is. They prune it, quantize it, fine-tune it, or overwrite it. The Robustness lab runs those attacks
            on the watermark and records what survives, honest limits included.
          </p>
          <Link to="/app/robustness" className="btn dark" style={{ alignSelf: "flex-start" }}>Open the Robustness lab <Icon name="arrow" size={18} /></Link>
        </div>
        <div style={{ flex: "1 1 560px", minWidth: 0, display: "flex", flexDirection: "column", gap: 14 }}>
          {ATTACKS.map((a) => (
            <div key={a.name} className="box lift wig rowcard" style={{ marginLeft: a.indent, background: a.warn ? "var(--caramel-soft)" : undefined }}>
              <span className="ibub" style={a.warn ? { background: "var(--paper)" } : undefined}><Icon name={a.icon} /></span>
              <div style={{ flex: "1 1 220px", minWidth: 0 }}><div style={{ fontWeight: 700, fontSize: 17 }}>{a.name}</div><div className="muted" style={{ fontSize: 14.5 }}>{a.text}</div></div>
              <span className={`chip mono${a.warn ? " warn" : ""}`}>{a.chip}</span>
            </div>
          ))}
        </div>
      </section>

      {/* SDK */}
      <section id="sdk" className="section" style={{ display: "flex", flexWrap: "wrap-reverse", gap: 56, alignItems: "center" }}>
        <div style={{ flex: "1 1 560px", minWidth: 0 }}>
          <div className="codebox">
            <div className="bar"><i /><i /><i /><span className="mono" style={{ marginLeft: 10, fontSize: 13, color: "var(--latte)" }}>protect.py</span></div>
            <div className="body">
              <div><span className="tk-k">from</span> sigil <span className="tk-k">import</span> protocol <span className="tk-k">as</span> P</div>
              <div><span className="tk-k">from</span> sigil.embed <span className="tk-k">import</span> embed_torch</div>
              <div><span className="tk-k">from</span> sigil.zk.circom <span className="tk-k">import</span> prove</div>
              <div> </div>
              <div><span className="tk-c"># a secret seed, bound to your Ed25519 key</span></div>
              <div>cfg = P.<span className="tk-f">Config</span>(T=<span className="tk-s">64</span>, layer=<span className="tk-s">"conv2"</span>)</div>
              <div>seed, pkh = P.<span className="tk-f">new_seed</span>(), P.<span className="tk-f">pk_hash</span>(owner.public_bytes)</div>
              <div> </div>
              <div><span className="tk-c"># hide the signature in the weights while training</span></div>
              <div>model, det = <span className="tk-f">embed_torch</span>(model, data, cfg, seed, pkh)</div>
              <div> </div>
              <div><span className="tk-c"># later: prove ownership, reveal nothing</span></div>
              <div>proof, public, _ = <span className="tk-f">prove</span>(cfg, P.<span className="tk-f">circuit_input</span>(seed, w_q, pkh, cfg, nonce))<span className="caret" /></div>
            </div>
          </div>
        </div>
        <div style={{ flex: "1 1 380px", minWidth: 0, display: "flex", flexDirection: "column", gap: 22 }}>
          <span className="eyebrow">Python SDK</span>
          <h2 className="h-xl">Mark it in training. <span className="jw hlw">Prove</span> it in court.</h2>
          <p className="muted" style={{ margin: 0, fontSize: 17 }}>One API for PyTorch, TensorFlow and ONNX, plus a <span className="mono">sigil</span> command line for owners and verifiers.</p>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 12 }}>
            {["Reads .pt, .h5/.keras and .onnx files, identically", "Groth16 proofs verify with SnarkJS or a Solidity verifier", "Safe loading: no pickles from untrusted files"].map((x) => (
              <li key={x} style={{ display: "flex", gap: 12, alignItems: "center", fontWeight: 600 }}>
                <span className="ibub" style={{ width: 30, height: 30, borderRadius: 10, background: "var(--caramel)" }}><Icon name="check" size={16} /></span>{x}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* TEAM */}
      <section id="team" className="section" style={{ display: "flex", flexDirection: "column", gap: 44 }}>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 24 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <span className="eyebrow">Team</span>
            <h2 className="h-xl">The people behind the <span className="jw hlw">seal.</span></h2>
          </div>
          <p className="muted" style={{ margin: 0, maxWidth: 380 }}>Guided by Er. Fiza Shaikh (Co-Guide) and the Department Review Committee.</p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(250px, 100%), 1fr))", gap: 24 }}>
          {TEAM.map((m) => (
            <article key={m.roll} className="box lift" style={{ padding: 28, display: "flex", flexDirection: "column", gap: 18 }}>
              <div style={{ position: "relative", width: 92, height: 92, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <div className="blob" style={{ position: "absolute", inset: 0, background: m.bg, animationDelay: m.delay }} />
                <span className="display" style={{ position: "relative", fontSize: 30, color: m.light ? "var(--paper)" : undefined }}>{m.initials}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}><h3 className="h-sm" style={{ fontSize: 24 }}>{m.name}</h3><span className="mono muted" style={{ fontSize: 13 }}>{m.roll}</span></div>
              <span className="chip good" style={{ alignSelf: "flex-start" }}>{m.role}</span>
              <p className="muted" style={{ margin: 0 }}>{m.text}</p>
            </article>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="section" style={{ paddingBottom: 96 }}>
        <div style={{ position: "relative", overflow: "hidden", backgroundColor: "var(--espresso)", backgroundImage: "radial-gradient(color-mix(in oklab, var(--cream) 16%, transparent) 1.1px, transparent 1.5px)", backgroundSize: "22px 22px",
          color: "var(--paper)", border: "var(--line)", borderRadius: 36, boxShadow: "10px 10px 0 var(--caramel)", padding: "clamp(40px, 6vw, 88px)", display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 36 }}>
          <svg className="spin-slow" viewBox="0 0 24 24" aria-hidden style={{ position: "absolute", right: "6%", top: -26, width: 120, height: 120, fill: "var(--caramel)" }}><path d={SPARK} /></svg>
          <h2 className="h-xl" style={{ position: "relative", color: "var(--paper)", maxWidth: 680 }}>Your weights. Your proof. <span style={{ color: "var(--caramel)" }}>Nobody else's business.</span></h2>
          <Link to="/app" className="btn primary lg" style={{ position: "relative" }}>Open the dashboard <Icon name="arrow" size={18} /></Link>
        </div>
      </section>

      <footer style={{ borderTop: "var(--line)", background: "var(--paper)" }}>
        <div style={{ maxWidth: 1240, margin: "0 auto", padding: "28px clamp(16px, 4vw, 40px)", display: "flex", flexWrap: "wrap", gap: 16, justifyContent: "space-between", alignItems: "center" }}>
          <a className="brandlink" href="#top"><Logo size={30} /><span className="display" style={{ fontSize: 24 }}>sigil</span></a>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>Student final-year project, aligned with the OWASP AI Model Watermarking incubator project · not official OWASP work · 2026–27</p>
        </div>
      </footer>
    </div>
  );
}
