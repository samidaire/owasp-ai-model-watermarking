# Committed-seed ZK ownership verification for neural-network watermarks

A **student final-year engineering project**, aligned with the [OWASP AI Model Watermarking](https://owasp.org/www-project-ai-model-watermarking/) incubator project (also listed at <https://owasp.org/projects/ai-model-watermarking>). **It is not official OWASP work** and is not published or endorsed by OWASP. Contributing it upstream is only a possible later step (`02_Demo_Plan_Tomorrow.md` §8).

It shows two things:
- **Uncommitted zero-knowledge (ZK) ownership proofs for neural-network watermarks can be forged.** A thief's forged proof verifies under the owner's own verification key.
- **A committed seed fixes this.** The watermark key and signature are both derived from a seed committed at embedding time.

**What is and isn't new.** Committing to a watermark key, timestamping it, deriving the watermark from a hash or a signature, and proving ownership in ZK all have prior work:
- Adi et al., USENIX Security 2018;
- Li et al., arXiv 1910.01226;
- NeuralMark, AAAI 2026;
- FedZKP, arXiv 2305.04507.

The project's contribution is narrower. It is a SNARK proof of Uchida-style white-box extraction in which **both the key and the signature are derived inside the circuit** from a committed seed bound to an authenticated owner key, with the threshold enforced in-circuit and the proof bound to the suspect model. Around that come measured forgery (RQ1), robustness × ZK (RQ2) and cost (RQ3) results.

**Status:** the in-circuit derivation is built. `circuits/ownership.circom` (Circom + SnarkJS Groth16) derives the key and signature from the committed seed, enforces the threshold and binds the proof to the suspect model. **Demo F** (`demo/08_protocol_v2.py`) runs it end to end through the `sigil` SDK. The EZKL demo E3 remains at the D1 level for comparison. The protocol is in `docs/protocol.md`; see `01_Literature_Gap_Analysis.md` §3.4 for the positioning.

The demo is evaluated against **project requirements R1 (robustness) and R2 (non-ambiguity)**. We derived them from the OWASP AI Exchange `#MODEL WATERMARKING` text, which says watermarks should "remain detectable even if the model is modified" and should "avoid ambiguity where multiple parties could plausibly claim ownership of the same model". The R1/R2 labels are ours, not OWASP's.

| Path | What |
|---|---|
| `01_Literature_Gap_Analysis.md` | Literature review and gap analysis (every source verified) |
| `02_Demo_Plan_Tomorrow.md` | Review-meeting demo plan and narration |
| `demo/` | Demos A–F (PyTorch, EZKL, and protocol v2 with Circom + Groth16) and `server.py`, the local API and UI server. See `demo/README.md`. |
| `frontend/` | React + TypeScript web UI: a home page at `/`, the dashboard at `/app` (overview, embed, verify, robustness lab, research demos A–F). See `frontend/README.md`. |
| `contract/` | API types, captured fixtures, recorded logs, and a minimal example UI |
| `sdk/` | **`sigil` Python SDK and CLI**: protocol v2, Poseidon, Ed25519 identities, PyTorch/Keras/ONNX adapters, ZK prove/verify. See `sdk/README.md`. |
| `circuits/` | Circom circuit (`ownership.circom`), verification keys and setup transcripts (`keys/`), on-chain verifier (`onchain/`) |
| `docs/` | `protocol.md` (the specification), `SOP.pdf`, reports (`reports/`) |
| `experiments/` | Parity study, robustness studies, ZK cost benchmark, with their results |
| `setup.ps1` / `setup.sh` | **One-command setup on a new machine** (see below) |
| **`UI_INTEGRATION.md`** | **How a UI connects to the backend: every endpoint and field, and how to drop in a new UI** |
| **`REQUIREMENTS.md`** | **What must be built to complete the project against the SOP: requirement IDs, acceptance criteria, owners, SOP traceability** |
| **`WORKFLOW.md`** | **How it gets built: phases (complete the build → update the UI design → migrate the UI), milestones, gates, timeline, team workflow** |
| `Start-Demo-UI.cmd` / `Start-Demo-UI-Simulate.cmd` | Windows launchers |

## Quick start on a new machine

**Presenting the demo?** See **[DEMO.md](DEMO.md)**: setup on a new machine in minutes, plus a presentation runbook. The illustrated user guide (install, every screen, walkthroughs, SDK, results, honest limits) is **[Sigil-User-Guide.pdf](Sigil-User-Guide.pdf)**; its source is `docs/guide/` (rebuild with `docs/guide/build.py`).

| You want | Do this | Time (≈50 Mbps) |
|---|---|---|
| The demo UI with every saved result (Run buttons replay recorded runs) | Only Python is needed: `python demo/server.py --simulate`, then open http://127.0.0.1:8765 | ~1 min |
| Everything live: SDK, training, proofs | Windows: `.\setup.ps1` · Linux/macOS: `./setup.sh` (needs Python 3.10+ and Node 20.19+) | 10–15 min CPU, 15–20 min with an NVIDIA GPU |
| …and skip the ZK setup | add `--keys sigil-proving-keys-t64.zip` (made with `scripts/package_keys.py --t64-only`, shared alongside the repo; each key is checked against `circuits/keys/*.setup.json`) | +1 min |
| …or generate the proving keys locally | add `--zk-setup` | +3–5 min |

Almost all of the time is downloading PyTorch. Trained models, results and verification keys are in the repository, so
nothing has to be retrained. Re-running the robustness studies in `experiments/` is optional and takes hours.

## Run

```bash
python demo/server.py --simulate      # any Python 3 (tested: 3.14), no ML install: saved results + replayed runs
python demo/server.py                 # live runs: needs the .venv from setup.ps1 / setup.sh
```

Then open http://127.0.0.1:8765. On Windows you can double-click `Start-Demo-UI.cmd` instead.

**Note:** `demo/ckpt/owner_secret.json` is the demo's owner seed. It's committed on purpose so the saved results stay reproducible. It's a demo value, not a real secret.
