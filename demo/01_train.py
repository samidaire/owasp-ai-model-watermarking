"""DEMO A (setup): the owner commits to a secret seed, derives key + signature from it,
and trains a clean baseline, a watermarked model, and independent "null" models.

Outputs:
  ckpt/clean.pt, ckpt/watermarked.pt, ckpt/null_*.pt
  ckpt/owner_secret.json        (PRIVATE: the seed)
  results/public_commitment.json (PUBLIC: H(seed || owner_id) + timestamp)

Transactional: nothing above is replaced until every model has trained and been saved.
New files are written to ckpt/.staging/ first; the previous owner_secret.json and
public_commitment.json are copied to ckpt/backup/<UTC time>/; then everything is swapped in
with os.replace. A failed or killed run leaves the current demo seed and models untouched.
"""
import argparse
import json
import os
import shutil
import time

import torch

from demo_common import replace_file
from wm_core import (CKPT, OWNER_ID, RESULTS, Net, accuracy, banner, ber, commitment,
                     derive_key, derive_signature, device, extract_bits, load_mnist,
                     train, utc_now, write_train_summary)

STAGE = CKPT / ".staging"      # new files, until every model is trained and saved
BACKUP = CKPT / "backup"       # previous owner secret + commitment, one folder per retrain

ap = argparse.ArgumentParser()
ap.add_argument("--epochs", type=int, default=3)
ap.add_argument("--nulls", type=int, default=4, help="independent clean models for the null check")
args = ap.parse_args()


def stage_model(model, name):
    torch.save(model.state_dict(), STAGE / f"{name}.pt")


def backup_previous():
    """Copy the current owner secret and commitment to ckpt/backup/<UTC time>/ (None if there are none)."""
    old = [p for p in (CKPT / "owner_secret.json", RESULTS / "public_commitment.json") if p.exists()]
    if not old:
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest, n = BACKUP / stamp, 1
    while dest.exists():
        n += 1
        dest = BACKUP / f"{stamp}-{n}"
    dest.mkdir(parents=True)
    for p in old:
        shutil.copy2(p, dest / p.name)
    return dest


dev = device()
d = load_mnist(dev)
CKPT.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)
shutil.rmtree(STAGE, ignore_errors=True)            # leftovers of an interrupted run
STAGE.mkdir(parents=True)
try:
    banner("STEP 1: Owner commits to a secret seed (at embedding time)")
    seed = os.urandom(32)
    C = commitment(seed, OWNER_ID)
    public = {"owner_id": OWNER_ID, "commitment_sha256": C, "timestamp_utc": utc_now(),
              "scheme": "C = SHA256('commit|' + seed + '|' + owner_id); "
                        "b = SHA256('sig|' + seed + '|' + owner_id)[:64 bits]; "
                        "X = PCG64(SHA256('key|' + seed)).normal(64 x 288)",
              "note": "Demo stores this locally. In production: publish to a transparency log "
                      "(e.g. Sigstore) so the timestamp is independently verifiable."}
    (STAGE / "public_commitment.json").write_text(json.dumps(public, indent=2))
    (STAGE / "owner_secret.json").write_text(json.dumps({"owner_id": OWNER_ID, "seed_hex": seed.hex()}, indent=2))
    print(f"  Published commitment : {C}")
    print(f"  Timestamp (UTC)      : {public['timestamp_utc']}")
    print("  Secret seed          : kept private in ckpt/owner_secret.json")

    X = torch.from_numpy(derive_key(seed)).to(dev)
    b = torch.from_numpy(derive_signature(seed, OWNER_ID)).to(dev)
    print(f"  Derived key X        : {tuple(X.shape)} Gaussian projection")
    print(f"  Derived signature b  : {''.join(map(str, b.tolist()[:8]))}... ({len(b.tolist())} bits; full value kept out of logs)")

    banner("STEP 2: Train clean baseline and watermarked model (same init seed)")
    torch.manual_seed(1)
    clean = train(Net().to(dev), d["x_owner"], d["y_owner"], args.epochs, seed=1, tag="clean")
    torch.manual_seed(1)
    wm = train(Net().to(dev), d["x_owner"], d["y_owner"], args.epochs, seed=1, wm=(X, b), tag="watermarked")
    stage_model(clean, "clean")
    stage_model(wm, "watermarked")

    banner(f"STEP 3: Train {args.nulls} independent null models (never watermarked)")
    for i in range(args.nulls):
        torch.manual_seed(100 + i)
        m = train(Net().to(dev), d["x_owner"], d["y_owner"], max(1, args.epochs - 1), seed=100 + i, tag=f"null_{i}")
        stage_model(m, f"null_{i}")

    # Every model is trained and saved: back up the old owner files, then swap the new ones in.
    backup = backup_previous()
    for f in sorted(STAGE.glob("*.pt")):
        replace_file(f, CKPT / f.name)
    replace_file(STAGE / "owner_secret.json", CKPT / "owner_secret.json")
    replace_file(STAGE / "public_commitment.json", RESULTS / "public_commitment.json")
    print("\n  New owner secret, commitment and models saved"
          + (f" (previous secret and commitment backed up to ckpt/backup/{backup.name}/)" if backup else ""))
finally:
    shutil.rmtree(STAGE, ignore_errors=True)        # on failure: nothing was replaced

banner("RESULT")
print(f"  Clean       : acc={accuracy(clean, d['x_test'], d['y_test']):.4f}  "
      f"BER(owner key)={ber(extract_bits(clean, X), b):.3f}")
print(f"  Watermarked : acc={accuracy(wm, d['x_test'], d['y_test']):.4f}  "
      f"BER(owner key)={ber(extract_bits(wm, X), b):.3f}")
write_train_summary(dev, d, epochs=args.epochs)   # results/train.json for the web UI
