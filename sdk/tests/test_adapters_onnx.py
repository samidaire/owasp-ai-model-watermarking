"""ONNX adapter (WM-05, SDK-04) on hand-built graphs: layouts, name resolution, external data, refusals.

The end-to-end PyTorch -> ONNX and Keras -> ONNX checks live in test_adapters_torch.py and
test_adapters_keras.py; these need only the onnx package.
"""
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from sigil import adapters  # noqa: E402
from sigil import protocol as P  # noqa: E402
from sigil.adapters import onnx_adapter  # noqa: E402

RNG = np.random.default_rng(7)


def _model(nodes, inits, inputs, outputs, opset=17):
    graph = helper.make_graph(nodes, "g", inputs, outputs, [numpy_helper.from_array(v, k) for k, v in inits.items()])
    return helper.make_model(graph, opset_imports=[helper.make_opsetid("", opset)])


def _vi(name, shape):
    return helper.make_tensor_value_info(name, TensorProto.FLOAT, shape)


def conv_gemm_model(conv_name="conv2", w_name="w_conv", transpose_conv=False, trans_b=1):
    """x -> Conv(conv_name) -> Flatten -> Gemm(fc, transB) ; optionally the conv weight sits behind a
    Transpose of an HWIO initializer (as an exporter keeping Keras' layout would produce)."""
    oihw = RNG.normal(size=(4, 3, 3, 3)).astype(np.float32)
    fc = RNG.normal(size=(5, 4 * 2 * 2)).astype(np.float32)          # OI
    inits = {"fc.weight": fc if trans_b else np.ascontiguousarray(fc.T)}
    nodes = []
    if transpose_conv:
        inits[w_name + "_hwio"] = np.ascontiguousarray(np.transpose(oihw, (2, 3, 1, 0)))
        nodes.append(helper.make_node("Transpose", [w_name + "_hwio"], [w_name], perm=[3, 2, 0, 1]))
    else:
        inits[w_name] = oihw
    nodes += [helper.make_node("Conv", ["x", w_name], ["c"], name=conv_name),
              helper.make_node("Flatten", ["c"], ["f"]),
              helper.make_node("Gemm", ["f", "fc.weight"], ["y"], name="/fc/Gemm", transB=trans_b)]
    m = _model(nodes, inits, [_vi("x", [1, 3, 4, 4])], [_vi("y", [1, 5])])
    return m, oihw, fc


def test_conv_and_gemm_layouts(tmp_path):
    for trans_b, layout in ((1, "OI"), (0, "IO")):
        m, oihw, fc = conv_gemm_model(trans_b=trans_b)
        onnx.save(m, tmp_path / "m.onnx")
        k, lay = adapters.get_kernel(tmp_path / "m.onnx", "conv2")
        assert lay == "OIHW" and np.array_equal(k, oihw)
        k, lay = adapters.get_kernel(tmp_path / "m.onnx", "fc")
        assert lay == layout
        assert np.array_equal(P.uchida_vector(k, lay), P.uchida_vector(fc, "OI"))


def test_weight_behind_transpose_and_constant(tmp_path):
    m, oihw, _ = conv_gemm_model(transpose_conv=True)
    k, lay = adapters.get_kernel(m, "conv2")
    assert lay == "OIHW" and np.array_equal(k, oihw)
    w = RNG.normal(size=(6, 3)).astype(np.float32)                   # MatMul B is (K, N) = IO
    const = helper.make_node("Constant", [], ["w"], value=numpy_helper.from_array(w, "w_value"))
    mm = helper.make_node("MatMul", ["x", "w"], ["y"], name="model/dense_1/MatMul")
    m2 = _model([const, mm], {}, [_vi("x", [2, 6])], [_vi("y", [2, 3])])
    k, lay = adapters.get_kernel(m2, "dense")
    assert lay == "IO" and np.array_equal(k, w)


def test_tf2onnx_style_names_and_ambiguity():
    w1 = RNG.normal(size=(2, 3, 3, 3)).astype(np.float32)
    w2 = RNG.normal(size=(2, 2, 3, 3)).astype(np.float32)
    nodes = [helper.make_node("Conv", ["x", "m_1/conv2_1/convolution/ReadVariableOp:0"], ["a"],
                              name="m_1/conv2_1/convolution"),
             helper.make_node("Conv", ["a", "m_1/conv2_1_1/convolution/ReadVariableOp:0"], ["y"],
                              name="m_1/conv2_1_1/convolution")]
    inits = {"m_1/conv2_1/convolution/ReadVariableOp:0": w1, "m_1/conv2_1_1/convolution/ReadVariableOp:0": w2}
    m = _model(nodes, inits, [_vi("x", [1, 3, 6, 6])], [_vi("y", [1, 2, 2, 2])])
    k, _ = adapters.get_kernel(m, "conv2")                            # Keras layer "conv2" -> scope conv2_1
    assert np.array_equal(k, w1)
    with pytest.raises(adapters.LayerNotFoundError, match="ambiguous"):
        adapters.get_kernel(m, "conv2_1")                            # Keras layer "conv2_1" or "conv2"? refuse
    k, _ = adapters.get_kernel(m, "m_1/conv2_1_1/convolution")       # exact node name always works
    assert np.array_equal(k, w2)
    k, _ = adapters.get_kernel(m, "m_1/conv2_1/convolution/ReadVariableOp:0")
    assert np.array_equal(k, w1)
    with pytest.raises(adapters.LayerNotFoundError, match="weight nodes"):
        adapters.get_kernel(m, "conv3")


def test_dotted_torch_names():
    w = RNG.normal(size=(2, 3, 3, 3)).astype(np.float32)
    nodes = [helper.make_node("Conv", ["x", "onnx::Conv_17"], ["y"], name="/layer3/layer3.1/conv2/Conv")]
    m = _model(nodes, {"onnx::Conv_17": w}, [_vi("x", [1, 3, 5, 5])], [_vi("y", [1, 2, 3, 3])])
    k, lay = adapters.get_kernel(m, "layer3.1.conv2")
    assert lay == "OIHW" and np.array_equal(k, w)


def test_external_data_inside_dir_only(tmp_path):
    m, oihw, _ = conv_gemm_model()
    onnx.save_model(m, tmp_path / "ext.onnx", save_as_external_data=True, all_tensors_to_one_file=True,
                    location="ext.onnx.data", size_threshold=0)
    k, _ = adapters.get_kernel(tmp_path / "ext.onnx", "conv2")
    assert np.array_equal(k, oihw)
    assert np.array_equal(adapters.get_kernel(adapters.load_onnx(tmp_path / "ext.onnx"), "conv2")[0], oihw)
    with pytest.raises(adapters.FileTooLargeError, match="external data"):
        adapters.get_kernel(tmp_path / "ext.onnx", "conv2",
                            max_bytes=(tmp_path / "ext.onnx").stat().st_size + 100)
    # rewrite the location to escape the model directory
    sub = tmp_path / "sub"
    sub.mkdir()
    evil = onnx.load(tmp_path / "ext.onnx", load_external_data=False)
    for t in evil.graph.initializer:
        for e in t.external_data:
            if e.key == "location":
                e.value = "../ext.onnx.data"
    onnx.save(evil, sub / "evil.onnx")
    with pytest.raises(adapters.UnsafeModelError, match="outside"):
        adapters.get_kernel(sub / "evil.onnx", "conv2")
    for t in evil.graph.initializer:
        for e in t.external_data:
            if e.key == "location":
                e.value = str((tmp_path / "ext.onnx.data").resolve())
    onnx.save(evil, sub / "abs.onnx")
    with pytest.raises(adapters.UnsafeModelError, match="outside"):
        adapters.get_kernel(sub / "abs.onnx", "conv2")


def test_invalid_files_refused(tmp_path):
    (tmp_path / "junk.onnx").write_bytes(b"\x08\x07garbage that is not a protobuf model" * 3)
    with pytest.raises(adapters.AdapterError):
        adapters.get_kernel(tmp_path / "junk.onnx", "conv2")
    m, _, _ = conv_gemm_model()
    m.graph.node[0].input[0] = "undefined_input"                     # graph is no longer topologically valid
    onnx.save(m, tmp_path / "bad.onnx")
    with pytest.raises(adapters.AdapterError, match="onnx.checker"):
        adapters.get_kernel(tmp_path / "bad.onnx", "conv2")
    good, _, _ = conv_gemm_model()
    onnx.save(good, tmp_path / "good.onnx")
    with pytest.raises(adapters.FileTooLargeError):
        adapters.get_kernel(tmp_path / "good.onnx", "conv2", max_bytes=64)


def test_unsupported_weights_reported():
    w = RNG.normal(size=(2, 3, 3)).astype(np.float32)                 # Conv1d
    m = _model([helper.make_node("Conv", ["x", "w"], ["y"], name="conv1d")], {"w": w},
               [_vi("x", [1, 3, 8])], [_vi("y", [1, 2, 6])])
    with pytest.raises(adapters.LayerNotFoundError, match="3-D"):
        onnx_adapter.get_kernel(m, "conv1d")
