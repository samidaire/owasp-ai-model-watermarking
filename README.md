# OWASP AI Model Watermarking: committed-seed ZK ownership verification

This is a final-year engineering project aligned with the [OWASP AI Model Watermarking](https://owasp.org/projects/ai-model-watermarking) incubator project.

It shows two things:
- **Uncommitted zero-knowledge (ZK) ownership proofs for neural-network watermarks can be forged.** A thief's forged proof verifies under the owner's own verification key.
- **A committed seed fixes this.** The watermark key and signature are both derived from a seed committed at embedding time.

The demo is evaluated against the OWASP AI Exchange `#MODEL WATERMARKING` requirements.

| Path | What |
|---|---|
| `01_Literature_Gap_Analysis.md` | Literature review and gap analysis (every source verified) |
| `02_Demo_Plan_Tomorrow.md` | Review-meeting demo plan and narration |
| `demo/` | Demos A–E (PyTorch + EZKL) and `server.py`, the local API and UI server. See `demo/README.md`. |
| `frontend/` | React + TypeScript web UI (the reference implementation). See `frontend/README.md`. |
| `contract/` | API types, captured fixtures, recorded logs, and a minimal example UI |
| **`UI_INTEGRATION.md`** | **How a UI connects to the backend: every endpoint and field, and how to drop in a new UI** |
| `Start-Demo-UI.cmd` / `Start-Demo-UI-Simulate.cmd` | Windows launchers |

## Run

```bash
python demo/server.py --simulate      # any Python 3 (tested: 3.14), no ML install: saved results + replayed runs
python demo/server.py                 # live runs: needs demo/.venv (see demo/README.md)
```

Then open http://127.0.0.1:8765. On Windows you can double-click `Start-Demo-UI.cmd` instead.

**Note:** `demo/ckpt/owner_secret.json` is the demo's owner seed. It's committed on purpose so the saved results stay reproducible. It's a demo value, not a real secret.
