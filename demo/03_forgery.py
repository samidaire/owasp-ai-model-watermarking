"""DEMO C: ownership forgery when the watermark key is NOT committed in advance
(OWASP AI Exchange requirement R2: 'avoid ambiguity where multiple parties could
plausibly claim ownership').

Part 1 - Uchida ambiguity attack (cf. Fan et al., NeurIPS 2019): given only the weights,
         fit a counterfeit key X' so that extraction yields the thief's chosen signature.
Part 2 - Same construction against the relation ZKROWNN's circuit checks
         (Sheybani et al., DAC 2023, Algorithm 1). ZKROWNN states a semi-honest prover;
         this shows what happens when that assumption is dropped. The relation is evaluated
         in plain PyTorch here; their zkSNARK circuit is not run.
"""
import numpy as np
import torch
import torch.nn.functional as F

from wm_core import (M_DIM, T_BITS, THETA, banner, ber, bits_to_text, device, extract_bits,
                     load_mnist, load_model, load_owner, null_model_names, text_to_bits,
                     wm_vector)

dev = device()
d = load_mnist(dev)
_, _, _, X_owner, b_owner = load_owner(dev)
stolen = load_model("watermarked", dev)
clean = load_model("clean", dev)
nulls = {n: load_model(n, dev) for n in null_model_names()}
thief_bits = torch.from_numpy(text_to_bits("MALLORY!")).to(dev)


def sign_fit(R, proj, target):
    """Flip each random row/column so its projection lands on the target bit's side."""
    s = torch.sign(proj)
    s[s == 0] = 1
    return s * (target.float() * 2 - 1)


def forge_uchida_key(model, target, seed=0):
    w = wm_vector(model).detach()
    R = torch.randn(T_BITS, M_DIM, generator=torch.Generator().manual_seed(seed)).to(dev)
    return R * sign_fit(R, R @ w, target).unsqueeze(1)


def ks_stat(a, b):
    a, b = np.sort(a), np.sort(b)
    v = np.concatenate([a, b])
    return np.max(np.abs(np.searchsorted(a, v, "right") / len(a) - np.searchsorted(b, v, "right") / len(b)))


# --------------------------------------------------------------------------- part 1
banner("DEMO C, part 1: Uchida ambiguity attack (thief has only the stolen weights)")
Xf = forge_uchida_key(stolen, thief_bits)
print(f"  Owner, real key        : BER = {ber(extract_bits(stolen, X_owner), b_owner):.3f}")
fb = extract_bits(stolen, Xf)
print(f"  Thief, counterfeit key : BER = {ber(fb, thief_bits):.3f}   extracted message = '{bits_to_text(fb.cpu())}'")
print("  -> Both parties 'prove' ownership of the same model.\n")

def margins(K, model):
    w = wm_vector(model).detach()
    return ((K @ w).abs() / w.norm()).cpu().numpy()      # in units of a random row's std


def forge_large_margin_key(model, target, min_margin, seed=0):
    """A more careful forger: keep only random rows whose projection is at least min_margin."""
    w = wm_vector(model).detach()
    g = torch.Generator().manual_seed(seed)
    rows = []
    while len(rows) < T_BITS:
        R = torch.randn(4096, M_DIM, generator=g).to(dev)
        rows += list(R[((R @ w).abs() / w.norm()) >= min_margin])
    R = torch.stack(rows[:T_BITS])
    return R * sign_fit(R, R @ w, target).unsqueeze(1)


a = X_owner.flatten().cpu().numpy()
crit = 1.36 * np.sqrt(2 / len(a))
mo = margins(X_owner, stolen)
Xl = forge_large_margin_key(stolen, thief_bits, float(mo.min()))
print("  Can a judge who SEES the key and weights tell the counterfeit apart?")
print(f"    {'key':<27}{'entry mean':>11}{'entry std':>10}{'KS D':>8}{'min margin':>12}{'median margin':>15}")
for name, K in [("owner (real)", X_owner), ("forged, naive", Xf), ("forged, large-margin rows", Xl)]:
    e, m = K.flatten().cpu().numpy(), margins(K, stolen)
    print(f"    {name:<27}{e.mean():>+11.4f}{e.std():>10.4f}{ks_stat(a, e):>8.4f}{m.min():>12.2f}{np.median(m):>15.2f}")
print(f"    (KS 5% critical value {crit:.4f}; margins in units of a random row's std)")
print(f"    Large-margin forgery BER = {ber(extract_bits(stolen, Xl), thief_bits):.3f}")
print("    -> Entry distributions match a real key. The naive forgery has smaller margins, which a")
print("       careful forger can raise by rejection sampling. Under ZK the verifier sees neither.\n")

print("  The same trick 'proves' ownership of models that were NEVER watermarked:")
for name, m in [("clean", clean), *nulls.items()]:
    print(f"    {name:<8} thief BER = {ber(extract_bits(m, forge_uchida_key(m, thief_bits)), thief_bits):.3f}")


# --------------------------------------------------------------------------- part 2
def zkrownn_relation(model, Xkey, A, wm, theta=THETA):
    """Algorithm 1 of ZKROWNN: zkFeedForward to l_wm (first hidden layer), zkAverage,
    zkSigmoid(mu @ A), zkHardThresholding(0.5), zkBER <= theta. Returns (passes, BER)."""
    with torch.no_grad():
        acts = F.relu(model.conv1(Xkey)).flatten(1)
        mu = acts.mean(0)
        wm_hat = (torch.sigmoid(mu @ A) >= 0.5).to(torch.uint8)
        e = ber(wm_hat, wm)
    return e <= theta, e


def forge_zkrownn_witness(model, Xkey, target, seed=0):
    with torch.no_grad():
        mu = F.relu(model.conv1(Xkey)).flatten(1).mean(0)
    R = torch.randn(mu.numel(), T_BITS, generator=torch.Generator().manual_seed(seed)).to(dev)
    return R * sign_fit(R, mu @ R, target).unsqueeze(0)


banner("DEMO C, part 2: same construction against ZKROWNN's Algorithm 1 relation")
Xkey = d["x_att"][:100]   # thief's own 'trigger key': 1% of their data, as in DeepSigns
print("  Private witness chosen by the thief AFTER seeing the model:")
print(f"    trigger key X_key : {tuple(Xkey.shape)} (thief's own images)")
print(f"    projection A      : fitted, {forge_zkrownn_witness(stolen, Xkey, thief_bits).shape[0]} x {T_BITS}")
print("    watermark wm      : 'MALLORY!' (64 bits)\n")
for name, m in [("stolen", stolen), ("clean", clean), *nulls.items()]:
    ok, e = zkrownn_relation(m, Xkey, forge_zkrownn_witness(m, Xkey, thief_bits), thief_bits)
    print(f"    {name:<8} relation satisfied = {ok}   BER = {e:.3f}")
print("\n  -> Without a prior commitment, a valid witness exists for ANY model.")
print("     A zero-knowledge proof of this relation would verify, and would hide the fitted A.")
print("  Caveat: ZKROWNN assumes a semi-honest prover; this is outside its stated threat model.")

# ---- structured results for the web UI (additive; recomputes the same deterministic values)
from demo_common import current_commitment, write_json
key_stats = []
for name, K in [("owner (real)", X_owner), ("forged, naive", Xf), ("forged, large-margin rows", Xl)]:
    e, m = K.flatten().cpu().numpy(), margins(K, stolen)
    key_stats.append({"key": name, "entry_mean": float(e.mean()), "entry_std": float(e.std()),
                      "ks_d": float(ks_stat(a, e)), "min_margin": float(m.min()), "median_margin": float(np.median(m))})
owner_bits = extract_bits(stolen, X_owner)
zk_rows = []
for name, m in [("stolen", stolen), ("clean", clean), *nulls.items()]:
    ok, e = zkrownn_relation(m, Xkey, forge_zkrownn_witness(m, Xkey, thief_bits), thief_bits)
    zk_rows.append({"model": name, "satisfied": bool(ok), "ber": e})
write_json("forgery.json", {
    "commitment": current_commitment(), "threshold": THETA,
    "owner": {"ber": ber(owner_bits, b_owner), "signature_bits": b_owner.tolist(), "extracted_bits": owner_bits.tolist()},
    "thief": {"target_text": "MALLORY!", "target_bits": thief_bits.tolist(), "extracted_bits": fb.tolist(),
              "ber": ber(fb, thief_bits), "message": bits_to_text(fb.cpu())},
    "large_margin_ber": ber(extract_bits(stolen, Xl), thief_bits),
    "key_stats": key_stats, "ks_critical": float(crit),
    "never_watermarked": [{"model": n, "thief_ber": ber(extract_bits(m, forge_uchida_key(m, thief_bits)), thief_bits)}
                          for n, m in [("clean", clean), *nulls.items()]],
    "zkrownn": {"xkey_shape": list(Xkey.shape), "a_shape": [int(forge_zkrownn_witness(stolen, Xkey, thief_bits).shape[0]), T_BITS],
                "rows": zk_rows},
})
