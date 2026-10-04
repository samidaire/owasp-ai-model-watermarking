# Demo: committed-seed ZK ownership verification (MNIST, Uchida watermark)

Companion code for `../01_Literature_Gap_Analysis.md` and `../02_Demo_Plan_Tomorrow.md`.

## Web UI (primary)

Double-click `../Start-Demo-UI.cmd`. It starts `server.py` and opens http://127.0.0.1:8765.

- **`server.py`** uses the Python standard library only. It binds to 127.0.0.1, serves the built React app from `../frontend/dist`, and runs a whitelist of demo steps one at a time.
- **Same launch path as the CLI.** Steps run exactly like `run_all.py` (shared `demo_common.py`: interpreter, cwd, `HOME`/UTF-8 env, noise filter) and stream output to the browser over SSE.
- **Results come from JSON, not parsed text.** Each script writes `results/*.json` (`train`, `attacks`, `forgery`, `committed_seed`, `vk_crosscheck`, `ezkl_*/summary.json`), which the UI renders.
- **Stale detection.** Every result records the owner's SHA-256 commitment; the UI flags results made with an older key as **Stale**.
- **Steps.** `evaluate` re-verifies A without retraining. `retrain` and `zk_hashed` sit behind confirmations. `all` runs A (evaluate) → B → C → D → E1/E2.
- **Changing the frontend** (`../frontend`): `npm run dev` for hot reload (it proxies `/api` to this server), then `npm run build`. The server serves `dist/` as-is, so the meeting needs no npm.

## CLI (fallback)

PowerShell, from the `demo` folder (needs the ML venv; see "Setting up the ML environment" below):

```powershell
.\.venv\Scripts\python.exe run_all.py --ezkl
```

Git Bash, from `demo/`:

```bash
.venv/Scripts/python run_all.py --ezkl
```

- Uses the saved checkpoints in `ckpt/`. Takes **~26 s** on the RTX 5080.
- `--retrain` retrains every model first (+30 s on GPU, ~1.5 min on CPU).
- `--pause` waits for Enter between demos, for presenting.
- `--hashed` re-runs the Poseidon-committed proofs. Each takes ~1.5 min (calibrate ~16 s, setup ~34 s, prove ~40–47 s) and writes a ~10 GB temporary proving key, which is deleted afterwards.
- **No GPU?** The global `python` (CPU torch) runs `run_all.py` without `--ezkl`. EZKL is installed only in `.venv`.

## What each script shows

| Script | Demo | Shows |
|---|---|---|
| `00_env_check.py` | — | torch/CUDA/sm_120/VRAM, MNIST present |
| `01_train.py` | A | Owner commits SHA-256(seed‖owner) **at embedding time**; key *X* and signature *b* derived from the seed; trains clean, watermarked and 4 null models |
| `02_attacks.py` | B | SoK-style removal attacks: pruning, int8/int4, FTAL, RTAL, overwriting, **feature permutation** (+ owner realignment). Writes `results/attacks.png` |
| `03_forgery.py` | C | Counterfeit key gives the thief BER 0 ("MALLORY!"); KS test says it's indistinguishable; the same sign-fit satisfies **ZKROWNN's Algorithm 1 relation** on *any* model (evaluated in PyTorch, not their circuit) |
| `04_committed_seed.py` | D | D0 owner verifies; **D1** free signature: thief wins 100%; **D2** derived signature: thief's seed search accepted 0/20,000 (theory 2.8e-10 per try). Writes `results/forgery_search.png` |
| `05_ezkl_spike.py` | E1 | EZKL (Halo2/KZG) proof of extraction: private key+signature, public weights, public score |
| `06_vk_crosscheck.py` | E2 | **Thief's forged proof verifies under the owner's verification key** (no commitment) |
| `07_commitment_summary.py` | E3 | With Poseidon-hashed params, owner's hash matches the published value and the thief's doesn't. Also prints the cost. |

## Dry-run results (2026-10-05, RTX 5080)

| Item | Result |
|---|---|
| Accuracy, clean vs watermarked | 98.69% vs 98.66%; owner BER 0.000 (clean model 0.531) |
| Pruning 65% / 90% | Accuracy 65.7% / 9.4%; owner BER 0.000 / 0.016. The watermark outlives the model. |
| FTAL-5, RTAL-5, int4 | BER 0.000 |
| Overwrite (thief embeds own mark) | Owner BER 0.047 **and** thief BER 0.000: two valid marks, ambiguity again |
| Feature permutation | Accuracy unchanged, **owner BER 0.438: removed**. Owner realignment restores BER 0.000. |
| Forgery (Uchida and ZKROWNN relation) | Thief BER 0.000 on stolen, clean and null models. Entry KS D = 0.0104 < 0.0142. Large-margin forgery matches the owner's margins (min 1.43 vs 1.42). |
| D1 / D2 | 1000/1000 (true by construction) / 0/20,000 accepted (best thief BER 0.250); D2 work factor ~2^32 at T=64 (GPU-feasible), ~2^120 at T=256 |
| EZKL uncommitted (logrows 15) | prove 0.63 s, verify 20 ms, proof 60 KB, pk 132 MB, peak RAM 0.6 GiB |
| EZKL Poseidon-committed (logrows 20) | prove ~36 s, verify ~0.5–0.6 s, proof 65 KB, pk 9.8 GiB, sampled peak RAM 2.6 GiB |

Numbers vary slightly per retrain: the seed is random each time `01_train.py` runs.

## Caveats (say these out loud)

- **Not a calibrated false-positive rate.** θ = 8/64 is indicative. Four null models can't give a false-positive rate.
- **Demo C runs ZKROWNN's *relation*, not ZKROWNN's code.** ZKROWNN states a semi-honest prover, so the attack is outside its threat model.
- **E3 is the D1 level of the fix.** It commits to (*X*, *s*) directly. Deriving them from the seed inside the circuit (the D2 level) is Phase 3.
- **E3's "owner's commitment" is taken from the owner's own proof run.** In the protocol it is published at embedding time. It is **not yet linked** to the SHA-256 seed commitment from demo A.
- **The Poseidon hash covers parameters quantised at the calibrated scale** (13 here), so a real commitment must also pin the circuit settings.
- **The D2 security level is only ~2^32 at T=64** (GPU-feasible). Timestamps stay necessary; T=256 gives ~2^120.
- **EZKL needs `HOME`.** It panics if `HOME` is unset (PowerShell/cmd). The scripts set it automatically.
- **EZKL has no open-source licence file** (gap G5). Use it for research and demo only.
- **The SRS is downloaded once.** `get_srs` fetches it and it's cached in each `results/ezkl_*` folder. If you're offline with no cache, the script falls back to a TEST-ONLY SRS in a separate file and says so. The SRS files (129 MB each at logrows 20) aren't in git; they're downloaded on first use.
- **`ckpt/owner_secret.json` is the demo's "secret" seed.** It's committed so the saved results (D0, E3) stay reproducible. Anyone with the repo can produce the owner's proofs, so treat it as a demo value, never a real secret.

## Setting up the ML environment (live runs only)

UI work doesn't need this: `server.py` serves saved results with any Python 3 (tested with 3.14), and `--simulate` replays recorded runs. For live runs, from the `demo` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Without an NVIDIA GPU, install the CPU build instead (`pip install torch==2.14.1`); the MNIST demos still run, just more slowly. Versions are pinned in `requirements.txt`.
