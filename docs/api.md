# API reference (v1 + v2)

The machine-readable spec is [`contract/openapi.json`](../contract/openapi.json) (served at `/api/openapi.json`;
regenerate with `python -m backend.app.cli export-openapi`; a test fails if the committed file is stale).
Running the backend: [backend.md](backend.md). v1 details: [UI_INTEGRATION.md §4](../UI_INTEGRATION.md).

## Conventions

* **Base:** `http://127.0.0.1:8765`. Every request needs a localhost `Host`; state-changing requests must not
  carry a foreign `Origin` and must be `Content-Type: application/json` (uploads: `multipart/form-data`).
* **v1** (`/api/*`, `/results/*`): unauthenticated localhost demo; errors are `{"error": "..."}`.
* **v2** (`/api/v2/*`): `Authorization: Bearer sgl_...` from `POST /api/v2/auth/login` (except `health`,
  `registry` and `auth/login`); errors are RFC 9457 `application/problem+json`:
  `{"type": "about:blank", "title": "...", "status": 422, "detail": "...", "instance": "/api/v2/...", ...}`
  with extension members such as `problems` (registration checks) or `errors` (validation).
* **Lists** take `limit` (1–500, default 100) and `offset`.
* **Roles:** O = owner, V = verifier, A = admin (admins pass every role check), * = any signed-in user.

## v1: demo (unchanged contract)

| Method | Path | Purpose | Codes |
|---|---|---|---|
| GET | `/api/state` | Everything to render panels A–F (`DemoState`, incl. `results.protocol_v2`) | 200 |
| GET | `/api/steps` | Step catalogue: labels, durations, timeouts, confirmations | 200 |
| POST | `/api/run` | Start a step `{step, tries?}`; one job at a time | 202, 400, 403, 409, 413, 415 |
| POST | `/api/jobs/{id}/cancel` | Stop a running job (`{}`) | 202, 400, 403, 404, 409, 415 |
| GET | `/api/jobs/{id}` | Job status + all output | 200, 404 |
| GET | `/api/jobs/{id}/stream` | SSE: one event per line (`id` = index), `: keepalive`, `event: done`; `Last-Event-ID` resumes | 200, 404 |
| GET | `/results/{file}` | PNG/CSV/JSON/TXT from `demo/results` (`Cache-Control: no-cache`) | 200, 404 |
| GET | `/*` | The UI build, SPA fallback to `index.html` | 200, 503 |

## v2

| Method | Path | Roles | Purpose | Codes |
|---|---|---|---|---|
| POST | `/api/v2/auth/login` | – | Username + password → API token (`sgl_...`, shown once) | 200, 401, 422 |
| GET | `/api/v2/auth/me` | * | The calling user | 200, 401 |
| GET / POST | `/api/v2/auth/tokens` | * | List your tokens / create another one | 200, 201, 401, 422 |
| DELETE | `/api/v2/auth/tokens/{id}` | * | Revoke a token (admins: anyone's) | 204, 401, 404 |
| GET / POST | `/api/v2/users` | A | List accounts / create one with a role | 200, 201, 403, 409, 422 |
| PATCH | `/api/v2/users/{id}` | A | Change role, deactivate | 200, 403, 404, 422 |
| POST | `/api/v2/owners` | O | Register an Ed25519 **public** key | 201, 403, 409, 422 |
| GET | `/api/v2/owners`, `/api/v2/owners/{id}` | * | Owner keys with their Poseidon `pk_hash` | 200, 404 |
| POST | `/api/v2/models` | O, V | Upload `.pt` `.h5` `.keras` `.onnx` (multipart `file`, `name`, `description`, `purpose`) | 201, 403, 413, 415, 422 |
| GET | `/api/v2/models`, `/api/v2/models/{id}` | * | Models and artefacts (filter `purpose`, `sha256`) | 200, 404 |
| GET | `/api/v2/artifacts/{id}/layers` | * | Weight tensors / layers via safe loaders | 200, 404, 422 |
| POST / GET | `/api/v2/embeddings` | O / * | Record / list embedding reports (public config + metrics) | 201, 200, 404, 422 |
| GET | `/api/v2/registry` | – | Registry public key, trusted keys, dispute rule | 200 |
| POST | `/api/v2/registrations` | O | Submit a `sigil.registration/v2` record; returns it with the registry receipt | 201, 403, 409, 422 |
| GET | `/api/v2/registrations`, `/{id}` | * | Registrations + receipts (filter `model_sha256`, `owner_id`) | 200, 404 |
| GET | `/api/v2/registrations/earliest?model_sha256=` | * | Dispute rule: earliest valid registration wins | 200, 422 |
| POST | `/api/v2/claims` | V | Open a claim `{registration_id, suspect_artifact_id}` (fresh nonce) | 201, 403, 404, 422 |
| GET | `/api/v2/claims`, `/{id}` | * | Claims (the owner needs the nonce) | 200, 404 |
| POST | `/api/v2/claims/{id}/proofs` | O | Proof bundle as JSON `{proof, public}` | 201, 403, 404, 422 |
| POST | `/api/v2/claims/{id}/proofs/upload` | O | Proof bundle as files `proof`, `public`, optional `claim` | 201, 403, 404, 413, 422 |
| GET | `/api/v2/proofs/{id}`, `/{id}/bundle` | * | Proof metadata / full bundle (proof, public, claim, registration, receipt) | 200, 404 |
| POST | `/api/v2/verifications` | V | Verify `{proof_id}`: verdict + named reasons, persisted | 201, 403, 404, 409, 422 |
| GET | `/api/v2/verifications`, `/{id}` | * | Verification history (filter `claim_id`, `accepted`) | 200, 404 |
| GET | `/api/v2/verifications/{id}/certificate` | * | Ownership certificate, registry-signed JSON | 200, 404 |
| GET | `/api/v2/verifications/{id}/certificate.pdf` | * | The certificate as PDF | 200, 404 |
| GET | `/api/v2/jobs`, `/{id}?output=true` | * | Persisted jobs (v1 and v2) with status | 200, 404 |
| POST | `/api/v2/jobs/{id}/cancel` | O | Cancel a queued or running job | 202, 403, 404, 409 |
| GET | `/api/v2/attacks/runs`, `/{id}` | * | Attack runs and per-attack accuracy / BER / verdict | 200, 404 |
| POST | `/api/v2/attacks/runs` | O | Start the attack suite as a job (queued if busy) | 202, 403 |
| POST / GET | `/api/v2/deployments` | O / * | Register / list deployments | 201, 200, 403, 404, 422 |
| GET | `/api/v2/deployments/alerts` | * | Active deployments whose last check alerted | 200 |
| GET / PATCH | `/api/v2/deployments/{id}` | * / O | One deployment / pause, resume, accept a new hash | 200, 403, 404, 422 |
| POST | `/api/v2/deployments/{id}/check` | O | Re-hash now (`ok`, `mismatch`, `missing`, `error`) | 200, 403, 404 |
| GET | `/api/v2/deployments/{id}/checks` | * | Check history | 200, 404 |
| GET | `/api/v2/audit/events` | V | Events in chain order (`after_seq`, `action`) | 200, 403 |
| GET | `/api/v2/audit/verify` | V | Re-check the chain (optional `anchor_seq` + `anchor_hash`) | 200, 403, 422 |
| GET | `/api/v2/audit/head` | V | Registry-signed chain head | 200, 403 |
| GET | `/api/v2/audit/export?format=json\|csv` | V | Export with the hash-chain proof | 200, 403 |
| GET | `/api/v2/reports/compliance`, `.pdf` | * | Evidence mapped to OWASP #MODEL WATERMARKING and REQUIREMENTS IDs | 200 |
| POST | `/api/v2/reports/verify-signature` | * | Check a registry-signed document | 200, 422 |
| GET | `/api/v2/history/results`, `/{id}` | * | Versions of the demo result files (DB-04) | 200, 404 |
| GET | `/api/v2/health` | – | Liveness + database | 200 |
| GET | `/api/v2/environment` | * | Mode, GPU probe, SDK/adapters, ZK toolchain, database dialect | 200 |

All v2 endpoints may also answer 401 (no or bad token) and 403 (role, host or origin).

## Verification reasons

`POST /api/v2/verifications` returns `checks` (each `true`/`false`) and `reasons`, from
`sigil.verify.verify_ownership` (docs/protocol.md §8): `registration invalid: ...`, `registry receipt invalid: ...`,
`registration is not earlier than the claim`, `claim refers to a different registration`, `claim refers to a
different suspect model file`, `wrong number of public signals`, `proof is about a different model (w_hash
mismatch)`, `proof was made for a different claim (nonce mismatch: replay?)`, `proof opens a different
commitment`, `proof is for a different owner key`, `proof uses a different watermark configuration`,
`the zk-SNARK does not verify`. The backend adds `the zk-SNARK was not checked: ...` when no verification key or
ZK toolchain is available (the proof is then not accepted).

## Example

```bash
T=$(curl -s -X POST localhost:8765/api/v2/auth/login -H 'Content-Type: application/json' \
      -d '{"username":"olivia","password":"..."}' | python -c 'import json,sys;print(json.load(sys.stdin)["token"])')
curl -s -X POST localhost:8765/api/v2/owners -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
     -d "{\"public_key\": \"$(sigil --json keygen | jq -r .public_key)\", \"label\": \"lab key\"}"
curl -s -X POST localhost:8765/api/v2/models -H "Authorization: Bearer $T" -F file=@model.wm.pt -F name=mnist
curl -s -X POST localhost:8765/api/v2/registrations -H "Authorization: Bearer $T" \
     -H 'Content-Type: application/json' --data @registration.json
```
