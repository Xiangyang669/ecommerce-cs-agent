"""装配：把项目①（检索内核）与项目②（多 Agent 编排）起起来，挂成一个统一入口。

**不合并两个仓的代码。** 这里只做两件事：把两个包导入进来、把两个 app 挂上去。

⚠️ 两个必须显式处理的地方（都是踩过的坑）：

1. **历史上工作区里有两份 `ragv1`**（合并前的事）。现在只剩 `packages/ragv1` 一份，
   但这里仍然显式指定 `RAG_REPO` 并在 `import_roots()` 里把**实际导入来源**暴露出来 ——
   万一将来又出现第二份，是看得见的，而不是靠 sys.path 的偶然顺序。

2. **项目② 的适配器会静默降级** —— 它的写法是
   `try: from ragv1... import run_query  except ImportError: _DEFAULT_QUERY_FN = None`。
   **导不到就悄悄变成「没有检索能力」，不报错。** 所以这里提供 `adapter_query_fn()`
   供上层显式断言，绝不假设"它能自己搞定"。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 合并成 monorepo 之后，两个包就在本仓的 packages/ 下（不再是外面的兄弟目录）。
# 环境变量仍可覆盖 —— 部署时镜像里没有 .indexes，得指到别处。
REPO_ROOT = Path(__file__).resolve().parents[3]           # 仓库根
PACKAGES = REPO_ROOT / "packages"
RAG_REPO = Path(os.environ.get("RAG_REPO", PACKAGES / "ragv1"))
CS_REPO = Path(os.environ.get("CS_REPO", PACKAGES / "csagent"))

# 项目① 的索引目录（中文语料）；可用环境变量覆盖
RAG_INDEX_DIR = Path(os.environ.get("RAG_INDEX_DIR", RAG_REPO / ".indexes" / "kb_zh"))


def _ensure_paths() -> None:
    """把两个仓的根塞进 sys.path。

    ⚠️ 顺序有意：先 cs-agent 再 rag-v1 —— 反过来也行，但**必须先清掉别的 ragv1 来源**，
    否则拿到的可能是学习仓那一份。下面的 `import_roots()` 就是为了让这件事**可见**。
    """
    for p in (str(CS_REPO), str(RAG_REPO)):
        if p not in sys.path:
            sys.path.insert(0, p)


def import_roots() -> dict[str, str]:
    """返回两个包**实际**是从哪个文件导入的 —— 让"用错了哪一份"这件事一眼可见。"""
    _ensure_paths()
    import csagent
    import ragv1

    return {"ragv1": ragv1.__file__, "csagent": csagent.__file__}


def adapter_query_fn():
    """项目② 的适配器**实际**拿到的项目① 查询函数；没导到就是 None。

    上层要显式断言它不为 None —— 否则服务会"看起来正常但什么都不会做"。
    """
    _ensure_paths()
    from csagent.adapters import ragv1_retriever

    return ragv1_retriever._DEFAULT_QUERY_FN


def build_app(*, with_real_engine: bool = True):
    """组装统一入口。

    `with_real_engine=False` 时只挂空的子应用（测试用）——
    它验证的是**路由形状**，不是引擎本身。
    """
    _ensure_paths()

    from fastapi import FastAPI

    app = FastAPI(title="atlas", description="统一入口：三层检索 + 多 Agent 编排")

    state: dict[str, str] = {}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "assembled": state, }

    if with_real_engine:
        rag_app, cs_app = _real_subapps(state)
    else:
        rag_app, cs_app = _stub_subapps()

    # 挂载：两个子应用对外就是同一个服务的两组端点
    app.mount("/retrieval", rag_app)
    app.mount("/orchestrate", cs_app)
    return app


def _stub_subapps():
    from fastapi import FastAPI

    rag = FastAPI(title="retrieval")

    @rag.post("/search")
    def search() -> dict:
        return {"degraded": "stub"}

    cs = FastAPI(title="orchestrate")

    @cs.post("/ticket")
    def ticket() -> dict:
        return {"degraded": "stub"}

    @cs.post("/ticket/{thread_id}/resume")
    def resume(thread_id: str) -> dict:
        return {"degraded": "stub"}

    return rag, cs


def _real_subapps(state: dict[str, str]):
    """用两个仓**自己的装配函数**起子应用。失败要落进 state，不吞。"""
    from fastapi import FastAPI

    rag = FastAPI(title="retrieval")
    cs = FastAPI(title="orchestrate")

    try:
        from ragv1.api.main import create_app as rag_create_app
        from ragv1.api.server import _open as rag_open

        retriever, store = rag_open(RAG_INDEX_DIR)
        # ⚠️ 索引体检：SQLite 遇到不存在的库会**自己建一个空的**，于是服务"起来了"、
        #    检索却永远返回空 —— 典型的静默失败。这里显式查一次块数，空就直接判失败。
        if not store.chunk_ids():
            raise RuntimeError(
                f"索引是空的：{RAG_INDEX_DIR} —— 确认 RAG_INDEX_DIR 指的是**具体那一份索引目录**"
                f"（例如 .indexes/kb_zh），而不是它的父目录"
            )
        rag = rag_create_app(retriever, meta_lookup=store.meta_of)
        state["retrieval"] = "ok"
    except Exception as exc:  # noqa: BLE001 —— 装配失败必须被看见
        # 带上异常文本：只记类型的话，"四个检查全崩"那类问题会完全没线索（踩过）
        state["retrieval"] = f"failed:{type(exc).__name__}: {exc}"

    try:
        from csagent.api.main import create_app as cs_create_app
        from csagent.graph import build_graph

        cs = cs_create_app(build_graph(_retriever_for_cs()))
        state["orchestrate"] = "ok"
    except Exception as exc:  # noqa: BLE001
        state["orchestrate"] = f"failed:{type(exc).__name__}: {exc}"

    return rag, cs


def _retriever_for_cs():
    """项目② 要的检索接口 —— 两仓之间只认这个窄协议。

    ⚠️ `RagV1Retriever` 需要两样东西：
    - `graph`：项目① 的检索图（`supervisor.build_graph(retriever, ALL_PATHS)`）
    - `text_of`：chunk_id → 正文。**这个不能省** —— 适配器的文档里写着
      `ragv1.types.FusedHit` 不含正文，不接这个解析口的话，回复里就只剩 ID 没有人话。

    这里复用项目① **自己的生产装配函数** `ragv1.api.server._open`，
    而不是另拼一套 —— 否则就是在两个地方各决定一次"系统长什么样"。
    """
    from csagent.adapters.ragv1_retriever import RagV1Retriever
    from ragv1.api.server import _open as rag_open
    from ragv1.orchestration.supervisor import build_graph
    from ragv1.retrieve import ALL_PATHS

    retriever, fts = rag_open(RAG_INDEX_DIR)
    return RagV1Retriever(graph=build_graph(retriever, ALL_PATHS), text_of=fts.text_of)
