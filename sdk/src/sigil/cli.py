"""`sigil` command line (SDK-03). Every command can print JSON (--json) for scripts and the backend.

Owner:     keygen, seed, register, detect, prove
Verifier:  claim, verify
Registry:  registry-keygen, receipt
Toolchain: zk-setup, zk-info

Passphrases come from SIGIL_PASSPHRASE (owner) / SIGIL_REGISTRY_PASSPHRASE (registry) or a prompt.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path

from . import __version__
from . import protocol as P
from . import secretbox
from .identity import KeyPair
from .records import make_claim, make_receipt, make_registration, verify_receipt, verify_registration


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
    from .zk.circom import prove
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
    return {"bundle": str(out), "timing": timing, "errors": det.errors}


def cmd_verify(a):
    from .verify import verify_ownership
    bundle = Path(a.bundle)
    rec, rcp = _read(a.registration), _read(a.receipt)
    cfg = P.Config.from_dict(rec["config"])
    verdict = verify_ownership(
        proof=_read(bundle / "proof.json"), public=_read(bundle / "public.json"), registration=rec, receipt=rcp,
        claim=_read(bundle / "claim.json"), suspect_w=_model_vector(a.suspect, cfg.layer, a.trust),
        suspect_model_sha256=_sha256_file(a.suspect), trusted_registry_keys=set(a.trusted_registry))
    return verdict.to_dict()


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
    if a.cmd == "verify":
        return 0 if result.get("accepted") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
