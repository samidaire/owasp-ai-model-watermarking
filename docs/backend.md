# Backend (M6): FastAPI + PostgreSQL

**Requirements:** API-01 to API-10, DB-01 to DB-04, CR-03 (registry side), NFR-04 ([REQUIREMENTS.md](../REQUIREMENTS.md)).
**Code:** `backend/` · **API reference:** [api.md](api.md) and [`contract/openapi.json`](../contract/openapi.json) ·
**Schema:** [er-diagram.md](er-diagram.md)

The backend replaces `demo/server.py` for live use. It serves the UI build and the unchanged v1 demo API, and
adds an authenticated v2 API: owner keys, model uploads, registrations with registry timestamps, claims,
proof bundles, verifications with named reasons, attack runs, deployment monitoring, a hash-chained audit
log and signed reports. `demo/server.py` stays as the fallback until Gate 1.

```
backend/
├── alembic.ini, migrations/          Alembic (DB-01); 0001 = schema + append-only audit triggers, 0002 = jobs.model
├── requirements.txt
├── testing.py                        helpers for tests/test_backend_*.py (embedded PostgreSQL, live uvicorn)
└── app/
    ├── main.py                       app factory + lifespan (migrate, registry key, job runner, monitor)
    ├── config.py                     settings (env / backend/.env)
    ├── security.py                   Host / Origin / JSON / size / CORS middleware + request log (API-01)
    ├── legacy.py                     bridge to demo/server.py (step catalogue, Job/SimJob, parsers)
    ├── v1.py, static.py              v1 demo API, /results, UI with SPA fallback (API-02)
    ├── jobs.py                       persisted job runner, queue, crash recovery (API-04)
    ├── models.py, db.py              SQLAlchemy 2 models, engine/sessions (DB-02)
    ├── audit.py                      hash chain (DB-03)        history.py   demo import (DB-04)
    ├── auth.py                       Argon2id accounts, bearer tokens, roles (API-06)
    ├── registry.py                   registry Ed25519 key, signed documents (CR-03)
    ├── uploads.py                    upload validation (API-05)  monitor.py   deployments (API-09)
    ├── reports.py                    certificates, audit export, compliance report (API-08)
    ├── problems.py, logs.py          RFC 9457 errors, redacting JSON logs (API-10)
    ├── cli.py                        python -m backend.app.cli ...
    └── v2/                           the /api/v2 routers and their pydantic schemas (API-03)
```

## 1. Run it

```bash
pip install -e ./sdk[torch,onnx]        # the SDK (adapters read uploaded models)
pip install -r backend/requirements.txt
python -m backend.app --simulate        # http://127.0.0.1:8765, SQLite in backend/var, runs replay recorded logs
python -m backend.app                   # live runs (needs torch etc. in this Python, or SIGIL_DEMO_PYTHON)
uvicorn backend.app.main:app --host 127.0.0.1 --port 8765     # same app; settings from the environment
```

`python -m backend.app` takes the same flags as `demo/server.py` (`--port`, `--simulate`, `--ui DIR`, `--open`)
and always binds 127.0.0.1. On start-up the backend migrates the database (`alembic upgrade head`), creates the
registry key on first run, marks jobs a previous process left running as `interrupted`, imports the demo
results as history into an empty database, and starts the deployment monitor.

Create the first account, then sign in:

```bash
SIGIL_ADMIN_PASSWORD='...' python -m backend.app.cli create-admin --username admin
python -m backend.app.cli create-user --username olivia --role owner      # password from SIGIL_USER_PASSWORD or a prompt
curl -s -X POST http://127.0.0.1:8765/api/v2/auth/login -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"..."}'                            # -> {"token": "sgl_...", ...}
curl -s http://127.0.0.1:8765/api/v2/auth/me -H "Authorization: Bearer sgl_..."
```

## 2. Configuration

Environment variables (or `backend/.env`, gitignored). All are optional.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | SQLite `backend/var/sigil.db` | `postgresql+psycopg://user:pass@127.0.0.1:5432/sigil`. SQLite is for development and tests only (DEC-06). |
| `SIGIL_SIMULATE` | `0` | v1 runs replay `contract/fixtures/logs/<step>.log`; nothing executes |
| `SIGIL_UI_DIR` | `frontend/dist` | static UI build to serve |
| `SIGIL_DEMO_PYTHON` | this interpreter | Python for live demo runs (e.g. `demo/.venv/Scripts/python.exe`) |
| `SIGIL_REGISTRY_KEY` | `backend/var/registry.key` | registry Ed25519 key (encrypted PKCS#8), created on first run |
| `SIGIL_REGISTRY_PASSPHRASE` | dev file `backend/var/registry.passphrase` | passphrase for that key. **Set it for any real deployment.** |
| `SIGIL_TRUSTED_REGISTRY_KEYS` | none | extra registry public keys (hex, comma-separated) whose receipts verifications accept |
| `SIGIL_VAR_DIR` | `backend/var` | runtime state (SQLite, key, uploads) |
| `SIGIL_STORAGE_DIR` | `<var>/uploads` | uploaded models; must be outside the UI and results folders (checked at start-up) |
| `SIGIL_MAX_UPLOAD_BYTES` | `524288000` (500 MB) | model upload limit (API-05) |
| `SIGIL_MAX_JSON_BYTES` | `1048576` | v2 JSON body limit (v1 keeps 64 KiB) |
| `SIGIL_DEPLOYMENT_ROOTS` | `<var>/deployments` and the upload folder | folders deployments may point into (`os.pathsep`-separated) |
| `SIGIL_MONITOR_INTERVAL` | `3600` | seconds between scheduled deployment checks; `0` = off |
| `SIGIL_TOKEN_TTL_DAYS` | `90` | lifetime of tokens from `/auth/login`; `0` = no expiry |
| `SIGIL_AUTO_MIGRATE` / `SIGIL_AUTO_IMPORT_DEMO` | `1` / `1` | migrate / import demo history at start-up |
| `SIGIL_LOG_LEVEL` / `SIGIL_LOG_JSON` | `INFO` / `1` | structured logging |
| `SIGIL_API_DOCS` | `0` | serve Swagger UI at `/api/docs` (it loads assets from a CDN, so it's off for offline use) |
| `SIGIL_CIRCUITS`, `SIGIL_NODE`, `SIGIL_CIRCOM` | SDK defaults | ZK toolchain used to check Groth16 proofs (`sigil.zk.circom`) |

The OpenAPI spec is always at `/api/openapi.json` (and committed as `contract/openapi.json`).

## 3. PostgreSQL

**docker compose** (recommended; `docker-compose.yml` at the repo root):

```bash
docker compose up -d db
export DATABASE_URL=postgresql+psycopg://sigil:sigil-dev-only@127.0.0.1:5432/sigil
python -m backend.app --simulate         # migrates and imports the demo history on first start
```

**Native install** (Windows installer from postgresql.org, `apt install postgresql-16`, or `brew install postgresql@16`):

```sql
-- psql -U postgres
CREATE ROLE sigil LOGIN PASSWORD 'choose-one';
CREATE DATABASE sigil OWNER sigil;
```

then set `DATABASE_URL` as above. Keep PostgreSQL listening on localhost only (`listen_addresses = 'localhost'`).

### Migrations (DB-01)

```bash
python -m backend.app.cli migrate                   # = alembic upgrade head on DATABASE_URL
alembic -c backend/alembic.ini upgrade head          # the same with the Alembic CLI (from the repo root)
alembic -c backend/alembic.ini revision --autogenerate -m "describe the change"    # after editing models.py
```

`0001_initial_schema` creates every table of [the ER diagram](er-diagram.md) plus the triggers that make
`audit_events` append-only; `0002_job_model` adds `jobs.model` (the model a `model_test` job tests). A test (`test_migrations_create_exactly_the_orm_schema`, and its PostgreSQL twin)
fails if the models and the migrations drift apart.

### Backup and restore

| | Backup | Restore (stop the backend first) |
|---|---|---|
| PostgreSQL (compose) | `docker compose exec db pg_dump -U sigil -Fc sigil > sigil.dump` | `docker compose exec -T db pg_restore -U sigil -d sigil --clean --if-exists < sigil.dump` |
| PostgreSQL (native) | `pg_dump -h 127.0.0.1 -U sigil -Fc -f sigil.dump sigil` | `pg_restore -h 127.0.0.1 -U sigil -d sigil --clean --if-exists sigil.dump` |
| either, via the CLI | `python -m backend.app.cli backup --out FILE` | `python -m backend.app.cli restore --from FILE` |
| SQLite (dev) | the CLI uses SQLite's online backup API; or copy `backend/var/sigil.db` while stopped | copy the file back |

Back up `backend/var/registry.key` (and keep its passphrase) together with the database: receipts and
certificates are signed with it. Uploaded models live in `backend/var/uploads` (content-addressed by SHA-256).
After a restore, `python -m backend.app.cli verify-audit` checks the audit chain.

## 4. How v1 maps to the demo server (API-02)

The v1 API is `demo/server.py`'s contract (UI_INTEGRATION.md §4), unchanged, so the current UI and
`contract/examples/minimal-ui` run on FastAPI as they are. `backend/app/legacy.py` loads `demo/server.py` and
reuses, rather than re-implements:

| From demo/server.py | Used for |
|---|---|
| `STEPS`, `STEP_INFO` (incl. per-step `timeout`; demo F `protocol_v2`) | `/api/steps`, what `/api/run` executes |
| `Job.run()`, `cancel()`, the timeout watchdog, `kill_tree` | every job: crash-safe, cancel = code −2, timeout = code −3, process tree killed |
| `sim_log_for` | simulate mode's choice of recorded log (incl. `tries`) |
| `host_of`, `origin_allowed`, `safe_join`, `parse_object`, `read_json`, `CONTENT_TYPES` | the middleware, `/results`, request parsing, `/api/state` |
| `model_catalogue` (`catalogue`, `resolve`, `safe_name`) | `/api/models`, the `model` of a `model_test` run (catalogue ids only, never paths), its simulate-mode recording |
| `demo_common` (`child_env`, `is_noise`, `scrub_paths`, `current_commitment`) | live runs and log scrubbing |

Same status codes and bodies: 202 / 400 / 403 / 404 / 409 (`another demo is running` with the running job) /
413 / 415, `{"error": "..."}`. Same SSE framing (`id:` = line index, JSON-encoded `data:`, `: keepalive` every
~10 s, `event: done` with the final `JobInfo`, then the stream closes) and `Last-Event-ID` resume.

Additive differences: jobs and every output line are persisted (`GET /api/jobs/{id}` and its stream also work
after a restart); a job the server was running when it stopped ends as `interrupted` (code 1) at the next
start; every run and cancel writes an audit event; successful live runs snapshot the result files they wrote
(history).

## 5. The v2 API in one flow

| Who | CLI (SDK) | API |
|---|---|---|
| owner | `sigil keygen` | `POST /api/v2/owners {public_key}`: public keys only; private keys and seeds never reach the server |
| owner | `sigil embed ...` (training needs the seed) | `POST /api/v2/models` (upload), optionally `POST /api/v2/embeddings` (report) |
| owner | `sigil register model.pt` | `POST /api/v2/registrations` with that JSON: re-verified (`verify_registration`), then timestamped by the registry key (`make_receipt`) |
| verifier | upload the suspect | `POST /api/v2/models` (purpose `suspect`), `POST /api/v2/claims` (fresh nonce, `make_claim`) |
| owner | `sigil prove model.pt --claim claim.json` | `POST /api/v2/claims/{id}/proofs` (JSON) or `/proofs/upload` (files) |
| verifier | `sigil verify bundle/ ...` | `POST /api/v2/verifications`: `sigil.verify.verify_ownership`, with the suspect's Uchida vector recomputed from the stored file by `sigil.adapters` and the Groth16 proof checked with SnarkJS; verdict and every named reason persisted |
| anyone | | `GET /api/v2/verifications/{id}/certificate` (signed JSON) and `.pdf`; `GET /api/v2/registrations/earliest?model_sha256=` (dispute rule) |

Proving happens on the owner's machine because it needs the seed; the server never holds one. If
`sigil.adapters` is not installed, `POST /verifications` requires `suspect_vector` in the request and records
`vector_source: "request"` (flagged in the certificate) — **TODO(M4) fallback only**; with the adapters (the
default since M4) the vector always comes from the file.

## 6. Jobs (API-04)

One job runs at a time. `POST /api/run` (v1) answers 409 while a job runs; `POST /api/v2/attacks/runs` queues
behind it (FIFO). Every job and line is written to `jobs` / `job_logs` by a single writer thread (batched, so a
slow database never slows a job). Cancel (`POST /api/jobs/{id}/cancel`, `POST /api/v2/jobs/{id}/cancel`) also
works for queued jobs. A successful `attacks` (or `all`) job records an `attack_runs` row from `attacks.json`.

## 7. Audit log (DB-03)

`event_json` is the canonical JSON (sorted keys, no whitespace, UTF-8) of
`{seq, ts, actor, action, resource_type, resource_id, details}`, and
`hash = SHA-256(prev_hash_hex || event_json)` with 64 zeros before the first event. Every state-changing call
appends one event in the same transaction as the change (a process lock plus `pg_advisory_xact_lock` keep the
chain linear). Database triggers refuse `UPDATE`, `DELETE` and `TRUNCATE` on `audit_events`.

* `GET /api/v2/audit/verify` (or `python -m backend.app.cli verify-audit`) re-checks every link, the hash, and
  that the stored columns equal the hashed JSON. Someone who disables the triggers and edits a row is caught.
* Someone who rewrites the *whole* chain is caught by an earlier **signed head**: keep the output of
  `GET /api/v2/audit/head` (or an export) and pass it as `?anchor_seq=&anchor_hash=`.
* `GET /api/v2/audit/export?format=json|csv` includes every event's `event_json`, `prev_hash` and `hash`, so it
  can be verified offline (`verify-audit --export FILE`); the JSON is registry-signed, the CSV's signed head is in
  the `X-Sigil-Chain-Head` header.

## 8. Reports (API-08) and monitoring (API-09)

* **Certificate** per verification: `sigil.certificate/v1` JSON (registration, receipt, claim, proof hash,
  public signals, verdict, every check and reason, honest-claim statements) signed by the registry key, plus a
  PDF rendering. `POST /api/v2/reports/verify-signature` checks any signed document.
* **Compliance report** (`/api/v2/reports/compliance`, `.pdf`): the evidence in the database mapped to the OWASP
  AI Exchange #MODEL WATERMARKING text (R1 robustness, R2 non-ambiguity, R3 purpose, L1 limitation; quoted from
  `01_Literature_Gap_Analysis.md` §2) and to REQUIREMENTS IDs, with an honest status per item (L1 stays
  `missing` until WM-06/ROB-03).
* **Deployments**: name, environment, artefact path (inside `SIGIL_DEPLOYMENT_ROOTS`), expected SHA-256. A check
  (on demand, or every `SIGIL_MONITOR_INTERVAL` s) re-hashes the file: `ok`, `mismatch`, `missing` or `error`;
  anything but `ok` is an alert (`GET /api/v2/deployments/alerts`, audit event `deployment.alert`). Each check also
  records whether the observed hash has a registration. Watermark detection needs the owner's seed, so it is
  not part of the server-side check.

## 9. Security model (NFR-04, UI_INTEGRATION.md §10)

* **Local only:** binds 127.0.0.1; the `Host` header must be localhost / 127.0.0.1 / [::1] with a digits-only
  port (403 otherwise; blocks DNS rebinding).
* **No cross-site requests:** state-changing requests with a foreign `Origin` get 403 and must be
  `application/json` (415). The two upload endpoints also take `multipart/form-data`, but need a bearer token,
  which a cross-site form can't send. CORS is answered only for localhost origins, never `*`.
* **Authentication:** v2 needs `Authorization: Bearer sgl_...`; tokens are stored as SHA-256, passwords as
  Argon2id; tokens expire and can be revoked; a deactivated account's tokens stop working at once.
* **Roles:** *owner* (owner keys, model uploads, registrations, proofs, deployments, attack jobs), *verifier*
  (suspect uploads, claims, verifications, audit), *admin* (everything, plus accounts). Owners can only use
  owner keys they registered. The v1 demo endpoints stay unauthenticated (they're the localhost demo).
* **No secrets on the server:** request models reject unknown fields, so a seed or private key sent by mistake
  is refused, not stored. The only server secret is the registry key, encrypted at rest.
* **Uploads:** size limit, extension and magic-byte checks, structure checks (`onnx.checker`, zip directory),
  SHA-256 on receipt, content-addressed storage outside every static root; raw pickle `.pt` files are refused
  and nothing is ever unpickled (layer listing uses `torch.load(weights_only=True)`).
* **Errors and logs:** v2 errors are RFC 9457 `application/problem+json`; logs are one JSON object per line,
  without request bodies or query strings, with tokens, passwords, passphrases, seeds and private keys masked.
* **Path confinement:** `/results` and the UI use `safe_join`; deployments can only point into the configured
  roots.

Not covered yet: login rate limiting, TLS (local-only by design), RFC 3161 timestamps (CR-03 SHOULD).

## 10. Tests

```bash
pip install -r backend/requirements.txt
python -m pytest tests/test_backend_*.py                 # SQLite
SIGIL_TEST_DB=pg python -m pytest tests/test_backend_*.py  # the whole suite on an embedded PostgreSQL 16 (pgserver)
python -m pytest -m pg tests/test_backend_pg.py          # PostgreSQL-specific checks
SIGIL_CIRCUITS=<repo>/circuits python -m pytest tests/test_backend_flow.py   # incl. a real Groth16 proof
```

The embedded PostgreSQL comes from the `pgserver` wheel (data in `backend/var/test-pg`); each test app gets a
fresh database migrated with Alembic. The real-proof test needs the T = 64 circuit set up (`circuits/build/*.zkey`)
and `node`; it is skipped otherwise.
