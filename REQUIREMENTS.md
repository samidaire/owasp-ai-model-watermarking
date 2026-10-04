# Requirements: completing the AI Model Watermarking project

**Version 1.0 · 2026-10-05 · Owner: Sami Daire (project lead)**

This document says **what** must be built. [WORKFLOW.md](WORKFLOW.md) says **how, when and by whom**.

**Sources:**
- The SOP (Statement of Purpose; Role Distribution updated 2026-10-05).
- The review of the current build (2026-10-05).
- [UI_INTEGRATION.md](UI_INTEGRATION.md) and [01_Literature_Gap_Analysis.md](01_Literature_Gap_Analysis.md).
- The UI design canvas, "Sigil · Cocoa Pop" (private; ask the project lead for access).

---

## 1. Goal and definition of done

The project moves through three phases, in order:

1. **Complete and correct the build** so that it delivers everything the SOP promises, and every claim it makes is true.
2. **Update the UI design** (design canvas) so it covers everything Phase 1 adds.
3. **Migrate the frontend** to that design.

A phase is done when its exit gate in [WORKFLOW.md](WORKFLOW.md) passes. The project as a whole is **complete against the SOP** when:
- every **MUST** requirement below is *Done*: acceptance criteria met, tested, documented and reviewed;
- every SOP line in the traceability matrix (§16) maps only to *Done* requirements.

## 2. Conventions

- **IDs** have the form `AREA-NN`:

  | Area | Covers |
  |---|---|
  | FIX | Corrections to the existing build |
  | WM | Watermarking |
  | CR | Cryptography, identity and secrets |
  | ZK | Zero-knowledge proofs |
  | ROB | Robustness and evaluation |
  | SDK | Python SDK and CLI |
  | API | Backend API |
  | DB | Database |
  | NFR | Non-functional requirements |
  | UD | UI design (Phase 2) |
  | UM | UI migration (Phase 3) |

- **Priority:**
  - **MUST**: needed for SOP completeness or for correctness.
  - **SHOULD**: expected by examiners, or a large improvement.
  - **COULD**: stretch goal; only after the Phase 1 gate.
- **Owner** is the person accountable; anyone can contribute.

  | Initials | Person | Role |
  |---|---|---|
  | **SD** | Sami Daire | Lead; ZK and verification; integration |
  | **MA** | Mohamed Ansari | AI and watermarking; robustness |
  | **AS** | Arfat Shaikh | Frontend and integration; SDK packaging |
  | **YB** | Yash Bandiwadekar | Backend: FastAPI, PostgreSQL, APIs |

- **Status** lives in the issue tracker. Each issue title starts with its requirement ID (e.g. `ZK-03: enforce θ in-circuit`).

## 3. Baseline (what exists on 2026-10-05)

**Sound and kept:**
- Uchida white-box watermark on an MNIST CNN: T = 64, conv2 layer, M = 288. Accuracy goes from 98.69% to 98.66%.
- Removal-attack demo: pruning, int8/int4, FTAL/RTAL, overwrite, permutation.
- Ownership-forgery demo against ZKROWNN's relation.
- Committed-seed defence, D0–D2. Its statistics re-derive correctly.
- EZKL proofs, E1–E3.
- A security-hardened local server and a React + TypeScript UI.
- A verified literature review.

**Missing against the SOP:**
- TensorFlow/Keras and ONNX watermarking.
- Circom + SnarkJS.
- An installable, framework-agnostic SDK.
- Compression and model-extraction tests.
- FastAPI, PostgreSQL, Tailwind.
- Model registration, verification history, deployment monitoring, audit reporting.
- RSA/ECC owner identity.

**Known defects:** §5.

## 4. Decisions to confirm (before Phase 1, milestone M2)

| ID | Decision | Recommended default | Why | Decided by |
|---|---|---|---|---|
| DEC-01 | ZK backend | **Circom 2 + SnarkJS (Groth16)** as the primary backend; keep EZKL only as a research-comparison backend | The SOP names Circom and SnarkJS. They're GPL-3.0 licensed, whereas EZKL has no licence. Groth16 proofs are a few hundred bytes. | SD + guide |
| DEC-02 | Key derivation | Derive the key **X ∈ {−1,+1}^(T×M)** with a Poseidon-based PRG, replacing numpy's Gaussian generator | The key can then be re-derived inside the circuit (the D2 level), and it no longer depends on the numpy version. Parity must be shown first (WM-02). | SD + MA |
| DEC-03 | Signature length | T = 64 for the live demo; **T = 256** as the security configuration | Seed-search work is about 2^32 at T = 64 versus about 2^120 at T = 256 | SD + MA |
| DEC-04 | Models | MNIST CNN for the live demo; **CIFAR-10 ResNet-18** (PyTorch) for evaluation; one **Keras CNN** for TensorFlow coverage | Fast demo, credible evaluation, SOP framework coverage | MA |
| DEC-05 | Owner identity | **Ed25519** signatures (ECC, per the SOP's "RSA / ECC") | Small, fast, well supported by `cryptography` | SD |
| DEC-06 | Database | **PostgreSQL 16**; SQLite for unit tests only | The SOP names PostgreSQL | YB |
| DEC-07 | Product/package name | Working name **`sigil`** (matches the design); renamed in one place if changed | One name across SDK, CLI and UI | Team |
| DEC-08 | Licence | Apache-2.0 for the SDK, backend and frontend; **GPL-3.0 for `circuits/`**, because circomlib is GPL-3.0 | Clean OWASP contribution path | Team + guide |
| DEC-09 | Scope statement | Present the project as the SOP **plus** a research contribution (forgery study, committed seed, RQ1–RQ3); send the guide a short SOP addendum | The build already goes beyond the SOP in research depth | SD |
| DEC-10 | Timestamps | The registry signs timestamps, which works offline; add an optional RFC 3161 token when online | The demo room may have no internet | SD + YB |

Record each decision here with **"Confirmed on <date>"** once agreed.

---

## 5. FIX: corrections to the existing build

Each row comes from the 2026-10-05 review. File references are to the current repo.

| ID | Problem (evidence) | Required change | Pri | Owner |
|---|---|---|---|---|
| FIX-01 | The D2 work factor is shown **3,600× too high**. `single_core_hours` stores seconds (`demo/04_committed_seed.py:106`), and the UI shows "257,463 core-hours" (`frontend/src/panels/PanelD.tsx:71`). | Store hours, or rename the field to `single_core_seconds` and convert in the UI. Add a unit test. *Accept:* the UI shows about 71 core-hours for the saved run. | MUST | MA |
| FIX-02 | The ZK verifier checks only that a proof is valid (`demo/06_vk_crosscheck.py:33-42`, `demo/07_commitment_summary.py:20`). It doesn't check the public score, or that the public `w` is the suspect model's. | Check every public signal: score or threshold, model binding, commitment. Do this now in the EZKL path; the Circom pipeline does it through ZK-06. *Accept:* a test shows an owner proof with score 0 is rejected, and so is a proof made on a different model. | MUST | SD |
| FIX-03 | The owner's key X and signature s are **readable inside** `demo/results/ezkl_*_owner/extract.onnx`. The signature bits are also served in `train.json` and `forgery.json`. | Export the circuit model with the key and signature as inputs, not initializers. Delete the leaked files (and purge them from history once git exists). Never write secrets under `results/`. Show owner-only fields only in owner views. *Accept:* a test scans every artefact for key bytes and finds none. | MUST | SD |
| FIX-04 | **The owner ID can be ground.** X depends only on the seed (`demo/wm_core.py:126-129`), while the signature depends on an unauthenticated `owner_id`, so a thief can try many IDs cheaply. | Derive both X and the signature from (seed, owner public key), and authenticate the key (CR-01, CR-02, CR-06). Re-measure the D2 cost with grinding included. | MUST | SD |
| FIX-05 | **The commitment is under-specified:** <br>• no T, layer, M, normalisation, scale or θ <br>• inputs joined with `"\|"` <br>• the numpy generator is version-dependent <br>• D0 never checks `owner_id` against the public record (`demo/04_committed_seed.py:38`) | Implement protocol v2 (CR-06). | MUST | SD |
| FIX-06 | The ZK circuit accepts only a perfect 64-bit match. That is stricter than θ = 8/64, so the overwrite case (3 flipped bits) fails the proof, and there's no ZK acceptance rule. | The circuit enforces the same θ as the BER test (ZK-03). | MUST | SD |
| FIX-07 | **Doc numbers don't match the saved results:** <br>• E3 proving time: "~36 s" in the docs, 46.9 s and 39.1 s saved <br>• E1: "0.63 s" in the docs, 0.663 s and 0.671 s saved <br>• `run_log.txt` comes from a different run than the JSON (FTAL-5, RTAL and overwrite accuracies; seeds/s) | Regenerate every result in one run. Generate doc tables from the results JSON (NFR-08). Save the thief's post-overwrite BER in JSON. | MUST | MA |
| FIX-08 | **The novelty is overstated** (`02_Demo_Plan_Tomorrow.md:133`, `01_Literature_Gap_Analysis.md:135`). Prior work exists:<br>• Adi et al., USENIX Security 2018: committed trigger set, timestamped, with a ZK argument<br>• Li et al., arXiv:1910.01226: RSA signature and timestamp, then SHA-256-derived watermark<br>• NeuralMark, AAAI 2026, arXiv:2507.11137<br>• FedZKP, arXiv:2305.04507 | Cite these. Restate the contribution narrowly: a SNARK-verified Uchida extraction, with key and signature derived in-circuit from a committed seed, plus measured forgery, robustness and cost results. | MUST | SD |
| FIX-09 | "OWASP R1/R2" reads as OWASP's own numbering (`01_Literature_Gap_Analysis.md:12`, `02_Demo_Plan_Tomorrow.md:15`, `README.md:9`). The README title could read as official OWASP work. | Say "project requirements R1/R2, derived from the OWASP AI Exchange #MODEL WATERMARKING text". Make clear this is a student project aligned with the OWASP incubator project. | MUST | SD |
| FIX-10 | **Wording errors:** <br>• wrong paper labels at `01_Literature_Gap_Analysis.md:269` <br>• "indistinguishable" at `demo/README.md:43`, which breaks §15 rule 3 <br>• the ZKROWNN forgery nuance at `01_Literature_Gap_Analysis.md:107` | Correct the wording. | SHOULD | SD |
| FIX-11 | **Server robustness:** <br>• the job thread has no try/finally (`demo/server.py:109-131`), so one crash means permanent 409s <br>• no cancel or timeout <br>• a non-object JSON body crashes the handler (`:313-314`) <br>• `/results/*` is cached for 1 h (`:245`) <br>• simulate mode ignores `tries` <br>• the GPU probe hides stderr <br>• result writes aren't atomic (`demo/demo_common.py:27`, `demo/05_ezkl_spike.py:167`) <br>• `current_commitment()` isn't guarded | Fix in the current server now, since it's the demo server until M6. Carry the fixes into API-04. | MUST | YB |
| FIX-12 | `retrain` writes the new commitment and secret **before** training (`demo/01_train.py:38-39`). A failed run destroys the demo seed. | Write to temp files and swap on success. Back up the previous secret. Keep the confirmation dialog. | MUST | MA |
| FIX-13 | **UI fragility:** <br>• the UI can stick on "Running" (`frontend/src/api.ts:29` has no `onerror`; a 409 is never attached to the running job; the poll only matches the same id, `frontend/src/App.tsx:139-190`) <br>• the console covers the bottom of panels (`frontend/src/styles.css:119,259-266`) <br>• no ErrorBoundary <br>• the sidebar's E stale logic differs from the panel's (`App.tsx:80-88` vs `PanelE.tsx:37`) <br>• `isStale` is false when the commitment is null (`api.ts:41`) <br>• confirmation texts are hard-coded instead of read from `/api/steps` <br>• no `aria-live` | Fix in the current UI; it stays the demo UI until the Phase 3 cutover. | MUST | AS |
| FIX-14 | `contract/types.ts` lacks `public_param_hashes`. `frontend/README.md` says the types live in `src/api.ts`. | Update both. | SHOULD | AS |
| FIX-15 | **Repo hygiene:** <br>• no LICENSE, tests or CI <br>• torch and the Python version aren't pinned; no Node version stated <br>• Windows-only instructions <br>• personal paths in the served `demo/results/run_log.txt:142` and in `02_Demo_Plan_Tomorrow.md:53` | Scrub the paths now. The rest is covered by NFR-02, NFR-06, NFR-07 and NFR-09. | MUST | YB |
| FIX-16 | **Robustness method gaps:** <br>• no recovery fine-tuning after pruning <br>• single runs <br>• quantisation simulated per tensor (`demo/02_attacks.py:41-47`) <br>• permutation never followed by fine-tuning <br>• realignment uses the exact original | Covered by ROB-01 and ROB-04. | MUST | MA |
| FIX-17 | Proofs carry no claimant identity or nonce, so they can be replayed. | Make the owner key hash and a claim nonce public inputs (ZK-03). | SHOULD | SD |

---

## 6. WM: watermarking core and frameworks

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| WM-01 | Uchida white-box embedding as a library function. It works on any named conv or linear layer, with T ∈ {64, 128, 256} and λ configurable. It is not hard-coded to `Net.conv2` (`demo/wm_core.py:104`). | Embeds into the MNIST CNN and ResNet-18 at T = 64 and T = 256; the owner's BER on the watermarked model is 0. | MUST | MA |
| WM-02 | Key and signature derived per protocol v2 (CR-06): a Poseidon PRG and a ±1 key. | **Parity study before switching:** over 5 seeds on MNIST, the ±1 key matches the current Gaussian key in accuracy cost and owner BER (within the standard deviation), and in survival across the B attack suite. | MUST | MA + SD |
| WM-03 | PyTorch adapter. Embed through a regulariser hook in the user's own training loop, plus a fine-tune helper. Extract from an in-memory module or from a `.pt` file loaded with `weights_only=True`. | Unit tests on both models; no use of pickle on untrusted files. | MUST | MA |
| WM-04 | TensorFlow/Keras adapter. Embed through a custom regulariser or callback. Extract from `.keras` and `.h5` files. | A Keras CNN is watermarked with BER 0 and an accuracy cost within WM-09. | MUST | MA |
| WM-05 | ONNX support: extract and verify from the `.onnx` initializers of a named layer. **Canonical weight ordering** across frameworks (PyTorch OIHW vs Keras HWIO). | PyTorch→ONNX and Keras→ONNX exports give the **identical** extracted bits as the source model. | MUST | MA |
| WM-06 | Black-box **trigger-set** watermark (Adi et al. 2018) whose trigger set is committed: its hash is registered. This covers model extraction (OWASP limitation L1). | Trigger accuracy is reported on extracted copies (ROB-03), alongside its null-model false-positive rate. | SHOULD | MA |
| WM-07 | **Null-model calibration of θ:** at least 30 null models on MNIST and at least 10 on CIFAR-10. | False-positive rate reported with a Clopper–Pearson 95% upper bound; θ chosen and documented per configuration. | MUST | MA |
| WM-08 | The detection API returns BER, matched bits, θ, a decision and a config hash, and **no secret material**. | Schema documented; covered by the secret-scan test (CR-04). | MUST | MA |
| WM-09 | Accuracy-cost targets at T = 256: at most 0.5 percentage points on MNIST and at most 1.0 on CIFAR-10 ResNet-18. | Mean ± std over at least 5 seeds; a target that's missed is reported honestly, not hidden. | MUST | MA |
| WM-10 | Embedding in biases or activations (DeepSigns-style), as the SOP's methodology mentions. | Prototype plus a comparison table. | COULD | MA |
| WM-11 | LLM fingerprint on a model of 3B parameters or fewer (gap G6). | Spike report. | COULD | MA |

## 7. CR: commitment, identity and secrets

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| CR-01 | The owner's identity is an **Ed25519** key pair. The private key is stored encrypted, using a key derived from a passphrase (scrypt or Argon2id) and AES-GCM or similar from `cryptography`. | Generate, export the public key, sign, verify; a wrong passphrase fails cleanly. | MUST | SD |
| CR-02 | **Registration record:** canonical JSON (RFC 8785) containing schema version, owner public key, commitment C, config hash, the watermarked artefact's `model_sha256`, and `created_at`. **Signed by the owner key.** | Verifies offline; any changed byte fails verification. | MUST | SD |
| CR-03 | **Timestamps:** the registry signs (record hash, time) with its own key, and the earliest valid registration wins a dispute. An optional RFC 3161 token is added when online. | The dispute test with owner-first and thief-later registrations picks the owner. | MUST (RFC 3161: SHOULD) | SD + YB |
| CR-04 | **Secrets** (seed, owner private key, X, s) never appear in `results/`, logs, ONNX/zkey/witness files, API responses or git. `secrets/` is gitignored. The only exception is the labelled demo seed in `demo/ckpt/owner_secret.json`. | CI runs a secret scan (e.g. gitleaks), plus a test that searches every artefact for key bytes. | MUST | SD |
| CR-05 | **Hashing:** SHA-256 for files, artefacts and the audit chain. Poseidon (BN254) for the in-circuit commitment and the PRG. The Python Poseidon is **bit-exact** with circomlib. | The test vectors match circomlibjs. | MUST | SD |
| CR-06 | **Protocol spec v2** in `docs/protocol.md`, defined once:<br>• a uniform seed of at least 128 bits<br>• domain-separated derivations: X = PRG(Poseidon("key", seed, pk_hash)) → ±1; b = bits(Poseidon("sig", seed, pk_hash))[:T]; C = Poseidon(seed, pk_hash, config_hash)<br>• `config_hash` pins T, layer, M, normalisation, fixed-point scale, θ and the PRG version<br>• versioned, with test vectors | Python and Circom produce identical outputs on all the test vectors. | MUST | SD |

## 8. ZK: zero-knowledge proofs (Circom + SnarkJS)

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| ZK-01 | The circuit `circuits/ownership.circom`, parameterised by T, M and scale, using circomlib.<br>**Private inputs:** seed, quantised `w`.<br>**Public inputs:** C, H(w_q), pk_hash, config_hash, claim nonce.<br>**Constraints:** C opens correctly; X and b are derived in-circuit; matches m = Σ[sign(X·w)ᵢ = bᵢ]; **m ≥ T − ⌊θT⌋**. | A valid owner proof verifies for the MNIST T = 64 configuration; the constraint count is recorded. | MUST | SD |
| ZK-02 | A **Python reference implementation** of the exact statement: same quantisation, same PRG, same tie handling. | At least 20 test vectors (including zero entries and ties) agree with the circuit's witness. | MUST | SD |
| ZK-03 | The circuit's acceptance rule uses the **same θ** as WM-07. The claim nonce and pk_hash are public, so a proof can't be replayed for another claim. | The overwrite case with 3 flipped bits passes if θ allows it; a replay with a different nonce fails. | MUST | SD |
| ZK-04 | **Trusted setup is scripted:** Groth16 using a public Powers of Tau file of adequate size (e.g. `powersOfTau28_hez_final_<k>.ptau`), with a phase-2 contribution whose transcript hash is recorded. Artefacts are cached for offline use, and the trust assumption is documented. | A clean machine reproduces the setup from the script alone. | MUST | SD |
| ZK-05 | Prove and verify through SnarkJS, wrapped by the SDK. Rapidsnark is optional for speed. | `sigil prove` and `sigil verify` work end to end. | MUST (rapidsnark: COULD) | SD |
| ZK-06 | **The verification procedure** is SnarkJS verify **and** all of these checks:<br>• C is registered, with a valid owner signature and a timestamp earlier than the claim<br>• H(w_q) recomputed from the suspect model equals the public signal<br>• the config hash matches the registration<br>• the nonce matches the claim<br>Every rejection carries a reason. | Each failed check produces its own named reason. | MUST | SD |
| ZK-07 | **Negative tests** reject each of these:<br>• the thief's forged key (Demo C style)<br>• the free-signature (D1) variant<br>• a proof for a different model<br>• a replayed proof<br>• a byte-tampered proof<br>• a proof whose commitment isn't registered | All six are rejected in CI. | MUST | SD |
| ZK-08 | **On-chain verification:** export a Solidity verifier with `snarkjs zkey export solidityverifier`, deploy it to a local dev chain (Hardhat or Anvil), and verify the same proof there. | Proof verifies on-chain; gas recorded. | SHOULD | SD |
| ZK-09 | A `ProofBackend` interface, with `circom` as the default and `ezkl` as a research comparison carrying the licence caveat. Demos C–E keep working. | Both backends pass the shared positive and negative tests where applicable. | SHOULD | SD |
| ZK-10 | **Cost benchmarks (RQ3):** constraints, setup time, prove time, verify time, proof size, zkey size and peak RAM, for T ∈ {64, 256} and M ∈ {288, one ResNet-18 layer}, on the team laptop and on the GPU workstation. | A results JSON plus a table in the docs. | MUST | SD |

## 9. ROB: robustness and evaluation

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| ROB-01 | **Attack suite:**<br>• unstructured pruning from 10% to 90%, and structured (channel) pruning<br>• pruning followed by recovery fine-tuning; fine-pruning<br>• real post-training quantisation to int8 and int4 (torch.ao or ONNX Runtime)<br>• FTLL, FTAL, RTLL, RTAL<br>• overwriting<br>• permutation, and permutation followed by fine-tuning | Every attack is runnable from the CLI and the API. | MUST | MA |
| ROB-02 | **Compression:** k-means weight sharing (at least 2 cluster counts), low-rank (SVD) factorisation, and knowledge distillation into a white-box student. | Results recorded in the matrix. | MUST | MA |
| ROB-03 | **Model extraction:** black-box query distillation with budgets from 1k to 50k queries, using attacker data. Report the weight-mark BER (expected to be about 0.5) and the trigger-set accuracy (WM-06). | Reported honestly, including the weight mark's failure. | MUST | MA |
| ROB-04 | **Method:**<br>• at least 5 seeds per cell, reported as mean ± std<br>• attacker data disjoint from the owner's<br>• the attacker's accuracy cost reported<br>• θ taken from WM-07<br>• every configuration stored as versioned YAML | Reviewed by SD before results are quoted. | MUST | MA |
| ROB-05 | **ZK in the loop (RQ2):** for each attacked model, generate and verify a proof, and add a "proof verifies" column to the matrix. | Matrix complete for MNIST, T = 64 and T = 256. | MUST | MA + SD |
| ROB-06 | **Adaptive security layer** (an SOP expected outcome):<br>• choose layers, T and λ automatically from a robustness profile, within an accuracy budget<br>• a dual-mark policy: white-box plus trigger set<br>• owner-side realignment before extraction | Recommended configs per model are published, with their evidence. | SHOULD | MA |
| ROB-07 | **Trade-off evaluation** (SOP Semester 8): accuracy against λ and T, and robustness against λ, on MNIST and CIFAR-10. | Charts and a table in the report. | MUST | MA |
| ROB-08 | Outputs are schema-versioned JSON, CSV and SVG/PNG, produced by `sigil attack` and by API jobs. | Re-running the same config with the same seed gives the same output. | MUST | MA |

## 10. SDK: Python SDK and CLI

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| SDK-01 | A pip-installable package `sigil` in `sdk/`: `pyproject.toml`, src layout, Python 3.11–3.14, extras `[torch]`, `[tf]`, `[onnx]` and `[zk]`. The core has no heavy dependencies. | `pip install ./sdk[torch,onnx]` works on a clean virtual environment. | MUST | AS |
| SDK-02 | **A typed public API with docstrings:** `Owner.generate/load`, `Watermark.derive`, `embed`, `detect`, `register`, `prove`, `verify`, `attack`. The framework is auto-detected from the model object or file. | The quickstart runs for `.pt`, `.keras`/`.h5` and `.onnx`. | MUST | MA + AS |
| SDK-03 | **A CLI** that mirrors the API: `sigil keygen`, `embed`, `detect`, `register`, `prove`, `verify`, `attack`, `report`, each with a `--json` option. | Help text exists for every command; covered by smoke tests. | MUST | AS |
| SDK-04 | **Safe loading:**<br>• `torch.load(weights_only=True)`<br>• Keras `safe_mode=True`, refusing `.h5` files with Lambda layers unless `--trust` is passed<br>• `onnx.checker`<br>• a maximum file size | Malicious-file tests are rejected. | MUST | AS |
| SDK-05 | **Versioned, documented artefact formats:** `registration.json`, and a proof bundle containing `proof.json`, `public.json`, `claim.json` and the verification-key hash. | A JSON Schema exists for each format. | MUST | SD |
| SDK-06 | The demo scripts `demo/0N_*.py` call the SDK, so there's one source of truth. Their output schemas stay the same, or are versioned. | The demos run unchanged from the UI. | MUST | MA |
| SDK-07 | **Tests and docs:** at least 80% line coverage on `sigil.core`, a generated API reference, and one example notebook per framework. | The coverage report is published in CI. | MUST | AS |
| SDK-08 | Release wheels; TestPyPI optional. | A tagged release has a wheel attached. | SHOULD | AS |

## 11. API: backend (FastAPI)

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| API-01 | **A FastAPI app** in `backend/` (uvicorn) replaces `demo/server.py` for live use. It serves the UI build, binds to 127.0.0.1 by default, and implements the security posture of [UI_INTEGRATION.md §10](UI_INTEGRATION.md) as middleware: Host and Origin checks, localhost-only CORS, JSON content type for mutations. | Middleware tests cover each rule. | MUST | YB |
| API-02 | **v1 compatibility:** `/api/state`, `/api/steps`, `/api/run`, `/api/jobs/{id}`, `/api/jobs/{id}/stream` and `/results/{file}` keep today's contract until the Phase 3 cutover. Simulate mode is kept. | Contract tests against `contract/fixtures/` pass; the current UI works unchanged against FastAPI. | MUST | YB |
| API-03 | **v2 resources** (OpenAPI):<br>• owners (public keys only)<br>• models: upload, hash, framework, layers<br>• embeddings: jobs<br>• registrations: signed record and timestamp<br>• proofs: generate job, download bundle<br>• verifications: bundle plus suspect model in, persisted result with reasons out<br>• attacks: jobs and results<br>• deployments, audit events, reports, health and environment | Every endpoint has tests and an OpenAPI description. | MUST | YB |
| API-04 | **Job runner:**<br>• jobs persisted, one GPU-heavy job at a time (queued)<br>• cancel; per-step timeout<br>• crash-safe: a job always reaches a final state<br>• SSE with `Last-Event-ID` resume; logs persisted | Tests cover a killed job, a timeout, a cancel and a reconnect. | MUST | YB |
| API-05 | **Uploads:** a size limit (default 500 MB, configurable), extension and magic-byte checks, SHA-256 computed on receipt, files stored outside the static root, and only the SDK's safe loaders used. | Bad-file tests are rejected. | MUST | YB |
| API-06 | **Authentication and roles:** local accounts (Argon2id password hashes) or per-user API tokens. Roles are *owner* (embed, register, prove), *verifier* (verify only, never sees secrets) and *admin*. | Role tests; a verifier can't reach owner endpoints. | MUST | YB |
| API-07 | The OpenAPI spec is exported to `contract/openapi.json`. Frontend types are generated from it with `openapi-typescript`, replacing the hand-written types. | Spec export and type generation run in CI. | MUST | YB |
| API-08 | **Reports:**<br>• an ownership certificate per verification, as a PDF plus signed JSON<br>• an audit export (CSV and JSON) with hash-chain proof<br>• a compliance report mapping evidence to the OWASP AI Exchange #MODEL WATERMARKING text and to these requirements | Generated from real records; signatures verify. | MUST | YB + SD |
| API-09 | **Deployment monitoring:** register deployments (name, environment, artefact location, expected hash). A scheduled re-check (hash match, watermark detection, optional proof) keeps a history and raises alerts in the UI. | A tampered artefact raises an alert. | SHOULD | YB |
| API-10 | Errors use RFC 9457 `problem+json`. Logs are structured and contain no secrets. | Log scan in tests. | MUST | YB |

## 12. DB: database (PostgreSQL)

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| DB-01 | PostgreSQL 16, via `docker compose` with native-install instructions as an alternative. SQLAlchemy 2.x and Alembic migrations. | `alembic upgrade head` works on an empty database. | MUST | YB |
| DB-02 | **Schema:** users, owners, models, model_artifacts, watermark_configs, registrations, embeddings, proofs, verifications, attack_runs and attack_results, deployments and deployment_checks, jobs and job_logs, audit_events. | An ER diagram in `docs/`. | MUST | YB |
| DB-03 | `audit_events` is **append-only and hash-chained**: each row stores SHA-256(previous hash ‖ canonical event). Every state-changing call writes an event. `sigil audit verify` checks the chain. | A tampered row is detected. | MUST | YB |
| DB-04 | A seed command imports the existing `demo/results/*.json`, so a fresh install shows the demo history. Backup and restore commands are documented. | A fresh install shows panels A–E plus their history. | MUST | YB |

## 13. NFR: non-functional requirements

| ID | Requirement | Acceptance criteria | Pri | Owner |
|---|---|---|---|---|
| NFR-01 | **Works offline after setup.** Fonts, the ptau/zkey files, the SRS, models and MNIST are all cached, with a documented "prepare offline" step. | The demo runs with the network disabled; CI checks that the UI build references no external URL. | MUST | All |
| NFR-02 | **Reproducibility:**<br>• lock files for Python (torch included) and Node (`package-lock.json`, plus `engines` and `.nvmrc` with Node ≥ 20.19)<br>• every result stamped with schema version, git commit, config hash, seed and environment<br>• one command regenerates every result and every doc table | Two runs of that command produce the same tables. | MUST | YB |
| NFR-03 | **Performance targets**, measured rather than assumed: proving MNIST T = 64 takes at most 30 s and verifying at most 1 s on the team laptop's CPU (SnarkJS Groth16); the full live demo takes at most 2 min on the GPU workstation. | Benchmark JSON in the repo. | SHOULD | SD |
| NFR-04 | **Security:**<br>• local-only by default<br>• no pickle loading of untrusted files<br>• `pip-audit` and `npm audit` show no high-severity findings<br>• secret scanning in CI<br>• a short app threat model in `docs/threat-model.md` | CI enforces these checks. | MUST | YB |
| NFR-05 | **Accessibility to WCAG 2.1 AA:** contrast, keyboard access, visible focus, `aria-live` for job status, reduced motion. | Automated axe checks plus a manual keyboard pass. | MUST | AS |
| NFR-06 | **Cross-platform:** Windows 11 is the primary platform; the SDK and backend also run on Linux and macOS, with launchers for both. Note that TensorFlow has no native-Windows GPU support after 2.10; use the CPU or WSL2. | CI runs on Windows and Ubuntu. | SHOULD | YB |
| NFR-07 | **Testing and CI:**<br>• pytest for the SDK and backend<br>• circuit tests: the Python reference against the SnarkJS witness<br>• API contract tests<br>• Vitest and a Playwright smoke test for the frontend<br>• GitHub Actions on every PR: lint, typecheck, tests, build | Main is green; PRs are blocked on red. | MUST | All |
| NFR-08 | **Documentation:** README, `docs/protocol.md`, the OpenAPI spec, SDK docs, a user guide, the demo script and the final report. **Every number in the docs and UI traces to a results file**: tables are generated, never typed by hand. | A doc build script regenerates every table from results. | MUST | SD |
| NFR-09 | **Licensing:** a LICENSE file per DEC-08, plus third-party notes: circom, SnarkJS and circomlib are GPL-3.0; EZKL has no licence, so research use only. | Both files are present. | MUST | SD |
| NFR-10 | **Honest claims:** the §15 statements stay visible on screen, not only inside collapsed notes. No copy claims a property the code doesn't have; for example, "survives extraction" may only be said of the trigger-set mark, and only after ROB-03 shows it. | A copy review checklist is signed off at each gate. | MUST | SD |

---

## 14. Phase 2 and Phase 3: UI requirements

### 14.1 UD: design updates on the design canvas (Phase 2)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| UD-01 | **Align the existing artboards with the real system:**<br>• signature lengths (64/256)<br>• BER and θ wording instead of "bits recovered %"<br>• Circom/Groth16 (per DEC-01)<br>• real model names (MNIST CNN, ResNet-18 CIFAR-10, Keras CNN)<br>• real config fields (layer, λ, T, PRG version)<br>• invented sample numbers removed or bound to `contract/fixtures` | MUST | AS |
| UD-02 | **New screens:**<br>• model detail and upload/register<br>• registrations and timestamps<br>• proof generation, with job and bundle download<br>• verification submission, result and certificate<br>• full audit log, with hash-chain status and export<br>• deployments and monitoring<br>• owner keys and API tokens<br>• settings and environment (GPU, mode, offline assets)<br>• sign-in | MUST | AS |
| UD-03 | **The research storyline:** demos A–E (commit and embed, removal attacks, forgery, committed seed, ZK proofs) redesigned in Cocoa Pop, with a presenter mode: ← → navigation, presenter notes, projector-friendly. | MUST | AS |
| UD-04 | **A state sheet for every screen:**<br>• empty, loading or probing, running, done<br>• failed (old results kept)<br>• stale badge; busy (409)<br>• confirmation dialog, with text from `/api/steps`<br>• simulate banner; offline<br>The running state includes a console drawer that never hides content. | MUST | AS |
| UD-05 | Copy pass: the §15 statements are placed visibly, and nothing claims more than the evidence shows. | MUST | AS + SD |
| UD-06 | Responsive at 1920×1080 (projector), 1366×768 (laptop) and 375 px wide (phone, read-only views). | MUST | AS |
| UD-07 | **A hand-off package** in `docs/design/`:<br>• final tokens (Tailwind v4 `@theme`; the kit's `tailwind.config.js` values map 1:1)<br>• a component inventory with all states<br>• a motion spec: durations, easings, reduced-motion behaviour<br>• a map from each screen to the endpoints it uses<br>• exports of every artboard | MUST | AS |
| UD-08 | The team and the guide sign off on the design before Phase 3 starts. | MUST | AS + SD |

### 14.2 UM: migrating the frontend (Phase 3)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| UM-01 | A React 19 + TypeScript + Vite + **Tailwind CSS** app (per the SOP) implementing the approved design. It builds to `frontend/dist`, which FastAPI serves. | MUST | AS |
| UM-02 | Fonts are **self-hosted**: Bricolage Grotesque, Instrument Sans and JetBrains Mono. No network access at runtime (NFR-01). | MUST | AS |
| UM-03 | A component library built from the UD-07 inventory, with a preview page. Storybook or Ladle is optional. | MUST (tooling: COULD) | AS |
| UM-04 | The API is called through the generated client (API-07). SSE handles reconnect, resume, 409 and errors by design, closing the FIX-13 class of bugs. | MUST | AS |
| UM-05 | **Feature parity** with the current panels A–E before cutover (checklist in WORKFLOW Phase 3), plus every v2 screen. | MUST | AS |
| UM-06 | Charts are hand-built SVG, or an offline-bundled library. They are colour-blind safe, and status is never shown by colour alone. | MUST | AS |
| UM-07 | Motion follows the design, with `prefers-reduced-motion` and a motion toggle respected. Smooth on the demo laptop: no layout thrash, and only transform and opacity are animated. | MUST | AS |
| UM-08 | **Tests:** Vitest unit tests. Playwright end-to-end tests for embed → register → prove → verify, a demo step run, the 409 case and the stale case. axe accessibility checks. | MUST | AS |
| UM-09 | **Cutover:** the old UI stays available through `--ui frontend-legacy/dist` until sign-off, then is removed. The checklist in [UI_INTEGRATION.md §12](UI_INTEGRATION.md) passes on the new UI. | MUST | AS |

---

## 15. Statements that must stay true on screen

This list is updated from [UI_INTEGRATION.md §8](UI_INTEGRATION.md). Reword freely, but never drop or contradict a statement while it is still true.

1. θ is indicative until WM-07 is done. After that, state the measured false-positive bound.
2. Demo C runs **ZKROWNN's relation in PyTorch**, not their code; the attack is outside their semi-honest threat model.
3. "Entry distributions match a real key; under ZK the verifier sees neither." Don't say "indistinguishable" without that qualifier.
4. D1's 1000/1000 holds **by construction**.
5. D2 work is about 2^32 at T = 64 (feasible on a GPU) and about 2^120 at T = 256. Timestamps still matter.
6. Until ZK-01 lands, E3 is at the D1 level and is not linked to the seed commitment. Once it lands, state exactly what the circuit proves (ZK-01).
7. Peak RAM figures are sampled.
8. The literature cost rows are orders of magnitude only.
9. EZKL has no open-source licence; use it for research and demos only.
10. **New:** white-box marks do not survive model extraction. Only the trigger-set mark is evaluated for that (OWASP limitation L1).
11. **New:** Groth16 relies on a trusted setup; we use a public Powers of Tau file plus our own phase-2 contribution.
12. **New:** the contribution is positioned against prior work: Adi 2018, Li 2019, NeuralMark 2026, FedZKP.

## 16. SOP traceability matrix

| SOP item | Requirements |
|---|---|
| **Sem 7:** secure cryptographic watermark embedding across TensorFlow, PyTorch and ONNX | WM-01–05, WM-07–09, CR-01–06, FIX-03–05 |
| **Sem 7:** privacy-preserving ZKP generation and verification (zk-SNARKs via Circom and SnarkJS) | ZK-01–07, ZK-09, FIX-02, FIX-06, FIX-17 |
| **Sem 7:** open-source, framework-agnostic Python SDK/API | SDK-01–07, WM-03–05 |
| **Sem 8:** robustness against fine-tuning, pruning, quantisation, compression and extraction | ROB-01–05, ROB-08, WM-06, FIX-16 |
| **Sem 8:** web dashboard (React, FastAPI, Tailwind) for provenance, deployment monitoring and audit-ready reporting | API-01–10, DB-01–04, UD-01–08, UM-01–09 |
| **Sem 8:** end-to-end integration, performance evaluation (resilience vs accuracy), documentation | ROB-07, ZK-10, NFR-02, NFR-03, NFR-07, NFR-08 |
| Methodology: watermark in weights, biases or activations | WM-01, WM-10 |
| Methodology: verification off-chain or on-chain with public keys | ZK-05, ZK-06, ZK-08 |
| Methodology: FastAPI and PostgreSQL for tracking, deployment logs and verification history | API-03, API-09, DB-02, DB-03 |
| Tools: SHA-256, RSA/ECC, Circom, SnarkJS | CR-01–05, ZK-01–05 |
| Tools: TensorFlow, PyTorch, NumPy, scikit-learn, ONNX | WM-03–05; scikit-learn for k-means weight sharing (ROB-02) and statistics |
| Tools: React, Tailwind CSS, FastAPI | UM-01, API-01 |
| Tools: PostgreSQL | DB-01 |
| Outcome: SDK and API for `.pt`, `.h5` and `.onnx` | SDK-01–06, WM-03–05 |
| Outcome: ZKP pipeline that validates ownership without revealing the watermark | ZK-01–07, CR-04, FIX-03 |
| Outcome: interactive dashboard for model management, verification logging and compliance auditing | API-03, API-08, DB-03, UD-02, UM-05 |
| Outcome: adaptive security layer keeping extraction rates high after attacks | ROB-06, WM-06, ROB-05 |

## 17. Out of scope

- A multi-party trusted-setup ceremony. We document the single-contributor phase 2 instead.
- Internet-facing or cloud production hosting. The app is local-first.
- Zero-knowledge proofs over transformer inference.
- Legal enforcement processes.
- Native mobile apps.
