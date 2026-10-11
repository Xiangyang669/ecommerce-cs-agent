# 装配验证（Task 1）

## 结论：两个包能在同一个进程里导入，且**用的是作品仓那一份 `ragv1`**

```
ragv1   ← D:\claude deepseek\rag-v1\ragv1\__init__.py      （作品仓，不是学习仓）
csagent ← D:\claude deepseek\cs-agent\csagent\__init__.py
```

工作区里有**两个** `ragv1`：`rag-v1/`（作品仓）与 `ai-agent-90days/rag_v1/`（学习仓）。
项目② 的适配器按**名字**导入，所以"用哪一份"必须由 `RAG_REPO` 显式决定 ——
`assemble.import_roots()` 的存在就是为了让这件事**一眼可见**，而不是靠 sys.path 的偶然顺序。

## 🔴 一处静默降级（必须显式盯住）

项目② 的适配器写的是：

```python
try:  # ragv1 未安装时仍然可用（只是没有真实检索能力）
    from ragv1.orchestration.supervisor import run_query as _ragv1_run_query
except ImportError:
    _ragv1_run_query = None
```

**导不到就悄悄变成「没有检索能力」，不报错。** 服务会看起来正常、但检索永远返回空。

所以 `assemble.adapter_query_fn()` 供上层**显式断言它不为 None** ——
`tests/test_assembly.py::test_adapter_really_found_ragv1_not_silently_none` 盯着这条。
