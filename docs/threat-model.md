# Threat model (NFR-04)

This covers the **software**: SDK, CLI, demo server, backend and UI. The cryptographic protocol's threat model
(malicious prover, thief, registry trust) is in [protocol.md](protocol.md) §1 and §10.

## Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| Owner seed | `secrets/seed.json` (scrypt + AES-256-GCM) | Anyone holding it can prove ownership of every model it marked |
| Owner Ed25519 private key | `secrets/owner.key` (encrypted PKCS#8) | Signs registrations: it *is* the owner's identity |
| Registry private key | backend `var/` (encrypted) or `secrets/registry.key` | Issues the timestamps that settle disputes |
| Watermark key X and signature b | derived in memory from the seed; never stored | They reveal the mark; with them, removal is easy |
| Proving keys (`*.zkey`) | `circuits/build/`, shipped as a zip | Public; integrity matters (a swapped key yields unverifiable proofs) |
| Verification keys, setup transcripts | `circuits/keys/` (in git) | Public; integrity matters (they define what "valid" means) |
| Registrations, receipts, proofs, verifications, audit log | backend database, `demo/results/` | Integrity and history of claims |
| Demo identities (`demo/ckpt/v2`, `demo/ckpt/owner_secret.json`) | in git | **Public by design.** Demo values, never real secrets |

## Trust boundaries

1. **The local machine and a browser on it.** The server binds `127.0.0.1` only.
2. **Model files from outside.** Suspect models are untrusted input: they may be crafted to execute code when loaded.
3. **Proof bundles from a prover.** Untrusted: the verifier recomputes everything it can.
4. **Other websites in the same browser.** They can send requests to localhost (CSRF, DNS rebinding).
5. **Downloads at setup time:** PyPI, npm, the circom release, the Powers of Tau file.

## STRIDE

| Threat | Example | Control in this codebase | Residual risk |
|---|---|---|---|
| **S**poofing an owner | Thief registers a model under someone else's name | Registrations are Ed25519-signed; the commitment is bound to `pk_hash` (`records.py`, `protocol.py`) | Owner key theft (protect `secrets/`) |
| Spoofing the registry | Fake receipt to back-date a claim | Receipt signature checked against **trusted** registry keys only (`verify_receipt`) | Registry key compromise: rotate and re-trust |
| **T**ampering with a proof or public signals | Edit `public.json` to point at another model | Groth16 verification and every public signal recomputed by the verifier (`verify.py`); test `test_tampered_public_signal_rejected` | — |
| Tampering with proving keys | Swapped zkey in a shipped zip | `setup_env.py --keys` accepts a zkey only if its SHA-256 matches the committed setup transcript | Transcript in git must itself be trusted |
| Tampering with Powers of Tau | Malicious ptau download | Transcript verification on first download (`snarkjs powersoftau verify`), then BLAKE2b pinned in `sigil.zk.ptau` | One honest ceremony participant assumed (Groth16) |
| Tampering with results/history | Edit verification history in the DB | Hash-chained, append-only `audit_events` (backend, DB-03) | Whoever controls the DB can rebuild the chain; export and sign periodically |
| **R**epudiation | Owner denies having registered | Signed registration and registry receipt; audit log | — |
| **I**nformation disclosure: seed or key | Seed in logs or result files | Seeds encrypted at rest; key and signature never written. 01_train/evaluate print only 8 signature bits. `TorchWatermark` and the Keras regulariser refuse to print or serialise the key. Test `test_no_secret_artifacts.py` scans results. | Process memory while the owner proves |
| Disclosure through ONNX exports | Key baked into an exported circuit model (FIX-03) | `05_ezkl_spike.py` deletes `extract.onnx`; `.gitignore`; secret-scan test | **Old git history still contains the demo's v1 files.** That key is a public demo value anyway. |
| Disclosure through proofs | Proof leaks the watermark | Groth16 is zero-knowledge; public signals are hashes and the nonce only | — |
| **D**enial of service | Huge or zip-bomb model upload; a job that never ends | Upload size limits and zip-bomb checks (adapters, API-05); per-step timeouts, cancel, one GPU job at a time (FIX-11, API-04) | Local machine resources |
| **E**levation: code execution from a model file | Malicious pickle in a `.pt`; a Keras `Lambda` | `torch.load(weights_only=True)` only; Keras `safe_mode=True`, Lambda refused without `--trust`; `onnx.checker`; tests with malicious files (`test_adapters_*`) | `--trust` exists for the owner's own files: never use it on suspect files |
| Elevation from another website | A page in the user's browser POSTs `/api/run` | Host allow-list (blocks DNS rebinding), Origin check, `Content-Type: application/json` required, localhost-only CORS (FIX-11, API-01; `tests/test_server.py`) | — |
| Path traversal | `/results/../../secrets/owner.key` | `safe_join` on `/results` and static files; traversal tests | — |
| Supply chain | Compromised npm/PyPI package | Pinned versions (`demo/requirements.txt`, lock files); circom from the official release | Pins aren't hashes everywhere yet (see NFR-02 follow-up) |

## Rules for operators

- Keep `secrets/` off shared drives and out of chats; it's gitignored.
- Never run `--trust` on a model you didn't produce.
- Treat `demo/ckpt/**` identities as public: they are.
- Verify with the registry public keys you obtained out of band, not with keys from the prover.
