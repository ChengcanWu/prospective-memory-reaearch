总结：方法类文章大致可拆成下列模块（Benchmark / 协议 / 纯系统刻画不单列成新算法，但可挂在评测或工程侧）。

---

## 一. 原始信息 → 初步记录（先落成可读文本/片段）

1. **按属性标注后入账**：时间戳、人物、说话人、主题、态度等（A-Mem / AdaMem / RaMem 情节坐标 / ZEP 双时间轴）。
2. **直接分段**：按 turn、会话或固定窗切开。
3. **重叠切片**：窗与窗重叠，减轻边界丢上下文（E-mem / RaMem 滑窗抽取）。
4. **整段轨迹入库**：把(请求, 完成轨迹)或整次任务执行史当一条原始记忆（Memory Management / Memp / LongMemEval-V2 式 agent 轨迹）。
5. **文件系统落盘**：原始日志以文件读写动作写入外部目录（AutoMem）。

---

## 二. 初步记录 → 结构化 Memory

### 1. 层级 / 类型拆分

1.1 **低→中→高上涌**：Working → Episodic → Persona / 画像（AdaMem）；或 原文 → 类型化记录 → 主题轨迹 → 用户画像（NapMem 金字塔）。  
1.2 **情节缓冲 vs 主题巩固物理分开**：局部事件图攒够语义切换再写入全局主题网（GAM）。  
1.3 **短/中/长分库分查**（LightMem-SLM）；**树巩固时间、图管实体**（H-Mem）。  
1.4 **同级多类型**：情节(事实叙述) + 程序(方法流程)（PlugMem / ProcMEM Skill）；或（意图, 经验, 效用）（MemRL）；或（状态, 意图, 内容）类拆分。  
1.5 **压缩单元**：Gist→Fact（REMem）；事实框架 + 事实节点（SEEM）；Note–关键词–主题（MemFly）；abstract 块（Memora）。

### 2. 添加索引 / 把手

2.1 **摘要 / abstract / 极短助手摘要**（Memora / E-mem）。  
2.2 **嵌入向量**（几乎所有 RAG 系）。  
2.3 **关键词 / 符号 / 多视图**（Memora；SimpleMem 语义+词法+符号）。  
2.4 **实体–关系–Tag / Cue**（MRAgent / PlugMem / ZEP 社区）。  
2.5 **Handle / 分页指针**：满库时只留索引，用时回填正文（Demand-Paging）。  
2.6 **程序侧 k-v**：任务描述 → 可复用行动脚本（Memp / DuoMem 过程脚本）。

### 3. 构图与连边

3.1 **文本/语义相似度连邻居**（A-Mem；更新/调用联动邻居）。  
3.2 **索引/Cue/Tag 连线**（MRAgent；PlugMem）。  
3.3 **因果图 / 时序图**（AMA-Bench 因果；ZEP 双轴；H-Mem 混合树图）。  
3.4 **场景–角色档案**（CAST 场景聚合后人设绑定）。

### 4. 为 Memory 赋「价值 / 效用」

4.1 **可学习标量**：Q / v / 效用，随成败滑动更新（MemQ / AdMem / MemRL）。  
4.2 **Agent 或规则打分**：记忆质量评判、evaluator 过滤（Mem-α；Memory Management）。  
4.3 **过程清晰度信号**：信念熵惩罚糊摘要（MMPO）。  
4.4 **压缩/合并目标**：信息瓶颈下决定合并/链接/追加（MemFly）。

---

## 三. Memory 的更新与维护

1. **相似合并 / 冲突改写 / 删除**：相似 abstract 合并（Memora）；矛盾 DELETE、细化 UPDATE（Memory-R1 操作集）；失败改写 k-v（Memp）；AtomMem 原子 CRUD。  
2. **联动传播**：改一条更新邻居（A-Mem）；父辈 Q 按关系衰减（MemQ）。  
3. **上涌与衰减**：低级满上涌（AdaMem）；置信度随时间衰减（LightMem-SLM）；FIFO / 压力库容淘汰（Demand-Paging；Memory Management）。  
4. **删「害记忆」**：多次被检索却导致失败则剔除（Memory Management）。  
5. **脚手架级改结构**：元模型改 schema/prompt/动作词表，不只改单条内容（AutoMem 外环）。  
6. **技能池演进**：失败因果解释 → 改 Skill，门控验收后入库（ProcMEM）。

---

## 四. Memory 的检索

1. **向量 / 关键词 / 多路融合粗召回**（经典 RAG；E-mem 三路；SimpleMem 三路）。  
2. **条件 / 情境约束**：时间轴、人物、会话跨度等 tag 与语义联合排序，防情境坍塌（RaMem；ZEP）。  
3. **图/树导航**：Cue→Tag→Content（MRAgent）；主题自上而下再下钻（GAM / H-Mem / NapMem 工具导航）。  
4. **效用精排**：相似召回后再按 Q/v 选（MemRL / MemQ）。  
5. **主动 / 分步查**：推理逐步小查（Memory in the Loop）；记忆 Agent 决定是否注入提醒（Proactive-Memory-Agent）；不够则子查询迭代（E-mem / MemFly）。  
6. **意图定深度**：先判语义题还是程序题 / 要多深再取（PlugMem；SimpleMem Intent-Aware）。  
7. **搜索决策本身可学**：MCTS（MemCon / Memory-Tree-based）；工具动作 + RL（AgeMem / NapMem / AtomMem / UMA）。

---

## 五. 检索到 Memory 之后

1. **蒸馏 / 精选再答**：通读候选、按时间戳消歧、先列出有用记忆再输出短答（Memory-R1 Answer Agent）。  
2. **小模型精挑 / 置信度截断**（LightMem-SLM 两阶段）。  
3. **剪枝与一句话合成**（PlugMem）；**保留情境字段再生成**（RaMem）。  
4. **多助手局部推理再汇总**（E-mem）。  
5. **直接当程序执行**：激活 Skill / 复用行动脚本，而非仅当阅读材料（ProcMEM / Memp）。  
6. **反馈回写价值**：答对抬 Q、答错降 Q 或记反思（MemQ / AdMem / MemRL）；邻域题边际效用（UMEM）。

---

## 六. 训练范式（横切各模块）

1. **结果导向 RL**：PPO / GRPO，奖励看最终答对或任务成败（Memory-R1/R2、Mem-α、MemexRL、Fine-Mem、UMA、AgeMem 等）。  
2. **过程 / 稠密信号**：信念熵（MMPO）、逐步 Q&A（Memory-R2）、记忆质量与格式项（Mem-α）。  
3. **只训记忆、冻任务**：UMEM / AutoMem 记忆专精 / MemRL 冻骨干只更效用。  
4. **蒸馏到端侧**：DuoMem 上下文脚本 + LoRA。  
5. **基础设施**：MemFactory 模块化拼装 + 统一 GRPO；memorywire 跨框架协议。

---

## 七. Benchmark 在测什么（对照方法缺口）

| 侧重 | 代表 |
|---|---|
| 对话事实 / 多跳回忆 | LoCoMo 类；LMEB 四类嵌入 |
| 状态更新 / 自我进化 | EvoMemBench；STALE 隐含状态 |
| 记忆操作对不对 | MemOps |
| 前瞻触发 | PM-Bench |
| Agent–环境轨迹 / 因果 | AMA-Bench；LongMemEval-V2；MemoryArena；MemGym |
| 系统成本与部署 | Agent-Native；Systems-Characterization |

**一句话总览**：主流路线是「落盘 →（层级/图/程序）结构化 →（价值或 RL）学会写与查 → 精选或当技能执行」；分歧点在表示形态（扁平 vs 金字塔 vs 图 vs 文件系统）、决策交给规则还是 RL、以及评测是「记得住」还是「用记忆把后续任务做对」。


story:当前构建memory base，做action，都使用一套固定规则，难以cover现实中多样化问题
让agent自我进化：base构建，action选取，有一套自我进化流程
评测：在多种数据上表现优秀，说明：自进化适应能力极强

创新点
1--> memory base: 多维度，动态构图
2--> state, goal --> action：多维度


plan：
1. 先去总结：bench有哪几类
2. 思考memory base的构建，action构建