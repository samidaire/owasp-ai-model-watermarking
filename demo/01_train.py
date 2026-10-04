"""DEMO A (setup): the owner commits to a secret seed, derives key + signature from it,
and trains a clean baseline, a watermarked model, and independent "null" models.

Outputs:
  ckpt/clean.pt, ckpt/watermarked.pt, ckpt/null_*.pt
  ckpt/owner_secret.json        (PRIVATE: the seed)
  results/public_commitment.json (PUBLIC: H(seed || owner_id) + timestamp)
"""
import argparse
import json
import os

import torch

from wm_core import (CKPT, OWNER_ID, RESULTS, Net, accuracy, banner, ber, commitment,
                     derive_key, derive_signature, device, extract_bits, load_mnist,
                     save_model, train, utc_now, write_train_summary)

ap = argparse.ArgumentParser()
ap.add_argument("--epochs", type=int, default=3)
ap.add_argument("--nulls", type=int, default=4, help="independent clean models for the null check")
args = ap.parse_args()

dev = device()
d = load_mnist(dev)
CKPT.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)

banner("STEP 1: Owner commits to a secret seed (at embedding time)")
seed = os.urandom(32)
C = commitment(seed, OWNER_ID)
public = {"owner_id": OWNER_ID, "commitment_sha256": C, "timestamp_utc": utc_now(),
          "scheme": "C = SHA256('commit|' + seed + '|' + owner_id); "
                    "b = SHA256('sig|' + seed + '|' + owner_id)[:64 bits]; "
                    "X = PCG64(SHA256('key|' + seed)).normal(64 x 288)",
          "note": "Demo stores this locally. In production: publish to a transparency log "
                  "(e.g. Sigstore) so the timestamp is independently verifiable."}
(RESULTS / "public_commitment.json").write_text(json.dumps(public, indent=2))
(CKPT / "owner_secret.json").write_text(json.dumps({"owner_id": OWNER_ID, "seed_hex": seed.hex()}, indent=2))
print(f"  Published commitment : {C}")
print(f"  Timestamp (UTC)      : {public['timestamp_utc']}")
print("  Secret seed          : kept private in ckpt/owner_secret.json")

X = torch.from_numpy(derive_key(seed)).to(dev)
b = torch.from_numpy(derive_signature(seed, OWNER_ID)).to(dev)
print(f"  Derived key X        : {tuple(X.shape)} Gaussian projection")
print(f"  Derived signature b  : {''.join(map(str, b.tolist()))}")

banner("STEP 2: Train clean baseline and watermarked model (same init seed)")
torch.manual_seed(1)
clean = train(Net().to(dev), d["x_owner"], d["y_owner"], args.epochs, seed=1, tag="clean")
torch.manual_seed(1)
wm = train(Net().to(dev), d["x_owner"], d["y_owner"], args.epochs, seed=1, wm=(X, b), tag="watermarked")
save_model(clean, "clean")
save_model(wm, "watermarked")

banner(f"STEP 3: Train {args.nulls} independent null models (never watermarked)")
for i in range(args.nulls):
    torch.manual_seed(100 + i)
    m = train(Net().to(dev), d["x_owner"], d["y_owner"], max(1, args.epochs - 1), seed=100 + i, tag=f"null_{i}")
    save_model(m, f"null_{i}")

banner("RESULT")
print(f"  Clean       : acc={accuracy(clean, d['x_test'], d['y_test']):.4f}  "
      f"BER(owner key)={ber(extract_bits(clean, X), b):.3f}")
print(f"  Watermarked : acc={accuracy(wm, d['x_test'], d['y_test']):.4f}  "
      f"BER(owner key)={ber(extract_bits(wm, X), b):.3f}")
write_train_summary(dev, d, epochs=args.epochs)   # results/train.json for the web UI
