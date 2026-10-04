"""ONNX adapter (WM-05): read the initializer feeding a named layer's Conv/Gemm/MatMul node.

Layer resolution, most specific first:
  1. an initializer named exactly ``layer`` or ``layer + ".weight"`` (PyTorch exports keep
     ``conv2.weight``), or a node named exactly ``layer``;
  2. path components of node or initializer names: ``conv2`` matches ``/conv2/Conv`` (torch legacy
     exporter) and ``kcnn_1/conv2_1/convolution`` (tf2onnx appends ``_<n>`` to Keras scope names).
     Dotted or slashed layer paths (``layer3.1.conv2``, ``backbone/conv2``) must match consecutive
     components. More than one distinct weight matching is an error, never a guess.

Layouts follow the ONNX operator definitions: Conv weights are OIHW; Gemm's B is OI when transB=1 and
IO otherwise; MatMul's B is IO. Weights reached through Identity/Transpose nodes are resolved too, so
an exporter that keeps Keras' HWIO kernel behind a Transpose still gives the canonical vector.

Files are size-checked (including external data), validated with onnx.checker, and external-data
locations must stay inside the model's directory (SDK-04).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import onnx
from onnx import numpy_helper
from onnx.external_data_helper import ExternalDataInfo, uses_external_data

from ._common import (DEFAULT_MAX_BYTES, AdapterError, FileTooLargeError, LayerNotFoundError,
                      UnsafeModelError, check_file)

WEIGHT_OPS = ("Conv", "Gemm", "MatMul")


# ------------------------------------------------------------------ safe loading
def _all_tensors(graph):
    yield from graph.initializer
    for node in graph.node:
        for a in node.attribute:
            if a.HasField("t"):
                yield a.t
            yield from a.tensors
            if a.HasField("g"):
                yield from _all_tensors(a.g)
            for g in a.graphs:
                yield from _all_tensors(g)


def _check_external_data(model: onnx.ModelProto, base_dir: Path, budget: int | None) -> None:
    """Every external-data location must be a relative path inside base_dir; total size within budget."""
    root = base_dir.resolve()
    sizes = {}
    for t in _all_tensors(model.graph):
        if not uses_external_data(t):
            continue
        loc = ExternalDataInfo(t).location
        parts = Path(loc).parts
        if not loc or os.path.isabs(loc) or Path(loc).drive or ".." in parts:
            raise UnsafeModelError(f"tensor {t.name!r} points to external data outside the model's "
                                   f"directory ({loc!r}); refused")
        target = (root / loc).resolve()
        if root not in target.parents or not target.is_file():
            raise UnsafeModelError(f"tensor {t.name!r}: external data file {loc!r} is missing or outside "
                                   f"the model's directory")
        sizes[target] = target.stat().st_size
    total = sum(sizes.values())
    if budget is not None and total > budget:
        raise FileTooLargeError(f"the model's external data is {total} bytes, above the remaining limit "
                                f"of {budget} bytes")


def _open(path, max_bytes: int | None, check: bool) -> tuple[onnx.ModelProto, Path]:
    p = check_file(path, max_bytes)
    try:
        model = onnx.load(str(p), load_external_data=False)
    except Exception as e:
        raise AdapterError(f"{p.name} is not a readable ONNX model: {type(e).__name__}: {e}") from None
    budget = None if max_bytes is None else max_bytes - p.stat().st_size
    _check_external_data(model, p.parent, budget)
    if check:
        try:
            onnx.checker.check_model(str(p))
        except onnx.checker.ValidationError as e:
            raise AdapterError(f"{p.name} failed onnx.checker: {str(e).splitlines()[0]}") from None
    return model, p.parent


def load_onnx(path, *, max_bytes: int | None = DEFAULT_MAX_BYTES, check: bool = True) -> onnx.ModelProto:
    """Load an .onnx file safely (size limit, external-data path checks, onnx.checker), data included."""
    model, base = _open(path, max_bytes, check)
    from onnx.external_data_helper import load_external_data_for_model
    load_external_data_for_model(model, str(base))
    return model


# ------------------------------------------------------------------ finding the layer's weight
@dataclass
class _Candidate:
    node: str
    op: str
    tensor: onnx.TensorProto
    perms: list = field(default_factory=list)       # Transposes applied between initializer and node
    layout: str = ""

    @property
    def key(self):
        return (self.tensor.name, tuple(map(tuple, self.perms)), self.layout)


def _resolve(name: str, consts: dict, producers: dict, depth: int = 0):
    """(TensorProto, [perm, ...]) when `name` is a constant, possibly behind Identity/Transpose nodes."""
    if name in consts:
        return consts[name], []
    node = producers.get(name)
    if node is None or depth > 8:
        return None
    if node.op_type == "Identity":
        return _resolve(node.input[0], consts, producers, depth + 1)
    if node.op_type == "Transpose":
        r = _resolve(node.input[0], consts, producers, depth + 1)
        if r is None:
            return None
        t, perms = r
        perm = next((list(a.ints) for a in node.attribute if a.name == "perm"), None)
        return t, perms + [perm or list(range(len(t.dims)))[::-1]]
    return None


def _candidates(graph) -> list[_Candidate]:
    consts = {t.name: t for t in graph.initializer}
    for node in graph.node:
        if node.op_type == "Constant":
            for a in node.attribute:
                if a.name == "value" and a.HasField("t"):
                    consts[node.output[0]] = a.t
    producers = {o: n for n in graph.node for o in n.output}
    out = []
    for node in graph.node:
        if node.op_type not in WEIGHT_OPS or len(node.input) < 2:
            continue
        r = _resolve(node.input[1], consts, producers)
        if r is None:
            continue
        tensor, perms = r
        ndim = len(tensor.dims)
        if node.op_type == "Conv":
            layout = "OIHW" if ndim == 4 else ""
        elif node.op_type == "Gemm":
            trans_b = next((a.i for a in node.attribute if a.name == "transB"), 0)
            layout = ("OI" if trans_b else "IO") if ndim == 2 else ""
        else:
            layout = "IO" if ndim == 2 else ""
        out.append(_Candidate(node.name, node.op_type, tensor, perms, layout))
    return out


def _components(name: str) -> list[str]:
    name = re.sub(r":\d+$", "", name)
    return [c for c in re.split(r"[/.]", name) if c]


def _component_match(layer_parts: list[str], name: str) -> bool:
    comps = _components(name)
    n = len(layer_parts)

    def same(want, got):
        return got == want or re.fullmatch(re.escape(want) + r"_\d+", got) is not None

    return any(all(same(w, g) for w, g in zip(layer_parts, comps[i:i + n]))
               for i in range(len(comps) - n + 1))


def _unique(cands: list[_Candidate], layer: str):
    uniq = {c.key: c for c in cands}
    if len(uniq) > 1:
        names = sorted({f"{c.node} <- {c.tensor.name}" for c in cands})
        raise LayerNotFoundError(f"layer {layer!r} is ambiguous in this ONNX graph: {names}; pass the exact "
                                 f"initializer or node name")
    return next(iter(uniq.values()), None)


def find_weight(model: onnx.ModelProto, layer: str) -> _Candidate:
    cands = _candidates(model.graph)
    exact = [c for c in cands if layer in (c.node, c.tensor.name) or c.tensor.name == f"{layer}.weight"]
    hit = _unique(exact, layer)
    if hit is None:
        parts = _components(layer)
        hit = _unique([c for c in cands if parts and (_component_match(parts, c.node)
                                                      or _component_match(parts, c.tensor.name))], layer)
    if hit is None:
        names = [f"{c.node} ({c.op}) <- {c.tensor.name}" for c in cands]
        raise LayerNotFoundError(f"no Conv/Gemm/MatMul weight for layer {layer!r}; weight nodes: {names}")
    if not hit.layout:
        raise LayerNotFoundError(f"layer {layer!r} ({hit.op}, weight {hit.tensor.name!r}) has a "
                                 f"{len(hit.tensor.dims)}-D weight; only 2-D Conv and 2-D Gemm/MatMul are supported")
    return hit


def get_kernel(model_or_path, layer: str, *, trust: bool = False, max_bytes: int | None = DEFAULT_MAX_BYTES,
               check: bool = True, base_dir=None) -> tuple[np.ndarray, str]:
    """(kernel, layout) of the weight feeding `layer`'s Conv (OIHW), Gemm (OI/IO) or MatMul (IO) node.

    model_or_path: an .onnx path or an onnx.ModelProto (base_dir: where its external data lives).
    `trust` has no effect for ONNX (no code is deserialised).
    """
    if isinstance(model_or_path, (str, os.PathLike)):
        model, base = _open(model_or_path, max_bytes, check)
    elif isinstance(model_or_path, onnx.ModelProto):
        model, base = model_or_path, Path(base_dir) if base_dir is not None else None
        if check:
            try:
                onnx.checker.check_model(model)
            except onnx.checker.ValidationError as e:
                raise AdapterError(f"model failed onnx.checker: {str(e).splitlines()[0]}") from None
    else:
        raise AdapterError(f"expected an .onnx path or an onnx.ModelProto, got {type(model_or_path).__name__}")
    hit = find_weight(model, layer)
    if uses_external_data(hit.tensor):
        if base is None:
            raise AdapterError(f"weight {hit.tensor.name!r} is stored externally; pass base_dir or a file path")
        if isinstance(model_or_path, onnx.ModelProto):
            _check_external_data(model, base, None)
    arr = numpy_helper.to_array(hit.tensor, base_dir=str(base) if base is not None else "")
    for perm in hit.perms:
        arr = np.transpose(arr, perm)
    if arr.dtype not in (np.float32, np.float64):
        if arr.dtype.kind != "f":
            raise LayerNotFoundError(f"weight {hit.tensor.name!r} has dtype {arr.dtype}; quantised weights are "
                                     f"not supported")
        arr = arr.astype(np.float32)                          # float16 -> float32 (exact)
    return np.ascontiguousarray(arr), hit.layout
