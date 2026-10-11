"""鉴权 + IP 限流 + 全局封顶。

## 双轨设计

匿名（无 key）走**严格**配额，带 `X-API-Key` 走**宽松**配额：

| 轨道 | 谁能用 | 配额 |
|---|---|---|
| 匿名 | 任何人（演示要能被直接试） | 严 |
| 认证 | 持有 key 的人 | 宽 |

这样"鉴权"和"能试"两件事都不牺牲。**带了 key 但不对 → 401，不悄悄降级成匿名** ——
否则带错 key 的人会以为自己认证成功了。

## 两条必须守住的规则

1. **先扣后放行。** 反过来（成功了再记账）意味着"让调用失败"是一条免费通道：
   刷的人只要构造必然失败的请求，就能无限占用算力而不进账。
2. **两个入口共用同一个计数器。** 各算一套的话，换个入口就绕过限额了。

⚠️ 进程内内存 + 一把锁。多实例部署要换成共享存储 —— 这一点写在 README 的已知边界里。
"""
import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    tier: str = "anonymous"
    reason: str | None = None      # bad_key / anon_quota / auth_quota / global_cap
    remaining: int = 0


@dataclass
class Guard:
    api_key: str | None = None
    anon_daily: int = 5
    auth_daily: int = 200
    global_cap: int = 500          # 全局请求数上限（不是钱，是次数）

    _used: dict = field(default_factory=dict, init=False)
    _total: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def check(self, *, ip: str | None, api_key: str | None, entry: str = "") -> Verdict:
        """`entry` 只用于审计日志，**不参与计数** —— 计数键是 (轨道, IP)，两个入口共用。"""
        with self._lock:
            if self._total >= self.global_cap:
                return Verdict(False, reason="global_cap")

            if api_key:
                # 配了 key 却不对 → 明确拒绝，不降级
                if self.api_key and api_key != self.api_key:
                    return Verdict(False, reason="bad_key")
                tier, limit = "authenticated", self.auth_daily
            else:
                tier, limit = "anonymous", self.anon_daily

            key = (tier, ip or "unknown")
            used = self._used.get(key, 0)
            if used >= limit:
                return Verdict(False, tier=tier, reason="anon_quota" if tier == "anonymous" else "auth_quota")

            # 先扣后放行
            self._used[key] = used + 1
            self._total += 1
            return Verdict(True, tier=tier, remaining=limit - used - 1)

    @property
    def total(self) -> int:
        return self._total
