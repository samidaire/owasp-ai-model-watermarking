"""Toolchain wrappers that don't need a proof run: ptau trust handling and circuit plumbing (ZK-04)."""
import hashlib

import pytest

from sigil import protocol as P
from sigil.zk import circom as Z
from sigil.zk import ptau


@pytest.mark.parametrize("n,k", [(1, 8), (250, 8), (251, 9), (116822, 17), (131066, 17), (131067, 18), (402292, 19)])
def test_power_for(n, k):
    assert ptau.power_for(n, 5) == k


def test_power_for_too_large():
    with pytest.raises(ValueError):
        ptau.power_for(1 << 30)


def test_unverified_ptau_refused_then_marked(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGIL_PTAU_DIR", str(tmp_path))
    monkeypatch.delenv("SIGIL_PTAU_ALLOW_UNVERIFIED", raising=False)
    f = tmp_path / ptau.FILENAME.format(k=10)
    f.write_bytes(b"not really a ptau")
    with pytest.raises(ValueError, match="not been verified"):
        ptau.get_ptau(10, download=False)
    assert ptau.verification_status(f) == "pending"
    monkeypatch.setenv("SIGIL_PTAU_ALLOW_UNVERIFIED", "1")
    assert ptau.get_ptau(10, download=False) == f
    f.with_suffix(".verified").write_text(ptau.blake2b_file(f))
    assert ptau.verification_status(f) == "verified"
    monkeypatch.delenv("SIGIL_PTAU_ALLOW_UNVERIFIED")
    assert ptau.get_ptau(10, download=False) == f


def test_pinned_mismatch_moves_file_aside(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGIL_PTAU_DIR", str(tmp_path))
    f = tmp_path / ptau.FILENAME.format(k=9)
    f.write_bytes(b"tampered")
    monkeypatch.setitem(ptau.PINNED, 9, hashlib.blake2b(b"genuine", digest_size=64).hexdigest())
    with pytest.raises(ValueError, match="mismatch"):
        ptau.get_ptau(9, download=False)
    assert not f.exists() and f.with_suffix(".bad").exists()


def test_missing_ptau_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGIL_PTAU_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        ptau.get_ptau(12, download=False)
    with pytest.raises(ValueError):
        ptau.get_ptau(40)


def test_circuit_name_and_main_source_track_the_config():
    cfg = P.Config(T=256, max_err=32)
    assert Z.circuit_name(cfg) == "ownership_T256_M288_E32_W24"
    src = Z.main_source(cfg)
    assert f"Ownership(256, 288, 24, {cfg.sum_bits}, 32, {P.PRG_BITS})" in src
    assert "public [pk_hash, config_hash, commitment, w_hash, nonce]" in src


def test_contribution_hash_parser():
    out = ("[INFO]  snarkJS: contribution #1 sigil project setup:\n"
           "\t\t7971c477 46c1718e 6c3358d2 501a9ac7\n\t\t10659df8 b3f9da3b 98df2e69 b1062a75\n"
           "[INFO]  snarkJS: -------------------------\n[INFO]  snarkJS: ZKey Ok!\n")
    assert Z._contribution_hash(out) == "7971c47746c1718e6c3358d2501a9ac710659df8b3f9da3b98df2e69b1062a75"
    assert Z._contribution_hash("ZKey Ok!") is None


@pytest.mark.zk
def test_compile_is_cached_and_r1cs_info_reads_sizes():
    a = Z.compile_circuit(P.Config())
    stamp = (a.build / f"{a.name}.srchash").stat().st_mtime
    assert Z.compile_circuit(P.Config()).r1cs == a.r1cs
    assert (a.build / f"{a.name}.srchash").stat().st_mtime == stamp      # not recompiled
    info = Z.r1cs_info(a)
    assert info["of_constraints"] == 116822 and info["of_public_inputs"] == 5
