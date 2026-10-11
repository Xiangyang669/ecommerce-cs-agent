"""起服务： py scripts/serve.py（默认 127.0.0.1:8000；容器里设 HOST=0.0.0.0）。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from atlas.main import create_app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
