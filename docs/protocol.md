# Protocol v2: committed-seed watermark ownership with zero-knowledge proofs

**Status:** implemented (`sdk/src/sigil/protocol.py`, `records.py`, `verify.py`; `circuits/ownership.circom`).
**Requirements:** CR-01 to CR-06, ZK-01 to ZK-07, FIX-02 to FIX-06, FIX-17 ([REQUIREMENTS.md](../REQUIREMENTS.md)).

This replaces the demo's protocol v1 (SHA-256 commitment, Gaussian key from numpy, signature bound to
an unauthenticated `owner_id`). v1 stays in `demo/` for the research demos A–E.

## 1. Parties and threat model

| Party | Holds | Trusted for |
|---|---|---|
| **Owner** | secret seed *s*, Ed25519 private key | nothing (may be malicious when claiming someone else's model) |
| **Registry** | Ed25519 registry key | issuing honest timestamps (receipts) |
| **Verifier** | registry public keys, the suspect model file | nothing beyond running the checks in §6 |
| **Thief** | the stolen weights; may register their own seed and key; may fine-tune, prune, overwrite | — |

The prover is **malicious**: the scheme must not rely on a semi-honest prover (contrast ZKROWNN).
White-box access to the suspect model is required (gap G3); model extraction is out of scope for the
white-box mark (OWASP limitation L1) and is handled by the trigger-set mark (WM-06).

## 2. Notation and primitives

- **Field:** BN254 scalar field, *p* = 0x30644e72e131a029b85045b68181585d2833e84879b9709143e1f593f0000001.
- **H(·):** Poseidon over BN254 with circomlib's parameters (8 full rounds, partial rounds per width as in
  circomlibjs, *t* = inputs + 1, 1–16 inputs). Python: `sigil.poseidon`; checked against circomlibjs vectors.
- **Domain tags:** KEY = 1, SIG = 2, COMMIT = 3, W = 4, PK = 5, CFG = 6. Protocol version = 2.
- **tag(text)** = the first 31 bytes of SHA-256(UTF-8 text), read big-endian (always < *p*).
- **PRG_BITS** = 200: the number of low bits taken from each Poseidon output. The low 200 bits of a uniform
  field element are within 2⁻⁵³ of uniform.

## 3. Configuration (public, fixed at embedding time)

| Field | Demo value | Meaning |
|---|---|---|
| T | 64 | signature length (bits); 256 is the security configuration (DEC-03) |
| M | 288 | length of the Uchida vector (in_channels × kh × kw for a conv layer) |
| layer | `conv2` | name of the watermarked layer |
| scale_bits | 16 | fixed point: *w_q* = round(*w* · 2^scale_bits), round half to even |
| w_bits | 24 | range: \|*w_q*\| < 2^w_bits |
| max_err | 8 | accept iff at most max_err of T bits disagree (θ = max_err / T) |
| norm | `none` | normalisation before quantising (v2 defines none) |

**config_hash** = H(CFG, 2, T, M, scale_bits, w_bits, max_err, tag(layer), tag(norm), PRG_BITS).

## 4. Derivations

| Value | Definition |
|---|---|
| owner key | Ed25519; public key *pk* (32 bytes) |
| pk_hash | H(PK, int(*pk*[0:16]), int(*pk*[16:32])), big-endian halves |
| seed *s* | 248 uniformly random bits (a canonical field element) |
| commitment C | H(COMMIT, *s*, pk_hash, config_hash) |
| key stream | for k = 0, 1, …: low PRG_BITS bits of H(KEY, *s*, pk_hash, k); bit *t* of block k is (out ≫ *t*) & 1 |
| key X | X[i][j] = 2·keybit[i·M + j] − 1 ∈ {−1, +1}, i < T, j < M (row-major) |
| signature b | first T bits of the stream H(SIG, *s*, pk_hash, k) |

Both X and b depend on the seed **and** the owner key, so a thief can't grind identities against a fixed
key (FIX-04). The config is inside the commitment, so it can't be changed after the fact (FIX-05).

**Embedding** (Uchida regulariser) trains the model so that sigmoid(X · *w*) ≈ b, where *w* is the Uchida
vector of the layer. The WM-02 parity study ([reports/wm02_parity.md](reports/wm02_parity.md)) shows the
±1 key performs like the original Gaussian key.

## 5. The suspect model's vector, detection and binding

1. **Uchida vector:** the mean over output units of the layer's float32 weights, computed in float64,
   flattened in the canonical order (in, kh, kw). PyTorch Conv2d is OIHW and Keras Conv2D is HWIO
   (transposed to OIHW first); Linear/Dense are OI/IO. So `.pt`, `.h5`/`.keras` and `.onnx` copies of the
   same weights give the identical vector.
2. **Quantise:** *w_q* = round(*w* · 2^scale_bits); reject if any \|*w_q*\| ≥ 2^w_bits.
3. **Extract:** bit_i = 1 if Σ_j X[i][j] · *w_q*[j] ≥ 0, else 0.
4. **Accept** iff #{i : bit_i ≠ b_i} ≤ max_err.
5. **w_hash** (binds a proof to the suspect): with *v_j* = *w_q*[j] + 2^w_bits, absorb 15 values per call:
   h₀ = W; h_{c+1} = H(h_c, v_{15c}, …, v_{15c+14}) (zero-padded); w_hash = H(h_last, M).

## 6. Records

All records are canonical JSON: sorted keys, no whitespace, UTF-8, integers and strings only (no floats),
which coincides with RFC 8785 for these schemas. Field elements are decimal strings.

| Record | Signed by | Contents |
|---|---|---|
| `sigil.registration/v2` | owner | owner_public_key, pk_hash, config, config_hash, commitment, model_sha256, created_at |
| `sigil.receipt/v2` | registry | registration_sha256, registered_at, registry_public_key |
| `sigil.claim/v2` | (verifier-issued) | claim_id, **nonce** (fresh, uniform field element), registration_sha256, suspect_model_sha256, opened_at |

**Dispute rule:** among valid (registration, receipt) pairs for the same model, the earliest `registered_at`
wins. Receipts can't be back-dated without the registry key.

## 7. The zero-knowledge statement (circuits/ownership.circom)

**Public:** pk_hash, config_hash, commitment, w_hash, nonce.
**Private:** *s*, *w_q* (M values), scale_bits, tag(layer), tag(norm).

The circuit, compiled for fixed (T, M, w_bits, sum_bits, max_err, PRG_BITS), enforces:

1. config_hash = H(CFG, 2, T, M, scale_bits, w_bits, max_err, layer_tag, norm_tag, PRG_BITS), using its own
   compiled-in parameters. A registration for a strict threshold can't be proven with a lenient circuit.
2. commitment = H(COMMIT, *s*, pk_hash, config_hash).
3. Every *w_q*[j] + 2^w_bits fits in w_bits + 1 bits, and w_hash is the sponge of §5.5.
4. X and b come from the key and signature streams. Each Poseidon output is decomposed with
   `Num2Bits_strict`, so the prover can't substitute the alias out + *p*.
5. For each i, Σ_j X[i][j]·*w_q*[j] + 2^sum_bits fits in sum_bits + 1 bits; its top bit is bit_i.
6. #{i : bit_i ≠ b_i} ≤ max_err: the **threshold is enforced in-circuit** (FIX-06).
7. nonce² is computed, so the nonce is bound (an unconstrained public input isn't).

Size at T = 64, M = 288: **116,822 constraints** (`--O2`), so a 2¹⁷ Powers of Tau.

## 8. Verification (sigil.verify.verify_ownership)

A proof is accepted only if **all** of these hold. Each failure has its own reason.

1. The registration is well-formed, every derived field recomputes, and the owner signature is valid.
2. The receipt is for this registration, signed by a trusted registry, and earlier than the claim.
3. The claim refers to this registration and to the SHA-256 of the suspect file the verifier holds.
4. The public signals equal [pk_hash, config_hash, commitment, w_hash, nonce]. The verifier takes these from
   the registration and claim, and **recomputes w_hash from the suspect file itself**.
5. The Groth16 proof verifies under the verification key for the registered configuration.

Check 4 is what the v1 demo lacked (FIX-02): a valid SNARK alone says nothing about *which* model, owner or
claim it is about.

## 9. Trusted setup (ZK-04)

Groth16 needs a structured reference string:
- **Phase 1:** the Privacy & Scaling Explorations *Perpetual Powers of Tau* (pot28_0080, 80 contributions).
  The file is verified with `snarkjs powersoftau verify` on first download, and its BLAKE2b is then pinned in
  `sigil.zk.ptau`.
- **Phase 2:** one contribution per circuit, made with in-memory randomness that is never stored. Its hash is
  recorded in `circuits/keys/<circuit>.setup.json`.

**Trust assumption:** the proving system is sound if at least one phase-1 contributor and the phase-2
contributor discarded their randomness. A multi-party phase 2 is out of scope (REQUIREMENTS §17).

## 10. Security notes

- **Forgery by search:** a thief who fixes a seed and key must still match T bits that are pseudo-random given
  (*s*, pk). Each try succeeds with probability P[Bin(T, ½) ≤ max_err]: about 2⁻³¹·⁷ at T = 64 and about 2⁻¹²⁰ at
  T = 256. Each try costs a Poseidon key derivation plus a projection, for any choice of *s* or owner key.
- **Overwriting:** a thief can embed their own valid mark after stealing. The registry timestamp, not the
  watermark, decides that dispute.
- **Permutation:** reordering a layer's channels is functionally neutral and changes *w*'s order. It defeats
  the white-box mark unless the owner realigns before proving (ROB-06).
- **Replay:** the verifier-issued nonce is a public input, so a proof can't be reused for another claim.
