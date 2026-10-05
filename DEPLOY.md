# Deploying Sigil

**This is a complete runbook, written so an AI coding agent can deploy the product by
following it alone, and so a person can too.** Work through sections 1–7 in order. Run every check. Where this file
says **ASK**, stop and ask the user before continuing.

TL;DR on a machine with Python 3.10+ and Node.js 20.19+, from the project folder:

```powershell
# Windows (PowerShell)
.\setup.ps1 --demo
.venv\Scripts\python scripts\verify_deploy.py        # must end with: ALL CHECKS PASSED
.venv\Scripts\python demo\server.py --open           # the app: http://127.0.0.1:8765
```

```bash
# macOS / Linux
./setup.sh --demo
.venv/bin/python scripts/verify_deploy.py            # must end with: ALL CHECKS PASSED
.venv/bin/python demo/server.py --open               # the app: http://127.0.0.1:8765
```

---

## 0. What you are deploying

Sigil is a final-year student project aligned with the OWASP AI Model Watermarking project. It hides a 64-bit
watermark in a neural network's weights, then proves who owns a model with a zero-knowledge proof (Groth16) that
reveals nothing about the watermark. The deliverable is a **local web app**: a Python server that serves a
prebuilt React UI and runs the demo scripts on the same machine.

```
browser ── http://127.0.0.1:8765 ──▶ demo/server.py   (Python standard library only; listens on 127.0.0.1)
                                      ├─ serves frontend/dist/      (prebuilt React app: fonts bundled, no internet)
                                      ├─ /api/*                     (state, steps, models, run, jobs, cancel)
                                      └─ runs demo/*.py with .venv's Python, one job at a time
                                           ├─ sigil SDK (sdk/)       watermark protocol, Ed25519 identities, verifier
                                           ├─ PyTorch + MNIST        demo/ckpt/ models, demo/data/ (in the package)
                                           └─ circom + SnarkJS       circuits/ (+ tools/bin/circom, circuits/build/*.zkey)
   the pages read demo/results/*.json   (shipped results; live runs overwrite them)
```

There are two ways to run it. Pick one in section 1.

| | **Replay mode** | **Live mode** |
|---|---|---|
| What the Run buttons do | Replay recorded output of real runs, then show the saved results | Really train, attack, prove and verify on this machine |
| Needs | Python 3.10+ only | Python 3.10+, Node.js 20.19+, internet during setup, about 3 GB of disk (8 GB with `--gpu`) |
| Install time | none | 5–15 minutes, mostly downloads |
| Start | `python demo/server.py --simulate` | `.venv` Python: `demo/server.py` |

Nothing is sent to any cloud service. The server only accepts connections from this machine.

## 1. Decide the mode

- The user only wants to **show** the project, or the machine has no internet, no Node.js, or the user won't allow
  installs: **replay mode**. Skip to section 5 with `--simulate`.
- The user wants the Run buttons to **really run** (for example a live demo where an examiner sees new results):
  **live mode**. This is the default when in doubt.
- If live setup fails twice for reasons you can't fix (section 8), fall back to replay mode and tell the user why.

## 2. Get the code

- **From the package** `owasp-wm-demo.zip` (preferred): unzip it. You get one folder, `owasp-ai-model-watermarking/`,
  containing everything, including the proving keys (`dist/sigil-proving-keys-t64.zip`), the trained models and the
  MNIST data.
- **From git:** the proving-keys zip is not in git. Either copy `dist/sigil-proving-keys-t64.zip` from the package
  into `dist/`, or add `--zk-setup` to the setup command in section 4 (it then generates the keys: about 3 more
  minutes and a one-time 144 MB download).

**Run every command in this file from the project folder** (the one that contains this `DEPLOY.md`).

## 3. Check the prerequisites

| Need | Check (Windows / macOS–Linux) | Pass when | Mode |
|---|---|---|---|
| Python 3.10+ | `py -3 --version` or `python --version` / `python3 --version` | prints 3.10 or newer | both |
| Node.js 20.19+ | `node --version` | prints v20.19 or newer | live |
| Internet | `python -c "import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=10); print('ok')"` | prints `ok` | live (setup only) |
| Disk space | — | about 3 GB free (8 GB with `--gpu`) | live |
| NVIDIA GPU (optional) | `nvidia-smi -L` | lists a GPU | live, only with `--gpu` |

The setup downloads from pypi.org, download.pytorch.org, registry.npmjs.org and github.com (the circom 2.2.3
release). A proxy or firewall that blocks these makes live setup fail.

**ASK before installing anything system-wide.** Python and Node.js are machine-wide installs, so get the user's
approval first. Suggested commands:

| OS | Python | Node.js |
|---|---|---|
| Windows | `winget install -e --id Python.Python.3.12` | `winget install -e --id OpenJS.NodeJS.LTS` |
| macOS (Homebrew) | `brew install python@3.12` | `brew install node` |
| Ubuntu / Debian | `sudo apt-get install -y python3 python3-venv` | Node.js 20.19+ from nodesource.com or nvm (apt's `nodejs` is often too old) |

On Windows, open a **new** terminal after installing so the new `PATH` takes effect.

## 4. Install (live mode only)

```powershell
.\setup.ps1 --demo                                            # Windows
powershell -ExecutionPolicy Bypass -File setup.ps1 --demo     # Windows, if scripts are blocked
```

```bash
./setup.sh --demo                                             # macOS / Linux  (or: bash setup.sh --demo)
```

Options: add `--gpu` for the NVIDIA CUDA build of PyTorch (a much bigger download), `--zk-setup` when there is no
proving-keys zip (see section 2).

What it does, skipping anything already done, so it is **safe to re-run**:

1. installs `uv` (a fast Python installer) and creates `.venv/` with Python 3.12;
2. installs PyTorch 2.14.1 (CPU build, or CUDA with `--gpu`), the demo requirements and the `sigil` SDK;
3. runs `npm ci` in `circuits/` (SnarkJS 0.7.6, circomlib 2.0.5) and downloads circom 2.2.3 into `tools/bin/`;
4. unpacks the proving keys from `dist/sigil-proving-keys*.zip` into `circuits/build/`, refusing any whose SHA-256
   doesn't match `circuits/keys/*.setup.json`;
5. runs a quick self-test.

**Success:** exit code 0 and the last line starts with `Done. Start the app:`. It takes 5–15 minutes the first
time. **Agents:** give this command a timeout of at least 30 minutes, or run it in the background and poll; don't
interrupt it while it downloads. The self-test in step 5 doesn't fail the setup, so **always run section 5**.

## 5. Verify (required)

```powershell
.venv\Scripts\python scripts\verify_deploy.py       # live mode, Windows
```

```bash
.venv/bin/python scripts/verify_deploy.py           # live mode, macOS / Linux
python scripts/verify_deploy.py --simulate          # replay mode (any Python 3.10+)
```

**Success:** every line starts with `PASS`, the last line is `ALL CHECKS PASSED`, and the exit code is 0. A live
run takes 1–3 minutes. Add `--json` for a machine-readable summary.

In live mode it checks the Python packages, Node.js, SnarkJS, circom, the proving key against its transcript, the
MNIST data, the web app build, and the test suite (`tests/`). It then starts the app on a free port, verifies demo
F's saved proof with SnarkJS, and **makes and verifies a real Groth16 proof** for the owner's model. It stops the
server afterwards and leaves the working tree as it found it.

**If something fails:** each `FAIL` line is followed by a `fix:` line. Apply it, re-run the setup (section 4, safe to
repeat), then re-run this check. If the same check still fails after two attempts, stop and report the exact `FAIL`
and `fix:` lines to the user. Section 8 has more.

## 6. Start the app

| | Windows | macOS / Linux |
|---|---|---|
| Live | double-click `Start-Demo-UI.cmd`, or `.venv\Scripts\python demo\server.py --open` | `.venv/bin/python demo/server.py --open` |
| Replay | double-click `Start-Demo-UI-Simulate.cmd`, or `python demo\server.py --simulate --open` | `python3 demo/server.py --simulate --open` |

The app is at **http://127.0.0.1:8765** (`--open` opens the browser). If the port is taken, add `--port 8770` and
use that port instead.

**Agents:** the server runs until it is stopped, so start it **in the background** rather than blocking your shell.
For example, on Windows: `Start-Process .venv\Scripts\python.exe -ArgumentList 'demo\server.py','--open'`; on
macOS/Linux: `nohup .venv/bin/python demo/server.py --open > server.log 2>&1 &`. Confirm it's up:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/state | Select-Object mode     # Windows: mode = live (or simulate)
```

```bash
curl -s http://127.0.0.1:8765/api/state | head -c 120                      # macOS / Linux: JSON with "mode"
```

Leave it running for the user. To stop it: close its window, press Ctrl+C in it, or end the process.

## 7. Hand over to the user

Tell the user:

- the address, **http://127.0.0.1:8765**, and the mode (live or replay);
- that pages start **empty** by design: **Run all live** (sidebar) fills demos A–E, **Run demo F live** makes the
  zero-knowledge proof, and **Clear results** empties the pages again for a new audience;
- that the **Model under test** bar on every page tests any model: the owner's, stolen copies made live, ones never
  watermarked, or their own file dropped into `demo/models/`;
- where the presenting material is: `Sigil-User-Guide.pdf` (full illustrated guide), `DEMO.md` (one-page runbook) and
  `OWASP AI Model Watermarking.pptx` (slides).

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `python` / `py` not recognised | Python missing or not on PATH | Install it (section 3, **ASK**), then open a new terminal |
| `setup.ps1 cannot be loaded… running scripts is disabled` | PowerShell execution policy | `powershell -ExecutionPolicy Bypass -File setup.ps1 --demo` |
| `./setup.sh: Permission denied` | not executable | `bash setup.sh --demo` |
| Setup fails installing `uv`, Python 3.12 or packages | no internet, or a proxy | Check access to pypi.org; set `HTTPS_PROXY` if the network needs a proxy; otherwise use replay mode |
| PyTorch download fails or is very slow | large download (CUDA build ~2.5 GB) | Re-run the setup; drop `--gpu` to get the much smaller CPU build |
| `Node.js 20.19+ is required…` | Node missing or too old | Install Node.js LTS (**ASK**), new terminal, re-run the setup |
| `npm ci` fails | registry blocked, or a broken `circuits/node_modules/` | Delete `circuits/node_modules/` and re-run; check access to registry.npmjs.org |
| circom download fails, or antivirus removes `tools/bin/circom.exe` | github.com blocked, or a false positive | Allow it (it's the official iden3 release), or download `circom-windows-amd64.exe` (or the `-linux-` / `-macos-` file) from github.com/iden3/circom/releases/tag/v2.2.3 and save it as `tools/bin/circom.exe` (`tools/bin/circom` elsewhere, then `chmod +x`) |
| macOS refuses to run `tools/bin/circom` | Gatekeeper quarantine | `xattr -d com.apple.quarantine tools/bin/circom` |
| `… does not match … refusing it (deleted)` | damaged proving-keys zip | Copy the package zip again, or re-run the setup with `--zk-setup` |
| verify: `server sees PyTorch` fails | the server ran with a Python that has no PyTorch | Start it with `.venv`'s Python (section 6), never the system Python, for live mode |
| verify: `prove ownership of a model` fails | toolchain or keys | Fix the earlier `FAIL` lines first (node, snarkjs, circom, proving key); the server log is printed below the results |
| Browser: "Can't reach the demo server" | server not running, or another port | Start it (section 6); use the port it printed |
| Port 8765 already in use | another program, or an old server | `--port 8770`, or stop the old server |
| The app's pages are empty | the intended starting state | Press **Run all live** / **Run demo F live**, or **Show saved results** in the sidebar |
| The sidebar says "No ML stack: replay only" | live server started without `.venv` | Start it with `.venv`'s Python, or use replay mode |

## 9. Rules for agents

- **Don't delete, move or regenerate** `demo/results/`, `demo/ckpt/`, `demo/data/`, `circuits/keys/` or
  `frontend/dist/`. They are the shipped results, the trained models and identities the proofs depend on, the data,
  the public verification keys and the built app.
- **Don't run** the `retrain` or `zk_hashed` (E3, needs about 32 GB of RAM) steps as part of a deployment. Both
  replace or need resources a deployment shouldn't touch.
- **Keep the server on 127.0.0.1.** Don't add a host option, port forwarding or a tunnel to expose it.
- **Don't commit or upload** `secrets/`, `.venv/`, `circuits/build/`, `tools/bin/` or anything in `demo/models/`.
- **Never pass `--trust`** to the SDK for a model file the user didn't make (it allows unsafe deserialisation).
- **ASK before** installing system-wide software, deleting anything outside the project folder, or any network
  access beyond the setup downloads listed in section 3.
- Don't edit `frontend/dist/` by hand. If the UI source changed, rebuild it (section 10).

## 10. Reference

**Folders**

| Path | What |
|---|---|
| `demo/` | `server.py` (the app server), demo scripts `01`–`10`, `results/` (what the pages show), `ckpt/` (models and demo identities), `data/` (MNIST), `models/` (drop the user's own models here) |
| `frontend/` | React + TypeScript UI source; `dist/` is the built app the server serves |
| `sdk/` | the `sigil` Python SDK and command line (`python -m sigil.cli --help`) |
| `circuits/` | `ownership.circom`, `keys/` (verification keys, setup transcripts), `build/` (proving keys, after setup), `onchain/` (Solidity verifier) |
| `contract/` | API types (`types.ts`) and fixtures, including the recorded logs replay mode plays back |
| `scripts/` | `setup_env.py`, `verify_deploy.py`, `make_share_zip.py`, `check_offline_build.py` |
| `docs/` | protocol specification, threat model, the user guide's source (`docs/guide/`) |
| `tests/`, `sdk/tests/` | automated tests |

**API** (all on `http://127.0.0.1:8765`; POST bodies are JSON with `Content-Type: application/json`)

| Endpoint | Purpose |
|---|---|
| `GET /api/state` | mode, environment (GPU/torch), every result the pages show, the current job |
| `GET /api/steps` | runnable steps: id, label, seconds, timeout, confirmation text |
| `GET /api/models` | the Model under test menu |
| `POST /api/run` `{"step": …, "tries"?: 20000\|100000, "model"?: id}` | start a step (one at a time; 409 if busy) |
| `GET /api/jobs/{id}`, `GET /api/jobs/{id}/stream` | a job's output (JSON, or server-sent events) |
| `POST /api/jobs/{id}/cancel` | stop a running job |

Steps: `evaluate`, `retrain`, `attacks`, `forgery`, `committed`, `zk`, `zk_hashed`, `protocol_v2`, `all`,
`verify_honest`, `verify_replay`, `verify_model`, `verify_tamper`, `verify_registry`, `model_test`. Details are in
`UI_INTEGRATION.md`.

**Tests**

```bash
.venv/bin/python -m pytest -q tests            # server and protocol, ~10 s   (Windows: .venv\Scripts\python)
.venv/bin/python -m pytest -q                  # everything incl. the SDK and zero-knowledge tests, ~2 min
```

**Rebuilding** (only needed after changing source)

- UI: `cd frontend && npm ci && npm run build`, then `python scripts/check_offline_build.py frontend/dist`.
- User guide PDF (Windows with Microsoft Edge; the app must be running in replay mode on port 8765):
  `.venv\Scripts\python docs\guide\build.py`.
- The shareable package: `.venv/bin/python scripts/make_share_zip.py` → `dist/owasp-wm-demo.zip` (built from the
  last git commit, plus the proving keys).

**Pinned versions:** Python 3.12 (in `.venv`), PyTorch 2.14.1, Node.js ≥ 20.19, SnarkJS 0.7.6, circomlib 2.0.5,
circom 2.2.3.
