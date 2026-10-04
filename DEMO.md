# Running the demo

This covers the presentation build: demos A–F in the Cocoa Pop UI. Everything runs locally; nothing is sent to a
cloud service.

| Demo | What it shows | Live run |
|---|---|---|
| **A · Commit & embed** | The owner publishes a hash of a secret seed; the watermark costs about 0.03 percentage points of accuracy | ~5 s |
| **B · Removal attacks** | Pruning, quantisation, fine-tuning, overwriting, permutation | ~10 s |
| **C · Ownership forgery** | Without a commitment, a thief fits a fake key ("MALLORY!") | ~3 s |
| **D · Committed seed** | The fix, without zero knowledge: 0 of 20,000 forgeries succeed | ~3 s |
| **E · Zero-knowledge proofs** | EZKL: the thief's forged proof verifies under the owner's key (E1, E2). E3 is precomputed. | ~10 s |
| **F · Protocol v2** | The full fix: a Circom + Groth16 proof, every verifier check, thief, misuse, attacks, the overwrite dispute | ~1–2 min |

## On a new machine

You need **Python 3.10+** ([python.org](https://www.python.org/downloads/); tick "Add to PATH"). Live demo F
also needs **Node.js 20.19+** ([nodejs.org](https://nodejs.org)).

### Option 1: the UI with every saved result (about 1 minute, nothing to install)

```bash
python demo/server.py --simulate
```

Then open <http://127.0.0.1:8765>. On Windows you can double-click `Start-Demo-UI-Simulate.cmd` instead.

Every panel shows the saved results, and the Run buttons replay recorded runs. Use this as the fallback during
the presentation.

### Option 2: everything live (about 5–15 minutes, mostly downloading)

Unzip `owasp-wm-demo.zip`, open a terminal in the `owasp-ai-model-watermarking` folder, and run:

- **Windows:** `.\setup.ps1 --demo`. If PowerShell blocks the script, run
  `powershell -ExecutionPolicy Bypass -File setup.ps1 --demo` instead.
- **Linux/macOS:** `./setup.sh --demo`

This installs a CPU build of PyTorch, the demo packages, the `sigil` SDK, and the circuit tools. It also installs
the proving keys bundled in `dist/`, checking each against `circuits/keys/`. Add `--gpu` to use an NVIDIA GPU.

Then start the app: double-click `Start-Demo-UI.cmd` (Windows), or run `.venv/bin/python demo/server.py` (Linux/macOS).

## Presenting

**Before you start:**
1. Start the server and open <http://127.0.0.1:8765>.
2. The top bar shows the GPU, or "CPU only · torch …". If it shows "Environment probe failed", the live
   packages aren't installed: use Option 1.
3. Keep a second terminal ready with `python demo/server.py --simulate --port 8766` in case anything goes wrong.

**During:**
- **Navigate** with ← → (or a presentation clicker's PageUp / PageDown).
- **Run** with the caramel button on each panel. The console at the bottom streams the run live; **Cancel run**
  stops it.
- **Say** what's in each panel's **Presenter notes**. The caveats there are the honest limits examiners will
  ask about.
- **Motion:** the toggle in the top bar turns the animations off if the projector machine is slow.

**What not to run live:**
- **Retrain:** it replaces the owner key and makes B–E stale.
- **E3:** it needs about 32 GB of RAM and ~10 GB of disk.

Both ask for confirmation first.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Can't reach the demo server" | The server isn't running, or port 8765 is taken: `python demo/server.py --port 8770` |
| "Environment probe failed" | No PyTorch in that Python: run the setup (Option 2), or present in simulate mode |
| Demo F says the circuit isn't set up | Re-run the setup (it installs `dist/sigil-proving-keys-t64.zip`), or `.venv\Scripts\python -m sigil.cli zk-setup` (~3 min) |
| Antivirus blocks `tools/bin/circom.exe` | It's the official circom 2.2.3 release from github.com/iden3/circom; allow it, or present demo F in simulate mode |
| Fonts look plain | They're bundled; a hard refresh (Ctrl+F5) fixes a cached old build |

## Making the zip for someone else

```bash
.venv/Scripts/python scripts/make_share_zip.py      # -> dist/owasp-wm-demo.zip (repo at HEAD + proving keys)
```
