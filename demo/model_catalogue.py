"""The models the UI's "Model under test" menu offers (stdlib only: the server imports this without torch).

Built-in models are the demo's checkpoints plus stolen copies of the owner's v2 model that 10_test_model.py
derives live (pruned, quantised, fine-tuned, permuted, overwritten). Any .pt/.h5/.keras/.onnx file dropped
into demo/models/ is listed too, as "file:<name>".
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CKPT = ROOT / "ckpt"
USER_DIR = ROOT / "models"
USER_SUFFIXES = (".pt", ".h5", ".keras", ".onnx")

OWNER, STOLEN, NEVER, USER = "Owner's models", "Stolen copies (attacked live)", "Never watermarked", "Your models (demo/models/)"

# id -> (group, label, file relative to demo/ or None for a derived copy, note)
BUILTIN = {
    "watermarked_v2": (OWNER, "watermarked_v2.pt", "ckpt/v2/watermarked_v2.pt",
                       "The owner's model as registered (protocol v2, demo F)."),
    "watermarked_v1": (OWNER, "watermarked.pt", "ckpt/watermarked.pt",
                       "The research baseline's model (protocol v1, demos A–E). Watermarked with a different owner key."),
    "prune65": (STOLEN, "watermarked_v2 · pruned 65%", None,
                "A thief zeroes the 65% smallest weights of every layer."),
    "prune90": (STOLEN, "watermarked_v2 · pruned 90%", None,
                "A thief zeroes the 90% smallest weights of every layer: the model barely works any more."),
    "int8": (STOLEN, "watermarked_v2 · int8 quantised", None,
             "A thief rounds every weight to 8 bits to shrink the model."),
    "finetune": (STOLEN, "watermarked_v2 · fine-tuned 5 epochs", None,
                 "A thief keeps training all layers on 10,000 images of their own."),
    "permute": (STOLEN, "watermarked_v2 · channels permuted", None,
                "A thief reorders conv1's channels: same predictions, different weight order. The known limit."),
    "overwrite": (STOLEN, "watermarked_v2 · overwritten by a thief", None,
                  "A thief embeds their own mark on top (3 epochs). The owner's mark should still read."),
    "clean": (NEVER, "clean.pt", "ckpt/clean.pt", "Same network trained without any watermark."),
    "null_0": (NEVER, "null_0.pt", "ckpt/null_0.pt", "An independently trained model, never watermarked."),
    "null_1": (NEVER, "null_1.pt", "ckpt/null_1.pt", "An independently trained model, never watermarked."),
    "null_2": (NEVER, "null_2.pt", "ckpt/null_2.pt", "An independently trained model, never watermarked."),
    "null_3": (NEVER, "null_3.pt", "ckpt/null_3.pt", "An independently trained model, never watermarked."),
}
# Attacked copies are made from this model.
SOURCE = "watermarked_v2"


def user_files():
    if not USER_DIR.is_dir():
        return []
    return sorted(p for p in USER_DIR.iterdir() if p.is_file() and p.suffix.lower() in USER_SUFFIXES)


def catalogue():
    """[{id, group, label, file, derived, note}] in menu order."""
    out = [{"id": k, "group": g, "label": lab, "file": f, "derived": f is None, "note": note}
           for k, (g, lab, f, note) in BUILTIN.items()]
    for p in user_files():
        out.append({"id": f"file:{p.name}", "group": USER, "label": p.name, "file": f"models/{p.name}",
                    "derived": False, "note": "Your own file. It must have a conv2 layer the watermark can be read from."})
    return out


def ids():
    return [m["id"] for m in catalogue()]


def resolve(model_id):
    """The catalogue entry for an id, or None (ids are only ever looked up, never joined into paths)."""
    return next((m for m in catalogue() if m["id"] == model_id), None)


def safe_name(model_id):
    """A filename for the model's result: built-in ids as they are, user files hashed into a fixed alphabet."""
    if model_id in BUILTIN:
        return model_id
    import hashlib
    return "file_" + hashlib.sha256(model_id.encode()).hexdigest()[:16]
