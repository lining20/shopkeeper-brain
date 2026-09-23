"""Verify that this project's PyTorch installation can use an NVIDIA GPU."""

from __future__ import annotations

import os
import sys
import time
import traceback


def main() -> int:
    print(f"Python executable: {sys.executable}")
    print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', '<not set>')}")

    try:
        import torch

        print(f"PyTorch version: {torch.__version__}")
        print(f"PyTorch CUDA build: {torch.version.cuda}")
        print(f"CUDA available: {torch.cuda.is_available()}")

        if not torch.cuda.is_available():
            print("FAIL: PyTorch cannot access an NVIDIA GPU.")
            return 1

        device = torch.device("cuda:0")
        print(f"GPU count: {torch.cuda.device_count()}")
        print(f"GPU name: {torch.cuda.get_device_name(device)}")
        print(f"GPU capability: {torch.cuda.get_device_capability(device)}")

        left = torch.randn((1024, 1024), device=device)
        right = torch.randn((1024, 1024), device=device)
        torch.cuda.synchronize(device)
        started_at = time.perf_counter()
        result = left @ right
        torch.cuda.synchronize(device)

        assert torch.isfinite(result).all().item()
        print(f"GPU matrix multiplication completed in {time.perf_counter() - started_at:.3f}s")
        print("SUCCESS: CUDA PyTorch is installed and the GPU calculation completed.")
        return 0
    except Exception:
        print("FAIL: The CUDA verification script raised an exception.")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
