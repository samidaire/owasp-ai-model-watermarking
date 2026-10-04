"""Environment sanity check: torch build, CUDA device, compute capability, VRAM."""
import platform
import sys

import torch

from wm_core import DATA, banner

banner("ENVIRONMENT CHECK")
print(f"  Python      : {sys.version.split()[0]} ({platform.system()} {platform.release()})")
print(f"  PyTorch     : {torch.__version__}  (CUDA build: {torch.version.cuda})")
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(f"  GPU         : {p.name}  sm_{p.major}{p.minor}  {p.total_memory / 2**30:.1f} GiB")
    x = torch.randn(1024, 1024, device="cuda")
    print(f"  CUDA matmul : OK ({(x @ x).sum().item():.1f})")
else:
    print("  GPU         : not available -> running on CPU (fine for MNIST)")
missing = [f for f in ["train-images-idx3-ubyte.gz", "train-labels-idx1-ubyte.gz",
                       "t10k-images-idx3-ubyte.gz", "t10k-labels-idx1-ubyte.gz"]
           if not (DATA / f).exists()]
print(f"  MNIST data  : {'OK' if not missing else 'MISSING ' + str(missing)}")
