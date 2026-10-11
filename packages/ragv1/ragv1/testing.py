"""测试与验证脚本共用的确定性假向量。

放在**包内**而不是 tests/conftest.py：合并成 monorepo 后，三个包各有自己的 tests/，
而 `conftest` 这个名字在 sys.path 上会互相遮蔽（实测：ragv1 的测试拿到了 csagent 的 conftest）。
按包名导入就不存在这个问题。

测试只验管道行为，不验 embedding 模型质量——统一用确定性假向量，
避免整套测试依赖网络与付费 API。

⚠️ 契约与真实 embedder 一致：**收文本列表、返向量列表**（批量）。
"""

import hashlib

DIM = 128


def _one(text: str) -> list[float]:
    """单个文本的确定性假向量：按字符袋构造并归一化。

    用 hashlib 而非内置 hash()——后者受 PYTHONHASHSEED 影响，跨进程不稳定。
    """
    vec = [0.0] * DIM
    for ch in text:
        h = int(hashlib.md5(ch.encode("utf-8")).hexdigest(), 16) % DIM
        vec[h] += 1.0
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec] if norm else vec


def fake_embed(texts: list[str]) -> list[list[float]]:
    """批量假向量。"""
    return [_one(t) for t in texts]
