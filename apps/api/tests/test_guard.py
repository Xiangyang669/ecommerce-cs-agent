"""Task 2 · 鉴权 + 限流 + 配额.

设计是**双轨**：匿名（无 key）走严格配额，带 key 走宽松配额。
这样"鉴权"和"面试官能直接试"两件事都不牺牲。

🔴 Review Focus 2：**两个入口必须共用同一个计数器** ——
否则刷的人换一个入口就绕过限额，限流形同虚设。
"""
import pytest

from atlas import guard


def _g(**kw):
    return guard.Guard(api_key="secret-key", **kw)


def test_anonymous_within_quota_is_allowed():
    v = _g(anon_daily=5).check(ip="1.2.3.4", api_key=None)
    assert v.allowed and v.tier == "anonymous"


def test_anonymous_over_quota_is_denied():
    g = _g(anon_daily=2)
    for _ in range(2):
        assert g.check(ip="1.2.3.4", api_key=None).allowed
    v = g.check(ip="1.2.3.4", api_key=None)
    assert not v.allowed and v.reason == "anon_quota"


def test_authenticated_tier_has_a_wider_limit():
    g = _g(anon_daily=1, auth_daily=5)
    for _ in range(5):
        assert g.check(ip="1.2.3.4", api_key="secret-key").allowed
    assert not g.check(ip="1.2.3.4", api_key="secret-key").allowed


def test_wrong_key_is_rejected_not_quietly_downgraded():
    """🔴 带了 key 但不对 → 401。**不能**悄悄降级成匿名放过去 ——
    那会让"带了错 key 的人"以为自己认证成功了。"""
    v = _g().check(ip="1.2.3.4", api_key="wrong")
    assert not v.allowed and v.reason == "bad_key"


def test_two_entries_share_one_counter():
    """🔴 Review Focus 2：两个入口各算一套的话，换个入口就能绕过限额。"""
    g = _g(anon_daily=2)
    assert g.check(ip="9.9.9.9", api_key=None, entry="retrieval").allowed
    assert g.check(ip="9.9.9.9", api_key=None, entry="orchestrate").allowed
    assert not g.check(ip="9.9.9.9", api_key=None, entry="retrieval").allowed, (
        "换回第一个入口又被放行了 —— 两个入口各算了一套计数器"
    )


def test_global_cap_stops_everyone():
    g = _g(anon_daily=99, auth_daily=99, global_cap=3)
    for _ in range(3):
        assert g.check(ip=f"10.0.0.{_}", api_key=None).allowed
    v = g.check(ip="10.0.0.99", api_key=None)
    assert not v.allowed and v.reason == "global_cap"


def test_different_ips_do_not_share_the_anon_counter():
    g = _g(anon_daily=1)
    assert g.check(ip="1.1.1.1", api_key=None).allowed
    assert g.check(ip="2.2.2.2", api_key=None).allowed


def test_no_configured_key_means_no_key_is_required():
    """没配 key 时，带不带 key 都不该报 401 —— 否则本地跑不起来。"""
    g = guard.Guard(api_key=None, anon_daily=1)
    assert g.check(ip="1.1.1.1", api_key=None).allowed
    assert g.check(ip="2.2.2.2", api_key="whatever").allowed
