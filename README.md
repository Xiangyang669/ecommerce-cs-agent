# atlas

**一个服务，两个能力**：拿一份问题去**检索**，或者拿一位用户的话去**走一遍编排**。
两者都在同一个带**鉴权、限流、配额**的入口后面。

```
                       ┌──────────────────────────────────────┐
   鉴权 / IP 限流 / 配额 │               atlas                  │
        ──────────────▶ │                                      │
                       │  /retrieval/*   三层检索（向量·全文·图谱）│
                       │  /orchestrate/* 多 Agent 编排（LangGraph）│
                       └──────────────────────────────────────┘
```

## 它由三块构成，但只有一个入口

| 块 | 干什么 | 位置 |
|---|---|---|
| **检索内核** | 向量 / 全文 / 图谱三条通路并行召回，RRF 融合成一份排序 | [`packages/ragv1`](packages/ragv1) |
| **编排层** | 显式条件边状态图：分流 → 取证据 → 终判 → 回复或转人工 | [`packages/csagent`](packages/csagent) |
| **入口** | 装配上面两块 + 鉴权、限流、配额、统一错误 | [`apps/api`](apps/api) |

**编排层依赖检索层**，两处之间只隔一个窄接口 ——
`packages/csagent/csagent/adapters/ragv1_retriever.py`，整个仓库里**唯一**的跨包代码引用。

## 实测

三个包的测试在根目录一次跑完：

```
574 passed, 3 skipped
  324 检索内核 · 232 编排层 · 18 入口层     （3 条 skip 是需要真实引擎的冒烟测试）
```

容器起来之后，真跑出来的：

```
GET  /healthz            → {"assembled":{"retrieval":"ok","orchestrate":"ok"}}

POST /retrieval/search   → {"results":[{"chunk_id":"ddecd0ea…","sources":["graph","vector"],…}]}
                           两路同时命中

POST /orchestrate/ticket → {"route_taken":"ask_user","final_reply":"为了帮您查询，请提供订单号。",…}
                           回复是人话，不是 ID

响应头                    → x-ratelimit-remaining: 2 · x-ratelimit-tier: anonymous
```

## 怎么跑

```bash
pip install -r requirements.txt
cp .env.example .env          # 填 DEEPSEEK_API_KEY 与 SILICONFLOW_API_KEY
py -m pytest -q               # 574 passed

# 起服务（需要索引，见下）
docker compose up -d          # → http://localhost:8000
```

> ⚠️ **索引不在仓库里。** 检索那一半需要一份 96MB 的索引，它要用真实 embedding 现建：
> `py packages/ragv1/scripts/build_index.py`（会产生 API 费用）。
> compose 把宿主机上的 `../rag-v1/.indexes` 挂进容器 —— 换机器时改那个路径即可。
> **编排那一半不需要索引**，开箱即用。

## 三层检索：它怎么找

三条通路并行，各自的盲区不重叠：

| 问法 | 谁来答 | 别的路为什么不行 |
|---|---|---|
| 词面型（`requests.get` 怎么设超时） | 全文（SQLite FTS5 + BM25） | 向量分不清 `get` 与 `get_all` |
| 语义型（"怎么配置服务"，文档写 Configuration） | 向量（Chroma + bge-m3） | 精确匹配一个字都对不上 |
| 聚合型（这参数在哪些函数里出现过） | 图谱（标题层级 + 正文标识符） | 前两路只会返回孤立的块 |

融合用 **RRF**：只看排名、不看分数 —— 因为三路分数量纲完全不同（余弦 0~1 / BM25 负值 / 命中数）。

**评测**（错误注入 + 公开横评记录的真实 badcase）：检出率 **0.905**、精确率 **0.963**、干净表误报 **0**。
判据「融合要赢过最强单路」**没有通过** —— 根因定位在 `packages/ragv1/ACCEPTANCE.md`。
另有一次 rerank 对照实验，结论是**朴素重排为负收益**（`packages/ragv1/RERANK_AB.md`）。

## 多 Agent 编排：它怎么决定

```
用户消息 → 分流（唯一一处调 LLM） → ┬ 高风险 ────────────→ 转人工（不经过守卫）
                                    ├ 缺信息 → 追问（满 2 次转人工）
                                    ├ 知识子图 ┐
                                    └ 业务子图 ┴→ 终判守卫 → 证据够 → 回复
                                                              └ 不足/故障 → 转人工（真挂起）
```

两条设计要点：

- **路由不让模型自主决定。** 决定下一步的是一条纯函数，控制流可审计 ——
  出了错能说清是哪一步、按什么规则。
- **终判守卫是"证据检查员"，不是"该不该转人工检查员"。** 它只读 `faults_hit` / `evidence` /
  `business`，回答"查到的东西够不够、可不可信"，不回答"这条消息该不该交给人"。

**评测**（110 条逐条人工复核）：**软条款路由准确率 —— 规则版 0.000 / LLM 版 1.000**。
三条局限写在 `packages/csagent/ACCEPTANCE.md`（提示词在见过评测集之后改过所以 LLM 分数偏乐观等）。

## 鉴权与配额

| 轨道 | 怎么进 | 配额 |
|---|---|---|
| 匿名 | 什么都不带（演示要能被直接试） | 每 IP 每天 5 次 |
| 认证 | 带 `X-API-Key` 头 | 每天 200 次 |

三条决定：带了 key 但不对 → **401，不悄悄降级成匿名**；**两个入口共用同一个计数器**（否则换个入口就绕过限额）；
**配额在放行之前扣**（反过来等于给"调用失败"开了一条免费通道）。

`mount()` 进去的子应用会不会绕过中间件？**不会，而且是实测过的**，
见 `apps/api/tests/test_mounting.py`。

## 已知边界

- **索引不在仓库里**（96MB，且要用真 embedding 现建）→ 检索那一半不是 clone 就能跑
- **护栏是进程内内存 + 一把锁** → 多实例部署要换成共享存储
- **检索层不做生成**（它交出的是排好序的块，不是答案）；**编排层不做价值判断**（不替人决定该不该退款）
- 两块的细节边界各自写在包的 README 与 ACCEPTANCE 里

## 目录

```
packages/
├── ragv1/      检索内核（三路召回 + RRF + 评测）  · 含它自己的 README / ACCEPTANCE / RERANK_AB
└── csagent/    编排层（LangGraph 条件边 + 治理评测）· 含它自己的 README / ACCEPTANCE
apps/api/       入口（装配 + 鉴权 + 限流 + 统一错误）
docs/           装配验证记录 · 检索层的设计文档（specs / plans）
```

## 设计文档

- `docs/assembly-check.md` —— 装配验证：两个包怎么导入、哪一处是静默降级
- `docs/design/ragv1/` —— 检索层的设计 spec 与实施计划
