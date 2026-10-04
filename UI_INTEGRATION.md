# UI Integration Guide: building a new front end for the watermark demo

This guide is for whoever builds a new UI for this project. It covers everything you need to replace the current React app with your own.

The backend is a small local HTTP API (`demo/server.py`). It serves your static UI build and hands it every result as JSON. It runs the demos on request and streams their console output live. **You don't need to read any Python to build a UI.** This document, `contract/types.ts` and the fixtures in `contract/fixtures/` are the whole contract.

The current UI in `frontend/` is a working reference implementation of everything described here.

---

## 1. Quick start (5 minutes, no GPU or ML install needed)

You need **Python 3** (standard library only; tested with Python 3.14) and the project folder.

```bash
# from the project folder
python demo/server.py --simulate          # or double-click Start-Demo-UI-Simulate.cmd (Windows)
# open http://127.0.0.1:8765
```

- **All saved results load.** That's every panel's data, from `demo/results/`.
- **"Run" buttons work in simulate mode.** They replay *recorded* console output from real runs, so you can build the running, streaming and done states. Nothing is executed and no results change.
- **`env.status` will be `"error"`** (no torch in your Python). That's expected for UI work.

To develop your UI with hot reload on another port, keep the server running and see §3.2.

---

## 2. Architecture

```
 Browser (your UI)                         demo/server.py  (Python stdlib, 127.0.0.1:8765)
 ─────────────────                         ──────────────────────────────────────────────
  GET  /               ───────────────────▶ static files from --ui DIR (default frontend/dist)
  GET  /api/state      ───────────────────▶ reads demo/results/*.json ──▶ one JSON object
  GET  /api/steps      ───────────────────▶ step catalogue (labels, durations, confirmations)
  POST /api/run {step} ───────────────────▶ starts ONE job ──▶ python demo/<script>.py …
  GET  /api/jobs/{id}/stream ◀── SSE ────── each console line, then "done"
  GET  /api/jobs/{id}  ───────────────────▶ job status + all output so far
  GET  /results/{file} ───────────────────▶ PNG/CSV/JSON/TXT from demo/results/
```

**The data flow is always the same:**
1. Load `/api/state` and render every panel from `state.results`.
2. On a user click, `POST /api/run`.
3. Stream the job's lines into a console.
4. When the `done` event arrives, fetch `/api/state` again and re-render.

The scripts write their results to `demo/results/*.json`; the server just reads those files. There's no database and no other endpoint.

---

## 3. Running the backend

### 3.1 Modes and flags

| Command | What it does |
|---|---|
| `python demo/server.py` | **Live mode.** Serves `frontend/dist`; runs execute the real demos. They need the ML venv (`demo/.venv`, see `demo/README.md`). |
| `python demo/server.py --simulate` | **Simulate mode.** Runs replay `contract/fixtures/logs/<step>.log`. Nothing executes, `results/` is untouched, and `/api/state` reports `"mode": "simulate"`. |
| `--ui PATH` (or env `DEMO_UI_DIR=PATH`) | Serve **your** static build from `PATH` instead of `frontend/dist`. |
| `--port N` | Default 8765. |
| `--open` | Open the browser at start-up. |
| `Start-Demo-UI.cmd [args]` | Windows launcher. Uses `demo\.venv` if present, otherwise `py -3`/`python`; passes extra args through. |
| `Start-Demo-UI-Simulate.cmd` | Same, with `--simulate`. |

Live runs started with a Python that has no torch fail with exit code 1, and the console shows the traceback. That's expected; use `--simulate` for UI work.

### 3.2 Two ways to plug in your UI

**A. Static build served by the backend (how the demo is presented).**
1. Build your app to static files: `index.html` plus assets.
2. Run `python demo/server.py --ui path/to/your/build`. Or replace the contents of `frontend/dist/`, so `Start-Demo-UI.cmd` picks it up with no flags.

Requirements:
- **Static only.** No server-side rendering or API routes of your own. Next.js needs `output: "export"`; SvelteKit needs `adapter-static`; Vite, CRA and Angular builds work as-is.
- **Base path `/`.** The app is served at the site root. Unknown paths return `index.html`, so client-side routing works.
- **Fully offline.** No CDN scripts, web fonts or analytics, because the demo room may have no internet. Bundle everything.
- **Same origin.** Use relative URLs (`/api/state`), so the build works on any port.

**B. Your own dev server (hot reload) talking to the backend.**
- **Option 1, a proxy.** Proxy `/api` and `/results` to `http://127.0.0.1:8765` (see `frontend/vite.config.ts`). Then your code uses the same relative URLs as in A.
- **Option 2, direct.** Call `http://127.0.0.1:8765/api/...` directly. The server answers CORS for **localhost and 127.0.0.1 origins on any port** (e.g. `http://localhost:3000`), including the preflight for `POST /api/run`. The reference UI reads an optional `VITE_API_BASE` for this.
- **Run the backend separately.** In both options, start the backend in its own terminal: `python demo/server.py --simulate`.

---

## 4. API reference (`api_version: 1`)

All responses are JSON, except the SSE stream and files. Types are in **`contract/types.ts`**, and real captured responses are in **`contract/fixtures/`**.

| Method & path | Purpose | Success | Errors |
|---|---|---|---|
| `GET /api/state` | Everything needed to render every panel | 200 `DemoState` | none |
| `GET /api/steps` | Step catalogue: what can be run, labels, durations, confirmations | 200 `StepsResponse` | none |
| `POST /api/run` | Start a demo step | 202 `JobInfo` | 400 bad step/tries · 403 foreign origin · 409 busy · 415 not JSON |
| `GET /api/jobs/{id}` | Job status and all output so far | 200 `JobDetail` | 404 unknown id |
| `GET /api/jobs/{id}/stream` | Live output (Server-Sent Events) | 200 `text/event-stream` | 404 unknown id |
| `GET /results/{file}` | Result files: `attacks.png`, `forgery_search.png`, `attacks.csv`, `run_log.txt`, `*.json` | 200 file | 404 |
| `GET /*` | Your static UI (SPA fallback to `index.html`) | 200 | 503 if no build |

### 4.1 `GET /api/state` → `DemoState`

```jsonc
{
  "api_version": 1,
  "mode": "live",                        // or "simulate": show a visible banner in simulate mode
  "env": { "status": "ok", "gpu": "NVIDIA GeForce RTX 5080", "sm": "sm_120",
           "torch": "2.14.1+cu130", "cuda": "13.0", "python": "3.14.0", "vram_gib": 15.9 },
  "commitment": "38751689ba3d…",         // owner's current SHA-256 seed commitment (staleness, §7)
  "results": {
    "train": { … },  "attacks": { … },  "forgery": { … },  "committed_seed": { … },
    "vk_crosscheck": { … },
    "ezkl": { "private_owner": { … }, "private_thief": { … }, "hashed_owner": { … }, "hashed_thief": { … } }
  },
  "job": { "id": "b44c5420d32c", "step": "all", "running": false, "code": 0,
           "started": 1791143395.46, "ended": 1791143421.69, "lines": 211 }   // or null
}
```

- **Any result may be `null`** if that step has never run. Render an empty state with a Run button.
- **`env.status`** is `"probing"` for a few seconds after start-up. Poll `/api/state` every ~2 s until it changes to `"ok"` or `"error"`.
- **`job`** is the most recent job, or `null`. If `job.running` is true on page load (e.g. the user reloaded mid-run), re-attach to `/api/jobs/{id}/stream`.

### 4.2 `GET /api/steps` → `StepsResponse`

The live catalogue is in `contract/fixtures/steps.json`.

| `id` | Panel | ~seconds | `confirm` | Writes |
|---|---|---|---|---|
| `evaluate` | A | 5 | — | `train.json` |
| `retrain` | A | 35 | **yes**: replaces the owner key; B–E go stale | `public_commitment.json`, `train.json` |
| `attacks` | B | 10 | — | `attacks.json`, `.csv`, `.png` |
| `forgery` | C | 3 | — | `forgery.json` |
| `committed` | D | 3 | — (option `tries`: 20000 or 100000) | `committed_seed.json`, `forgery_search.png` |
| `zk` | E | 10 | — | `ezkl_private_*/summary.json`, `vk_crosscheck.json` |
| `zk_hashed` | E | 200 | **yes**: ~3 min, ~10 GB temporary disk | `ezkl_hashed_*/summary.json` |
| `all` | `*` | 30 | — | evaluate → attacks → forgery → committed → zk |

- **`confirm`.** When it's non-null, show its text and require a confirmation before POSTing. These steps are destructive or slow.
- **Labels and durations.** Use `label` and `seconds` for buttons and for "this takes ~N s" hints.

### 4.3 `POST /api/run`

```http
POST /api/run
Content-Type: application/json

{"step": "committed", "tries": 20000}
```

| Field | Required | Notes |
|---|---|---|
| `step` | yes | One of the `id`s above. |
| `tries` | no | `committed` only: 20000 or 100000. Default 20000. |

- **202** returns the new `JobInfo`. Start streaming it.
- **409** means a job is already running: `{"error": "another demo is running", "job": JobInfo}`. **Only one job runs at a time.** Disable all Run buttons while any job is running (`state.job.running`).
- **415** means you didn't send `Content-Type: application/json`. Use `fetch` with that header; HTML form posts are rejected deliberately (§10).

### 4.4 `GET /api/jobs/{id}/stream`: Server-Sent Events

The raw stream looks like this:

```
id: 0
data: "$ python 03_forgery.py"

id: 1
data: ""

id: 2
data: "  DEMO C, part 1: Uchida ambiguity attack (thief has only the stolen weights)"

: keepalive

event: done
data: {"id": "bc32eea65dd4", "step": "forgery", "running": false, "code": 0, "started": …, "ended": …, "lines": 44}
```

- **Each output line** is one unnamed event. `data` is a **JSON-encoded string** (so `JSON.parse(e.data)`), and `id` is its 0-based line index.
- **A `done` event** is sent once the job ends. Its `data` is the final `JobInfo`: `code: 0` means success, anything else means failure. After it, the server closes the stream. Close your `EventSource` and refetch `/api/state`.
- **`: keepalive`** comments arrive every ~10 s while a job is quiet. Browsers ignore them.
- **Reconnects resume.** If the connection drops, `EventSource` reconnects automatically and sends `Last-Event-ID`. The server then resumes after that line, with no duplicates. Opening a new stream without that header replays from line 0.
- **The job keeps running** if no one is listening. `GET /api/jobs/{id}` returns `output: string[]` with everything so far.
- **Lines are plain text** from the demo scripts. They're already filtered for known harmless noise, and they may contain box-drawing characters (`====`). Render them in a monospace `<pre>` with `textContent`, **never as HTML**.

Minimal client:

```js
const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify({ step: "forgery" }) });
const job = await res.json();                       // check res.status === 202 first
const es = new EventSource(`/api/jobs/${job.id}/stream`);
es.onmessage = (e) => console.log(JSON.parse(e.data));
es.addEventListener("done", async (e) => {
  es.close();
  const info = JSON.parse(e.data);                  // info.code === 0 means success
  const state = await (await fetch("/api/state")).json();   // re-render from fresh state
});
```

### 4.5 `GET /results/{file}`

These are optional static images if you'd rather show the matplotlib figures than draw charts:
- `/results/attacks.png`: pruning curves and the attack bars;
- `/results/forgery_search.png`: the D2 histogram;
- `/results/run_log.txt`: the last CLI run.

The JSON in `/api/state` carries the same data, so you can draw interactive charts instead.

---

## 5. Job lifecycle

```
idle ──POST /api/run──▶ running (state.job.running = true; stream lines)
                           │
                           └─ "done" event ──▶ finished (code 0 = ok, else failed) ──▶ refetch /api/state ──▶ idle
```

- **While running:**
  - keep showing the previous results, dimmed, for the affected panel;
  - show a spinner on that panel;
  - disable every Run button;
  - stream lines into a console.
- **On failure** (`code != 0`): keep the old results and show the last console lines. Never blank a panel.
- **Robustness:** while a job runs, also poll `/api/state` every ~5 s, in case the stream drops behind a proxy.

---

## 6. Where each panel's data comes from

The fields below are exactly what the reference panels in `frontend/src/panels/` read. JSON paths are relative to `state.results`.

### Panel A: Commit & embed (`results.train`, steps `evaluate` / `retrain`)

| JSON path | Shown as |
|---|---|
| `train.commitment`, `train.timestamp_utc`, `train.owner_id`, `train.key_shape` | "Published commitment" card |
| `train.models.clean.accuracy`, `train.models.watermarked.accuracy` | Two stat tiles, plus the difference in percentage points |
| `train.signature_bits` (64 × 0/1) | Bit grid: the owner's signature |
| `train.models.{watermarked,clean}.extracted_bits` vs `signature_bits` | Bit grids with mismatches marked; `owner_ber` beside each |
| `train.threshold` | `owner_ber <= threshold` → "ownership shown", else "no match" |
| `train.nulls[] {name, accuracy, owner_ber}` | Null-model table ("correctly not claimed" when `owner_ber > threshold`) |

### Panel B: Removal attacks (`results.attacks`, step `attacks`)

| JSON path | Shown as |
|---|---|
| `attacks.rows[]` with `family` `baseline` or `prune` | Two line charts vs pruning %: `accuracy` and `owner_ber`. The % is parsed from `attack` (e.g. `"prune 65%"`); the baseline is 0%. |
| `attacks.rows[]`, all other families | Table: `attack`, `family`, `accuracy`, `owner_ber`, and a verdict from `survives` |
| `attacks.threshold` | Threshold line on the BER chart |
| rows `"feature permutation"` and `"permutation + owner realign"` | Callout: removed at zero accuracy cost; realignment restores it |
| row with `family == "overwrite"` | Callout: two watermarks coexist (ambiguity) |

`family` takes the values `baseline`, `prune`, `quantise`, `finetune`, `overwrite` and `permute`.

### Panel C: Ownership forgery (`results.forgery`, step `forgery`)

| JSON path | Shown as |
|---|---|
| `forgery.owner.{ber, extracted_bits, signature_bits}` | The owner's claim card, with a bit grid |
| `forgery.thief.{ber, message, extracted_bits, target_bits, target_text}` | The thief's claim card; `message` is `"MALLORY!"` |
| `forgery.key_stats[] {key, entry_mean, entry_std, ks_d, min_margin, median_margin}`, `forgery.ks_critical`, `forgery.large_margin_ber` | Key-statistics table and footnote |
| `forgery.never_watermarked[] {model, thief_ber}` | "False claim works" table |
| `forgery.zkrownn.{xkey_shape, a_shape, rows[] {model, satisfied, ber}}` | ZKROWNN relation table |

### Panel D: Committed seed (`results.committed_seed`, step `committed`)

| JSON path | Shown as |
|---|---|
| `d0.{commitment_matches, owner_ber, verified}` | D0 card |
| `d1.{wins, trials}` | D1 hero number "1,000/1,000" (holds **by construction**) |
| `d2.{accepted, tries, min_ber, seconds}` | D2 hero number "0/20,000" plus a caption |
| `d2.histogram[] {ber, count}` (65 bins, `ber = k/64`) | Histogram, with markers at `threshold` and `d0.owner_ber` |
| `d2.p_per_try`, `d2.log2_work`, `d2.seeds_for_half`, `d2.single_core_hours`, `d2.seeds_per_s`, `d2.log2_work_T256`, `signature_bits_T` | Four stat tiles plus a warning callout |
| `nulls[] {model, owner_ber}` | Null-check table |

### Panel E: Zero-knowledge proofs (`results.ezkl`, `results.vk_crosscheck`, steps `zk` / `zk_hashed`)

| JSON path | Shown as |
|---|---|
| `ezkl.private_owner`, `ezkl.private_thief` → `verified`, `public_outputs[0][0]` (score, a string), `seconds.prove`, `seconds.verify`, `proof_bytes`, `pk_bytes`, `peak_rss_bytes`, `logrows`, `srs` | E1 proof cards (owner and thief) |
| `vk_crosscheck.{owner_vk, thief_vk, identical, thief_verified_under_owner_vk}` | E2 card: the thief's proof verifies under the owner's key |
| `ezkl.hashed_owner.param_commitment_poseidon[0][0]` | "Owner's commitment" (in the demo it's taken from the owner's run) |
| `ezkl.hashed_{owner,thief}.{verified, param_commitment_poseidon}` | E3 table: **accept** only when `verified` is true **and** the hash equals the owner's |
| `ezkl.{private,hashed}_owner.{seconds, proof_bytes, pk_bytes, peak_rss_bytes, logrows}` | RQ3 cost table. The literature rows are hard-coded constants in `PanelE.tsx`. |

### Header

| Field | Shown as |
|---|---|
| `env.gpu`, `env.sm`, `env.torch`, or `env.status` | GPU badge |
| `commitment` | Owner-commitment chip (first 12 characters) |
| `mode` | A banner when `"simulate"` |

---

## 7. Staleness rule

Every result records the owner commitment that was current when it was produced:
- `train.commitment`, `attacks.commitment`, `forgery.commitment`, `committed_seed.commitment`, `vk_crosscheck.commitment`;
- `ezkl.*.commitment` (optional; older files may lack it).

**A result is stale when its `commitment` exists and differs from `state.commitment`.** This only happens after a `retrain`. Show a "Stale: re-run" badge; don't hide the data. If the field is missing, treat the result as fresh.

---

## 8. Copy that must survive a redesign

These statements are what the project defends in front of examiners. A new UI may reword them, but **it must not drop or contradict them**. Each one corrects an overclaim that was caught in review.

1. **θ = 8/64 is indicative.** The handful of null models is not a calibrated false-positive rate.
2. **Demo C runs ZKROWNN's *relation* (Algorithm 1) in PyTorch, not ZKROWNN's code.** ZKROWNN assumes a semi-honest prover, so the attack is outside its stated threat model. Present it as "our analysis, demonstrated", not as a bug in their paper.
3. **"Entry distributions match a real key; under ZK the verifier sees neither."** Don't say "statistically indistinguishable" without that qualifier.
4. **D1's 1000/1000 holds by construction,** not as a measured rate.
5. **D2 is only about 2³² work at T = 64.** That's feasible on a GPU, so timestamps still matter. The target is about 2¹²⁰ at T = 256.
6. **E3 is the D1 level of the fix.** It commits to (key, signature) directly. Its "owner's commitment" is taken from the owner's run (in the protocol it's published at embedding time), and it is **not yet linked** to the SHA-256 seed commitment from demo A. Deriving the key in-circuit is Phase 3.
7. **Peak RAM figures are sampled.**
8. **Literature cost rows (ZKROWNN, RoSeMary) are orders of magnitude only.** They use different circuits, proof systems and hardware.
9. **EZKL has no open-source licence file.** Research and demo use only.

The current wording lives in each panel's "Presenter notes" and callouts (`frontend/src/panels/*.tsx`) and in `02_Demo_Plan_Tomorrow.md` §3.

---

## 9. Design notes from the reference UI (optional but recommended)

- **Charts are hand-built SVG** in `frontend/src/components/charts.tsx`. There's no chart library and nothing loads from the network.
- **Colours** are validated for colour-vision deficiency in light and dark (`frontend/src/styles.css` tokens).
- **Status is never colour alone.** Every verdict chip has an icon and a label.
- **Presenter-friendly navigation.** ← → and PageUp/PageDown move between panels, so a presentation clicker works.
- **Projector.** A light theme is available; projectors wash out dark themes.
- **Never blank a panel.** Saved results render immediately on load. A failed or slow run must not empty a panel.

---

## 10. Security model (please keep it)

The server runs code on the presenter's machine. It's deliberately locked down:
- **Local only.** It binds to `127.0.0.1`.
- **Host check.** Requests whose `Host` isn't localhost are rejected (403), which blocks DNS rebinding.
- **Origin check.** `POST /api/run` rejects foreign `Origin`s (403) and requires `Content-Type: application/json` (415). Other websites can't trigger runs.
- **CORS.** It's only answered for `localhost` / `127.0.0.1` / `[::1]` origins, never `*`.
- **Whitelisted steps.** Only the steps listed above run; no request field ever reaches a shell.

If your UI needs something the API doesn't provide, add a read-only endpoint. Don't loosen these checks.

---

## 11. Contract files

| Path | What |
|---|---|
| `contract/types.ts` | TypeScript types for every response. The reference UI imports these directly. |
| `contract/fixtures/state.json` | A real `/api/state` response (live mode, all results present) |
| `contract/fixtures/steps.json` | A real `/api/steps` response |
| `contract/fixtures/job.json` | A real `/api/jobs/{id}` response (output truncated) |
| `contract/fixtures/logs/<step>.log` | The exact lines the server streamed for each step during a real run (used by `--simulate`). `retrain.log` is hand-maintained and labelled, because running `retrain` would replace the owner key. |
| `contract/capture_fixtures.py` | Re-records the fixtures from a live server |
| `contract/examples/minimal-ui/index.html` | A ~120-line vanilla-JS UI built only from this guide. Try it with `python demo/server.py --simulate --ui contract/examples/minimal-ui`. |

You can also build against the fixtures with no server at all: import `state.json` as mock data.

---

## 12. Hand-back checklist

- [ ] `python demo/server.py --simulate --ui <your build>` loads with **no network access**, and no console errors.
- [ ] Every panel renders from `state.results` on load; `null` results show an empty state with a Run button.
- [ ] One run of each step streams to completion; panels refresh afterwards; Run buttons are disabled while a job runs.
- [ ] `retrain` and `zk_hashed` ask for confirmation (text from `/api/steps`).
- [ ] A 409 response shows a message rather than crashing.
- [ ] Stale results show a badge (§7). To test, temporarily edit `demo/results/attacks.json` → `"commitment": "x"`, then put it back.
- [ ] Simulate mode shows a visible banner.
- [ ] Everything in §8 is still said somewhere on screen.
- [ ] It works at 1920×1080 on a projector (light theme) and on a 1366×768 laptop.
- [ ] Build output goes into `frontend/dist/` (or pass `--ui`), and `Start-Demo-UI.cmd` serves it.
