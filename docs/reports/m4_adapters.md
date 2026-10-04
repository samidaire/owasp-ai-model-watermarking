# M4: framework adapters (WM-01, WM-03, WM-04, WM-05, SDK-04)

**Status:** implemented and tested. **Code:** `sdk/src/sigil/adapters/`, `sdk/src/sigil/embed.py`.
**Tests:** `sdk/tests/test_adapters_{common,onnx,torch,keras}.py`.

The adapters let the protocol-v2 core (`sigil.protocol`, [protocol.md](../protocol.md)) work on real models.
They read a named layer's kernel from PyTorch, Keras or ONNX, and they embed the Uchida watermark with
the protocol's key and signature. `protocol.py` is unchanged: every adapter ends in
`protocol.uchida_vector(kernel, layout)`, `protocol.quantize` and `protocol.detect`.

## 1. What was built

| Module | Contents |
|---|---|
| `sigil.adapters` | The common interface: `get_kernel(model_or_path, layer) -> (kernel, layout)`, `uchida_vector`, `quantized_vector`, `detect`, `detect_framework`, plus the errors `AdapterError`, `LayerNotFoundError`, `UnsafeModelError` and `FileTooLargeError`. The framework is detected from the object's class hierarchy or the file extension (`.pt/.pth`, `.keras/.h5/.hdf5`, `.onnx`), and imported only when it's needed. |
| `adapters.torch_adapter` (WM-03) | Reads `Conv2d` (OIHW) and `Linear` (OI) layers by dotted name (`layer3.1.conv2`) from an `nn.Module`, a `state_dict`, a checkpoint dict or a `.pt/.pth` file. `TorchWatermark.loss(model)` is the regulariser for your own training loop, and `finetune_embed(...)` runs that loop for you. |
| `adapters.keras_adapter` (WM-04) | Reads `Conv2D` (HWIO) and `Dense` (IO) layers by name (`outer/inner` for nested models) from a `keras.Model` or a `.keras/.h5` file. `UchidaRegularizer` and `KerasWatermark` handle embedding (`attach`, `detach` and `attached()`), and a `callback()` logs `wm_errors` each epoch. |
| `adapters.onnx_adapter` (WM-05) | Finds the initializer that feeds a layer's `Conv` (OIHW), `Gemm` (OI if `transB`, else IO) or `MatMul` (IO) node. It also follows `Identity`, `Transpose` and `Constant` nodes. `load_onnx` loads a file safely. |
| `sigil.embed` (WM-01) | `embed_torch(...)` and `embed_keras(...)`. Each one derives X = `key_matrix` and b = `signature_bits`, checks that the layer's vector has length `cfg.M`, trains, and returns `(model, Detection)`. The detection is computed on the **quantised** vector. |

**The regulariser** is λ · mean BCE-with-logits(X·w, b), the same term `demo/wm_core.train` uses.
Here w is the differentiable Uchida vector: the mean over output units, flattened in the order
(in, kh, kw). Keras kernels are transposed HWIO→OIHW (IO→OI) before the mean, so **one X works in
every framework**.

**Safe loading (SDK-04)** applies to every file loader:

- **Size limit:** every loader takes `max_bytes`, with a default of 2 GiB. For ONNX the limit covers the external data; for `.keras` it covers the uncompressed archive (a zip-bomb guard).
- **PyTorch:** files are loaded only with `torch.load(path, map_location="cpu", weights_only=True)`. Whole pickled modules, TorchScript archives and pickles carrying code are refused. `trust=True` never turns on pickle.
- **Keras:** `load_model(safe_mode=True, compile=False)`, after a pre-scan of the saved config. A Lambda layer (Python bytecode) is refused unless the caller passes `trust=True`, and weights-only `.h5` files are rejected with a clear error.
- **ONNX:**
  - external-data locations must be relative paths inside the model's directory;
  - the model must pass `onnx.checker`;
  - only the one tensor that's needed is read from external data.

**Secrets (CR-04):** in Keras, the regulariser is attached to the kernel *variable* only while `fit`
runs, so the saved config never contains it. `UchidaRegularizer.get_config()` raises, so the key can't be
serialised by accident. The `repr()` of both watermark classes hides X and b.

## 2. Usage

```python
from sigil import adapters, protocol as P
from sigil.embed import embed_torch, embed_keras

cfg = P.Config(T=64, M=288, layer="conv2")            # T, layer and lambda are free; M must match the layer

# PyTorch: one call, or the regulariser inside your own loop
model, det = embed_torch(model, (x, y), cfg, seed, pk_hash, epochs=2, lam=1.0)      # or a DataLoader
wm = adapters.TorchWatermark.derive(cfg, seed, pk_hash, lam=1.0)
loss = F.cross_entropy(model(xb), yb) + wm.loss(model)

# Keras: one call, or attach the regulariser around your own fit
model, det = embed_keras(model, (x, y), cfg, seed, pk_hash, epochs=2)
kwm = adapters.KerasWatermark.derive(cfg, seed, pk_hash)
with kwm.attached(model):
    model.fit(x, y, epochs=2, callbacks=[kwm.callback()])

# Detection and extraction from any framework or file (the framework is auto-detected)
adapters.detect("model.onnx", seed, pk_hash, cfg)               # -> Detection(errors, ber, max_err, accepted)
w_q = adapters.quantized_vector("model.keras", cfg)            # what w_hash and the circuit use
kernel, layout = adapters.get_kernel("model.pt", "layer3.1.conv2")
adapters.get_kernel("untrusted.h5", "dense", trust=True)        # only for files from a trusted source
```

## 3. Test results

**Setup:** the main venv on Windows 11, with torch 2.14.1+cu130 on an RTX 4060, TensorFlow 2.21.0 (CPU),
Keras 3.15.1, tf2onnx 1.17.0 and onnx 1.23.1. **Config:** T = 64, M = 288, layer `conv2`, max_err = 8, λ = 1.
The watermarked and clean models share their initialisation and data order; only the regulariser differs.

| | PyTorch (`demo/wm_core.Net`, CUDA) | Keras CNN (CPU) |
|---|---|---|
| Training | 2 epochs on 20,000 MNIST images | 2 epochs on 10,000 MNIST images |
| Test accuracy: clean → watermarked | 98.01–98.08% → 97.92–97.98% | 96.76% → 96.76% (50 of 10,000 predictions differ) |
| Accuracy cost | **0.03–0.11 pp** (3 runs; CUDA isn't deterministic) | **0.00 pp** |
| Owner errors, quantised vector | **0 / 64, accepted** | **0 / 64, accepted** |
| Clean model, owner key | 27–28 / 64, rejected | 28 / 64, rejected |
| Watermarked model, wrong owner key | rejected | rejected |
| Watermark training time | 1.4–2.1 s | 3.9–4.6 s |

The Keras model is Input(28,28,1) → Conv2D(32,3) → **Conv2D(64,3) "conv2"** → MaxPool → Dense(10).

**WM-05 exports.** Each export below gives the same kernel, the **identical** quantised vector, the same
`w_hash` and the same `Detection` as its source model:
- PyTorch → ONNX, dynamo exporter (4–9 s, writes `wm.onnx.data` as external data);
- PyTorch → ONNX, TorchScript exporter (0.1–2 s);
- Keras → ONNX through `tf2onnx.convert.from_keras` (about 1 s).

The `.keras` and `.h5` reloads also give the identical vector. **Cross-framework:** a PyTorch conv2 kernel
copied into a Keras Conv2D (OIHW→HWIO) gives the identical vector and detection, both in Keras and after tf2onnx.

```
$ PYTHONPATH=sdk/src .venv/Scripts/python -m pytest sdk/tests/test_adapters_common.py \
      sdk/tests/test_adapters_onnx.py sdk/tests/test_adapters_torch.py sdk/tests/test_adapters_keras.py
====================== 37 passed, 65 warnings in 45.89s =======================
```

The whole `sdk/tests` suite passes too (123 passed in 57–99 s). The two test files that train models are
marked `ml`. `test_adapters_common.py` and `test_adapters_onnx.py` (hand-built ONNX graphs) need only numpy
and onnx, so they aren't marked.

## 4. Limitations and findings

- **BatchNorm folding.** Both PyTorch exporters, and tf2onnx (even with `optimizers={}`), fold an
  eval-mode BatchNorm into the conv before it. That changes the kernel, so the ONNX vector differs from the
  source. This affects ResNet-style layers (WM-01's ResNet-18 target).
  - PyTorch: export with `optimize=False` (dynamo) or `do_constant_folding=False` (TorchScript exporter). This is tested.
  - Keras: we found no tf2onnx switch. Detect on the `.keras`/`.h5` file, or watermark a conv that isn't followed by BN.
- **tf2onnx names.** tf2onnx names nodes from Keras 3 scopes with a `_<n>` suffix: `kcnn_1/conv2_1/convolution`
  and `…/ReadVariableOp:0`. The suffix depends on the model name and on how many times the model was traced.
  The matcher accepts `_<n>`. Layer names that differ only by such a suffix (`conv2` and `conv2_1`) are
  reported as ambiguous, never guessed; pass the exact node or initializer name instead.
- **Supported layers.** Only 2-D convolutions (Conv2d/Conv2D) and linear layers (Linear/Dense) are
  supported. Conv1d/3d, transposed and depthwise convs, and quantised ONNX weights (`DequantizeLinear`) are
  rejected with an error. Grouped convs are read but untested.
- **PyTorch files.** Full pickled modules and TorchScript archives are refused by design. Users must save
  a `state_dict`.
- **Keras versions.** Only Keras 3 is supported. Legacy tf.keras-2 `.h5` files with `TFOpLambda` layers
  can't be loaded by Keras 3 at all.
- **Float summation order.** `protocol.uchida_vector` takes the float64 mean along memory's outer axis for
  OIHW but along the inner axis for HWIO, so NumPy may sum in a different order. Sums of float32 values in
  float64 are exact unless one column's dynamic range exceeds about 2²⁹, so the vectors were identical in
  every test. A pathological kernel could differ in the last float64 bit, which matters only at a 2⁻¹⁷
  rounding boundary. Making this exact would mean reducing a contiguous OIHW copy inside `protocol.py`;
  it is left as a possible protocol change.
- **No onnxruntime.** onnxruntime isn't installed in the venv, so the exported graphs were compared on
  weights only; they were never executed.
- **Windows console encoding.** On Windows, the dynamo exporter prints ✅ and crashes on a piped cp1252
  console (`UnicodeEncodeError`). Set `PYTHONIOENCODING=utf-8`.
- **Not evidence for WM-09.** The accuracy numbers are single-seed smoke tests at T = 64. They are not the
  WM-09 evidence, which needs T = 256 and at least 5 seeds. ResNet-18 embedding (WM-01) isn't run here;
  the API supports it through dotted layer names and a free T and λ.
