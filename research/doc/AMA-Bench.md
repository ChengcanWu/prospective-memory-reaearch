# AMA-Bench 笔记

> Zhao et al., arXiv:2602.22769 — *AMA-Bench: Evaluating Long-Horizon Memory for Agentic Applications*

## 1. 要解决的问题

现有记忆评测多围绕**对话式人机交互**（LoCoMo、LongMemEval、MemoryAgentBench 等）或**静态长文档**（RULER、LongBench），而真实 agent 的记忆是**agent–environment 连续交互流**：大量机器生成表示（JSON、代码块、ASCII 表）、**因果 grounded**（动作→隐状态转移→后续观测）、**客观信息密集**而非闲聊冗余。

在此 gap 下，对话-centric 记忆系统常在 agent 长程任务上**反而不如直接塞全长上下文**；损失性压缩 + 纯相似度检索会在多步中**误差累积**。需要专门评 agent 应用记忆的 benchmark，并给出与之匹配的 memory 设计。

**核心问题**：如何构建覆盖真实 agent 轨迹、可任意拉长 horizon、并诊断 Recall / 因果推理 / 状态更新 / 状态抽象四类能力的评测；以及如何设计不丢因果与客观信息的 memory 基线 **AMA-Agent**。

## 2. 方法流程（完整工作流）

AMA-Bench（Agent Memory with Any length）= **Real-world 子集** + **Synthetic 子集**，统一抽象为：交互历史 ht → **Build** 成外部记忆 mt → 对 query **Retrieve** 得 ct → 策略 π 生成回答。

---

### 部分 A：Benchmark 怎么建

#### A1. 问题形式与四类记忆能力

Agent 在 POMDP 里 reason-and-act，产生轨迹 `(x, a1, o1, …, ot)`。记忆系统两阶段：
- **Build**：ht → 结构化 mt（摘要、图、向量等）；
- **Retrieve**：(mt, q) → 查询相关上下文 ct。

对应三大机制、**四类评测维度**（Tab. 2）：
| 机制 | 能力 | 测什么 |
|------|------|--------|
| Memory Retrieval | **A. Recall** | 时间/顺序信息 |
| Memory Retrieval | **B. Causal Inference** | 动作前置条件、状态依赖 |
| Memory Evolution | **C. State Updating** | 显式/隐式状态变化跟踪 |
| Memory Condensation | **D. State Abstraction** | 去冗余且精确压缩 |

#### A2. Real-world 子集

从 **6 类代表 agent 域**  curated 长轨迹（Web、Open-world QA、Text2SQL、Software Engineering、Gaming、Embodied AI），共 **208** 条轨迹、**2496** QA（每条轨迹 **12** 题，覆盖四类能力）。

**轨迹来源**（黑盒：只有 action–observation log，无 backend 状态）：
- Embodied AI：ALFWorld（ALFRED 专家轨迹）等；
- Gaming：BALROG / LMGame-Bench；
- Web：WebArena + WebArena agent；
- SWE：SWE-bench Verified + OpenHands；
- Open-world Tool QA：GAIA + Co-Sight；
- Text2SQL：Spider 2.0-Snow + Spider2-Agent。

优先选**更长**轨迹并保持域内分布；研究生级标注者按统一 guideline 写 QA，**答案必须可由 log 中明确证据支撑**；第二人 cross-review sanity check。

平均约 **73** turns、**57.5K** tokens/轨迹，最长约 **997K** tokens（GAIA 域）。

#### A3. Synthetic 子集

可编程环境 + 全 MDP 访问，**任意拉长 horizon**：
1. **Environment Synthesis**：难度向量 φ + 随机种子生成 backend；潜状态 st 与转移 Pφ 可机器验证；调 φ（如 BabyAI 地图大小、指令链长度）系统放大上下文长度 L。
2. **Trajectory Synthesis**：在部分可观测下用最优策略 π* 生成 (at, ot)；可加 **Action Stochasticity ε**（偏离最优测鲁棒性）和 **Observation Verbosity γ**（同一状态多种符号渲染）。
3. **QA Synthesis**：锚定 backend 变量（st、Pφ 等）自动生成 golden QA。
4. **Needle 协议**：自动标注「回答所需最小 turn ID 集合」；可验证 needle，用于消融 construction vs retrieval 损失。

Synthetic 两环境：**BabyAI**、**TextWorld**；共 **1200** QA，按 **8K / 16K / 32K / 64K / 128K** 五档长度分层（每档 240 样本）。Synthetic 与 real-world 排名高度相关，可作高保真代理。

#### A4. 评测协议

- 指标：**Accuracy** + **F1**；正确性由 **Qwen3-32B LLM-as-judge** 判定。
- 对比三类基线：长上下文直接塞轨迹、RAG（BM25 / Qwen3-Emb / GraphRAG / HippoRAG2）、Agent Memory（MemGPT、Mem0、Mem-α、A-Mem、MemoryBank、MemoRAG 等 **15** 种）。

---

### 部分 B：AMA-Agent 基线方法工作流

动机来自 AMA-Bench 上三类发现：（1）多数 memory 系统常**输给** long-context baseline；（2）换 8B→32B backbone 提升很小，换 memory 架构方差大——**瓶颈在 memory 设计**；（3）BabyAI needle 消融：构造后 MemoryBank 等骤降 **41%+**，相似度检索 end-to-end 再降 **43%+**。

AMA-Agent 两核心机制：

#### B1. Memory Construction：Causality Graph（因果图）

把 agent 轨迹建成**因果图**，保留客观信息与显式依赖，而非 lossy NL 摘要或纯实体相似度图。

**三阶段**：
1. **局部解析**：对每个 timestep，解析相邻三元组 `(ot−1, at, ot)`，抽取环境/对象状态、状态间因果依赖、状态–对象关联；
2. **建边**：因果依赖 → **有向边**；关联 → **无向边**，连接状态节点；
3. **全局整合**：局部子图合并为全局 Causality Graph；节点映射到 embedding 空间（实验用 **Qwen3-4B-embedding**）以支持相似检索与关系推理。

#### B2. Memory Retrieval：Hybrid Tool-Augmented Retrieval（混合工具增强检索）

不 passive 相似度一把梭：

1. **初检索**：embedding 相似度取 top **K=5** 节点；
2. **自评**：判断证据是否足以答题；
3. **不足则选路由**：
   - **Graph node search tool**：深度可控的邻域遍历，聚合多跳上下文与因果链；
   - **Keyword search tool**：通过 tool 接口写脚本做程序化分析——精确 keyword 匹配、统计聚合（适合 JSON/代码等机器表示）；
4. **综合**检索到的证据生成最终回答。

评测 backbone 统一 **Qwen3-32B / Qwen3-8B**；AMA-Agent 图嵌入与 K=5 如上。

---

### 部分 C：一次完整 QA 评测怎么跑

1. 输入：某条 agent 轨迹（real 或 synthetic）+ 一道 memory-intensive QA（带类型 A/B/C/D）；
2. **Build 阶段**：AMA-Agent 用 Causality Graph 处理全长轨迹（或 baseline 各自 construction）；
3. **Retrieve + Answer**：对问题走 Tool-Augmented Retrieval（或 baseline 检索），拼上下文由 Qwen3-32B 作答；
4. **Judge**：LLM-as-judge 判 Acc/F1；可按 Recall / Causal Inference / State Updating / State Abstraction 分维汇总。

---

## 3. 达到的效果

- **Real-world（Qwen3-32B 控 backbone，Tab. 5）**：AMA-Agent 平均 Acc **0.5722**，Recall **0.6238**、Causal **0.6145**、State Updating **0.5305**、State Abstraction **0.4719**——四维均 SOTA；超最强 RAG HippoRAG2（**0.4480**）与最强 memory 方法 MemoRAG（**0.4606**）；较最强 memory 基线平均约 **+11.16%**（摘要/官网亦报 **57.22%** 平均准确率）。
- **Long-context 对照**：同 backbone 下 long context 仍强，但 AMA-Agent 在控变量比较中系统性优于结构化 memory + RAG 管线；GPT 5.2 全长上下文 real-world 平均约 **72.26%**，说明即 frontier 模型也未「 mastered」轨迹型 agent 记忆。
- **Synthetic  scaling**：8K→128K 长度上 AMA-Agent 维持高 Acc；long context 在 **32K 后**明显衰减；synthetic 与 real-world 方法排名高度一致。
- **消融（Tab. 6）**：去掉 Causality Graph 平均 **0.57→0.43（−24.6%）**；去掉 Tool-Augmented Retrieval **→0.44（−22.8%）**——**因果构图与工具检索缺一不可**。
- **诊断价值**：needle 协议量化 construction loss 与 retrieval loss；支撑「agent-centric memory 需保留因果与客观信息，而非对话式压缩+相似度检索」的结论。
