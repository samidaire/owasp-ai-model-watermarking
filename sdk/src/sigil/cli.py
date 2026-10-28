"""`sigil` command line (SDK-03). Every command can print JSON (--json) for scripts and the backend.

Owner:      keygen, seed, embed, register, detect, prove
Verifier:   claim, verify, report
Registry:   registry-keygen, receipt
Robustness: attack
Toolchain:  zk-setup, zk-info

Passphrases come from SIGIL_PASSPHRASE (owner) / SIGIL_REGISTRY_PASSPHRASE (registry) or a prompt.
Training data for embed/attack is an .npz file with arrays `x` (inputs) and `y` (integer labels), loaded
without pickle. A PyTorch .pt file holds only weights, so embed/attack also need --arch module:callable,
which is imported and called to build the network: name only code you trust.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

import numpy as np

from . import __version__
from . import protocol as P
from . import secretbox
from .identity import KeyPair
from .records import (BUNDLE_SCHEMA, make_claim, make_receipt, make_registration, utc_now, verify_receipt,
                      verify_registration)


def _pass(env: str, prompt: str) -> str:
    return os.environ.get(env) or getpass.getpass(prompt)


def _owner(path: str) -> KeyPair:
    return KeyPair.load(path, _pass("SIGIL_PASSPHRASE", "owner key passphrase: "))


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str | Path, obj) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def _model_vector(path: str, layer: str, trust: bool = False):
    from .adapters import uchida_vector          # lazy: pulls in torch / keras / onnx only when needed
    return uchida_vector(path, layer, trust=trust) if trust else uchida_vector(path, layer)


def _load_seed(path: str) -> dict:
    s = secretbox.load(path, _pass("SIGIL_PASSPHRASE", "seed passphrase: "), "seed")
    s["config"] = P.Config.from_dict(s["config"])
    return s


def _resolve(spec: str):
    """'module:callable' (e.g. 'torchvision.models:resnet18') -> the object; the current folder is importable."""
    mod, sep, attr = spec.partition(":")
    if not (sep and mod and attr):
        raise ValueError(f"--arch must look like module:callable, got {spec!r}")
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    obj = importlib.import_module(mod)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def _framework(path: str) -> str:
    from .adapters import detect_framework
    return detect_framework(path)


def _trainable(path: str, arch: str | None, trust: bool = False, device: str = "cpu"):
    """(framework, model) for a file that can be trained: a PyTorch state_dict plus --arch, or a Keras file."""
    fw = _framework(path)
    if fw == "torch":
        if not arch:
            raise ValueError("a .pt file holds only weights: pass --arch module:callable that builds the network")
        from .adapters import load_torch
        model = _resolve(arch)()
        model.load_state_dict(load_torch(path))
        return fw, model.to(device)
    if fw == "keras":
        from .adapters import load_keras
        return fw, load_keras(path, trust=trust)
    raise ValueError(f"{fw} models can't be trained: embed into the PyTorch or Keras model, then export it")


def _npz(path: str) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as d:
        if not {"x", "y"} <= set(d.files):
            raise ValueError(f"{path}: needs arrays 'x' (inputs) and 'y' (integer labels)")
        return d["x"], d["y"]


def _tensors(path: str, device: str):
    import torch
    x, y = _npz(path)
    return torch.as_tensor(x, dtype=torch.float32, device=device), torch.as_tensor(y, dtype=torch.long, device=device)


def _derived(path: str, tag: str) -> Path:
    p = Path(path)
    return p.with_name(f"{p.stem}.{tag}{p.suffix}")


def _save_model(fw: str, model, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if fw == "torch":
        import torch
        torch.save({k: v.detach().cpu() for k, v in model.state_dict().items()}, out)
    else:
        model.save(str(out))
    return out


# ------------------------------------------------------------------ commands
def cmd_keygen(a):
    k = KeyPair.generate()
    k.save(a.out, _pass("SIGIL_PASSPHRASE", "new passphrase for the owner key: "))
    return {"owner_key": str(a.out), "public_key": k.public_hex, "pk_hash": str(P.pk_hash(k.public_bytes))}


def cmd_registry_keygen(a):
    k = KeyPair.generate()
    k.save(a.out, _pass("SIGIL_REGISTRY_PASSPHRASE", "new passphrase for the registry key: "))
    return {"registry_key": str(a.out), "registry_public_key": k.public_hex}


def cmd_seed(a):
    owner = _owner(a.owner)
    cfg = P.Config(T=a.bits, M=a.m, layer=a.layer, max_err=a.max_err if a.max_err is not None else a.bits // 8)
    seed = P.new_seed()
    secretbox.save(a.out, {"seed": str(seed), "config": cfg.to_dict(), "owner_public_key": owner.public_hex},
                   _pass("SIGIL_PASSPHRASE", "passphrase to encrypt the seed: "), "seed")
    pkh = P.pk_hash(owner.public_bytes)
    return {"seed_file": str(a.out), "config": cfg.to_dict(), "commitment": str(P.commitment(seed, pkh, cfg))}


def cmd_embed(a):
    from .embed import embed_keras, embed_torch
    owner, s = _owner(a.owner), _load_seed(a.seed)
    cfg, seed, pkh = s["config"], int(s["seed"]), P.pk_hash(owner.public_bytes)
    fw, model = _trainable(a.model, a.arch, a.trust, a.device)
    if fw == "torch":
        model, det = embed_torch(model, _tensors(a.data, a.device), cfg, seed, pkh, a.epochs, a.lam, lr=a.lr,
                                 batch_size=a.batch_size)
    else:
        x, y = _npz(a.data)
        model, det = embed_keras(model, (x.astype(np.float32), y), cfg, seed, pkh, a.epochs, a.lam, lr=a.lr,
                                 batch_size=a.batch_size)
    if not det.accepted:
        raise SystemExit(f"the watermark didn't take ({det.errors}/{cfg.T} bits wrong > {cfg.max_err}); train longer "
                         "(--epochs) or raise --lam. Nothing was saved.")
    out = _save_model(fw, model, Path(a.out) if a.out else _derived(a.model, "wm"))
    return {"model": str(out), "framework": fw, "layer": cfg.layer, **det.to_dict(), "theta": cfg.theta}


def cmd_register(a):
    owner, s = _owner(a.owner), _load_seed(a.seed)
    rec = make_registration(owner, int(s["seed"]), s["config"], _sha256_file(a.model))
    _write(a.out, rec)
    out = {"registration": str(a.out), "commitment": rec["commitment"]}
    if a.registry_key:
        reg = KeyPair.load(a.registry_key, _pass("SIGIL_REGISTRY_PASSPHRASE", "registry key passphrase: "))
        rcp = make_receipt(reg, rec)
        out["receipt"] = str(_write(Path(a.out).with_suffix(".receipt.json"), rcp))
    return out


def cmd_receipt(a):
    reg = KeyPair.load(a.registry_key, _pass("SIGIL_REGISTRY_PASSPHRASE", "registry key passphrase: "))
    rec = _read(a.registration)
    problems = verify_registration(rec)
    if problems:
        raise SystemExit("refusing to timestamp an invalid registration: " + "; ".join(problems))
    return {"receipt": str(_write(a.out, make_receipt(reg, rec)))}


def cmd_detect(a):
    owner, s = _owner(a.owner), _load_seed(a.seed)
    cfg = s["config"]
    det = P.detect(int(s["seed"]), P.pk_hash(owner.public_bytes), cfg, _model_vector(a.model, cfg.layer, a.trust))
    return {"model": a.model, **det.to_dict(), "theta": cfg.theta}


def cmd_claim(a):
    rec = _read(a.registration)
    return {"claim": str(_write(a.out, make_claim(rec, _sha256_file(a.suspect))))}


def cmd_prove(a):
    from .zk.circom import artifacts, prove
    owner, s, claim = _owner(a.owner), _load_seed(a.seed), _read(a.claim)
    cfg = s["config"]
    if claim["suspect_model_sha256"] != _sha256_file(a.model):
        raise SystemExit("this claim is about a different model file")
    w_q = P.quantize(_model_vector(a.model, cfg.layer, a.trust), cfg)
    det = P.detect(int(s["seed"]), P.pk_hash(owner.public_bytes), cfg, w_q)
    if not det.accepted:
        raise SystemExit(f"the watermark isn't present ({det.errors}/{cfg.T} bits wrong > {cfg.max_err}); no proof possible")
    proof, public, timing = prove(cfg, P.circuit_input(int(s["seed"]), w_q, P.pk_hash(owner.public_bytes), cfg,
                                                       int(claim["nonce"])))
    out = Path(a.out)
    _write(out / "proof.json", proof)
    _write(out / "public.json", public)
    _write(out / "claim.json", claim)
    art = artifacts(cfg)
    _write(out / "bundle.json", {"schema": BUNDLE_SCHEMA, "circuit": art.name, "vkey_sha256": _sha256_file(art.vkey),
                                 "files": ["proof.json", "public.json", "claim.json"], "created_at": utc_now()})
    return {"bundle": str(out), "timing": timing, "errors": det.errors}


def _verify_bundle(a) -> tuple[dict, dict, dict, dict, str]:
    """(verdict, registration, receipt, claim, suspect sha256) for verify and report."""
    from .verify import verify_ownership
    from .zk.circom import artifacts
    bundle = Path(a.bundle)
    rec, rcp, claim = _read(a.registration), _read(a.receipt), _read(bundle / "claim.json")
    cfg = P.Config.from_dict(rec["config"])
    suspect_sha = _sha256_file(a.suspect)
    v = verify_ownership(
        proof=_read(bundle / "proof.json"), public=_read(bundle / "public.json"), registration=rec, receipt=rcp,
        claim=claim, suspect_w=_model_vector(a.suspect, cfg.layer, a.trust), suspect_model_sha256=suspect_sha,
        trusted_registry_keys=set(a.trusted_registry)).to_dict()
    if (bundle / "bundle.json").exists():       # bundles from `sigil prove` name the verification key they target
        vkey = artifacts(cfg).vkey
        ok = vkey.exists() and _read(bundle / "bundle.json").get("vkey_sha256") == _sha256_file(vkey)
        v["checks"]["bundle_vkey_matches"] = ok
        if not ok:
            v["accepted"] = False
            v["reasons"].append("the bundle was made for a different verification key")
    return v, rec, rcp, claim, suspect_sha


def cmd_verify(a):
    return _verify_bundle(a)[0]


def cmd_report(a):
    v, rec, rcp, claim, suspect_sha = _verify_bundle(a)
    cfg = P.Config.from_dict(rec["config"])
    lines = [
        "# Ownership verification report", "",
        f"**Verdict: {'OWNERSHIP PROVEN' if v['accepted'] else 'NOT PROVEN'}**", "",
        "| | |", "|---|---|",
        f"| Suspect model | `{Path(a.suspect).name}`, SHA-256 `{suspect_sha}` |",
        f"| Owner public key | `{rec['owner_public_key']}` |",
        f"| Registered | {rcp['registered_at']} by registry `{rcp['registry_public_key']}` |",
        f"| Commitment | `{rec['commitment']}` |",
        f"| Watermark | layer `{cfg.layer}`, T = {cfg.T} bits, accepted with at most {cfg.max_err} wrong (θ = {cfg.theta:g}) |",
        f"| Claim | `{claim['claim_id']}`, opened {claim['opened_at']} |",
        f"| Report | {utc_now()}, sigil {__version__} |",
        "", "## Checks", "", "| Check | Result |", "|---|---|",
        *(f"| {name} | {'pass' if ok else 'FAIL'} |" for name, ok in v["checks"].items()),
    ]
    if v["reasons"]:
        lines += ["", "## Why it was rejected", "", *(f"- {r}" for r in v["reasons"])]
    lines += ["", "An accepted verdict means: the holder of the registered owner key knew the seed committed in the "
              "registration, the watermark derived from that seed is present in this exact file (within the "
              "threshold above), and the registry timestamped the registration before the claim was opened. The "
              "seed, the watermark key and the signature were not revealed (docs/protocol.md)."]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out), **v}


# attack name -> (needs --data, call(model, data, recipe, args) -> model or (model, info))
ATTACKS = {
    "prune": (False, lambda m, d, r, a, A: A.prune_magnitude(m, a.ratio)),
    "prune-channels": (False, lambda m, d, r, a, A: A.prune_channels(m, a.ratio)),
    "prune-finetune": (True, lambda m, d, r, a, A: A.prune_finetune(m, a.ratio, *d, r)),
    "fine-prune": (True, lambda m, d, r, a, A: A.fine_prune(m, _need(a.layer, "--layer"), a.ratio, *d, r)),
    "quantize": (False, lambda m, d, r, a, A: A.ptq(m, a.bits, d[0] if d else None, granularity=a.granularity)),
    "ftll": (True, lambda m, d, r, a, A: A.ftll(m, *d, r)),
    "ftal": (True, lambda m, d, r, a, A: A.ftal(m, *d, r)),
    "rtll": (True, lambda m, d, r, a, A: A.rtll(m, *d, r)),
    "rtal": (True, lambda m, d, r, a, A: A.rtal(m, *d, r)),
    "overwrite": (True, lambda m, d, r, a, A: A.overwrite(m, *d, r, layer=_need(a.layer, "--layer"),
                                                          **_thief_key(m, a.layer, a.thief_bits), lam=a.lam)),
    "permute": (False, lambda m, d, r, a, A: A.permute_channels(m, _need(a.producer, "--producer"),
                                                                _need(a.consumer, "--consumer"), seed=a.attack_seed)),
    "kmeans": (False, lambda m, d, r, a, A: A.kmeans_share(m, a.clusters, seed=a.attack_seed)),
    "low-rank": (False, lambda m, d, r, a, A: A.low_rank(m, a.rank_fraction, include_conv=a.include_conv)),
    "distill": (True, lambda m, d, r, a, A: A.distill(m, _resolve(a.arch)().to(a.device), d[0], r,
                                                      temperature=a.temperature)),
    "extract": (True, lambda m, d, r, a, A: A.extract(m, _resolve(a.arch)().to(a.device), d[0], a.budget, r,
                                                      output=a.output)),
}


def _need(value, flag: str):
    if value is None:
        raise ValueError(f"this attack needs {flag}")
    return value


def _thief_key(model, layer: str, bits: int) -> dict:
    """A thief's own random protocol key and signature for `layer` (they don't know the owner's)."""
    cfg = P.Config(T=bits, M=_model_vector_of(model, layer).shape[0], layer=layer, max_err=bits // 8)
    seed, pkh = P.new_seed(), P.pk_hash(os.urandom(32))
    return {"X": P.key_matrix(seed, pkh, cfg).astype(np.float32), "b": P.signature_bits(seed, pkh, cfg)}


def _model_vector_of(model, layer: str):
    from .adapters import uchida_vector
    return uchida_vector(model, layer)


def cmd_attack(a):
    if _framework(a.model) != "torch":
        raise ValueError("sigil attack works on PyTorch models (sigil.attacks); attack the PyTorch source model")
    from . import attacks as A
    needs_data, run = ATTACKS[a.name]
    _, model = _trainable(a.model, a.arch, device=a.device)
    model.eval()
    data = _tensors(a.data, a.device) if a.data else None
    if needs_data and data is None:
        raise ValueError(f"attack {a.name!r} trains on the attacker's data: pass --data FILE.npz")
    recipe = A.Fit(epochs=a.epochs, lr=a.lr, batch_size=a.batch_size, seed=a.attack_seed)
    result = run(model, data, recipe, a, A)
    attacked, info = result if isinstance(result, tuple) else (result, {})
    out = _save_model("torch", attacked, Path(a.out) if a.out else _derived(a.model, a.name))
    res = {"attack": a.name, "model": str(out), **info}
    if a.eval:
        x, y = _tensors(a.eval, a.device)
        res["accuracy_before"], res["accuracy_after"] = A.accuracy(model, x, y), A.accuracy(attacked, x, y)
    return res


def cmd_zk_setup(a):
    from .zk.circom import setup
    return setup(P.Config(T=a.bits, M=a.m, layer=a.layer, max_err=a.max_err if a.max_err is not None else a.bits // 8))


def cmd_zk_info(a):
    from .zk.circom import artifacts, compile_circuit, r1cs_info
    cfg = P.Config(T=a.bits, M=a.m, max_err=a.max_err if a.max_err is not None else a.bits // 8)
    art = compile_circuit(cfg)
    return {"circuit": art.name, **r1cs_info(art), "zkey": art.zkey.exists(), "vkey": str(art.vkey)}


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sigil", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"sigil {__version__}")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cfg_args(p):
        p.add_argument("--bits", type=int, default=64, help="signature length T (64 demo, 256 secure)")
        p.add_argument("--m", type=int, default=288, help="Uchida vector length of the layer")
        p.add_argument("--layer", default="conv2")
        p.add_argument("--max-err", type=int, default=None, help="accept threshold (default T/8)")

    p = sub.add_parser("keygen", help="create an owner Ed25519 key (encrypted)")
    p.add_argument("--out", default="secrets/owner.key")
    p.set_defaults(fn=cmd_keygen)
    p = sub.add_parser("registry-keygen", help="create a registry key (for local/offline registries)")
    p.add_argument("--out", default="secrets/registry.key")
    p.set_defaults(fn=cmd_registry_keygen)
    p = sub.add_parser("seed", help="create the secret watermark seed (encrypted) for a config")
    p.add_argument("--owner", default="secrets/owner.key")
    p.add_argument("--out", default="secrets/seed.json")
    cfg_args(p)
    p.set_defaults(fn=cmd_seed)

    def train_args(p, epochs: int):
        p.add_argument("--arch", help="module:callable that builds the network (needed for .pt files)")
        p.add_argument("--epochs", type=int, default=epochs)
        p.add_argument("--lr", type=float, default=1e-3)
        p.add_argument("--batch-size", type=int, default=128)
        p.add_argument("--device", default="cpu", help="cpu or cuda (PyTorch)")
        p.add_argument("--out", help="output model file (default: <model>.<tag><suffix>)")

    p = sub.add_parser("embed", help="owner: train the watermark of the seed's config into a PyTorch or Keras model")
    p.add_argument("model", help=".pt state_dict (with --arch), or .keras / .h5")
    p.add_argument("--data", required=True, help=".npz with x (inputs) and y (integer labels) to train on")
    p.add_argument("--owner", default="secrets/owner.key")
    p.add_argument("--seed", default="secrets/seed.json")
    p.add_argument("--lam", type=float, default=1.0, help="weight of the watermark loss")
    p.add_argument("--trust", action="store_true", help="allow unsafe Keras deserialisation (never for untrusted files)")
    train_args(p, epochs=2)
    p.set_defaults(fn=cmd_embed)
    p = sub.add_parser("register", help="sign a registration for a watermarked model file")
    p.add_argument("model")
    p.add_argument("--owner", default="secrets/owner.key")
    p.add_argument("--seed", default="secrets/seed.json")
    p.add_argument("--out", default="registration.json")
    p.add_argument("--registry-key", help="also timestamp it with this local registry key")
    p.set_defaults(fn=cmd_register)
    p = sub.add_parser("receipt", help="registry: timestamp a registration")
    p.add_argument("registration")
    p.add_argument("--registry-key", default="secrets/registry.key")
    p.add_argument("--out", default="receipt.json")
    p.set_defaults(fn=cmd_receipt)
    p = sub.add_parser("detect", help="owner: check the watermark in a model file")
    p.add_argument("model")
    p.add_argument("--owner", default="secrets/owner.key")
    p.add_argument("--seed", default="secrets/seed.json")
    p.add_argument("--trust", action="store_true", help="allow unsafe model deserialisation (never for untrusted files)")
    p.set_defaults(fn=cmd_detect)
    p = sub.add_parser("claim", help="verifier: open a claim (fresh nonce) about a suspect model")
    p.add_argument("registration")
    p.add_argument("--suspect", required=True)
    p.add_argument("--out", default="claim.json")
    p.set_defaults(fn=cmd_claim)
    p = sub.add_parser("prove", help="owner: zero-knowledge proof of ownership for a claim")
    p.add_argument("model")
    p.add_argument("--claim", required=True)
    p.add_argument("--owner", default="secrets/owner.key")
    p.add_argument("--seed", default="secrets/seed.json")
    p.add_argument("--out", default="bundle")
    p.add_argument("--trust", action="store_true")
    p.set_defaults(fn=cmd_prove)
    p = sub.add_parser("verify", help="verifier: check a proof bundle against the suspect model")
    p.add_argument("bundle")
    p.add_argument("--suspect", required=True)
    p.add_argument("--registration", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--trusted-registry", action="append", required=True, help="registry public key (hex)")
    p.add_argument("--trust", action="store_true")
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("report", help="verifier: verify a proof bundle and write a Markdown ownership report")
    p.add_argument("bundle")
    p.add_argument("--suspect", required=True)
    p.add_argument("--registration", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--trusted-registry", action="append", required=True, help="registry public key (hex)")
    p.add_argument("--trust", action="store_true")
    p.add_argument("--out", default="report.md")
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("attack", help="robustness: run one removal/compression/extraction attack on a PyTorch model")
    p.add_argument("name", choices=list(ATTACKS))
    p.add_argument("model", help=".pt state_dict (with --arch)")
    p.add_argument("--data", help="the attacker's own .npz (x, y); needed by the attacks that train")
    p.add_argument("--eval", help=".npz (x, y) to report accuracy before and after")
    p.add_argument("--ratio", type=float, default=0.5, help="prune*, fine-prune: share of weights or channels")
    p.add_argument("--bits", type=int, default=8, help="quantize: weight bits (activations 8 when --data is given)")
    p.add_argument("--granularity", choices=["channel", "tensor"], default="channel", help="quantize")
    p.add_argument("--layer", help="fine-prune, overwrite: the layer")
    p.add_argument("--thief-bits", type=int, default=64, help="overwrite: length of the thief's own signature")
    p.add_argument("--lam", type=float, default=1.0, help="overwrite: weight of the thief's watermark loss")
    p.add_argument("--producer", help="permute: layer whose output channels are reordered")
    p.add_argument("--consumer", help="permute: layer whose input channels follow")
    p.add_argument("--clusters", type=int, default=16, help="kmeans: distinct values per layer")
    p.add_argument("--rank-fraction", type=float, default=0.5, help="low-rank: share of the full rank kept")
    p.add_argument("--include-conv", action="store_true", help="low-rank: also factorise conv layers")
    p.add_argument("--temperature", type=float, default=4.0, help="distill")
    p.add_argument("--budget", type=int, default=10000, help="extract: number of queries")
    p.add_argument("--output", choices=["probs", "labels"], default="probs", help="extract: what the victim returns")
    p.add_argument("--attack-seed", type=int, default=0, help="seed of the attack (batch order, permutation, ...)")
    train_args(p, epochs=5)
    p.set_defaults(fn=cmd_attack)
    p = sub.add_parser("zk-setup", help="compile the circuit and run the Groth16 setup for a config")
    cfg_args(p)
    p.set_defaults(fn=cmd_zk_setup)
    p = sub.add_parser("zk-info", help="compile the circuit for a config and print its size")
    cfg_args(p)
    p.set_defaults(fn=cmd_zk_info)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        result = a.fn(a)
    except (ValueError, FileNotFoundError) as e:
        print(f"sigil: error: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(result, indent=2))
    else:
        for k, v in result.items():
            print(f"{k:>24}: {v if not isinstance(v, (dict, list)) else json.dumps(v)}")
    if a.cmd in ("verify", "report"):
        return 0 if result.get("accepted") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
