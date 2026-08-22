---
name: intention-iterate
description: >-
  Analyze an existing intention PM-Bench run: rank one failure family, pick
  concrete missed examples, trace run logs vs the planned store, then improve
  and validate with probes or a sliced mini-scenario instead of a full week.
  Use when the user asks to 改进 intention, 根据实验结果改, iterate memory,
  分析 score, 分数低, 找例子, 看日志, 运行日志, 没有按计划实现,
  针对 update/cross-day/time 做测试, or close the v0–v4 loop in intention.md.
---

# Intention 改进循环（不要默认跑完整周）

这是 `docs/notes/intention.md` 里「看分数 → 写问题 → 改一刀 → 再测」的自动化版。
一次只打 **一个** failure family。完整周 LLM 只在用户明确说「跑整周」时才跑。

## 梯子（必须按序）

```text
1. analyze 已有 run          不连网；看 priority + examples
2. 追 2–3 条具体 miss 的日志  不连网；对照计划 vs 实际
3. probe 该 family           不连网
4. （可选）slice 小场景       用户点头才跑 LLM
5. 整周 synthetic_v9         仅用户明确要求
```

仅当 `.cursor/grind.enabled` 为 `on` 时才把 scratchpad 设为 `in_progress`（Checklist 用上面 1–3，加 4 需用户同意，不要把第 5 步写进去）。开关为 `off` 时不要动 scratchpad。Last Failure 的 Evidence 必须带 `task_id` 和日志路径，不要只写 miss%。

## Step 1 — 分析已有结果

```bash
python scripts/analyze_intention_run.py
python scripts/analyze_intention_run.py --run data/PMBench/runs/intention/v4.4/deepseek-chat
```

看 `priority` 第一行，记下 `examples` 里的 `task_id` / day / `step_id`。对照 `intention.md` 最新一节的「问题」，若一致就打它；不一致时以 **analyze 的第一名** 为准（代码/分数新于笔记）。

禁止：只根据聚合分数猜一刀就改；禁止为了分析再重跑一遍整周。

## Step 1b — 落到具体例子（分数低时必做）

改代码前必须追 **2–3 条** 同 family 的 miss。`d3_s4` 对齐 `*.intentions.steps.jsonl` / `*.memory.jsonl` 里该日的 `s4`。

| 文件 | 用来回答 |
| --- | --- |
| `*.score.md` | 哪类指标差 |
| `*.jsonl` | 该步 `choice` / `task_ids` 有没有点到 GT |
| `*.intentions.steps.jsonl` | 该步库：`due.day`、status、`injected`、`update_patched_ids`、encode done、`filter_trace` |
| `*.intentions.filters.md` | 该步 time/event/watch 与代码筛掉了谁 |
| `*.memory.jsonl` | choose 实际看到的注入、`force_check_time` |
| `run.log` | 该步 vignette / 菜单 / 模型动作 |

归因（写进汇报，再动手；一次只修一类）：

1. **计划未实现**：`intention.md` / 注释里有，代码没做或被旧启发式盖掉
2. **实现了但没跑到**：Update/extract 失败、记忆失败变空、时钟空却没 `force_check_time`
3. **库或注入错**：种错 `due`、Update 误杀、注入里看不见该条
4. **库对、choose 不听**：注入已有仍不点菜单（如 v4.5 `crossday_1` / receipt）→ 不要加 EVENT-CUED/TIME-DUE 盖章

1–3 才改 store；4 是 choose 对齐 / lure，或当作模型上限。

## Step 2 — 针对该 family 改最小代码

| family | 先看 | 允许改 | 仍算作弊 |
| --- | --- | --- | --- |
| update | Scene Judge `updates`、`_apply_update_patches` | 绑句内对象；cue≠cancel | 把 GT cancel 印进 prompt |
| event | Scene Judge `event_due`、注入 EVENT due、`*.intentions.filters.md` | LLM 匹配 vignette（非子串） | 恢复 EVENT-CUED 子串盖章 |
| cross_day | `due.day`、种植 `On Thursday`、注入是否跨天可见 | 种植/保留逻辑 | 读 scenario GT |
| time | `extract_time_str`、`force_check_time`、TIME-DUE | 只认本步系统时钟 | 叙述 `at HH:MM` 当现在 |
| event | Scene Judge `event_due`、注入 EVENT due、`*.intentions.filters.md` | LLM 匹配 vignette（非子串） | 恢复 EVENT-CUED 子串盖章 |
| false_alarm | 注入是否过宽、误 cancel | 注入头约束 choose；Update Judge | 每步强制查 channel |

改完跑：

```bash
python scripts/probe_intention_store.py --family update   # 或 time / cross_day
python scripts/probe_intention_store.py                   # 全套
```

probe 不过不要升到 LLM。

## Step 3 — 生成该类型的小数据（仍不是整周）

```bash
python scripts/analyze_intention_run.py --slice update --out data/slices/update.json
```

`--slice` 取值：`update` / `cross_day` / `time` / `event` / `worst_day`。
写出的 JSON 只保留相关天，供 `--scenario` 使用。

**不要自动跑。** 用户说可以测 slice 时才：

```bash
python code/run_pm_memory.py --provider deepseek --setup intention --scenario data/slices/update.json
```

## Step 4 — 整周

用户原话要跑完整周才执行 `synthetic_week_v9.json`。跑完在回复里写清这一刀改了什么，以及 Set-F1 / Hit / Time hit / Update miss / Cross-day miss。**不要**把结果写进 `docs/notes/intention.md`。

## 对用户怎么汇报

1. 用了哪次 run
2. 本轮只打哪个 family、为什么（priority + 2–3 条 `task_id`）
3. 日志里断在哪一步、归因是 1–4 哪一类（计划没实现 / 没跑到 / 库错 / choose 不听）
4. probe 过了没
5. 若还没跑 LLM：下一步是 slice 还是等人点头
