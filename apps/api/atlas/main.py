"""统一入口：把两个子应用挂起来，并在前面加一道鉴权 / 限流。

## 🔴 这里唯一要紧的技术点

鉴权是**在父应用上用中间件**做的。问题是：**`mount()` 进去的子应用，会不会绕过它？**

代码上不会 —— Starlette 的中间件栈包住的是 router，而 mount 就是 router 里的一条路由，
所以打到 `/retrieval/*`、`/orchestrate/*` 的请求**同样**要过这道中间件。

**但这件事必须实测**（`tests/test_mounting.py::test_subapp_is_not_an_open_backdoor`）——
因为"想当然以为挂上了"的后果是：一个**完全开放的后门**，
`/retrieval/search` 谁都能打，而你以为它有鉴权。

## 开放的路径

只有健康检查与文档页开放。**业务端点一律要过鉴权与限流。**
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from atlas import assemble, guard as guard_mod

OPEN_PATHS = frozenset({"/healthz", "/docs", "/openapi.json", "/redoc"})

_GENERIC_DENIED = {
    "bad_key": (401, "API Key 无效"),
    "anon_quota": (429, "匿名额度已用完；带 X-API-Key 可获得更高额度"),
    "auth_quota": (429, "今日额度已用完"),
    "global_cap": (503, "服务总量已达上限，请稍后再试"),
}


def guard_from_env() -> guard_mod.Guard:
    return guard_mod.Guard(
        api_key=os.environ.get("ATLAS_API_KEY") or None,
        anon_daily=int(os.environ.get("ATLAS_ANON_DAILY", "5")),
        auth_daily=int(os.environ.get("ATLAS_AUTH_DAILY", "200")),
        global_cap=int(os.environ.get("ATLAS_GLOBAL_CAP", "500")),
    )


def create_app(*, guard=None, with_real_engine: bool = True) -> FastAPI:
    g = guard or guard_from_env()
    app = assemble.build_app(with_real_engine=with_real_engine)

    @app.middleware("http")
    async def _auth_and_limit(request: Request, call_next):
        path = request.url.path
        if path in OPEN_PATHS:
            return await call_next(request)

        verdict = g.check(
            ip=request.client.host if request.client else None,
            api_key=request.headers.get("X-API-Key"),
            # 只用于审计；计数键是 (轨道, IP)，两个入口共用
            entry=path.strip("/").split("/")[0],
        )
        if not verdict.allowed:
            status, msg = _GENERIC_DENIED.get(verdict.reason, (403, "请求被拒绝"))
            return JSONResponse(status_code=status, content={"error": msg, "reason": verdict.reason})

        response = await call_next(request)
        # 顺带把剩余额度告知调用方，便于自测
        response.headers["X-RateLimit-Remaining"] = str(verdict.remaining)
        response.headers["X-RateLimit-Tier"] = verdict.tier
        return response

    return app
