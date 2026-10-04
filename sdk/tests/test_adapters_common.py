"""Adapter interface (SDK-02, SDK-04): framework detection, lazy imports, size limits. No ML deps needed."""
import os
import subprocess
import sys

import pytest

from sigil import adapters


def test_import_is_lazy():
    """`import sigil`, `sigil.adapters` and `sigil.embed` must not pull in torch, TensorFlow, Keras or onnx."""
    code = ("import sys, sigil, sigil.adapters, sigil.embed; "
            "heavy = [m for m in ('torch', 'tensorflow', 'keras', 'onnx', 'tf2onnx') if m in sys.modules]; "
            "print(','.join(heavy))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=os.environ.copy(),
                         check=True)
    assert out.stdout.strip() == ""


@pytest.mark.parametrize("name,fw", [("m.pt", "torch"), ("m.PTH", "torch"), ("m.keras", "keras"),
                                     ("m.h5", "keras"), ("m.hdf5", "keras"), ("m.onnx", "onnx")])
def test_framework_from_extension(name, fw):
    assert adapters.detect_framework(name) == fw


def test_unknown_inputs_rejected(tmp_path):
    with pytest.raises(adapters.AdapterError, match="extension"):
        adapters.detect_framework("model.pkl")
    with pytest.raises(adapters.AdapterError, match="framework"):
        adapters.get_kernel(object(), "conv2")
    with pytest.raises(adapters.AdapterError, match="unknown framework"):
        adapters.get_kernel("x.pt", "conv2", framework="jax")


def test_size_limit_and_missing_file(tmp_path):
    p = tmp_path / "m.onnx"
    p.write_bytes(b"\0" * 2048)
    with pytest.raises(adapters.FileTooLargeError, match="limit"):
        adapters.check_file(p, max_bytes=1024)
    assert adapters.check_file(p, max_bytes=4096) == p
    assert issubclass(adapters.FileTooLargeError, adapters.UnsafeModelError)
    with pytest.raises(adapters.AdapterError, match="not a file"):
        adapters.check_file(tmp_path / "missing.pt")
    assert adapters.DEFAULT_MAX_BYTES == 2 * 1024 ** 3
