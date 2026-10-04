# OWASP AI Model Watermarking: committed-seed ZK ownership verification

This is a final-year engineering project aligned with the [OWASP AI Model Watermarking](https://owasp.org/projects/ai-model-watermarking) incubator project.

It shows two things:
- **Uncommitted zero-knowledge (ZK) ownership proofs for neural-network watermarks can be forged.** A thief's forged proof verifies under the owner's own verification key.
- **A committed seed fixes this.** The watermark key and signature are both derived from a seed committed at embedding time.

**What is and isn't new.** Committing to a watermark key, timestamping it, deriving the watermark from a hash or a signature, and proving ownership in ZK all have prior work:
- Adi et al., USENIX Security 2018;
- Li et al., arXiv 1910.01226;
- NeuralMark, AAAI 2026;
- FedZKP, arXiv 2305.04507.

The project's contribution is narrower. It is a SNARK proof of Uchida-style white-box extraction in which **both the key and the signature are derived inside the circuit** from a committed seed bound to an authenticated owner key, with the threshold enforced in-circuit and the proof bound to the suspect model. Around that come measured forgery (RQ1), robustness × ZK (RQ2) and cost (RQ3) results.

The current demo reaches only the D1 level: E3 commits to the key and signature directly, and the in-circuit derivation is still to be built (`REQUIREMENTS.md` ZK-01). See `01_Literature_Gap_Analysis.md` §3.4.

The demo is evaluated against the OWASP AI Exchange `#MODEL WATERMARKING` requirements.

| Path | What |
|---|---|
| `01_Literature_Gap_Analysis.md` | Literature review and gap analysis (every source verified) |
| `02_Demo_Plan_Tomorrow.md` | Review-meeting demo plan and narration |
| `demo/` | Demos A–E (PyTorch + EZKL) and `server.py`, the local API and UI server. See `demo/README.md`. |
| `frontend/` | React + TypeScript web UI (the reference implementation). See `frontend/README.md`. |
| `contract/` | API types, captured fixtures, recorded logs, and a minimal example UI |
| **`UI_INTEGRATION.md`** | **How a UI connects to the backend: every endpoint and field, and how to drop in a new UI** |
| **`REQUIREMENTS.md`** | **What must be built to complete the project against the SOP: requirement IDs, acceptance criteria, owners, SOP traceability** |
| **`WORKFLOW.md`** | **How it gets built: phases (complete the build → update the UI design → migrate the UI), milestones, gates, timeline, team workflow** |
| `Start-Demo-UI.cmd` / `Start-Demo-UI-Simulate.cmd` | Windows launchers |

## Run

```bash
python demo/server.py --simulate      # any Python 3 (tested: 3.14), no ML install: saved results + replayed runs
python demo/server.py                 # live runs: needs demo/.venv (see demo/README.md)
```

Then open http://127.0.0.1:8765. On Windows you can double-click `Start-Demo-UI.cmd` instead.

**Note:** `demo/ckpt/owner_secret.json` is the demo's owner seed. It's committed on purpose so the saved results stay reproducible. It's a demo value, not a real secret.
