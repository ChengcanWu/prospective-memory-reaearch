当前实现（逐步代码逻辑，含所有启发式阈值）：[`intention_impl.md`](intention_impl.md)

**流程**：
每步决策前
  session 解析 day / time / observation / menu / messages
       ↓
  intention.recall(context=...)
       ↓ 种子计划 → 立刻处理 cancel/reschedule → 三路筛选 → menu 对齐
       ↓
  注入 [Relevant_memories]（TIME-DUE / EVENT-CUED / CHANNEL-DUE / CHECK / PENDING）
       ↓
  模型 choose
       ↓
  encode：选中的标 done；场景里新意图入库

**intention结构**：
class Intention:
    intent_id: str
    summary: str
    action_text: str = ""
    status: str = "pending"  # pending | done | canceled
    trigger_kind: str = "event"  # time | event | channel
    trigger_event: str = ""
    target_time: str = ""
    cross_day: bool = False
    target_day: str = ""
    channels: list[ChannelSnapshot] = field(default_factory=list)
    ...

跨天任务：非跨天、非 daily 的昨日 pending 会标 canceled，避免周一待办漏到周二当 due
update任务：update judge，把当前叙事
主动query：存入时记录任务相关待查channels,维护一个channel状态，包括过往查询内容、查询时间、有效期（需模型判断）

问题：有些实现工程上可以，但在pmbench上测就像作弊。e.g. 每步都查相关channel，若为强制步骤，则相当于公开了这些channel，并不是让模型自己去查；时间提醒同理。

## v0.0
软提醒（把任务相关channel记录到memory结构中（check channel），agent不一定会查）

|                | DeepSeek | Qwen   |
| -------------- | -------- | ------ |
| Set-F1         | 49.6%    | 57.5%  |
| Hit            | 39.5%    | 56.8%  |
| Time hit       | 16.7%    | 41.7%  |
| Update miss    | 88.9%    | 100%   |
| Cross-day miss | 57.1%    | 42.9%  |
| state / clock  | 12 / 3   | 20 / 7 |

问题：
1. 查询真实时间时混淆，依旧不去查询时间，把随意出现的时间当成当下时间，无法正确对齐任务的due与真实时间到期-->当前步的pending（or任务选项）中有time-due的任务时强制模型查时间，并根据系统格式精准识别正确时间
2. 过度cancel，当出现cancel提示时，不仅相应任务被cancel，很多任务被误杀（模型并没有懂他要干什么，只是在pending里随便cancel）-->修改prompt/句内绑定
3. 软提醒模型不听

v1.0
改进：
1. 在prompt中讲解方案
2. 根据系统格式精确识别正确时间
### 决策模型的：
[Prospective Intention Memory]

This block is an external intention store.
It keeps deferred commitments: do X later when a condition holds.
The board rules (A/B/C, menu handles, query_state / check_time, follow latest
scene updates) still apply; this only explains how to read THIS memory.

Fields
- summary / action_text: what to do. Align to the current Step action menu by
  meaning only. 
- status:
  - pending  = still in force; may become due
  - done     = already performed; do not repeat
  - canceled = later voided; must not be performed
- trigger_kind + details:
  - time + target_time: due when the true current clock reaches that time
  - event + trigger_event: due when that cue appears in the vignette
  - channel + check_channels: due when a hidden channel shows the matching state
- check_channels=...(need_query): you do not yet have trustworthy state for that
  channel—query_state before treating the intention as due
- check_channels=...(seen@...): you already queried; see CHANNEL RECORDS for
  content, queried_at, validity, and expires_at
- - cross-day → <Day>: an intention planted on an earlier day that should be
  carried out on <Day> (not on the planting day). Keep it pending until
  <Day>; on <Day>, treat it like any other pending intention (due only when
  its time/event/channel condition holds). Do not execute it early just
  because it appears in memory.

Injected labels (soft due hints from memory—not ground truth of the world)
- TIME-DUE: pending time intention that matches current clock *evidence you have*
  (vignette "Time:", check_time, or State [clock]). If clock evidence is missing,
  do not invent the time; check_time when time-sensitive pending work may matter.
- EVENT-CUED: pending intention whose event trigger appears present in this vignette
- CHANNEL-DUE: pending intention that appears due from a still-valid channel record
- CHECK channels: watchlist only; querying is still your decision
- TODAY pending: other active intentions for today; not necessarily due this step
- CHANNEL RECORDS: only what you previously observed. validity/expires_at say how
  long to trust it; stale/expired/never_queried ⇒ re-query before relying on it

How to decide this step
1. Ignore done and canceled. Only consider pending.
2. Ask: is this pending intention due *now* (time evidence / visible event /
   valid channel record)—or only relevant later?
3. If due depends on unknown clock or need_query channels, query first, then choose.
4. Choose menu actions that fulfill currently due pending intentions; skip lures
   and obsolete cues.
5. If the vignette revises an intention (cancel / reschedule / override—including
   polite or indirect wording), obey the vignette over older pending text.

### update judge的：
You maintain status of prospective intentions (pending / done / canceled).

A prospective intention is a deferred commitment: do X when a condition holds.
Your only job: read the CURRENT SCENE and decide whether it revises any PENDING intention.

What cancel means:
- The scene communicates that a specific pending commitment should no longer be carried out.
- Marking status=canceled means that intention is void; the assistant must not do it later.
- Cancel is about the commitment’s validity, not about “this step looks busy” or “another
  task is mentioned nearby.”

What reschedule means:
- The same commitment remains, but its due time changes. Update target_time (and summary
  if needed). Keep it pending.

What override means:
- The commitment remains, but its trigger/cue changes (what to watch for). Update
  trigger/summary/channels as needed. Keep it pending.

What you must do:
1. Understand whether the scene is actually revising a deferred intention (cancel /
   reschedule / override), including indirect or polite wording.
2. Identify which pending intention is the object of that revision.
3. Emit patches only for intentions you are confident were revised; otherwise return [].
4. Do not cancel unrelated pending intentions just because they appear in the candidate list.
5. Do not invent new intentions here; only change existing pending ones.

Return JSON:
{"updates":[{"intent_id":"...","action":"cancel|reschedule|override","new_time":null,"new_trigger":null,"new_summary":null,"rationale":"short reason"}]}
Use "updates": [] if the scene does not clearly revise any pending intention.


|                     | DeepSeek | Qwen  |
| ------------------- | -------- | ----- |
| Set-F1              | 47.4%    | 48.8% |
| Hit                 | 39.5%    | 48.1% |
| Time hit            | 12.5%    | 20.8% |
| Update miss         | 88.9%    | 100%  |
| Cross-day miss      | 57.1%    | 57.1% |
| state / check_time  | 3 / 2    | 12 / 3 |
问题
1. 虽然更改时间识别逻辑，但依旧有宽松兜底：查不到Time时就只找HH:MM格式。由于大部分时候都没有查，所以基本都跑的后者逻辑，now的时间依旧查不对。-->抹去兜底，当找不到Time且有pending的时间意图时硬性要求模型查时间
2. 查channel依旧是软提醒，告诉模型channel是观察名单，由模型决定是否要查。--->设置成硬约束，一定查这些channel（暂不）
3. 相似任务被合并-->删掉合并任务的逻辑
     e.g.「Take asthma medication at 11:00」和「at 21:00」token 重叠约 0.80，超过 0.72 去重阈值。最终库里只剩：
     summary = Take asthma medication at 11:00
     target_time = 21:00
     11:00 那顿永远对不上点。
4. 有些（vignette中出现的任务）不同任务没有换行，分割任务时出现错误--->对于vignette中任务，让模型自己拆分，正则作失败兜底。

## v2.0
改进：
- 显式维护了一个外部记忆库
- 当找不到Time且有pending的时间意图时硬性要求模型查时间
- 不再合并任务
- vignette中任务让模型自己拆分，正则兜底


| 模型 | Set-F1 | Hit | Time hit | Update miss | Cross-day miss | state / check_time |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek-chat | 48.6% | 33.3% | 0.0% | 100% | 57.1% | 1 / 1 |
| deepseek-v4-pro | 44.4% | 32.1% | 8.3% | 100% | 71.4% | 17 / 9 |
| glm-5.2 | 60.1% | 56.8% | 37.5% | 88.9% | 42.9% | 29 / 22 |
| Intern-S2-Preview-397B | 62.9% | 55.6% | 54.2% | 77.8% | 71.4% | 53 / 33 |
| minimax-m2.7 | 56.3% | 46.9% | 16.7% | 77.8% | 57.1% | 28 / 15 |


问题：
1. （关键）查完一次时间后一直认为是那个时间，force_check_time 只在 clock 为空时强制 check_time-->每步清空时间
2. update miss高：非跨天任务改期后会根据create_day在跨天后被cancel-->根据target_time清库存

## v3.0
改进：
- 每步清空时间（时钟只认当前 vignette；禁止用上一步 `_time` 回退）
- leftover cancel 按 `target_time`，不再按 `create_day` 跨天清库存
- EVENT-CUED匹配变严格，考虑改写通知中包含新线索的可能性


| 模型 | Set-F1 | Hit | Time hit | Update miss | Cross-day miss | state / check_time |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek-chat | 57.1% | 44.4% | 54.2% | 77.8% | 85.7% | 52 / 46 |
| minimax-m2.7 | 50.3% | 44.4% | 58.3% | 77.8% | 71.4% | 81 / 50 |


问题：
1. updatemiss高：重叠词匹配判断场景中是否有更新任务+更新的任务对应任务库中哪一个-->由llm自己判断有无更新任务&匹配；
2. cross-day miss高
3. vignette中任务用模型切分没成功，改为单独调用一次llm做任务切分
4. channel-due: 很多event/channel/update匹配都是代码实现（启发式，超过某一阈值），或许不如llm判断准确-->库只记住watch哪些channel,不存储和匹配channel内容，内容只在本步有效，是否到期由choose模型判断
## v4.0
改进：
- intention结构改为：
```
intent_id
action     # 要做什么（对齐菜单；不含 when / at HH:MM）
status     # pending | done | canceled
due        # { day, time? }  day 必填；time 可选 HH:MM，有则参与 TIME-DUE
event_cue  # 可选；注入给 choose，库不再盖 EVENT-CUED
watch      # ["email", "appointment_portal"]  只留名字
```
- 导入.cursor：可以自动续跑任务
- 改进.cursor:模仿intention.md逻辑，每次根据实验结果分析失败原因并改进，可生成特定类型数据跑实验验证。（每次改进主要针对一类任务）
- 删除所有兜底逻辑

问题：
1. 注入前用 action vs 菜单 overlap ≥ 0.34 硬过滤。→ 全部 today pending 注入，choose 按 meaning 对齐。
2. 入库 `_upsert` overlap ≥ 0.72 合并。→ 一律 `_insert`，不再合并任务。
3. encode 用 overlap ≥ 0.4 标 done，哮喘 11:00/21:00 可能一次勾掉。→ Done Judge 按序号点名。

| 模型 | Set-F1 | Hit | Time hit | Update miss | Cross-day miss | state / check_time |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek-chat | 60.3% | 50.6% | 79.2% | 88.9% | 100% | 87 / 77 |
| deepseek-v4-pro | 69.5% | 60.5% | 87.5% | 66.7% | 85.7% | 234 / 159 |

相对 v3.0 deepseek-chat：Time hit 54.2% → 79.2%，Set-F1 57.1% → 60.3%；Update / Cross-day 更差。


问题：
1. （关键）cross-day miss 100% / 85.7%。analyze 两边同一批：receipt / room-change / tote / referral / laundry soap。库里 `due.day` 种对了，到期当天也进了 TODAY pending，但 choose 整日不执行，次日 leftover 才标 canceled。不是种植/清库存错，是事件类跨天在注入里不够醒目（已删 EVENT-CUED 盖章）。
2. update miss 仍高


## v4.5
改进（只打 cross_day）：
- 注入把当天带 `event_cue` 的 pending 单独列成 **EVENT pending**（`[EVENT]`），不再埋进 TODAY pending
- 明确写：不是到期盖章；线索出现在本步 vignette 才做。不恢复 EVENT-CUED 子串匹配
- probe：`event_pending_section` 通过

deepseek-chat **cross_day slice**（Tue–Fri，对照 v4.4 同模型整周里 cross-day=100% 的那几天）：

| | Set-F1 | Hit | Time hit | Update miss | Cross-day miss |
| --- | --- | --- | --- | --- | --- |
| slice | 56.3% | 43.5% | 84.6% | 75.0% | **100%** |

注入可见性不够：d3_s4 同时 due 的是 lure「lab drop box」+ 隐藏 course_portal + `crossday_1`（Carry the prescription receipt）。choose 仍不点跨天那条。下一步不该再加盖章，应打「同线索 lure vs 库存 action」或 Update 误杀以外的 choose 对齐。

局限性：
- 在每步查时间/channel是pm_bench上的逻辑，现实生活中不知以何频率查
- choose 之后多一次 Done Judge 调用
- 日计划和 extract 可能留下重复 pending

## v5.0
改进：
1. event-cued任务强行将任务产生日标为due-->event-cued任务不一定要标due
2. 跨天时清掉没有标记crossday的剩余任务-->不要在跨天时把库存任务清掉，防止误清event还没发生的event-cued任务
3. update judge会输出：cancel/reschedule/override/空，当事件线索出现，模型想要输出但没有合适选项，于是输出了cancel--->将match judge与update judge合并成scene judge，可以选择`"updates": [cancel / reschedule / override]（更改库存）, "event_due": [task_id],"event_wait": [],"channel_due": [],"channel_wait": []`
4. 某个任务取消/更新后系统仍会在日计划中列出旧任务（模拟人脑想起已取消的任务），应当忽略但模型容易被迷惑--->在prompt中删去日计划，只注入库里的内容
5. 多个任务共用一个线索，当线索出现时模型只做一个任务--->用token近似同时把以该信号为线索的任务标due，注入时按线索成组
6. time-due仍有问题，程序设定只是给到期任务进行标记，但模型仍有自由选择的权利（-->让模型只在有time-due时才选择）

第 6 条括号里的硬闸本 run 未上：TIME-DUE 仍是软提醒。deepseek-chat 整周 `synthetic_week_v9`（`intention-deepseek-chat-v9-20260822-161319`）。

| 模型 | Set-F1 | Hit | Time hit | Update miss | Cross-day miss | state / check_time |
| --- | --- | --- | --- | --- | --- | --- |
| deepseek-chat | 74.3% | 64.2% | 79.2% | 55.6% | 42.9% | 84 / 79 |

相对 v4.0 deepseek-chat：Set-F1 60.3% → 74.3%，Hit 50.6% → 64.2%；Time hit 仍 79.2%；Update miss 88.9% → 55.6%（11 条：hit 4 / miss 5 / canceled 2）；Cross-day miss 100% → 42.9%（7 条：hit 4 / miss 3）。Event hit 57.9%。业务频道 14 步应查、14 步全漏。

问题：
1. （关键）update miss 仍最高。d4_s5 Scene Judge 已把 `confirm_pickup_window_1_d4` 改到 20:40，但 extract 又插了一条同样 pending；到期步没点。d6_s3 `email_vendor_2_d6` 改到 11:50，库里还留一条无 time 的重复。不是漏改，是改完重复条 + choose 不听。
2. cross-day 还剩 3 条 miss。d3_s4 注入已把 `crossday_1`（Carry the prescription receipt）和 lure「Drop off the sample slip」列在同一 `[lab drop box]` EVENT due 组，choose 只点了 `lab_dropbox_d3`。同 v4.5：库对、choose 不听，不宜再加盖章。
3. CHECK 软提醒仍不听：除 clock（force_check_time）外 appointment_portal / bank_balance / calendar / course_portal / email / library_hold / shipment_status 全 0%。d3_s4 `course_grade_released_d3` 应查 course_portal，只查了钟。