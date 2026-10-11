"""测试共用的构造辅助。

放在**包内**而不是 tests/conftest.py：合并成 monorepo 后 `conftest` 这个名字
在 sys.path 上会互相遮蔽（ragv1 与 csagent 各有一份）。按包名导入不存在这个问题。

「怎么搭一张图」只有一处答案 —— 将来 `build_graph` 的签名变了，要改的也只有这里。
"""


def build_stub_graph(retriever, **kwargs):
    """用**桩检索**搭一张图。不碰检索内核、不碰数据库、不碰网络。"""
    from csagent.graph import build_graph

    return build_graph(retriever, **kwargs)
