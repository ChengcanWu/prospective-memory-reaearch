# PASK 笔记

> et al., arXiv:2604.08000 (2026) — *PASK: Toward Intent-Aware Proactive Agents with Long-Term Memory*

## 1. 要解决的问题

流式真实场景里，有用帮助往往来自**推断潜伏需求**并主动做事，而不是等用户把意图写全。纯被动问答 + 事后检索不够；还要在延迟与长程约束下做需求检测、记忆建模与主动执行。

**核心问题**：如何把「需求检测—记忆—主动智能体」串成可落地的流式范式，并在潜伏需求基准上验证？

## 2. 方法流程（完整工作流）

提出范式 **DD–MM–PAS**，并实例化为系统 **Pask**。

---

### 阶段 A：DD — Demand Detection（IntentFlow）

用流式 IntentFlow 模型从持续多模态/交互上下文中检测用户意图与潜伏需求（不仅显式指令）。

---

### 阶段 B：MM — Memory Modeling（三级混合记忆）

维护 **workspace / user / global** 三层长期记忆，支撑个性化与跨会话状态，供主动策略调用。

---

### 阶段 C：PAS — Proactive Agent System

后端池（VLM / ASR / LLM 等）在 IntentFlow 判定「该帮什么」后，真正用工具与专家策略把事做完。配套 **LatentNeeds-Bench** 评潜伏需求下的主动协助。

## 3. 达到的效果

报告在延迟约束下 IntentFlow 可具竞争力，且能抓到更隐式的需求；系统偏工程完整度与基准建设。

**与条件延迟记忆的关系**：同属「主动、意图、长程记忆」邻域，但主线是**潜伏需求检测与主动执行**，不是 PM-Bench 式「已宣布意图 + 时钟/事件 cue + due-set Set-F1」。可作主动助手相关工作，勿当作同构 PM 基准。
