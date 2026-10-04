# sigil: watermark neural networks, prove ownership in zero knowledge

`sigil` is the project's Python SDK (REQUIREMENTS.md §10). It covers:
- **Watermark:** embeds a white-box (Uchida-style) watermark into a PyTorch or Keras model.
- **Commit:** the key and signature are derived from a secret seed, committed with Poseidon and bound to an
  Ed25519 owner key.
- **Prove:** proves ownership with a **Groth16 zk-SNARK (Circom + SnarkJS)** without revealing the seed, the
  key or the signature.
- **Verify:** the verifier recomputes everything it can from the suspect model file.

Everything is specified in [`../docs/protocol.md`](../docs/protocol.md).

```bash
pip install -e "./sdk[torch,onnx]"          # from the repository root
pip install -e "./sdk[tf]"                  # TensorFlow/Keras support (tf2onnx included)
cd circuits && npm install                  # Circom libraries + SnarkJS for proving/verifying
```

The circom 2.2.x compiler is also needed: `tools/bin/circom(.exe)`, or set `SIGIL_CIRCOM`.

## The two roles, from the command line

**Owner** (once per model):

```bash
export SIGIL_PASSPHRASE='a long passphrase'          # or you'll be prompted
sigil keygen                                          # secrets/owner.key  (Ed25519, encrypted)
sigil seed --bits 64 --layer conv2                    # secrets/seed.json  (encrypted seed + config)
# ... train with the watermark (Python API below), save model.pt ...
sigil detect model.pt                                 # errors / T, accepted?
sigil register model.pt --registry-key secrets/registry.key   # registration.json + registry receipt
```

**Verifier** (in a dispute; the owner proves):

```bash
sigil claim registration.json --suspect suspect.onnx            # claim.json with a fresh nonce
sigil prove suspect.onnx --claim claim.json --out bundle        # (owner) bundle/proof.json, public.json
sigil verify bundle --suspect suspect.onnx --registration registration.json \
             --receipt registration.receipt.json --trusted-registry <registry public key hex>
```

`verify` exits with 0 only when **every** check passes:
- registration signature;
- registry receipt, earlier than the claim;
- claim ↔ registration ↔ suspect file;
- every public signal, including `w_hash` recomputed from the suspect file;
- the SNARK.

Each failure is reported with its own reason.

**One-time circuit setup** per configuration (downloads and checks the Powers of Tau):

```bash
sigil zk-setup --bits 64        # ~2.5 min; writes circuits/keys/<circuit>.vkey.json + setup transcript
sigil zk-info --bits 256
```

## Python API

```python
from sigil import protocol as P
from sigil.identity import KeyPair
from sigil.embed import embed_torch                      # or embed_keras
from sigil.adapters import uchida_vector, detect         # .pt / .h5 / .keras / .onnx or in-memory models

owner = KeyPair.generate()
cfg = P.Config(T=64, M=288, layer="conv2")               # M = in_channels * kh * kw of that layer
seed, pkh = P.new_seed(), P.pk_hash(owner.public_bytes)
model, det = embed_torch(model, (x_train, y_train), cfg, seed, pkh, epochs=2)
assert det.accepted                                      # checked on the quantised vector the proof uses

from sigil.records import make_registration, make_receipt, make_claim
reg = make_registration(owner, seed, cfg, model_sha256)  # owner-signed; contains no secret
rcp = make_receipt(registry_key, reg)                    # registry timestamp
claim = make_claim(reg, suspect_sha256)                  # verifier's nonce

from sigil.zk.circom import prove
w_q = P.quantize(uchida_vector("suspect.onnx", cfg.layer), cfg)
proof, public, timing = prove(cfg, P.circuit_input(seed, w_q, pkh, cfg, int(claim["nonce"])))

from sigil.verify import verify_ownership
verdict = verify_ownership(proof=proof, public=public, registration=reg, receipt=rcp, claim=claim,
                           suspect_w=uchida_vector("suspect.onnx", cfg.layer),
                           suspect_model_sha256=suspect_sha256,
                           trusted_registry_keys={registry_key.public_hex})
print(verdict.accepted, verdict.reasons)
```

| Module | What |
|---|---|
| `sigil.field`, `sigil.poseidon` | BN254 field and Poseidon, bit-exact with circomlib (checked against circomlibjs) |
| `sigil.protocol` | Config, key/signature/commitment derivation, quantisation, framework-independent Uchida vector, `w_hash`, detection, circuit input |
| `sigil.identity` | Ed25519 key pairs, encrypted PKCS#8 at rest |
| `sigil.secretbox` | Encrypted JSON (scrypt + AES-256-GCM) for seeds |
| `sigil.records` | Canonical JSON, signed registrations, registry receipts, dispute rule, claims |
| `sigil.adapters` | PyTorch / Keras / ONNX kernels and Uchida vectors, safe loading, regularisers ([report](../docs/reports/m4_adapters.md)) |
| `sigil.embed` | `embed_torch`, `embed_keras` |
| `sigil.zk` | Circom compile, Groth16 setup (PSE Powers of Tau), prove, verify |
| `sigil.verify` | The verifier's full procedure (ZK-06) |
| `sigil.cli` | The `sigil` command |

## Security rules the SDK enforces

- **No secret in a public file.** Seeds, owner private keys, X and the signature never appear in a public file:
  - registrations and claims contain none of them;
  - `TorchWatermark`/Keras regularisers refuse to print or serialise the key;
  - secrets are encrypted at rest.
- **Safe model loading only:**
  - `torch.load(weights_only=True)`;
  - Keras `safe_mode=True`, with Lambda layers refused unless you pass `trust=True`;
  - `onnx.checker`;
  - size limits.
- **Verification recomputes the model binding.** The suspect vector, and so `w_hash`, comes from the
  verifier's own copy of the suspect file, never from the prover.

## Known limitations

- **Model extraction:** white-box marks don't survive training a copy from the model's outputs (OWASP
  limitation L1). The trigger-set mark covers that case.
- **Permutation:** permuting a layer's channels removes the mark unless the owner realigns first.
- **BatchNorm folding:** ONNX exporters fold BatchNorm into the preceding conv, which changes the vector. See
  `docs/protocol.md` §5.
- **Trusted setup:** Groth16 needs one; see `docs/protocol.md` §9.

Licence: Apache-2.0. The circuits in `../circuits` are GPL-3.0.
