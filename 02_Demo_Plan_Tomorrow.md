# Demonstration Plan: Tomorrow Morning's Review

*Companion to [01_Literature_Gap_Analysis.md](01_Literature_Gap_Analysis.md) (v2). Section references (§) point there.*

**Status (2026-10-05, ~01:30 IST):** demo code is **built and dry-run**, and there is now a **React web UI** that runs every demo live and visualises the results. All demos A–E pass on your RTX 5080, both from the UI ("Run all live" ~26 s) and from the CLI fallback. Code and instructions: [demo/README.md](demo/README.md).

**Assumption:** a 15–25 minute review with your professor. Adjust the timings if the slot differs.

---

## 1. What the session must achieve

| # | Outcome | Evidence you show |
|---|---|---|
| 1 | Scope agreed: OWASP's ZK-ownership project, not output watermarking | OWASP project page and the verbatim AI Exchange requirements R1/R2 (§1, §2) |
| 2 | The gap accepted as real and backed by citations | §3.2 comparison table and the forward-citation sweep (§3.3) |
| 3 | The core problem *and* the fix seen running on your PC | Demos A–E (below) |
| 4 | Scope approved, and possibly a nod to contribute upstream to OWASP | §7 plan, RQ1–RQ3 |

**One-line pitch:** *"ZK proofs let you prove you own a model without revealing your watermark key. The current method (ZKROWNN) assumes the person proving ownership is honest and never commits to the key. Drop that assumption and a thief can fit a key to a stolen model, and on my machine the thief's proof verifies under the owner's own verification key. I'll show that live, then fix it with a committed seed, in line with OWASP's requirement to 'avoid ambiguity where multiple parties could plausibly claim ownership.'"*

---

## 2. Agenda (20 min)

| Time | Segment | Content | Source |
|---|---|---|---|
| 0:00–2:00 | Problem | Model theft. OWASP ML05, LLM10, AI Exchange #MODEL WATERMARKING; R1 and R2 quoted verbatim | §1, §2 |
| 2:00–6:00 | Literature | Taxonomy; SoK verdict ("none … robust in practice"); the three ZK systems compared | §3, §4 |
| 6:00–8:00 | Gaps | G1 forgery (core), G2 robustness × ZK, G5 no licence-clean tool; the citation sweep as method | §3.3, §5 |
| 8:00–16:00 | **Live demo** | Web UI: panels A → E, pressing **Run live** on each (narration in §3). CLI fallback: `run_all.py --ezkl --pause` | demo/ |
| 16:00–18:00 | Feasibility + plan | Measured costs (§4 below), 16-week phases, RQ1–RQ3 | §6, §7 |
| 18:00–20:00 | Asks / Q&A | Scope approval; OWASP contribution | §8 below |

**Slides (9; none exist yet).** Slides 6–8 can be replaced by switching to the web UI.
1. Title
2. Threat and OWASP requirements
3. Taxonomy
4. ZK systems comparison
5. Gap table
6. Demo architecture: owner / thief / verifier
7. `demo/results/attacks.png`
8. `demo/results/forgery_search.png` + the EZKL cost table (§4)
9. Plan and asks

---

## 3. Live demo: what to say at each pause

**Primary: the web UI.** Double-click `Start-Demo-UI.cmd` in the project folder. It starts the local server and opens http://127.0.0.1:8765 in your browser; keep its window open. Or run this in PowerShell (paths are for Yash's machine; elsewhere run `python demo\server.py --open` from the project folder):

```powershell
& "demo\.venv\Scripts\python.exe" "demo\server.py" --open
```

How to drive it:
- Every panel loads **saved results instantly**. Press **Run live** on a panel to re-run that demo; the console drawer at the bottom streams the output, and the panel refreshes when it finishes.
- Move between panels with **← →** or **PageUp / PageDown**, so a presentation clicker works.
- Each panel's **Presenter notes** holds the lines below.
- Use **Theme: light** on a projector.
- **Don't press "Retrain with a new seed…" or "Re-run E3…" in the meeting.** Both ask for confirmation. Retraining makes B–E stale, and E3 takes ~3 minutes.

**Fallback: the CLI.** This exact command was tested end-to-end in PowerShell on Yash's machine (exit 0, ~26 s); elsewhere run `.\.venv\Scripts\python.exe run_all.py --ezkl --pause` from the `demo` folder:

```powershell
& "demo\.venv\Scripts\python.exe" "demo\run_all.py" --ezkl --pause
```

| Demo | What appears (dry-run values) | What to say |
|---|---|---|
| **A. Commit & embed** | Commitment hash with a UTC timestamp. Clean vs watermarked accuracy **98.69% vs 98.66%**. Owner BER **0.000**; clean model **0.531**. | "Before anything is released, I publish a hash of a secret seed. The key *and* the signature are both derived from that seed. The watermark costs no accuracy." |
| **B. Removal attacks** | Pruning: the watermark survives to 95%, but accuracy is **65.7% at 65%** and **9% at 90%**. FTAL, RTAL, int8 and int4: BER 0. **Overwrite:** owner 0.047 *and* the thief's own mark both valid. **Feature permutation:** accuracy unchanged, **BER 0.438, removed**. Owner realignment brings it back to 0.000. | "On this scheme the watermark outlives the model under pruning. But a functionally identical model with channels reordered erases it for free; that's the SoK's point (OWASP R1, gap G2). The owner can undo it here because they hold the original. Making that work inside a ZK proof is Phase 4. And overwriting leaves *two* valid watermarks, which is the ambiguity problem again." |
| **C. Forgery** | Thief's counterfeit key: **BER 0.000, "MALLORY!"**. Entry-distribution KS **D = 0.0104 < 0.0142**. Margin table: the naive forgery has small margins; a large-margin forgery matches the owner (minimum 1.43 vs 1.42). The forgery "proves" ownership of the clean and null models too. ZKROWNN Alg. 1 relation is **satisfied on every model**. | "The thief fits a key to *my* weights in one line per bit. Its entries look like a real key's, and with rejection sampling even its margins match; under ZK the verifier sees neither. The same construction satisfies the relation ZKROWNN's circuit checks, here evaluated in PyTorch, not their code. ZKROWNN assumes an honest prover, so this is outside its threat model. But in a dispute the accuser is the one with a motive to cheat, which is exactly what the USENIX '24 false-claims paper shows. *This is my analysis; the demo is the evidence.*" |
| **D. Committed seed** | D0: commitment **MATCHES**, owner verified. **D1 (free signature): 1000/1000** (true by construction). **D2 (derived signature): 0/20,000 accepted**, best thief BER **0.250**. Work factor **~2³²** (~71 single-core hours); the target at T=256 is **~2¹²⁰**. Null models: BER 0.41–0.59. | "If only the key is derived, the thief just sets the signature to whatever their key extracts. That wins by construction, not by luck. Derive the signature from the seed too, and the thief has to search. But at 64 bits that's only about 2³² work, feasible on a GPU. That's why timestamp ordering still matters, and why RQ1 sets T and θ; at Uchida's 256 bits it would be about 2¹²⁰. The null models are an indicative check, not a calibrated false-positive rate." |
| **E1. ZK proof** | EZKL/Halo2: **verified, score 64/64**, prove **0.63 s**, verify **20 ms**, proof **60 KB**, peak RAM **0.6 GiB** | "This is a real zero-knowledge proof on my 32 GB machine. The key and signature are private; the suspect's weights are public." |
| **E2. Thief's proof** | Thief's forged proof **verified = True under the owner's VK** (identical VK hash) | "Without a commitment, the verifier literally cannot tell my proof from the thief's. This is gap G1 demonstrated cryptographically." |
| **E3. Committed proof** | Poseidon hash of the private params is public: owner **ACCEPT**, thief **REJECT**. The "owner's commitment" here is taken from the owner's own run; in the protocol it is published at embedding time. Cost: logrows **20**, prove **~36 s**, verify **~0.6 s**, pk **9.8 GiB**, sampled peak RAM **2.6 GiB**. | "Commit inside the proof and the thief is rejected. Honest scope: this commits to the key directly, which is the D1 level plus a timestamp. It isn't yet linked to the SHA-256 seed commitment from demo A, and a real commitment must also pin the circuit's quantisation settings. Deriving the key from the seed *inside* the circuit, the D2 level, is my Phase 3. The cost jump from logrows 15 to 20 is the RQ3 trade-off I'll optimise." |

**Fallbacks:**
- **Live run fails:** show slides 7–8, or `demo/results/run_log.txt`.
- **GPU breaks:** run demos A–D with the global `python run_all.py` (CPU torch). E needs `.venv`.

---

## 4. Measured feasibility (for slide 8)

| Workload (this machine) | Prove | Verify | Proof | Proving key | Peak RAM |
|---|---|---|---|---|---|
| Uchida extraction, params private (logrows 15) | 0.63 s | 20 ms | 60 KB | 132 MB | 0.6 GiB |
| Same + Poseidon commitment (logrows 20) | ~36 s | ~0.5–0.6 s | 65 KB | 9.8 GiB | 2.6 GiB (sampled) |
| *Literature: ZKROWNN CIFAR-10 CNN (128 GB box)* | *11.2 s* | *1 ms* | *127 B* | *117 MB* | *n/a* |
| *Literature: RoSeMary decoder* | *7.15 s* | *118.6 ms* | *17.1 KB* | *n/a* | *2.6 GB* |

These aren't like-for-like comparisons: different circuits, proof systems (Groth16 vs Halo2/KZG) and hardware. Present them as orders of magnitude only.

---

## 5. Morning timeline (all the building is done)

| When | Task |
|---|---|
| T-60 min | Reboot; plug in; disable sleep and notifications |
| T-50 min | Double-click `Start-Demo-UI.cmd`; press **Run all live** in the header. Expect "✓ All demos finished" in the console in about 30 s, with every panel showing ✓ in the sidebar. Leave the window open. |
| T-45 min | Open slides, the UI tab (Theme: light), and the 01 report. Keep `demo/results/run_log.txt` as the offline fallback. |
| T-40 min | Optional: screen-record one `--pause` run as a backup |
| T-30 min | Rehearse the §3 lines once, especially C, D1 vs D2, and E2 |

**Optional, only if you want fresh numbers:**
- `run_all.py --retrain --ezkl` (~1 min). The seed and numbers change slightly. **If you retrain, also add `--hashed`** (~2 min, ~20 GB of temporary disk), or skip E3. E3 reads precomputed proofs made with the current owner key.
- Add `--hashed` only if you have about 4 minutes and 20 GB of free disk.

---

## 6. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| CUDA issue in the morning | Low | CPU fallback for A–D (global python) |
| EZKL hiccup | Low (dry-run passed) | Show `results/ezkl_*/summary.json` and the run log |
| Offline in the meeting | Low | Tested with a simulated offline network: E1/E2 use the cached SRS in `results/ezkl_*` (no download) and verify. Without a cache the script falls back to a TEST-ONLY SRS, in a separate file so the cached public one is never overwritten, **and says so**. |
| On-screen noise from EZKL | Low | The UI and `run_all.py` share one noise filter; the full output is in `results/web_job_log.txt` and `run_log.txt` |
| UI won't load | Low | Use the CLI fallback command in §3. The UI only needs the Python server: no npm, no internet. |
| Accidental retrain in the UI | Low | It asks for confirmation first. If it happens, B–E show "Stale": press **Run all live**, and skip E3 or run **Re-run E3…** (~3 min). |
| Overclaiming | Med | Use the caveats in demo/README.md: indicative θ; relation not their code; E3 is D1-level |

---

## 7. Likely questions

| Question | Answer |
|---|---|
| "Why zero-knowledge at all?" | Revealing the key lets anyone remove or forge the watermark. That's ZKROWNN's own motivation (§3.2). |
| "What's novel? ZKROWNN exists." | ZKROWNN assumes an honest prover, commits nothing, and has no attack evaluation. I showed that its relation is forgeable and that a forged proof verifies under the owner's VK. I then add a committed seed, with key *and* signature derived, and test under SoK attacks. The sweep found nothing doing this (§3.3, §5). |
| "You attacked Uchida, not DeepSigns." | Demo C part 2 runs the same sign-fit against ZKROWNN's DeepSigns-style Alg. 1 relation, and it's satisfied on every model. |
| "Can't the thief just commit after stealing?" | With a free signature, yes: D1 wins by construction. With a derived signature they must search seeds: ~2³² work at T=64, feasible on a GPU, so timestamps remain necessary. At T=256 it's ~2¹²⁰ (RQ1). |
| "Is E3 the full fix?" | No. It's the D1 level inside ZK. Deriving the key in-circuit (D2) is Phase 3, and the logrows-20 cost shows why it needs optimisation. |
| "Feature permutation broke it. So the scheme is useless?" | It shows OWASP R1 isn't met by Uchida alone. Realignment restores it when the owner has the original model. Doing that verifiably is Phase 4 (G2). |
| "Does it stop API theft?" | No, and OWASP says so (limitation L1). Entangled watermarks are the extension path (G4). |
| "Why MNIST?" | For live speed. Phases 1–4 move to CIFAR-10 / ResNet-18 and benchmark against ZKROWNN's CIFAR-10 CNN. |
| "Which ZK library, and is it open source?" | EZKL for research. It has no open-source licence file, so an OWASP contribution needs a licence-clean backend (G5). |

---

## 8. Asks for the professor

1. Approve the scope: **committed-seed ZK ownership verification for NN watermarks, aligned with OWASP AI Exchange R1/R2.**
2. Agree on success metrics:
   - forgery success with vs without commitment (RQ1);
   - attack matrix with proof verified yes/no (RQ2);
   - prove/verify cost on a single workstation (RQ3).
3. Permission to contact the OWASP project leader about contributing the PoC. The repo currently has no code (S2).
