"""Task 1 · 先验证「两个项目能不能装在一起」.

工作区里有**两个** ragv1（`rag-v1/` 作品仓、`ai-agent-90days/rag_v1/` 学习仓），
而项目② 的适配器是按**名字**导入的 —— 用错一份，后面全是白干。
这个坑本项目已经栽过一次（2026-10-04）。

⚠️ 更要紧的是：项目② 的适配器是 `try: import ragv1 ... except ImportError: None` ——
**导不到就悄悄变成"没有检索能力"，不报错**。所以这里必须**显式断言它真的导到了**。
"""
import os
from pathlib import Path

import pytest

from atlas import assemble

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_both_packages_import_from_declared_roots():
    got = assemble.import_roots()
    # ⚠️ 跨平台断言：Windows 路径是反斜杠，别在源码里写字面量反斜杠（\'\\r\' 会被转义吃掉）。
    assert Path(got["ragv1"]).parts[-3:] == ("ragv1", "ragv1", "__init__.py"), (
        f"ragv1 不是从作品仓导入的：{got['ragv1']}"
    )
    assert Path(got["csagent"]).parts[-3:] == ("csagent", "csagent", "__init__.py"), (
        f"csagent 来源不对：{got[chr(39)+chr(99)+chr(115)+chr(97)+chr(103)+chr(101)+chr(110)+chr(116)+chr(39)]}"
    )


def test_adapter_really_found_ragv1_not_silently_none():
    """🔴 静默降级的反面：适配器**必须**真的拿到了项目① 的查询函数。"""
    assert assemble.adapter_query_fn() is not None, (
        "项目② 的适配器没导到 ragv1 —— 它会静默退化成「没有检索能力」，不报错"
    )


def test_unified_endpoints_are_declared():
    app = assemble.build_app(with_real_engine=False)
    paths = {r.path for r in app.routes}
    assert "/healthz" in paths
    assert any(p.startswith("/retrieval") for p in paths), f"没有挂检索入口：{sorted(paths)}"
    assert any(p.startswith("/orchestrate") for p in paths), f"没有挂编排入口：{sorted(paths)}"
