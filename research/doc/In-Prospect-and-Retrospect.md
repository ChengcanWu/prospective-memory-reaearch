# In-Prospect-and-Retrospect 笔记

> Tan et al., ACL 2025 / arXiv:2503.08026 — *In Prospect and Retrospect: Reflective Memory Management for Long-term Personalized Dialogue Agents*

## 1. 要解决的问题

长程个性化对话依赖外部记忆，但常见两点失败：（1）记忆粒度死板，切不开自然语言话题结构；（2）检索策略固定，难随对话自适应。

**核心问题**：如何用「前瞻组织 + 回顾精炼」的反思式记忆管理，提升长程个性化检索与作答？

## 2. 方法流程（完整工作流）

提出 **RMM（Reflective Memory Management）**，两条反思主线。

---

### 阶段 A：Prospective Reflection（前瞻反思 / 写入侧）

把交互按 utterance / turn / session 多粒度动态摘要，写入个性化记忆库，专为**将来检索**服务——这里的 “prospective” 指「为将来回忆做组织」，**不是**「到点执行延迟动作」。

---

### 阶段 B：Retrospective Reflection（回顾反思 / 检索侧）

在线 RL：根据模型作答时引用了哪些证据，迭代 refining 检索器/置信，使检索贴合实际有用证据。

---

### 阶段 C：轻量重排

对 query–memory 嵌入做轻量 reranker，适配多样对话语境。

## 3. 达到的效果

LongMemEval 等上相对无记忆管理基线准确率可 **+10%** 量级；个性化对话指标优于若干 MemoryBank / LD-Agent 类基线。

**边界（对本主题很重要）**：名称含 Prospect/Retrospect，但优化目标仍是 \(sim(e,q)\) 式回顾检索质量，**不要求**在隐藏 cue 下触发动作集合、不算 Set-F1/due-set。入库作「命名相近、问题正交」对照，避免 Related Work 混谈。
