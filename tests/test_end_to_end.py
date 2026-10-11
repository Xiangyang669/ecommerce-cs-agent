"""跨包的端到端测试 —— 这个目录存在的理由就是"单包测试测不到接口"。

三个包各自的测试都是绿的，但它们**接起来**能不能跑，只有这里能回答：
真装配（起检索内核 + 建编排图）→ 打两个入口 → 断言返回的是真东西。

需要索引与 API key；缺了就 skip —— 但**必须留下"跳过了"的记录**，
不能让"没跑"看起来像"通过了"。
"""
import pytest
from fastapi.testclient import TestClient

from atlas import assemble, guard
from atlas.main import create_app

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def client():
    if not assemble.RAG_INDEX_DIR.is_dir():
        pytest.skip(f"索引目录不存在：{assemble.RAG_INDEX_DIR}（跑 scripts/build_index.py 生成）")
    app = create_app(guard=guard.Guard(anon_daily=99), with_real_engine=True)
    return TestClient(app, raise_server_exceptions=False)


def test_both_halves_assemble(client):
    """装配这一层最容易静默失败 —— 必须两个都 ok，不能只看进程起没起来。"""
    body = client.get("/healthz").json()
    assert body["assembled"]["retrieval"] == "ok", body["assembled"]
    assert body["assembled"]["orchestrate"] == "ok", body["assembled"]


def test_retrieval_returns_real_chunks_not_an_empty_shell(client):
    """🔴 检索返回空 = 最危险的静默失败：服务"起来了"，但什么都没有。"""
    r = client.post("/retrieval/search", json={"query": "怎么配置模型"})
    assert r.status_code == 200
    body = r.json()
    assert body["results"], "检索返回了空结果 —— 多半是 RAG_INDEX_DIR 指错了（不是具体那一份索引）"
    first = body["results"][0]
    assert first["chunk_id"] and first["sources"], "返回结构不完整"


def test_orchestration_runs_a_whole_ticket(client):
    r = client.post("/orchestrate/ticket", json={"message": "我要退款"})
    assert r.status_code == 200
    body = r.json()
    assert body["thread_id"], "没拿到会话号"
    assert body["route_taken"], "没记录走了哪条路"
    assert "final_reply" in body


def test_the_two_entries_share_one_quota(client):
    """换一个入口不该能绕过限额 —— 这是入口层的核心承诺，跨包验证一次。"""
    app = create_app(guard=guard.Guard(anon_daily=1), with_real_engine=False)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/retrieval/search", json={"query": "x"}).status_code == 200
    assert c.post("/orchestrate/ticket", json={"message": "y"}).status_code == 429
