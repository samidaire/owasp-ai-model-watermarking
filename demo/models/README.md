# Your models

Drop a model file here (`.pt`, `.h5`, `.keras` or `.onnx`) and it appears in the app's **Model under test** menu,
under "Your models". Pressing **Test this model** reads the watermark from its `conv2` layer with the owner's keys,
measures its accuracy if it's the demo's MNIST network, and makes a zero-knowledge proof of ownership if the
owner's mark is there.

- Files load safely (no pickled code): `.pt` with `weights_only=True`, Keras in safe mode, ONNX through
  `onnx.checker`.
- A model without a `conv2` layer of 288 values is reported as "can't test", not as a failure.
- Replay mode (`--simulate`) can only replay the built-in models; start the server normally to test your files.
- Files here are git-ignored, so they are never committed by accident.
