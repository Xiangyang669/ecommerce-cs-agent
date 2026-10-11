"""Task 3 · 装配两个子应用并挂载.

🔴 Review Focus 1 在这里：**挂着鉴权的父应用，mount 进去的子应用也必须被拦。**
这条必须**实测** —— 想当然的话就是一个完全开放的后门（`/retrieval/search` 谁都能打）。
"""
from fastapi.testclient import TestClient

from atlas import guard
from atlas.main import create_app


def _client(**gkw):
    app = create_app(guard=guard.Guard(**gkw), with_real_engine=False)
    return TestClient(app, raise_server_exceptions=False)


def test_healthz_is_open():
    assert _client().get("/healthz").json()["status"] == "ok"


def test_subapp_is_not_an_open_backdoor():
    """🔴 挂载的子应用**必须**走父应用的鉴权/限流中间件。"""
    c = _client(anon_daily=1)
    assert c.post("/retrieval/search").status_code == 200
    r = c.post("/retrieval/search")
    assert r.status_code == 429, (
        f"mount 进去的子应用绕过了限流：得到 {r.status_code} —— 这就是一个开放后门"
    )


def test_both_entries_share_one_limiter():
    """🔴 Review Focus 2：换一个入口不该能绕过限额。"""
    c = _client(anon_daily=1)
    assert c.post("/retrieval/search").status_code == 200
    assert c.post("/orchestrate/ticket").status_code == 429


def test_wrong_api_key_gets_401_everywhere():
    c = _client(api_key="right-key")
    for path in ("/retrieval/search", "/orchestrate/ticket"):
        assert c.post(path, headers={"X-API-Key": "wrong"}).status_code == 401, path


def test_right_api_key_passes():
    c = _client(api_key="right-key", anon_daily=0)
    assert c.post("/retrieval/search", headers={"X-API-Key": "right-key"}).status_code == 200


def test_assembly_failure_is_reported_not_swallowed():
    """🔴 Review Focus 3：装配失败要在 /healthz 里如实报出来，不能变成一个"看起来正常"的服务。"""
    app = create_app(guard=guard.Guard(), with_real_engine=True)
    body = TestClient(app, raise_server_exceptions=False).get("/healthz").json()
    assert "assembled" in body and body["assembled"], "healthz 没报告装配状态"
    assert all(v == "ok" or str(v).startswith("failed:") for v in body["assembled"].values())


def test_real_assembly_succeeds_when_the_index_is_present():
    """端到端装配：两个子应用都该起来。

    索引不存在时跳过 —— 这条依赖工作区里的 `rag-v1/.indexes/`，
    不是每个环境都有。但**有索引时它必须过**，否则"服务起来了"是假的。
    """
    from atlas import assemble

    if not assemble.RAG_INDEX_DIR.is_dir():
        import pytest

        pytest.skip(f"索引目录不存在：{assemble.RAG_INDEX_DIR}")

    app = create_app(guard=guard.Guard(), with_real_engine=True)
    body = TestClient(app, raise_server_exceptions=False).get("/healthz").json()
    assert body["assembled"]["retrieval"] == "ok", body["assembled"]
    assert body["assembled"]["orchestrate"] == "ok", body["assembled"]
