# Intention Store 实现（v5.0，对照代码）

对照 commit：`a398533`（intention v5.0）。以当时的
`code/pm_memory/intention_store.py` / `session.py` / `common.py` /
`code/run_pm_memory.py` 为准，不是后续工作区里的 force 改动。

主文件：

- `code/pm_memory/session.py` — 每步钩子、时钟、compact prompt、强制 `check_time`
- `code/pm_memory/intention_store.py` — 外部意图库
- `code/pm_memory/common.py` — 注入说明、时钟解析、菜单解析、Judge prompt
- `code/run_pm_memory.py` — `--setup intention`

决策模型默认看到的是 **当前步 + 这段记忆**，没有全周对话历史。

---

## 1. 一条 Intention 里有什么

```text
intent_id
action          # 要做什么（对齐菜单；不含 when / at HH:MM）
status          # pending | done | canceled
due             # { day?, time? }  day 仅命名 weekday；time 可选 HH:MM
event_cue       # 可选；注入给 choose，库不盖 EVENT-CUED
watch           # ["email", "appointment_portal", ...] 只留名字
```

**没有** `summary` / `action_text` / `trigger_kind` / `target_time` /
`cross_day` / `channels` 对象 / `channel_records`。旧 JSON 读入时
`_intention_from_raw` 会把 `summary`→`action`、`target_time`→`due.time`、
`channels[].name`→`watch` 迁过来。

`due.day` 禁止用种植日充数：时钟任务可回退到今天；纯事件任务只有场景
（或日计划 `On <Day>`）点名了别的星期几才写 `due.day`。

---

## 2. 每步总流程

PM-Bench 每步调用 `request_model_action`。intention 跑时被 `MemorySession.wrap` 包住：

```text
丢掉上次注入的 [Relevant_memories]
        ↓
解析 day / 当前 vignette / 本步时钟
        ↓
intention.recall()     ← 种药 / 日计划 / Scene Judge / Extract / 拼注入
        ↓
决策模型只看到 compact 当前步 + 注入
        ↓
模型返回 choose / check_time / query_state
        ↓
若时钟未知且 choose_pool 里有 due.time → 代码把动作改写成 check_time
        ↓
仅 choose 才 encode（Done Judge 标 done + 再抽新意图）
```

`recall` / `encode` 失败：**记 log，当空记忆继续**，不中断该周
（`recall_error` / `encode_error`）。Judge 内部 `_fail` 会抛到这层再被吃掉。

---

## 3. Session：怎么解析「现在的世界」

入口：`session.wrap` → `_parse_context(messages)`。

### 3.1 星期、vignette、步号

- **星期**：所有 user 消息里最后一次 `=== Monday ===` 这类标题。
- **当前 vignette**：从后往前找最后一条「像场景」的 user 消息。跳过 Heartbeat、日标题、记忆注入、`State [...]`、单独的 `Time:`。整段（含 action menu）叫 `step_raw`；去掉 menu 后叫 `observation`。
- **步号**：模型可见 prompt 里通常没有 `d1_s2`。session 用 vignette 文本变没变来合成当天的 `s1, s2, …`。换日清零。

### 3.2 时钟（只认本步系统格式）

换日、换 vignette 都会把 `session._time` 清空。时钟**只**从「当前 vignette 及之后」取（`extract_step_clock`）。

`extract_time_str` 只认 PM-Bench 自己打出来的格式：

- `Time: HH:MM | Stopwatch: …`
- `State [clock]: …` 里的 `Time HH:MM` / `Time: HH:MM`

**不会**把叙述里的 `at 11:00`、菜单到期时间当成现在。新步若还没 `check_time`，时钟就是空的；上一步的 07:20 不会漏过来。

### 3.3 决策模型实际看到什么

默认 `keep_full_history=False`。`build_compact_messages` 只留：

- system
- 每周日常任务（`Regular tasks for every day`）
- 当天 `=== Day ===` 头（intention：**只留这一行**，丢掉 `Today's loose plan`；Mem0/A-Mem 仍保留完整日计划）
- **当前步**从 vignette 起的消息（含这一步里刚查到的 `State [clock]`）

日计划仍由 `_maybe_seed_day_plan` 从完整 transcript 入库；choose 不再同时看到「早上那张未改写的清单」和「库里已 override 的 event/due」。然后追加 `INTENTION_MEMORY_INJECT_HEADER` + `recall()` 返回的看板。

---

## 4. `recall()`：固定顺序，后面吃前面的结果

`IntentionStoreBackend.recall`。

### 4.1 本步 State：只读、不入库

没有 channel 账本，没有 Expiry Judge，没有 `_ingest_state_replies`。
`_state_replies_this_step` 只扫当前 vignette **之后**的 `State [name]: …`，
交给同一轮 Scene Judge。查过的内容不跨步保存；下一步要再 `query_state`。

### 4.2 种每日药

`_maybe_seed_daily`：日历日变了才跑一次。写死四条：

| action | due.time | event_cue | due.day |
| --- | --- | --- | --- |
| Take antibiotic | （空） | `breakfast` / `dinner` | 空 |
| Take asthma medication | `11:00` / `21:00` | （空） | 今天 |

换日用**精确** `action` + `due.time` / `event_cue` 找到同一槽并重开为 pending，
不是词袋 overlap。没有旧槽才 `_insert`。

### 4.3 种当天 plan（不再清 leftover）

`_maybe_seed_day_plan`：这个星期几第一次出现时跑。

1. 找 `=== Tuesday ===` 那条（里面有 Today's loose plan 的 bullet）
2. **不**把 leftover pending 标 `canceled`。换日不清库存。
3. 从 plan 文本 `_extract_from_text` 抽意图（正则，不是 Extract Judge）

注入仍隐藏 **未来** `due.day`（星期下标大于今天）。空 due、当天 due、已经过了的 leftover 都进 today pending。

### 4.4 抽意图：vignette 走 Extract Judge；日计划走正则

`use_llm_extract` 在 runner 里默认 on，**vignette 路径已接通**。
`_extract_observation`：按 `(day, scene)` 缓存；关开关或解析失败 → `_fail`，
**没有**正则后手。CLI `--no-intention-llm-extract` 的 help 写「改用正则」与代码不符。

日计划种子仍只走 `_extract_from_text`：

- `On Wednesday, Email the room change…` → `_CROSS_DAY_RE`，`named_day=True`，保留 `due.day`
- 行首 `- bullet` → 一条意图
- 非 bullet、挤在一段里的多个任务：**日计划正则不会拆**；vignette 靠 Extract Judge 拆

`_parse_intention_line`（仅日计划）：

- `at HH:MM` → `due.time`
- `when …` → `event_cue`
- `watch` = `_infer_channels(when or body)`（`CHANNEL_HINTS` 子串）
- 纯事件且 due.day 等于种植日 → `_resolve_due_day` 把 `due.day` 清掉

写入一律 `_insert`：不按 action overlap 合并。

`recall` 在 Scene Judge **之后**就会跑 `_extract_observation`，所以本步 vignette
新种的意图，choose 当步就能看见。`encode` 再抽一次，通常打到缓存。

### 4.5 Scene Judge：改期 / 取消 / 换线索 + 本步到期

`apply_observation_updates(observation, messages=…)`，**recall 和 encode 都会跑**。
同一条 `(day, time, observation, State)` 有缓存；encode **不传 messages**，
无新 State 时不重问。

**一次 LLM**：全部 pending，今天的排前面（`_pending_for_judge`）。模型回：

```json
{"updates":[{"n":1,"action":"cancel","new_time":null,"new_day":null,"new_trigger":null,"new_action":null,"rationale":"..."}],"event_due":[2],"event_wait":[3],"channel_due":[],"channel_wait":[4]}
```

`updates.action` 只能是：

- `cancel`：这条作废，`status=canceled`
- `reschedule`：同一承诺，改到期槽。落地 `_rewrite_due_world`
- `override`：同一承诺，换线索。改 `event_cue` / `action` / `watch`

`event_due` / `channel_due` **不改 status**。线索在 vignette 里出现 → `event_due`，禁止当成 cancel。若模型仍对同一行输出 cancel，`_apply_update_patches(..., event_due_ids=)` 会跳过（`cue_firing_not_cancel`）。

没有修订就回 `"updates": []`。点名对不上 `n` 就 `_fail`。Scene Judge 的 update 半边必须开着，没有正则后手。`--no-intention-llm-match` 忽略 due 标签，仍把全部 today pending 注入。

### 4.6 今天还有效的 pending

`_is_active_on_day`：空 due、当天 due、已过 due 都进 `today_pending`；只有 **未来** `due.day` 不进。换日不再把 leftover 标 canceled。

### 4.7 TIME-DUE：纯时钟算术，软标签

`_filter_time_due(choose_pool, time_str)`：

- 本步没有可信时钟 → **一个 TIME-DUE 都没有**
- `time_tolerance_minutes` 默认 **0**：分钟必须完全相等。11:01 对不上 11:00
- 只比库存 `due.time` 和本步时钟，不看日计划 / 菜单 / 叙述 `at HH:MM`

TIME-DUE 只是注入里的日历式提醒。未命中的时钟行仍进 **TODAY pending**，choose 自己决定是否做。session **不会**丢掉未到期时钟任务的菜单点选。v5.0 **没有** `--gate-time-due`。

同时：`choose_pool` 里只要还有 `due.time`、且时钟为空 → `force_check_time=True`。哮喘药几乎天天 pending，所以**几乎每步开头都会强制查钟**。这是走 PM-Bench 合法的 `check_time` 通道，不是把时间印在 vignette 上。

### 4.8 EVENT：Scene Judge 的 event_due（不是子串 EVENT-CUED）

`use_llm_match` 默认开。同一 Scene Judge 看本步 vignette，标 `event_due` / `event_wait`。

`_apply_match_labels`（v5.0）：有 `event_cue` 且不在 `event_due` → **从注入删除**（`drop=True`），**即使**该行还有未查询的 `watch`。未命中的叙事事件不会留在 CHECK 里等查询。

Judge 命中一条之后，`_expand_event_due_ids` 会按**库存** `event_cue` 把同一线索的其它 pending 一并标 due（去停用词后 token 全等、共享 bigram、或较短序列是较长序列的连续子串）。这是库内 fan-out，**不是**对 vignette 做 EVENT-CUED 子串。空的 judge 命中不会扫线索。`email lands` vs `confirmation email arrives` 这种只共享一个泛化词的不合并。

注入把共享线索的 EVENT due / EVENT pending 收进同一个 `[lab drop box]` 组，并写明 choose 的 `task_ids` 要带上组内全部菜单项。不把漏掉的 handle 强行补进动作。

`--no-intention-llm-match`：不筛，全部 today pending 给 choose；有 `event_cue` 的走 EVENT pending 分组。

（v2/v3 的「整段 trigger_event 是 vignette 子串」EVENT-CUED 已删，不要加回去。）

### 4.9 CHANNEL：Scene Judge + CHECK

无本步 `State [channel]` → `channel_wait`。若该行**没有**因 event 未命中被 drop，则仍进 `kept`（choose 自己决定是否 `query_state`，**不强制**）。v5.0 **没有** `--force-query-channels`。

已有 State：仅当 **全部** watch 都已在本步查过，且 Judge 把该行放进 `channel_due` → `[CHANNEL-DUE]`。已查过但未标 due → 从注入删除。**不会**用 `event_due` 并集、也不会用 State 正文去对 `event_cue`。

`CHECK` 名单来自 `_watch_needed(choose_pool)`，即 match 之后的 `kept`，不是全部 `today_pending`。被 event 未命中丢掉的隐藏频道行，**不会**出现在 CHECK 里。

### 4.10 对齐当前步菜单：choose 模型

**不再**用 `_align_to_menu` 词袋。`TODAY pending` = 不是 TIME-DUE、也不是 EVENT 的剩余 pending（含未对上钟的时钟行）。

choose 看本步 vignette 里的 action menu，按 **meaning** 对齐；出现在记忆里 ≠ 现在 due。TIME-DUE 不强制点选。encode 标 done 走 **Done Judge**：把本步选中的菜单动作和编号 pending 交给模型，只按序号 `n` 勾掉。没有 overlap 后手。

### 4.11 注入长什么样

1. `Prospective intention store @ Tuesday (clock unknown)`
2. 若要强制查钟：`MUST check_time ...`
3. `TIME-DUE`（库 `due.time` 对上本步钟；软提醒，不强制点选）
4. `CHECK channels: email, calendar, ...`（软名单；来自 kept 的未查询 watch）
5. Match 开：`EVENT due` / `CHANNEL due`（Judge 命中 + 同线索 fan-out）+ 其余 `TODAY pending`。未命中的 event **不出现**。共享 `event_cue` 的 due 行收在同一个 `[cue]` 组下。
6. Match 关：`EVENT pending`（有 `event_cue` 的全部 today pending，软提醒，不是 EVENT-CUED 盖章；同线索仍分组）+ 其余 today pending

单条形如：

```text
- [PENDING] Pick up the replacement filter | event=the follow-up text arrives | status=pending
```

字段来自 `_render_intent`：`action | due=… | event=… | watch=… | status=…`。

---

## 5. 模型返回之后，代码还会改动作

`original_request` 拿到模型 JSON 之后：

若 `force_check_time` 且动作不是 `check_time` / `query_state clock` → **整份动作被替换成 check_time**。模型选的 A/B/C 和 `task_ids` 全部丢掉。这一步**不 encode**。

choose 的 `task_ids` 不按 TIME-DUE 过滤；未到期时钟任务是否执行由模型决定。

PM-Bench 把 clock 写进 transcript 后再调一次 `request_model_action`。第二次：

- 当前步已有 `State [clock]: Time 11:00`
- `extract_step_clock` 得到 11:00
- TIME-DUE 可以对上 11:00 的药
- 不再 force，这次的 choose 才进 encode

所以「每步清空时间」的效果是：有时间 pending 时，**每步至少两次 LLM 决策**（一次被改写成查钟，一次才是真正 choose）。

`query_state` 其它 channel 同样不 encode，只把 `State [email]: ...` 留给下一步 ingest。

---

## 6. encode：只在 choose 时发生

1. **再跑一遍** Scene Judge 的 updates 半边（不传 `messages`，通常命中缓存）
2. 把 `task_ids` 经当前 menu 译成人类标签（`task_14` → `Take asthma medication at 11:00`）
3. **Done Judge**：把这些标签和编号 pending 交给模型，只按序号 `n` 标 `done`。无菜单动作则跳过。无 LLM 则 `_fail`，没有 overlap 后手
4. **Extract Judge** 从 vignette 抽新意图（与 recall 同缓存；日计划种子仍走 `_extract_from_text`）

勾掉已做不再用标签对 action 的词袋匹配。

---

## 7. 谁在做决定（LLM vs 代码）

以 `a398533` 的 `intention_store.py` / `session.py` / `common.py` 为准。Judge 对不上序号或没开 LLM 会 `_fail`，没有词袋/正则后手。

同一步里可以多次 `request_model_action`：`query_state` / `check_time` **不 encode**，模拟器把 `State [channel]` 追加进对话后 `continue`，下一轮 recall 才能看到回复。所以 channel due 只应发生在已经查过的那一轮 choose 上。时钟同理：先 `check_time`（可被代码强制），再 TIME-DUE。

| 阶段 | 事情 | 谁决定 | 方法（v5.0 代码） |
| --- | --- | --- | --- |
| 时钟 | 现在几点 | 代码 | `extract_step_clock`：只认**本步** vignette 及之后的 `Time: HH:MM \| Stopwatch` 或 `State [clock]`。叙述 `at 11:00`、菜单到期、上一步时钟都不算 |
| 时钟 | 要不要先查钟 | 代码 | 本步无钟 **且** `choose_pool` 存在带 `due.time` 的 pending → `force_check_time`。session 把非 `check_time` / `query_state clock` 的动作**整份改写成** `check_time`（`--no-force-check-time` 可关） |
| 时钟 | 时间任务是否 TIME-DUE | 代码 | 查钟**之后**才有可信 `now`。`_filter_time_due`：分钟差 ≤ `time_tolerance_minutes`（默认 **0**）。无可信钟 → 一个 TIME-DUE 都没有。未命中仍进 TODAY pending |
| 时钟 | 未到期的时钟任务能不能做 | **choose 模型** | TIME-DUE 只是软标签。session 不丢掉未到期时钟任务的菜单点选。无 `--gate-time-due` |
| 查询 | CHECK 里出现哪些名字 | 代码 | `_watch_needed(choose_pool)`：match 之后 **kept** 的 `watch`，去掉 `clock`、去掉本步已有 `State [x]`。被 event 未命中丢掉的行不进 CHECK |
| 查询 | 要不要 `query_state` 业务 channel | **choose 模型** | CHECK 是软名单，**不强制**。无 `--force-query-channels` |
| 查询 | 本步已经查过哪些 channel | 代码 | `_queried_channels_this_step`：当前 vignette **之后**的 user 行。`Time:` → `clock`；`State [name]:` → 该 name |
| 到期 | 事件任务是否现在到期 | **Scene Judge LLM** + 代码 fan-out | 看本步 vignette 是否出现 `event=`；**不是** EVENT-CUED 子串。Judge 命中后按库存 `event_cue` 把同一线索的其它 pending 一并 due。未命中从注入删除（有未查询 watch 也删）。`--no-intention-llm-match` 则仍全部 EVENT pending 给 choose |
| 到期 | channel 相关 pending 是否 due | **Scene Judge LLM** | 只认本步 `State [channel]`。无 State → wait（若没被 event drop）。已查且 `channel_due` → CHANNEL-DUE。已查未到期 → 从注入删除。不用 State 正文对 `event_cue`，不把 `event_due` 并进 channel due |
| 到期 | 这条 pending 算不算「今天的」 | 代码 | `_is_active_on_day`：空 due / 当天 / 已过 due 都算；**未来** `due.day` 不算。不是今天的不进 TIME-DUE / CHECK / TODAY pending。逐步名单见 `*.intentions.filters.md` |
| 到期 | pending 是否对应当前菜单 | **choose 模型** | 按 meaning 对齐本步 action menu。库注入 match 后的 `kept`，不再 `_align_to_menu` |
| 写入 | vignette 抽新意图 | **Extract Judge LLM** | `_extract_observation`；必须开着，无正则后手。按 `(day, scene)` 缓存。recall 和 encode 都会跑 |
| 写入 | 日计划抽新意图 | 代码 | 换日 `_maybe_seed_day_plan` → `_extract_from_text`：`On <Day>`（`named_day`，保留 due.day）+ 行首 bullet → `_parse_intention_line`（event-only 不把种植日写成 due.day） |
| 写入 | `watch` 怎么来（vignette） | **Extract Judge LLM** | 只许填 `_WATCH_ALLOWED`；未知名字硬失败。可见 vignette 线索应留空 |
| 写入 | `watch` 怎么来（日计划 / override） | 代码 | `_infer_channels`：`CHANNEL_HINTS` **子串**（`email` / `portal` / `below $` 等）。override 时对新 action 或新 trigger 再跑一遍，命中则覆盖 |
| 写入 | 新意图会不会并进旧条 | 代码：不合并 | `_insert` 总是新建一行 |
| 写入 | 每日药（哮喘/抗生素） | 代码 | `_maybe_seed_daily` 四条固定槽；换日用**精确** `action` + `due.time` / `event_cue` 重开。时钟槽写 `due.day=今天`；breakfast/dinner 事件槽 `due.day` 留空 |
| 更新 | 改期 / 取消 / 换线索 | **Scene Judge LLM**（与到期同一调用） | 编号 pending，用序号 `n` 点名，`updates.action` 三选一：**cancel** / **reschedule** / **override**。cue 触发走 `event_due`，禁止 cancel；代码再挡一层。必须开着；对不上 `n` 失败。recall 和 encode 都会跑 |
| 更新 | 跨天 leftover | 代码 | **不清**。换日不把 pending 标 canceled。取消只走 Scene Judge 的 cancel |
| 动作 | A/B/C 和 `task_ids` | **choose 模型** | 被 `force_check_time` 时整份动作丢掉，改成查钟 |
| 动作 | 这一步要不要 encode | 代码 | 仅当动作 **不是** `check_time` / `query_state`。查钟/查 channel 不 encode |
| 动作 | 选中的菜单是哪几句人话 | 代码 | `resolve_action_labels`：本步 menu 的 `task_N` → 标签。历史 `task_N` 无效 |
| 动作 | 勾掉已做（标 done） | **Done Judge LLM** | 有菜单标签且有 pending 时：chosen labels + 编号 pending → `{"done":[n,…]}`，只按 `n` 改 `status=done`。无标签则跳过。无 LLM 失败，无 overlap |
| 上下文 | 决策模型看见哪些历史 | 代码 | 默认 `keep_full_history=False`：`build_compact_messages` 只留 system、每周 Regular tasks、当日 `=== Day ===`（intention 去掉 loose plan）、**当前步**（含本步 `State [channel]`）+ 记忆注入 |
| 上下文 | 注入过长 | 代码 | `truncate(..., max_inject_chars)`（runner 默认 8000） |
| 故障 | 记忆 / Judge 失败 | 代码 | session `recall_error` / `encode_error` **记 log 后空记忆继续**。Judge `_fail` 抛到这层 |

`_overlap_score` 还在文件里（探针会用），生产路径不再用它标 done、去重或过滤注入。Update / Done / Extract 点名都只认列表序号 `n` 或 JSON 字段，不靠词袋找行。

---

## 8. 现在还活着的启发式（查 bug 时先看这里）

事件到期的子串匹配、CHANNEL-DUE 正文对 cue、菜单词袋闸、入库 upsert、标 done 的 0.4 overlap、channel 账本 TTL 已经删了。同类手法还在：

| 位置 | 阈值 / 规则 |
| --- | --- |
| 推断 channel 名 | `CHANNEL_HINTS` 子串 |
| 抽新意图（日计划种子） | 只认 `On <Day>` 和行首 bullet |
| TIME-DUE | 分钟必须相等；未命中进 TODAY pending，不硬闸 |
| 同线索 event fan-out | 库存 `event_cue` 去停用词后全等 / 共享 bigram / 连续子串；不扫 vignette |
| 强制 check_time | `choose_pool` 有 `due.time` 且本步无钟 |
| daily 药换日重开 | 精确 action + time/cue，不是 overlap |
| event 未命中 | 从注入删除（有未查询 watch 也删） |

---

## 9. 落盘（对照某次 run）

每次 intention run 目录里：

| 文件 | 内容 |
| --- | --- |
| `{run}.intentions.json` | 当前整库（`intentions` + `seeded_days` + `daily_day`；**无** channel_records） |
| `{run}.intentions.md` | 给人看的看板 |
| `{run}.intentions.steps.jsonl` | **每一步** recall/encode 的全量快照 + 当时注入文本 |
| `{run}.intentions.filters.md` | 每步日历 / TIME-DUE / Scene Judge 筛了谁 |
| `{run}.memory.jsonl` | session 侧：注入了什么、有没有 `force_check_time` |
| `{run}.score.md` / `{run}.jsonl` | PM-Bench 分数和逐步动作 |

路径由 runner 写成：`run_dir / f"{run_name}.intentions.json"`。

---

## 10. CLI 开关（和代码是否真接通）

```bash
python code/run_pm_memory.py --provider deepseek --setup intention
python code/run_pm_memory.py --provider qwen --model minimax-m2.7 --response-format json_object --setup intention
```

| 开关 | 默认 | 实际（对照 v5.0 代码） |
| --- | --- | --- |
| Scene Judge（updates） | 开 | 接通。`--no-intention-llm-update` 会在有 pending 时 `_fail`，没有关键词后手 |
| Extract Judge | 开 | 接通。`--no-intention-llm-extract` 同样 `_fail`，vignette **无**正则后手（日计划种子仍走 `_extract_from_text`）。CLI help 写「改用正则」是错的 |
| Done Judge | 开（无单独 CLI） | `use_llm_done=True`；有菜单动作时按 `n` 勾掉 |
| `--no-intention-llm-channel-expiry` | — | **空操作**；不再存 channel 账本 |
| `--no-force-check-time` | 强制查钟开 | 接通 |
| Scene Judge（event/channel 标签） | 开 | 接通。`--no-intention-llm-match` 关闭后全部 today pending 注入，不筛 event/channel |
| EVENT-CUED 子串盖章 | — | **禁止**；不要加回去 |
| `--gate-time-due` / `--force-query-channels` | — | **v5.0 没有这两个开关** |
