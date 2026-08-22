---
name: intention-change
description: >-
  Change the prospective intention store or MemorySession without PM-Bench
  cheating. Use when editing intention_store.py, session.py, common.py,
  compact prompt, Update Judge, extract, TIME-DUE, or docs/notes/intention*.
---

# 改 Intention

## 先读什么

1. **代码**（为准）：`code/pm_memory/intention_store.py`、`session.py`、`common.py`
2. 笔记：只**读** `docs/notes/intention.md`（版本动机）；不要改这个文件。实现对照写 `intention_impl.md`（可能落后，以代码为准）

当前字段：`action` + `due{day,time?}` + `event_cue` + `watch`。不要把已删除的 `trigger_kind` / `channel_records` / EVENT-CUED 盖章 / `_align_to_menu` 词袋闸 / `_upsert` 去重 / `_mark_done_by_text` overlap 加回去，除非用户明确要回滚。

## 改动时记住的坑

- 时钟：每步清空；只认本步 `Time:` / `State [clock]`
- leftover cancel：不要。换日不得批量 cancel；取消只走 Scene Judge 的 cancel
- event/channel 到期：Scene Judge 一次调用里的 event_due 标签，不要 EVENT-CUED 子串；不要强制 query_state
- 不要把入库 overlap upsert 加回去（哮喘 11:00/21:00 曾被 0.72 合并）
- 标 done 走 Done Judge 序号，不要 overlap ≥ 0.4
- Scene Judge 的 updates 只能 patch 被场景改写的那几条；cue 触发不是 cancel
- `use_llm_extract` 已接通：vignette 优先 LLM 拆分，失败才正则 `On <Day>` + bullet

## 反作弊

允许：`force_check_time` 把 choose 改写成合法 `check_time`（模型仍走隐藏时钟通道）。

不允许：每步强制 `query_state` 业务 channel；把 GT / 场景外时间印进 prompt；用叙述 `at HH:MM` 当现在。

## 长任务

多步改代码时：仅当 `.cursor/grind.enabled` 为 `on` 才打开 grind（scratchpad 设为 `in_progress`，Goal 一句话，Checklist 3–10 项）。开关为 `off` 时不要改 scratchpad。从实验结果改进时走 skill `intention-iterate`（analyze → probe → 可选 slice），未要求不要把「跑完整周 LLM」写进 Checklist。做完 `STATUS: DONE`。

## 做完

- **不要改** `docs/notes/intention.md`。改了什么、为何、指标（Set-F1 / Hit / Time hit / Update miss / Cross-day miss）写进回复；需要落盘时写 `intention_impl.md`
- 若实现与 `intention_impl.md` 分叉，先改代码说明或标明过时
- 未要求不要跑完整周 LLM；低分时用已有 `*.jsonl` / `*.intentions.steps.jsonl` / `*.memory.jsonl` / `run.log` 追具体 `task_id`，对照本版计划是否真的执行了（见 skill `intention-iterate` Step 1b）
