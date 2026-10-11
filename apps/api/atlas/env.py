"""读项目根目录的 .env（已存在的环境变量优先）。

为什么单独一个模块：**环境变量在 import 期就会被读**（`assemble` 在模块级解析
`RAG_INDEX_DIR`），所以必须在它 import 之前把 .env 载进来，不能等到某个函数被调用时。
"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]     # 仓库根


def load_dotenv(path: Path | None = None) -> None:
    env = path or (_ROOT / ".env")
    if not env.is_file():
        return
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
