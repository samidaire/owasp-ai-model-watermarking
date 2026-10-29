# Workflow: from the current build to the finished project

**Version 1.0 · 2026-10-05 · Owner: Sami Daire (project lead)**

This document says **how, when and by whom** the work gets done. [REQUIREMENTS.md](REQUIREMENTS.md) says **what** must be built; every task here cites requirement IDs from it.

```
 Phase 0         Phase 1                              Phase 2                Phase 3
 Set up    ──▶   Complete & correct the build   ──▶   Update the UI    ──▶   Migrate to the
 (1 week)        against the SOP                      design (canvas)        new UI
                 M1 … M7
                      │                                    │                      │
                 [Gate 1: SOP-complete]              [Gate 2: design      [Gate 3: parity
                                                      signed off]          and cutover]
```

**The one rule that overrides everything else: never break the demo.**
- `main` must always run `Start-Demo-UI-Simulate.cmd`, and live runs must work on the GPU workstation.
- Risky work goes on branches, behind flags, or in new entry points.

---

## 1. Team and ownership

| Workstream | Accountable | Supporting | Requirement areas |
|---|---|---|---|
| Project lead, protocol, ZK circuits, verification, integration | **Sami Daire (SD)** | all | CR, ZK, NFR-08–10, gates |
| Watermark core, frameworks, robustness, evaluation | **Mohamed Ansari (MA)** | SD | WM, ROB, FIX-01/07/12/16 |
| Frontend and integration, SDK packaging and CLI, design | **Arfat Shaikh (AS)** | YB | SDK packaging, UD, UM, FIX-13/14 |
| Backend: FastAPI, PostgreSQL, APIs, jobs, reports | **Yash Bandiwadekar (YB)** | SD | API, DB, FIX-11/15, NFR-02/04/06 |

Guide check-ins happen every two weeks, plus each gate (§9). Guide: Er. Fiza Shaikh (Co-Guide).

---

## 2. Ways of working

### 2.1 Repository and branches

- **The current folder has no git history.** Phase 0 creates the repository and tags the starting point as `baseline-2026-10-05`.
- **`main` is protected.** Merging needs a pull request, one reviewer who isn't the author, and green CI.
- **Branch names** carry the requirement ID: `fix/FIX-01-d2-units`, `feat/ZK-01-circuit`, `feat/API-04-jobs`, `ui/UM-05-panels`.
- **Commit messages** follow Conventional Commits with the ID: `fix(FIX-01): store D2 work in hours`.

### 2.2 Issues and tracking

- **One issue per requirement ID.** Large requirements get sub-tasks.
- **Labels:** area (`zk`, `wm`, `api` …), priority (`must`, `should`, `could`), phase (`p1`, `p2`, `p3`).
- **The board** has these columns: Backlog → This week → In progress → In review → Done.
- **Decisions** (DEC-01 … DEC-10) are recorded in REQUIREMENTS §4 with a "Confirmed on" date.

### 2.3 Pull request checklist (put it in `.github/pull_request_template.md`)

- [ ] Requirement IDs listed, and their acceptance criteria met.
- [ ] Tests added or updated; CI green.
- [ ] If numbers changed: results regenerated with the one-command script (NFR-02), and the doc tables regenerated (NFR-08).
- [ ] Docs updated: README, protocol, API, SDK, as relevant.
- [ ] No secrets, personal paths or large binaries added (CR-04).
- [ ] UI changes: screenshots at 1366×768 and 1920×1080; keyboard and reduced motion checked.
- [ ] The §15 statements in REQUIREMENTS are still true and still on screen.

### 2.4 Definition of done (per requirement)

A requirement is done when **all** of these hold:
- its acceptance criteria are met;
- it's covered by tests;
- it's documented;
- it has been reviewed and merged;
- the demo still runs;
- its issue is closed, with a link to the PR.

### 2.5 Weekly cadence

| When | What | Length |
|---|---|---|
| Monday | Sync: status by requirement ID, blockers, the week's plan | 30 min |
| Thursday | Integration check: fresh pull of `main`, run the simulate demo and the test suite, fix anything broken that same day | 30 min |
| Every 2nd Friday | Guide check-in: live demo of what's new, decisions needed | 30 min |
| 7 days before any review | **Demo freeze:** bug fixes only; tag `review-<date>`; offline drill (§8) | — |

### 2.6 Rules for results and secrets

- **Results come from scripts only.** Never edit `demo/results/*.json` by hand; regenerate them with the one-command script.
- **Back up the demo seed before anything touches it.** That means `demo/ckpt/owner_secret.json` and the checkpoints; keep the backup zip outside the repo.
- **Real secrets never enter the repo:** owner keys, seeds and tokens (CR-04). Secret scanning runs in CI.

---

## 3. Phase 0: set up (week 1)

**Owner:** SD, with YB for CI.

| # | Task | Done when |
|---|---|---|
| 0.1 | Create a private GitHub repository. Commit the current folder unchanged and tag it `baseline-2026-10-05`. | The tag exists, and the whole team has access. |
| 0.2 | Add the SOP (Role Distribution updated 2026-10-05) as `docs/SOP.pdf`, plus these two documents. | Files committed. |
| 0.3 | Back up `demo/ckpt/` and `demo/results/` to a zip kept **outside** the repo. | Backup verified by restoring it to a temp folder. |
| 0.4 | Protect `main`; add the PR template (§2.3) and the issue labels; create one issue per requirement ID. | Board populated. |
| 0.5 | Add a CI skeleton (GitHub Actions) that lints and runs `python demo/server.py --simulate` as a smoke test. | First green run. |
| 0.6 | Set up every member's dev environment:<br>• Python 3.11+ (3.14 tested)<br>• Node 22 LTS<br>• Git<br>• Docker Desktop (for PostgreSQL)<br>• circom 2 and snarkjs (SD first)<br>The GPU workstation keeps `demo/.venv` for live runs. | Each member runs the simulate demo locally. |
| 0.7 | Confirm decisions **DEC-01 to DEC-10** with the guide. | REQUIREMENTS §4 shows "Confirmed on" dates. |
| 0.8 | Share the design canvas with the team from its Share menu. Until it's shared, teammates can't open the link. | Everyone can open it. |

**Exit:** everyone can run the demo, CI is green, and every decision is confirmed.

---

## 4. Phase 1: complete and correct the build

Phase 1 has seven milestones. M1–M4 deliver the SOP's **Semester 7** objectives (embedding, ZKP, SDK). M5–M7 deliver the **Semester 8** objectives (robustness, dashboard backend, integration). Backend work (M6) starts in Semester 7, in parallel, because it's independent of the ZK work.

### 4.1 Timeline

Weeks are working weeks counted from 5 Oct 2026. Map them to your real calendar, including exams and the semester break, and fill in the review dates.

| Week | SD | MA | AS | YB |
|---|---|---|---|---|
| W1 | Phase 0; M1 docs fixes | M1 FIX-01/07/12 | M1 FIX-13/14 | M1 FIX-11/15 |
| W2–W4 | **M2** protocol v2 | M2 WM-02 parity study | M4 SDK skeleton and packaging | M1 wrap-up; **M6** FastAPI v1-parity |
| W3–W8 | **M3** Circom + SnarkJS pipeline | **M4** frameworks (PyTorch, Keras, ONNX) | M4 CLI, docs, tests | M6 database, auth, v2 resources |
| W9–W10 | Sem 7 review prep, freeze | Sem 7 review prep | Sem 7 review prep | M6 job runner, reports |
| **[SEM 7 REVIEW: date]** | | | | |
| W11–W15 | M5 ZK-in-the-loop; ZK-08 on-chain | **M5** robustness suite, CIFAR-10, trigger set | M5 support: charts, CLI `attack` | M6 deployments, OpenAPI export; switch the demo to FastAPI |
| W15–W17 | **M7** integration, evaluation, Gate 1 | M7 trade-off evaluation | **Phase 2** design (starts once the v2 OpenAPI spec is frozen) | M7 install, offline and CI hardening |
| W18–W23 | Phase 3 review; report | Report: evaluation chapter | **Phase 3** UI migration | Phase 3 API support |
| W24–W26 | **Final freeze, report, viva rehearsal** | | | |
| **[FINAL REVIEW / VIVA: date]** | | | | |

Phase 2 overlaps Phase 1 only after the v2 API contract is frozen. It otherwise runs after Phase 1, as planned.

### 4.2 Milestones

#### M1: stabilise and correct (W1–W3)
**Goal:** fix everything that's wrong today, without redesigning anything.
**Requirements:**
- FIX-01, FIX-07, FIX-08, FIX-09, FIX-10, FIX-11, FIX-12, FIX-13, FIX-14, FIX-15.
- **Interim** FIX-02: add the public-signal checks in the EZKL path.
- **Interim** FIX-03: delete the leaked `extract.onnx` files and change the export.

**Steps:**
1. **SD:** correct the docs for FIX-08, FIX-09 and FIX-10, adding the four prior-work citations. Restate the contribution.
2. **MA:** fix the D2 units (FIX-01) and make `retrain` transactional (FIX-12). Regenerate **all** results in one run, and fix every number in the docs (FIX-07).
3. **YB:** harden `demo/server.py` (FIX-11): try/finally, cancel, timeout, atomic writes, body validation, cache headers. Scrub personal paths (FIX-15).
4. **AS:** harden the current UI (FIX-13): SSE `onerror` and reattach on 409, a console drawer that doesn't cover content, an ErrorBoundary, consistent stale logic, confirm texts from `/api/steps`, `aria-live`. Fix the types (FIX-14). Rebuild `frontend/dist`.
5. **SD:** apply the interim FIX-02 and FIX-03 to the EZKL scripts. Add a test that no artefact contains key bytes.

**Exit:**
- `Start-Demo-UI-Simulate.cmd` and a live "Run all" both complete.
- Killing a job mid-run doesn't wedge the server or the UI.
- Every number in the docs matches the results.
- The tests for the interim checks are green.

#### M2: protocol v2 (commitment, identity, key derivation) (W2–W4)
**Goal:** one well-specified protocol that Python and Circom implement identically.
**Requirements:** CR-01 to CR-06, WM-02, FIX-04, FIX-05, DEC-02, DEC-05.

**Steps:**
1. **SD:** write `docs/protocol.md` v2. It covers:
   - the seed;
   - domain-separated Poseidon derivations of X (±1), b and C;
   - `config_hash`;
   - canonical JSON for the registration record;
   - Ed25519 signing;
   - registry timestamps;
   - the dispute rule.
2. **SD:** implement a Python Poseidon that's bit-exact with circomlib, plus test vectors generated with circomlibjs.
3. **SD:** implement owner key generation and encrypted storage (CR-01), and registration signing and verification (CR-02).
4. **MA:** run the **parity study** (WM-02): ±1 Poseidon key against the current Gaussian key, 5 seeds, MNIST, covering accuracy, owner BER and the B attack suite. If parity fails, follow the risk R2 fallback (§10).
5. **SD and MA:** switch `wm_core` derivation to v2 behind a `--protocol v2` flag; v1 stays for the existing demos. Re-measure D2, including owner-key grinding (FIX-04).

**Exit:**
- `protocol.md` is reviewed by the whole team, and the test vectors pass.
- The parity report is committed under `docs/reports/`.
- Registrations sign and verify, and the dispute test picks the earlier owner.

#### M3: Circom + SnarkJS ZK pipeline (W3–W8)
**Goal:** the SOP's ZK objective, done properly: derivation in-circuit, θ in-circuit, and a binding to the suspect model.
**Requirements:** ZK-01 to ZK-07, ZK-09, ZK-10, FIX-02 (final), FIX-06, FIX-17, DEC-01. ZK-08 (on-chain) moves to M5 if time is short.

**Steps, building the circuit in testable layers:**
1. A toy circuit: a dot product and sign over fixed-point inputs. Set up the Python reference (ZK-02) and the witness-comparison tests.
2. Add the Poseidon PRG → ±1 key, and the signature bits (from CR-06).
3. Add the commitment opening C, pk_hash and config_hash.
4. Add H(w_q) as the model binding.
5. Add the match count and the **θ threshold** (ZK-03); add the claim nonce.
6. Script the trusted setup (ZK-04): download the ptau file once, cache it for offline use, record the phase-2 contribution hash.
7. Wrap prove and verify in the SDK (ZK-05). Implement the full verification procedure with reasons (ZK-06).
8. Write the negative tests (ZK-07) and run them in CI.
9. Build the `ProofBackend` interface (ZK-09); keep the EZKL demos C–E working through it.
10. Run benchmarks for T ∈ {64, 256} and M ∈ {288, one ResNet-18 layer} (ZK-10).

**Exit:**
- The owner's proof verifies for MNIST at T = 64.
- All six negative cases are rejected in CI.
- The benchmark JSON is committed.
- §15 statement 6 is updated to say exactly what the circuit now proves.

#### M4: watermark core, multi-framework SDK and CLI (W3–W9)
**Goal:** the SOP's SDK objective, working across PyTorch, TensorFlow/Keras and ONNX.
**Requirements:** WM-01, WM-03, WM-04, WM-05, WM-07 (MNIST), WM-08, WM-09 (MNIST), SDK-01 to SDK-07.

**Steps:**
1. **AS:** scaffold `sdk/` (pyproject, src layout, extras), set up CI for it, and wire up docs generation.
2. **MA:** move the core out of `demo/wm_core.py` into `sigil.core`, layer-agnostic (WM-01).
3. **MA:** build the PyTorch adapter (WM-03), then the Keras adapter (WM-04), then ONNX extraction with canonical weight ordering (WM-05).
4. **MA:** run the null-model calibration on MNIST with at least 30 null models (WM-07).
5. **AS:** build the CLI (SDK-03) and safe loading (SDK-04); define the artefact schemas with SD (SDK-05).
6. **MA and AS:** switch the demo scripts over to the SDK (SDK-06); the UI still works unchanged.
7. **AS:** write tests (at least 80% on the core), the quickstart, and one notebook per framework (SDK-07).

**Exit:**
- On a clean virtual environment, `pip install ./sdk[torch,tf,onnx,zk]` works.
- `sigil keygen`, `embed`, `register`, `prove` and `verify` complete for `.pt`, `.keras`/`.h5` and `.onnx`.
- The demo scripts run through the SDK.

> **Semester 7 review.** Demonstrate M1–M4: embedding across frameworks, the Circom ZK proof with forgery rejected, and the SDK and CLI. The research demos A–E still run. Freeze 7 days before (§2.5).

#### M5: robustness, compression, extraction, adaptive layer (W11–W15)
**Requirements:** ROB-01 to ROB-08, WM-06, WM-07 (CIFAR-10), WM-09 (CIFAR-10), FIX-16, ZK-08 if it was deferred.

**Steps:**
1. **MA:** set up CIFAR-10 ResNet-18 training with the watermark, and calibrate its null models (at least 10).
2. **MA:** extend the attack suite (ROB-01): real quantisation, pruning with recovery, fine-pruning, permutation with fine-tuning.
3. **MA:** add compression (ROB-02) and model extraction with query budgets (ROB-03).
4. **MA:** build the trigger-set watermark with a committed trigger set (WM-06).
5. **MA and SD:** put ZK in the loop: a "proof verifies" column for every attacked model (ROB-05).
6. **MA:** build the adaptive layer (ROB-06) and run the trade-off evaluation (ROB-07).
7. **AS:** add chart and CLI support for the outputs (ROB-08).

**Exit:**
- The full attack matrix is complete: at least 5 seeds, mean ± std, both datasets, with ZK verification recorded.
- The extraction results are reported honestly.
- SD has reviewed the method (ROB-04).

#### M6: backend: FastAPI, PostgreSQL, registry, reports (W2–W15, parallel)
**Requirements:** API-01 to API-10, DB-01 to DB-04, CR-03 (registry side).

**Steps:**
1. Scaffold FastAPI with **v1 parity first** (API-01, API-02), and write contract tests against `contract/fixtures/`. The current UI must work against FastAPI before anything else changes.
2. Port the security middleware with tests (API-01).
3. Set up PostgreSQL with `docker compose`, the schema and Alembic migrations (DB-01, DB-02). Write the seed/import command (DB-04).
4. Add authentication and roles (API-06), then the v2 resources (API-03) and the hash-chained audit log (DB-03).
5. Build the job runner: persisted, queued, cancel, timeout, resume (API-04). Harden uploads (API-05).
6. Generate reports and certificates (API-08); set up deployment monitoring (API-09).
7. Export the OpenAPI spec and generate the TypeScript types (API-07). **Freeze v2 here; Phase 2 depends on it.**
8. Switch the launchers to FastAPI. Keep `demo/server.py` as a fallback until Gate 1.

**Exit:**
- The v1 contract tests pass, and the current UI runs on FastAPI.
- Every v2 endpoint is tested and documented.
- A fresh install with `docker compose up` shows the imported demo history.

#### M7: integration, evaluation, documentation (W15–W17)
**Requirements:** ROB-07 (final), ZK-10 (final), NFR-01 to NFR-10, any remaining FIX items.

**Steps:**
1. End-to-end flows: owner embed → register → prove; verifier verify → certificate. Test them from the CLI and the API.
2. Make `make results` (or its Python equivalent) regenerate every result and every doc table (NFR-02, NFR-08).
3. Run an offline drill (NFR-01) and a fresh-machine install on Windows and Ubuntu (NFR-06).
4. Do a security pass: `pip-audit`, `npm audit`, secret scan, `docs/threat-model.md` (NFR-04).
5. Add the LICENSE and third-party notes (NFR-09); do the copy review against §15 (NFR-10).

### 4.3 Gate 1: SOP-complete (end of Phase 1)

Signed off by the whole team, then the guide.

- [ ] Every **MUST** in FIX, WM, CR, ZK, ROB, SDK, API, DB and NFR is *Done*.
- [ ] Every row of the traceability matrix (REQUIREMENTS §16) is green.
- [ ] All results were regenerated in one run, and every doc table was generated from them.
- [ ] A fresh install works, on a machine that has never had the project, following only the README.
- [ ] The offline drill passes.
- [ ] CI is green on Windows and Ubuntu.
- [ ] The §15 statements are true, and visible in the current UI.

---

## 5. Phase 2: update the UI design

**Owner:** AS. **Reviewers:** SD, then the guide. **When:** W15–W18, starting once the v2 OpenAPI spec is frozen.
**Canvas:** the team's shared UI design canvas (ask the project lead for access).
- Edit it in the design tool; keep the "Cocoa Pop" look and the shared kit.
- Give feedback as canvas comments.
- Existing artboards: landing page, style and motion kit, dashboard, embed, verify, robustness lab.

| # | Step | Requirement | Output |
|---|---|---|---|
| 2.1 | **Gap audit.** List every v2 endpoint and every demo panel A–E. Map each one to an artboard, and mark what's missing or wrong. | UD-01, UD-02, UD-03 | `docs/design/gap-audit.md`: a table of feature, endpoint, artboard and status |
| 2.2 | **Correct the existing artboards** so they match the real system:<br>• signature lengths<br>• BER and θ wording<br>• Circom/Groth16<br>• real models and config fields<br>• fixture-based numbers | UD-01 | Updated artboards |
| 2.3 | **Add the new screens:**<br>• models and upload<br>• registrations<br>• prove<br>• verification result and certificate<br>• audit log<br>• deployments<br>• keys and tokens<br>• settings<br>• sign-in | UD-02 | New artboards |
| 2.4 | **Redesign the research storyline A–E** in Cocoa Pop, with presenter mode. | UD-03 | 5 artboards plus a presenter view |
| 2.5 | **State sheet:**<br>• empty, probing, running (with the console drawer), done<br>• failed, stale, 409<br>• confirmation, simulate banner, offline | UD-04 | One "States" artboard per screen family |
| 2.6 | **Copy pass** against REQUIREMENTS §15 and NFR-10. | UD-05 | Copy checklist signed |
| 2.7 | **Responsive check** at 1920×1080, 1366×768 and 375 px. | UD-06 | Screenshots in `docs/design/` |
| 2.8 | **Hand-off package:**<br>• tokens as Tailwind v4 `@theme`<br>• component inventory with states<br>• motion spec<br>• map of screens to endpoints<br>• exported artboards | UD-07 | Committed to `docs/design/` |
| 2.9 | **Review and sign-off:** team walkthrough, then the guide. | UD-08 | Sign-off noted in the issue |

**Gate 2:** every screen and state in the gap audit has an artboard, the copy checklist is signed, and the hand-off package is committed.

---

## 6. Phase 3: migrate to the new UI

**Owner:** AS. **Supporting:** YB (API), SD (review). **When:** W18–W23.

**Strategy:** build the new app **beside** the current one, and switch only when it reaches parity.
1. On branch `ui/cocoa-pop`, move the current app to `frontend-legacy/`, so FastAPI can still serve it with `--ui frontend-legacy/dist`.
2. Create the new app in `frontend/` (UM-01).

| # | Step | Requirement |
|---|---|---|
| 3.1 | Scaffold: Vite + React 19 + TypeScript + Tailwind; generated API client (API-07); self-hosted fonts (UM-02). | UM-01, UM-02 |
| 3.2 | Tokens from the hand-off; base styles; motion utilities with reduced motion and a motion toggle. | UM-07 |
| 3.3 | **Component library, in this order:**<br>• Button, Chip, Card, Segmented control, Switch, Range, Input<br>• Table, Stepper, Code window, Bit grid, Stamp<br>• Console drawer, Modal, Toast<br>• SVG charts<br>Each gets a preview page. | UM-03, UM-06 |
| 3.4 | App shell: sidebar, routing, presenter mode (← →, notes), simulate banner, ErrorBoundary. | UM-04 |
| 3.5 | **Screens, in priority order:**<br>1. research storyline A–E (needed for reviews)<br>2. dashboard<br>3. models and upload<br>4. embed<br>5. prove<br>6. verify and certificate<br>7. robustness lab<br>8. audit log<br>9. deployments<br>10. keys and settings<br>11. landing page (optional project site) | UM-05 |
| 3.6 | Jobs and SSE: run, stream, resume, cancel, 409, stale handling. | UM-04 |
| 3.7 | Accessibility and motion pass; performance check on the demo laptop. | UM-07, NFR-05 |
| 3.8 | Tests: Vitest; Playwright for the key flows; axe checks. | UM-08 |
| 3.9 | **Parity check and cutover** (below); then delete `frontend-legacy/` in a separate PR. | UM-05, UM-09 |

**Parity checklist (the old UI must not lose anything):**
- [ ] Panels A–E show every field listed in [UI_INTEGRATION.md §6](UI_INTEGRATION.md).
- [ ] Run buttons, confirmations, live console, disabled-while-running, and refresh after done.
- [ ] Stale badges follow the §7 rule; the simulate-mode banner appears.
- [ ] Keyboard navigation (← →, PageUp/PageDown), presenter notes, and a projector-friendly theme.
- [ ] Every statement in REQUIREMENTS §15 is visible.
- [ ] The [UI_INTEGRATION.md §12](UI_INTEGRATION.md) hand-back checklist passes in full.

**Gate 3:** parity checklist complete, Playwright and axe green, and a rehearsal demo run with the guide on the new UI.

---

## 7. Target repository layout (end of Phase 3)

```
.
├── sdk/                  # pip package "sigil": core, adapters/{torch,keras,onnx}, zk/, registry/, cli
├── circuits/             # ownership.circom, tests, setup scripts (GPL-3.0, per DEC-08)
├── backend/              # FastAPI app, models, migrations (Alembic), jobs, reports
├── demo/                 # research demos A–E (call the SDK), results/, ckpt/ (demo seed only)
├── experiments/          # robustness and benchmark configs (YAML) and outputs
├── frontend/             # new Cocoa Pop UI (React + TS + Tailwind) → dist/
├── contract/             # openapi.json, fixtures, generated TS types
├── docs/                 # SOP.pdf, protocol.md, threat-model.md, design/, reports/, final report
├── .github/              # CI workflows, PR template
├── REQUIREMENTS.md  WORKFLOW.md  UI_INTEGRATION.md  README.md  LICENSE
└── docker-compose.yml    # PostgreSQL
```

---

## 8. Reviews, freezes and the offline drill

**Before every review (Sem 7, Sem 8 mid-review, final viva):**
1. **T−7 days:** feature freeze. Tag `review-<date>`, and fix only bugs found in rehearsal.
2. **T−5:** regenerate results with the one-command script, and check that the docs match.
3. **T−3: offline drill.** Disconnect from the network, start from a cold boot, run the full demo on the presentation laptop, run the simulate fallback, and check the projector resolution.
4. **T−2:** full rehearsal with the narration ([02_Demo_Plan_Tomorrow.md](02_Demo_Plan_Tomorrow.md), updated per milestone).
5. **T−1:** pack the backups: results zip, recorded logs, and a screen recording of the demo as a last resort.

---

## 9. Gate summary

| Gate | When | Signed off by | Criteria |
|---|---|---|---|
| Phase 0 exit | W1 | SD | §3 exit |
| **Sem 7 review** | [date] | Guide and committee | M1–M4 demonstrated |
| **Gate 1: SOP-complete** | ~W17 | Team, then guide | §4.3 checklist |
| **Gate 2: design signed off** | ~W18 | Team, then guide | §5 Gate 2 |
| **Gate 3: cutover** | ~W23 | Team, then guide | §6 parity and tests |
| **Final review / viva** | [date] | Committee | Everything above, plus the report |

---

## 10. Risks and mitigations

| ID | Risk | Likelihood / impact | Mitigation | Owner |
|---|---|---|---|---|
| R1 | The Circom circuit is too large or slow (Poseidon PRG plus dot products) | Medium / High | Build in layers (M3 steps 1–5) and measure each one. If needed, reduce M; use rapidsnark; or fall back to committing (X, b) directly (the D1 level, as in today's E3) and document it. | SD |
| R2 | The ±1 key loses parity with the Gaussian key | Low / Medium | Use small-integer keys (e.g. {−2…2}) from the same PRG, or keep the Gaussian key outside the circuit with a hashed commitment, and document the trade-off. | MA |
| R3 | Only one GPU (the RTX 5080 workstation) | High / Medium | MNIST runs on CPU; batch the CIFAR-10 runs on the workstation; regenerate results in scheduled slots. | MA |
| R4 | TensorFlow on native Windows has no GPU support after 2.10 | High / Low | Use CPU TensorFlow for the Keras CNN, or WSL2. | MA |
| R5 | Losing the demo seed or results | Low / High | Backup in Phase 0; transactional retrain (FIX-12); git tags; the backup zip before every review. | SD |
| R6 | Scope creep (LLM stretch, extra screens) | Medium / Medium | COULD items only after Gate 1; new ideas go to the backlog, not into the sprint. | SD |
| R7 | Exams and team bandwidth | High / Medium | Buffer weeks (W9–W10, W24–W26); keep MUST items first; weekly status by ID. | SD |
| R8 | Demo-day failure (network, hardware) | Medium / High | Simulate mode, recorded logs, offline drill, and a screen recording as backup. | All |
| R9 | GPL-3.0 obligations from circomlib | Medium / Low | Keep circuits in `circuits/` under GPL-3.0 (DEC-08); decide before any OWASP contribution. | SD |
| R10 | Examiners challenge the novelty | Medium / High | FIX-08 citations and a narrowed contribution statement; §15 statement 12 shown on screen. | SD |

---

## 11. Command cheat sheet

**Today:**
```bash
python demo/server.py --simulate        # UI with saved results; Run buttons replay recorded logs
python demo/server.py                   # live runs (needs demo/.venv; see demo/README.md)
cd frontend && npm install && npm run dev   # current UI with hot reload on :5173
```

**Target, after M4 and M6** (names follow REQUIREMENTS; adjust if DEC-07 changes):
```bash
pip install -e "./sdk[torch,tf,onnx,zk]"
sigil keygen --out secrets/owner.key
sigil embed model.pt --bits 256 --layer layer3.1.conv2 --owner secrets/owner.key
sigil register model.wm.pt --owner secrets/owner.key
sigil prove model.wm.pt --claim claim.json --out bundle/
sigil verify bundle/ --model suspect.onnx
docker compose up -d db && alembic upgrade head
uvicorn backend.app:app --host 127.0.0.1 --port 8765
```
