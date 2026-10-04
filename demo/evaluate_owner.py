"""DEMO A (live, non-destructive): re-verify the saved owner models without retraining.
Writes results/train.json for the web UI. Use 01_train.py only to start over with a new seed."""
from wm_core import banner, device, load_mnist, write_train_summary

dev = device()
banner("DEMO A: Owner's committed seed, watermarked vs clean model (saved checkpoints)")
s = write_train_summary(dev, load_mnist(dev))
print(f"  Published commitment : {s['commitment']}")
print(f"  Timestamp (UTC)      : {s['timestamp_utc']}")
print(f"  Derived signature b  : {''.join(map(str, s['signature_bits']))}")
for name, m in s["models"].items():
    print(f"  {name.capitalize():<12}: acc={m['accuracy']:.4f}  BER(owner key)={m['owner_ber']:.3f}")
for n in s["nulls"]:
    print(f"  {n['name']:<12}: acc={n['accuracy']:.4f}  BER(owner key)={n['owner_ber']:.3f}")
print("\n  Saved results/train.json")
