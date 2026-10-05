# Running the demo

This covers the presentation build: demos A–F in the Cocoa Pop UI. Everything runs locally; nothing is sent to a
cloud service. **The full illustrated guide is [`Sigil-User-Guide.pdf`](Sigil-User-Guide.pdf)** (install, every
screen, walkthroughs, SDK, results, limits). **[`DEPLOY.md`](DEPLOY.md)** is the step-by-step deployment runbook,
written so an AI agent can follow it; after any setup, `scripts/verify_deploy.py` checks everything end to end.

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

Every page starts empty. A Run button replays the recorded output of a real run in the console, then that demo's
saved results appear. **Clear results** (sidebar) empties the pages for a new test; **Show saved results** fills
them all at once. Use this mode as the fallback during the presentation.

### The pages

| Address | Page | What it shows |
|---|---|---|
| `/` | Home | The project pitch: how it works, robustness, the SDK, the team |
| `/app` | Overview | Headline numbers, the models, the proof pipeline and an audit log |
| `/app/embed` | Embed watermark | How the models were watermarked, protocol v1 (demo A) or v2 (demo F) |
| `/app/verify` | Verify ownership | The claim, the real proof, the verdict (off-chain or on-chain) and the recorded misuse attempts |
| `/app/robustness` | Robustness lab | Every removal attack and the pruning sweep (demo B) |
| `/app/demo/A` … `/app/demo/F` | Research demos | The full research storyline, one demo per page |

Every address works as a link or after a reload.

Every dashboard page has a **Model under test** bar. Pick a model and press **Test this model** (4–15 s): it
measures the model's accuracy, reads the watermark with both owners' keys and, if the owner's mark is there, makes
and verifies a zero-knowledge proof for that exact file. The menu has the owner's models, six stolen copies made live
from the owner's model (pruned 65%/90%, int8, fine-tuned, channels permuted, overwritten), the never-watermarked
models, and any `.pt`/`.h5`/`.keras`/`.onnx` file you put in `demo/models/` (live mode only).

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
1. Start the server and open <http://127.0.0.1:8765>. That's the home page; **Open dashboard** goes to the app.
2. The sidebar shows the GPU, or "CPU only". If it shows "No ML stack: replay only", the live packages
   aren't installed: use Option 1.
3. Keep a second terminal ready with `python demo/server.py --simulate --port 8766` in case anything goes wrong.

**During:**
- **Start clean:** press **Clear results** so every page is empty, then fill them by running: **Run all live**
  (A–E) and **Run demo F live**. Clear again for the next group.
- **Suggested route:** Home → Overview → Embed watermark → Verify ownership (try a misuse) → Robustness lab,
  then the research demos A–F for the full story.
- **Navigate** with the sidebar. Inside the research demos, ← → (or a presentation clicker's PageUp /
  PageDown) moves between A–F.
- **Run** with the caramel buttons. The console at the bottom streams the run live; **Cancel run** stops it.
- **Test a model:** pick one in the **Model under test** bar and press **Test this model**. Good contrasts:
  *pruned 90%* (2% accuracy, ownership still proven), *channels permuted* (mark gone), *clean.pt* (never marked).
- **Misuse:** on Verify ownership, each "Try a misuse" button re-runs the verifier on the saved proof with one thing
  changed (about 1 s); the console prints every check, the failing one marked `[XX]`.
- **Say** what's in each demo's **Presenter notes**. The caveats there are the honest limits examiners will
  ask about.
- **Motion:** the toggle in the sidebar turns the animations off if the projector machine is slow.

**Showing the teacher it's really live** (needs Option 2 and `Start-Demo-UI.cmd`, so no "Simulate mode" banner):
1. Press **Clear results**: every page is empty, so everything that appears comes from runs the teacher watches.
2. Demo D: let the teacher pick 20,000 or 100,000 thief seeds and click **Run live** (~3 s / ~17 s).
   The Overview tile changes to the new count.
3. Demo F: **Run demo F live** (~80 s). The Verify page then shows a brand-new proof (new `pi_a`, nonce and
   registration time).
4. Let the teacher pick any model in the **Model under test** bar and press **Test this model**: a stolen copy is
   attacked and tested in front of them.
5. Robustness lab: **Run attacks live** (~10 s).
6. Optional, last: **Retrain with a new seed…** (~35 s), then **Run all live** (~30 s) to recompute B–E.

E3 and the on-chain check stay precomputed; after a live demo F run the On-chain view says it was made for an
earlier proof. Live runs overwrite `demo/results/`; unzip the package again to restore the shipped results.

**What not to run live:**
- **Retrain:** it replaces the owner key and makes B–E stale.
- **E3:** it needs about 32 GB of RAM and ~10 GB of disk.

Both ask for confirmation first.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Can't reach the demo server" | The server isn't running, or port 8765 is taken: `python demo/server.py --port 8770` |
| "No ML stack: replay only" | No PyTorch in that Python: run the setup (Option 2), or present in simulate mode |
| Demo F says the circuit isn't set up | Re-run the setup (it installs `dist/sigil-proving-keys-t64.zip`), or `.venv\Scripts\python -m sigil.cli zk-setup` (~3 min) |
| Antivirus blocks `tools/bin/circom.exe` | It's the official circom 2.2.3 release from github.com/iden3/circom; allow it, or present demo F in simulate mode |
| Fonts look plain | They're bundled; a hard refresh (Ctrl+F5) fixes a cached old build |

## Making the zip for someone else

```bash
.venv/Scripts/python scripts/make_share_zip.py      # -> dist/owasp-wm-demo.zip (repo at HEAD + proving keys)
```
