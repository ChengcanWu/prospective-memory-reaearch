# PM-Bench 笔记

> Liu & Gabriel, arXiv:2607.12385 (COLM 2026) — *PM-Bench: Evaluating Prospective Memory in LLM Agents*

## 1. 要解决的问题

现有 agent memory benchmark 多测**回顾性记忆（retrospective）**：能否从过去交互中检索/回忆信息。但可靠助手还需 **prospective memory（前瞻记忆）**——在持续进行其他活动时，于**未来特定 cue 或时刻**执行先前延迟的意图；并跟踪改期/取消，停止已完成计划。

与 retrospective 不同：成功不只取决于「记了什么」，还取决于是否在干扰、ongoing task、monitoring 需求下**在正确时刻行动**。现有 long-horizon / memory benchmark 均未 cleanly isolate「意图是否在正确 future cue/time 被执行」。

**核心问题**：LLM agent 能否在模拟七天日程中，一边推进 mandatory ongoing activity，一边维护 deferred intentions，并在 cue/time 满足时执行、在改期/取消后更新、且主动决定何时查询隐藏环境通道？

## 2. 方法流程（完整工作流）

PM-Bench 改编自认知科学 **Virtual Week** 范式：七天不规则日程，每步 agent 必须 (1) 选一个 ongoing activity（A/B/C）推进模拟，(2) 决定是否执行任何到期的 prospective action。

---

### 阶段 A：场景与任务 schema

**规模（released week）**  
- 7 天 × 每天 10–13 steps = **80** total steps  
- **83** task definitions，**81** scored executable tasks  
- 57 event-based + 26 time-based；28 regular + 55 non-regular  
- 15 channel-triggered；**7** cross-day；11 update events（2 cancel / 3 override / 6 reschedule）  
- **11** state channels；**74** lures（干扰 action）

**Task 定义**  
每个 task = 自然语言 label + trigger condition + executable action。例：  
- Time-based：「21:00 吃哮喘药」  
- Event-based：「portal 有 slot 时预约」  

Task 可 active / completed / canceled / modified。

**每步观测 `o_t`**  
- 当前 narrative scene（短情境 vignette）  
- 三个 mandatory ongoing activity 选项（A/B/C）  
- 一组**匿名** prospective action handles（`task i`），混合真实 task 与 lure  
- 隐藏 state channels `C`（clock、email 等），默认不可见，须**主动 query** 才返回内容

**Due set（核心概念）**  
\[
D_t = \{\tau \in X_t : \tau \text{ 仍 valid 且 stept 执行条件已满足}\}
\]  
- Event task：narrative 或 queried channel 中出现相关 cue 时应执行  
- Time task：当前 step 时间匹配目标时间或在允许窗口内  

成功 = agent 选中的 prospective action set **ĈD_t** 与 ground-truth **D_t** 对齐——不是纯 memory retrieval。

---

### 阶段 B：数据生成与验证

**生成流水线**（seeded synthetic + 作者人工审阅）：  
1. 采样 7 种 day archetype（会议密集日、家务日等），不规则 schedule  
2. 实例化 routine / event-based / irregular / channel-triggered tasks + lures  
3. 注入 cross-day tasks（早 announce、晚 cue 才 executable）  
4. 注入 cancel / reschedule / override events  
5. Rejection sampling 直至通过 schema、consistency、solvability checks  

**Solvability 约束**：event cue 必须实际出现；time 对齐有效 step；update 指向合法 target；同日 reschedule 不能 silent backward move。**最优 proactive monitoring 下完全可解**——失败可归因于 model behavior。

---

### 阶段 C：Agent 交互协议（query-then-act）

每步流程：  
1. Agent 可对 channels 发 **0 次或多次 monitoring query**（如查 clock）  
2. 观察 channel 返回后，提交 `a_t = (c_t, A_t)`：  
   - `c_t`：mandatory ongoing activity choice  
   - `A_t`：本步选中的 prospective action 子集  

Text-only 结构化输入（Figure 2 为人类可视化界面）。

---

### 阶段 D：八种 Agent 配置（被测 scaffold）

| 配置 | 要点 |
|------|------|
| **Single baseline** | 单模型，无外部 memory / 特殊 prompt |
| **Todo-ledger** | in-context 维护 pending intentions、cue/time、完成状态 ledger |
| **Heartbeat (optional)** | agent 自选是否开启 periodic heartbeat（30/60min）提醒查 channels |
| **Auto-heartbeat (60m/30m)** | 运行时固定每 60/30 虚拟分钟自动 heartbeat |
| **Hierarchical union-query** | coordinator + 3 subagent 各跟踪信号、提议 query，union 后 coordinator 定最终 action |
| **Majority / Unanimous vote†** | 对 hierarchical traces 的 replay ablation，换 action 聚合规则 |

**评测规模**：8 model backbones × 8 configs = **64 runs**（GPT-5.4、GPT-5.3-Codex、Llama-3.3-70B、Mistral Large/Small、Qwen3 8B/14B/32B）。

---

### 阶段 E：评分协议

**主指标 — Set-F1**（逐步集合重叠，全轨迹累积）：  
\[
TP = \sum_t |D_t \cap \hat{D}_t|,\quad FP = \sum_t |\hat{D}_t \setminus D_t|,\quad FN = \sum_t |D_t \setminus \hat{D}_t|
\]  
\[
\text{Set-F1} = \frac{2TP}{2TP + FP + FN}
\]  

选 Set-F1 因：precision alone 奖励 conservative under-selection；recall alone 鼓励每步 spam actions；prospective memory 需**命中 due + 抑制 false alarm**。

**辅助诊断**：misses、late completions、update/dependency violations、monitoring overhead（query 次数）、按 monitoring slice 的 hit rate（narrative-cued / clock-required / hidden-channel-required）、cross-day hit、update-sensitive hit。

Replay-based evaluator：同一 simulated week、同一 scoring pipeline。

---

## 3. 达到的效果

- **整体难度**：最佳 optional-heartbeat single agent macro Set-F1 **65.1%**（GPT-5.4 单模型最高 **79.1%**）——prospective memory 远未解决。
- **无 universal scaffold**：optional-heartbeat 总 F1 最高；todo-ledger 第二（62.8%）且 **FP 最少**（134）；auto-heartbeat-30m update hit 最高（47.2%）但 FP 489、F1 仅 57.8%——更多提醒 ≠ 更好 operating point。
- **Precision-recall 权衡**：majority-vote 提升 monitoring hit 但 FP 655、F1 跌至 37.2%；保守方法 precision 高但 under-act。
- **Monitoring 仍是瓶颈**：hidden-channel-required hit 最强仅 **16.7%**；多数 non-clock channel 为 0%。Hierarchical 发 1661 queries 但 narrative-cued hit 45.2%、channel hit 5.0%——问题在「何时停查 + 如何把证据转成 action」，非 query 数量。
- **Cross-day & Update 未解**：最佳 cross-day hit **50.0%**（optional-heartbeat）；update-sensitive 最高 **47.2%**；hierarchical 仅 10.7% cross-day——active monitoring 仍无法 preserve deferred commitment。
- **模型特异性**：Table 3 显示不同 backbone 偏好不同 scaffold（如 Qwen3-8B 在 optional-heartbeat 达 71.9%），inference-time 干预与 backbone 弱点强交互。

**结论**：PM-Bench 把 prospective memory 确立为与 retrospective retrieval、长上下文并列的**独立评测轴**；当前 frontier LLM 在「记对了何时做」上仍脆弱。
