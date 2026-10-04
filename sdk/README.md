# sigil: watermark neural networks, prove ownership in zero knowledge

`sigil` is the project's Python SDK (REQUIREMENTS.md §10). It embeds a white-box (Uchida-style)
watermark whose key and signature are derived from a secret seed committed with Poseidon and bound to
an Ed25519 owner key, and proves ownership with a Groth16 zk-SNARK (Circom + SnarkJS) without
revealing the seed, the key or the signature. The protocol is specified in
[`../docs/protocol.md`](../docs/protocol.md).

```bash
pip install -e "./sdk[torch,onnx]"     # from the repository root; extras: torch, tf, onnx, dev
```

| Module | What |
|---|---|
| `sigil.field`, `sigil.poseidon` | BN254 field and Poseidon, bit-exact with circomlib |
| `sigil.protocol` | Protocol v2: config, key/signature/commitment derivation, quantisation, model binding, detection |
| `sigil.identity` | Ed25519 owner keys, encrypted at rest |
| `sigil.records` | Canonical JSON, signed registrations, registry timestamps, claims |
| `sigil.zk` | Circom/SnarkJS backend: witness, setup, prove, verify with public-signal checks |

Licence: Apache-2.0 (the circuits in `../circuits` are GPL-3.0).
