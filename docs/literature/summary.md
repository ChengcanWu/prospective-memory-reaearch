（用一对 * 括住名称表示 Benchmark / 评测研究，如 *AMA-Bench*）

## 条件延迟 / 前瞻记忆专题（近一年补搜，2025–2026）

> 论文笔记见 `docs/literature/notes/`，PDF 见 `docs/literature/papers/read/`。

*PM-Bench*：Virtual Week 式七天日程，测 LLM agent 延迟意图、隐藏通道监控与改期取消；八脚手架最佳约 65.1% Set-F1。

*TriggerBench*：1265 题五维 PM 基准（状态/时间/逻辑/注意/安全编码），配 Neg/Overload 与同上下文 RM 对照；PM≪RM，隐式约束与并发干扰极脆。

PM-Failures-Mittal：TrustNLP 2026，负载下格式约束遵从掉 2–21%，salience 提醒可挽回——前瞻类比旁证，非日程协议。

In-Prospect-and-Retrospect：ACL 2025 RMM（多粒度摘要 + 检索 RL）；名称含 prospect，实为回顾检索，非 when-to-act。

PASK：流式主动助手 DD–MM–PAS + LatentNeeds-Bench；潜伏需求主动帮，与「已声明意图的条件触发」相邻。

---

A-Mem：按时间戳设定知识单元，并按语义相似度预先链接邻居；更新一条知识后，会联动更新邻居知识，调用某条知识时，也会顺带调用邻居知识。

AdaMem：每条知识设定「主题、态度、原因、事实片段、属性、时间戳、说话人身份」等属性，设立 FIFO 栈更新知识，并且由低级→高级设置 Working → Episodic consolidation → Persona；低级知识满后，不断向上涌入并更新至更高级知识。

AdMem：提取当前任务流中「上下文(c)+动作+期望+检索到的 Memory(m)」，之后评估 Memory 是否帮忙完成了期望；Memory 初始化分数 v，与上下文的联系 sim(c,m)，用二者共同刻画 m 在此轮的重要性，再按任务是否成功完成的布尔奖励滑动更新 v。

AgeMem：设定 LTM & STM 相关的多类记忆工具动作（存、取、更新、摘要、过滤、丢弃等），把记忆管理直接写进 Agent 策略；采用三阶段渐进训练，并用逐步 GRPO 把终局任务奖励回传到中间记忆决策上，学习何时该写、何时该压上下文。

*Agent-Memory-Systems-Characterization*：系统刻画文（非新算法），把十类记忆按长上下文、扁平检索、结构增强与智能体控制流等轴归类，相感知剖析构建、检索、生成三相的延迟、能量与存储；在长记忆基准与多会话场景上实测，给出选型、嵌入分流、新鲜度约束与尾延迟封顶等部署建议。

*Agent-Native-Memory-System*：把记忆系统拆解为存储、抽取、检索、维护四个模块，在统一工作负载下做端到端与模块消融，比较不同架构在证据保真、冲突更新、长程稳定性以及索引构建/查询延迟等系统指标上的表现，找出哪一环拖垮整体。

*AMA-Bench*：建 Causality Graph（因果图）：每个 timestep 解析(观测前, 动作, 观测后)，抽状态、因果依赖、对象关联，整合成全局有向/无向图；Bench 面向 agent–环境轨迹而非纯闲聊，类似游戏推理数据集，并配套因果图 + 工具增强检索的 AMA-Agent 基线。

APEX-EM：技术新意有限，更多是 prompt 流程，流程也很普通：规划/检索/生成/迭代/更新入库（PRGII），成功与失败经验分别作为正负例写入结构化程序性–情节经验库，再用语义+结构签名等混合检索复用。

AtomMem：把记忆管理拆成增删改查（Create/Read/Update/Delete）原子动作，与环境动作同轨迹决策；每步可强制维护草稿本以保全局状态，再按需语义检索若干条；先 SFT 学调用格式与基本模式，再用终局答题对错做 GRPO，把优势摊到记忆操作 token 上，端到端学「何时写、改、删、读」。

AutoMem：把记忆提升为与任务动作同一动作空间的文件系统读写（读/写/搜/追加）；每步先根据环境反馈决定是否落盘，再搜索/阅读相关文件后才提交世界动作。外环用强模型读完整局轨迹，迭代改脚手架（prompt、文件 schema、动作词表），固定种子上进度提升才保留；脚手架到位后，只挑自身「好记忆决策」片段做轻量微调，训出记忆专精副本，任务动作骨干冻结不动。

CAST：对话分段，把时空动作相近的段落聚合成场景，再按场景为每个人建角色档案；所有场景信息处理为两个版本：三元组版本（擅长逻辑链构建）与文本段落版本（上下文更丰富）。查询时按对应角色查档案从而定位场景，同时查询三元组版本和文本段落版本并融合。

Demand-Paging Memory Hierarchy：把存储满的记忆按 FIFO 顺序转变为 handle（只留索引把手），之后需要某记忆时，再按照索引去提取对应长文本内容，类似操作系统需求分页，在有限上下文预算下扩容可寻址记忆。

DuoMem：面向端侧小模型的双空间蒸馏——上下文侧检索并注入教师写好的过程脚本，替换学生自写的差记忆；参数侧用教师成功轨迹训轻量 LoRA，学习逐步动作与工具使用。在线时拼教师侧程序性记忆，再由「基座+适配器」与环境交互，以极少额外参数与较小记忆体积逼近大教师成功率，同时加快推理。

E-mem(ICML 2026)：长对话切成带重叠的片段，每个片段配一个「助手 Agent」独立保管，并生成一段极短摘要；查询时，主控 Agent 先用摘要+向量+关键词三路并行粗筛，选取 top 助手，让每个助手局部推理后再上报精炼证据，最后主控汇总证据生成答案；如果信息不足，主控还能生成子查询，再次迭代推理。

*EvoMemBench*：数据集更偏向于：状态更新后，Agent 能否及时更新记忆、在跨 episode 交互中自我进化；同时覆盖 episode 内/外 × 知识/执行等维度，强调持续改记忆而不只是静态回忆。

Fine-Mem：奖励函数设计为：每隔一段交互去提问题检验并给得分，再把得分归功到轨迹中每一步记忆操作的贡献；据此用 GRPO 训练记忆相关策略，让中间写/改记忆也能拿到稠密反馈。

GAM：活跃对话只写入本地事件进展图做情节缓冲，话题边界清晰或缓冲溢出时才巩固成主题节点，挂入全局主题关联网，用「写隔离」减少短暂噪声污染旧知识；检索时先锚定主题并扩展邻居，再下钻归档事件，按时间、角色与置信度等乘性重排后生成。训练免费、偏工程架构。

H-Mem：离线自底向上建时间–语义树：短时事件按窗口相似度合并、向上合成更长时摘要，同时构建实体关系图与实体档案；在线问答先拆子问题并标定偏短时还是长时范围，再在图上扩展实体、在树上自底向上取证，按语义、时间与巩固稳健性综合打分，证据不足还可带着锚点再补一轮缺口查询。

LightMem-SLM：短/中/长记忆分开存、分开查、分开维护，用 Controller 做检索规划、用两阶段检索控成本（RAG 先选出候选，结合置信度排序，小模型再精挑细选）；知识库条目按照时间推移进行置信度衰减，平衡新鲜度与噪声。

*LMEB*：分成情景、对话、语义、程序四大类测试记忆嵌入与检索，评测面较全，但对记忆系统架构本身无本质改进，更像表示/检索基准。

*LongMemEval-V2*：数据升级为：Agent 在 WebArena 等真实网站环境中执行任务时留下的成百上千条、含错率高的操作轨迹；测试的是记忆系统能否从这些轨迹里像资深同事一样「悟」出环境特有的布局、工作流、坑点、错误前提等隐性经验，而不仅仅是记住某句话。

Mem-α：把最终正确性、调用工具格式是否合法、Token 数量、记忆质量（由 Agent 评判）等项加权算成奖励，再用 GRPO 训练记忆相关策略，在效果与成本、格式合规之间折中。

MemCon：有决策、有状态（当前任务状态；记忆状态），之后使用 MCTS 搜索算法（经典 UCB 作为决策指标）在记忆操作空间里搜「下一步该怎么改/用记忆」，把记忆管理当成可搜索的序贯决策。

MemexRL：和 Mem-α 基本相同，把「记忆质量（Agent 评判）」一项改成了「调用工具的多样性奖励」，再用 GRPO 训练，鼓励更丰富的工具–记忆配合而非单一套路。

MemFactory：Memory-RL 的乐高式基建，把抽取、更新、检索（以及端到端循环记忆模块）做成可插拔组件，再拼成 Agent；环境统一吐出格式与判分等多维奖励，Trainer 原生接 GRPO 更新记忆策略权重；开箱可对齐 Memory-R1、RMM、MemAgent 等主流工作流，降低换模块与复现成本。

MemFly：新交互先收成带原文、去噪句、向量与关键词的 Note；在局部邻域上评估冗余与互补，再择一执行合并、建边或追加，并叠成 Note–关键词–主题三层图；答题时走主题宏观导航、关键词微观锚定与边扩展三通路融合，证据不足则生成子查询迭代补证，用信息瓶颈思想平衡压缩与保真。

*MemGround*：类似的逻辑推理游戏式 Benchmark，考验在资源有限设定下，推理能力与记忆资源分配能否配合完成任务。

*MemGym*：长程记忆评测场，把对话工具用、深度检索、编码、网页操作等多轨统一到「先压缩/检索再推理」的同一接口；固定推理模型，成对跑「有记忆 / 无记忆」算增益，从而隔离记忆贡献。自建合成轨迹专门堵住环境捷径与预训练捷径；另训轻量 MemRM，用压缩前后上下文预测行为是否不变，替代昂贵整段环境回放做内环迭代。

*MemOps*：依旧偏逻辑/对话推理，不过同时检测 Agent 对于记忆生命周期中间每一步操作（该不该写、改谁、改成什么、证据是否支撑）的正确性，不只看最终答案对不对。

Memora(ICML 2026)：先记录所有的 Memory，然后分块，每一块提取为一个小的 abstract；若库中有相似 abstract，则合并，否则给新来的 abstract 添加检索 keywords；最后用户提问 query，根据 keywords 对应 abstract，再对应详细的 Memory 实现记忆检索。

*MemoryArena*：统一评测场（非新记忆算法），把记忆、Agent、环境串成多会话闭环——每会话先检索再行动，结束后把轨迹写入持久记忆，再带入下一欠指定、相互依赖的子任务；覆盖网购约束、递进检索、群体出行规划、形式推理等人工题；用整任务成功率、子任务进度与深度衰减曲线，检验「回忆成功」是否真能支撑跨会话决策。

Memory in the Loop：主张让 Agent 在推理的每一步都「随手查记忆」，而不是开场一次性灌入大量候选；实验证明一次性查完大量记忆，在效果和成本上往往不如多次查询、每次只查少量记忆。

Memory Management(ACL 2026)：把(请求，完成轨迹)定义为一条 memory，运行时使用 GPT 作为 evaluator 过滤 memory；同时删除多次被检索且导致任务失败的 memory。测试时没有只卷榜，而是采用压力测试：为 memory 加噪声，并在有限存储空间中存 memory，看系统是否稳健。

Memory-R1：使用 RL 训练两个模块：Memory Manager 学习对记忆做 ADD/UPDATE/DELETE/NOOP 等管理操作；Answer Agent 学习从检索到的大量候选里做记忆蒸馏筛选，再据此回答。两边都用最终答案是否匹配标准答案作为奖励（PPO/GRPO），监督极少。

Memory-R2：将训练过程细分——R1 往往按一条完整对话的正确与否训练，R2 将对话分为若干个 session，每个 session 都有对应的 Q&A 来判断正确性，从而给记忆管理更细粒度的训练信号。

Memory-Tree-based：Builder 负责将原始 memory 总结成条目并在 query 到来时挑选；Summarizer 负责将 Builder 构建的条目挑选并总结成高层摘要，Agent 再到摘要上采样进行回答。构建一个深度为 3 的采样树，之后使用 MCTS 树搜索，同时用 GRPO 训练相关策略。

memorywire：定义了一套标准化协议，让不同记忆框架（mem0、Letta、Cognee 等）可以说同一种语言、互相切换、统一治理，偏互操作与工程治理而非单一新算法。

Memp(ACL 2026 Findings)：把历史完成的任务总结成 k-v（描述–行动内容），然后对 query 做 embedding 后对 k 进行 RAG；k-v 更新方式：若行动失败，根据失败轨迹对原来的 k-v 进行修改，使程序性经验可纠错迭代。

MemQ：每个 Memory 设置 Q 值（代表记忆质量，初始值随机）。假设当前已有 Memory & query：若 query 回答失败：记录反思 memory，并降低调用 Memory 的 Q 值，以及它们父辈的 Q 值（按关系远近衰减）；若 query 回答成功：把回答流程创建一个 Memory，Q 值为父 Memory（解决 query 所调用的 Memory）的平均，并增加调用 Memory 的 Q 值，以及它们父辈的 Q 值（按关系远近衰减）。

MemRL：记忆是三元组(意图 z, 经验 e, 效用 Q)：检索时先按意图/经验相似度召回候选，再按效用 Q 精选真正有用的经验；骨干模型冻结，环境奖励持续更新各条记忆的 Q，实现部署后仍可塑的运行时学习。

MMPO：每步完成后，问 LLM 一个固定锚定问题：「基于当前记忆，任务进度如何？还缺什么信息？」看回答的 token 概率熵；实验验证失败轨迹熵往往更高。仍用 RL 训记忆/摘要策略，但额外把「信念熵」做成稠密过程奖励，惩罚让模型更糊涂的中间摘要。

MRAgent(ICML 2026)：Memory 里面提出一些 Content 作为节点，Content 里面归纳出 Cue（如：实体，属性，动作…），Cue 给 Content 连线，线上标 Tag（该 Cue 与该 Content 的关系）。query 里面找 Cue，之后结合 LLM 推理出 Tag，找到对应 Content，同时阅读 Content 补充 Cue、Tag，形成可扩展的线索–内容图检索。

NapMem：按用户自底向上建多粒度记忆金字塔——原始对话、类型化记录（事实/事件/指令/偏好）、主题轨迹、用户画像，层间用溯源关系相连，可上钻摘要也可下钻原文；推理时把检索改成一组记忆工具（按层 search/get/读文件），Agent 按查询与中间证据主动选粒度并决定何时停手；再用 GRPO 学导航策略，奖励兼顾格式、答对与合理用工具。

PlugMem：每条 Memory 结构化成情节记忆（一些事实叙述）、程序记忆（解决方案的流程），并设计 Tag 与它们连线。Query 到来时，LLM 判断偏语义（事实查询）还是程序（如订票步骤），提取对应 Tag，根据 Tag 连线去搜索更多同类 Memory；之后 LLM 剪枝掉不需要的，最后把搜索到的 Memory 总结成一句话再用于作答。

*PM-Bench*：考验「前瞻性记忆」——当前说的一些要求：「X 天后帮我…」「X 小时后提醒我…」。考察 Agent 能否把这些要求记住，并在未来对应的时间点真正触发行动，而不是只会事后问答。

Proactive-Memory-Agent：不让主 Agent 独自负责想「要不要记/提」，而是让一个副 Agent（记忆 Agent）并行维护文本库：Status（自己的进度，私用）、Knowledge（从轨迹抽取的事实）、Procedural（主 Agent 的历史尝试结果与失败经历）；记忆 Agent 决定是否向主 Agent 注入简短提醒或保持沉默。可通过 SFT 或 GRPO 训练其记忆管理与是否提醒的策略，主 Agent 可保持不改。

ProcMEM：当 Agent 完成一类任务时：Skill 初始空白，LLM 首次做任务成功时，归纳出一个初始 Skill（含激活条件、执行规程、终止条件）；之后失败时，用 Agent 分析失败原因、给出因果解释，不断优化 Skill。用非参数 PPO（语义梯度提候选 + 门控验收 + 打分维护）在不改模型权重的前提下维护可执行技能池，检索时按相似度或估计回报选用 Skill。

RaMem：给每个 Memory 绑定情节坐标（事件发生时间、提及时间、会话跨度、相关人物等），缓解「内容相关但情节不对」的情境坍塌；query 到来后先诱导回忆条件（合法证据须满足的时间/人物等），检索时同时考虑 tag 重合度与 Memory 语义重合度排序选出 top-k，并在生成时保留结构化情境字段，条件不可靠时不强行硬过滤。

REMem(ICML 2026)：通过原始 Memory 提取「Gist」，Gist 再提取为 Fact：(subject, predicate, object) + 时间；检索时按照时间戳先关注 Fact，检索后再牵扯出对应的 Gist 作为提取的 Memory，兼顾可检验的原子事实与较丰富的情节摘要。

SEEM(ACL 2026)：一些 Memory message 总结为「事实框架（笼统 XX 事件）」与「事实节点（更具体的事，是一个结构化四元组）」；query 到来之后，RAG 检索事实节点，然后溯源事实框架，提取出相关 message，实现由细到粗的证据组织。

SimpleMem：滑窗切对话后用模型门控丢掉寒暄噪声，再做指代/时间消解并原子化为多视图可索引的事实单元；写入时在会话内当场把相关碎片合成为更高密度条目，建立语义、词法、符号三路索引；查询时先推断意图并动态决定检索深度与范围，三路并行召回后并集去重再答，在抬高 F1 的同时大幅压推理 token。

*STALE*：关注用户没有说的、隐含的状态更新——例如用户没有直说从北京搬家到上海，但是最近一直在上海活跃；考察 Agent 能否从行为证据推理出用户已搬家到上海这类未明示事实。

UMA：长文/长交互按块流式维护双记忆——可更新的核心摘要 + 键值账本，动作为创建/更新/删除条目与刷新核心等；答题时再查账本，并可混合检索原始块。同一策略端到端训练：记忆阶段用其连带的多题表现估计优势，问答阶段按题分层比较，从而把最终对错回传到「当初怎么写记忆」；并发布侧重持续状态跟踪的 Ledger-QA。

UMEM：冻结任务执行器，只训练记忆优化器——让它同时学会「从轨迹抽什么可复用经验」以及「对库做 ADD 还是 UPDATE」；奖励不看单题死记，而看语义邻域上一簇相近题在更新后的库上是否变好、答案是否更干净，并把边际效用最高的动作真正写入库，迫使抽出可迁移原则而非实例噪声。

ZEP：双时间轴记录：一个是真实世界时间（如 Alice 7 月搬到上海）；另一个是 Agent 系统的时间（Agent 在 8 月才知道 Alice 搬到上海），用于审计与时间推理。之后依旧抽取实体作为图的节点、抽取实体间的关系；实体聚类为社区，根据 query 中时间信息，按照时间轴推理，再选出对应的社区/实体/事件作为 memory 提取。

DeepControl：检索返回层级 evidence 树，Agent 先见粗根再按需 expand；用 novelty 与 effectiveness 组成逐步信息效用 U，训练期在效用连续偏低时注入停搜、在仍高却过早作答时强制再搜一轮，并 anneal 掉控制信号，配合 F1 终局奖励与工具违规惩罚，在 *NQ*/*HotpotQA* 等七集 search-RL 上超过 Search-R1。

Deterministic-Memory-Conflict：在 *MAB* FactConsolidation 上主张冲突消解瓶颈在检索后 assembly 而非记忆存储架构；BM25 取 fact-level top-10 后 LLM 只抽取语义匹配候选， freshness 用 Python max(serial)（多跳 CAR 则 Self-Ask 分解后对每 hop 重复），FC-SH 达 78%/95%（mini/gpt-4o）、FC-MH 30%/52%，长上下文下显著优于 LLM 一体式判新版本。

IGPO：多轮搜索 RL 中把每 turn 结束前后「生成标准答案的概率差」当作信息增益 intrinsic reward，与终局 F1 分组归一化后折扣累积，替换纯 outcome GRPO 的 advantage，缓解 zero-advantage 组并提高样本效率；在 *NQ*、*HotpotQA* 等七集 agentic search 上稳定超过 Search-R1/GRPO。

InfMem：超长文档单遍流式读入，维护有界 overwrite memory；每步 PRETHINK 判 STOP 或生成文内检索 query+topK，RETRIEVE 全局抓稀疏证据，WRITE 联合当前 chunk 与检索结果做证据感知压缩，SFT 学协议再 RL 对齐停/搜/写，相对 MemAgent 约 +8～+12 pp 且早停约 3.9× 加速。

MemSearcher：多轮搜索时 LLM 每轮只吃「问题+紧凑 memory」，action 后由同一模型整合 observation 进有上限的自然语言记忆，避免 ReAct 式堆满历史；multi-context GRPO 把轨迹级 advantage 复制到各 turn 分别优化，在七个 QA 集上优于 Search-R1 且 context token 近常数。

Search-R1：模板约束 think→`<search>`→`<information>` 多轮交替，终局 `<answer>`；PPO/GRPO 仅对模型 token 反传并 mask 检索段，奖励只用 EM，在 Wikipedia+E5 设定下 NQ+Hotpot 训练、七基准测，相对 RAG/R1 约 20%+ 相对提升，奠定 outcome-based agentic search RL 基线。

StepSearch：在 PPO 中对每轮 search 用金标文档覆盖度的次模信息增益减检索重复率惩罚作为 step reward，轨迹末叠加 answer F1 与 query–关键词 F1；MuSiQue 合成监督 + 四集 multi-hop 评测，整体强于 Search-R1，强调 process 监督可 plug-in PPO。

SUMER：LoCoMo 消息级未压缩入库（语义/关键词 search_memory+speaker/session 过滤），GRPO+RLVR 仅奖励交卷轨迹（LLM judge×token F1），最多 20 turn、工具响应 mask；学得 goal-directed memory search 后在 *LoCoMo* 验证 Overall F1 48.65，明显超过 Mem0/A-MEM/全上下文等压缩路线。

TeaRAG：Wikipedia 规模 chunk+抽三元组 KG，每步 hybrid 检索后建 chunk–triplet 共现 KAG 用 PPR 选高密度 context，再摘要并决定是否继续；SFT（MuSiQue 流程数据）+ IP-DPO 过程奖励惩罚多步 overthinking，六集 EM 约 +2～4% 同时 output token 约降 59%–61%。

---

# 调研差异评估

> 自各方向根目录「调研差异评估.md」迁入；以下为完整评估正文。

> 检索范围：2024–2026；脚本 + WebSearch；基准锚点 PM-Bench (arXiv:2607.12385, 2026)

---

## 1. 当前稿主张

- **问题重述**：LLM Agent 记忆评测多聚焦*回溯性*检索（LoCoMo、LongMemEval 等），但日常助手还需*前瞻性*记忆——在时钟/事件线索满足时执行延迟意图，并在改期、取消、诱饵下保持精确率—召回率平衡。
- **核心抽象**：提出**条件记忆** $I=(\phi,a,\sigma,meta)$——触发谓词、动作、生命周期状态分离，而非自由形式情节片段。
- **方法 ProMem**：双存储（情节库 $E$ + 前瞻意图库 PIS）、生命周期管理器（announce→active→fired/completed/canceled/modified）、**意图条件化**主动监控器 $\pi_{mon}$、到期集合打分器 $\pi_{due}$（含 lure/生命周期惩罚）。
- **评估**：以 PM-Bench Virtual Week 为主（Set-F1、通道/跨日/更新敏感切片），对比 Single、Todo-ledger、Optional/Auto-heartbeat、Hierarchical union-query；实验数值仍为占位。

---

## 2. 新搜高相关论文（≥4篇）

| 论文 | 年 | 重叠点 |
|------|-----|--------|
| **PM-Bench: Evaluating Prospective Memory in LLM Agents** (Liu & Gabriel) | 2026 | 直接定义任务与基线脚手架；最佳 optional-heartbeat 仅 65.1% macro Set-F1；通道监控、跨日、更新敏感是公认瓶颈 |
| **In Prospect and Retrospect: Reflective Memory Management for Long-term Personalized Dialogue Agents** (ACL 2025) | 2025 | 「前瞻/回顾」记忆命名相近，但面向对话 QA 的反思式写入/检索，**不要求**在隐藏通道下触发动作集合 |
| **HiAgent: Hierarchical Working Memory Management for Solving Long-Horizon Agent Tasks** (ACL 2025) | 2025 | 长程 Agent 的分层工作记忆控制；优化*上下文管理*，非 PM-Bench 式「何时行动」与 Set-F1 |
| **Memory Matters: The Need to Improve Long-Term Memory in LLM-Agents** (AAAI SS 2024) | 2024 | 综述性呼吁改进 Agent 记忆；未形式化条件意图或到期集合 |
| **A Prompt Chaining Framework for Long-Term Recall in LLM-Powered Intelligent Assistant** (2025) | 2025 | 提醒/链式 recall 工程实践；无 PIS 生命周期、无诱饵感知 due-set 打分 |

*注：工业界 heartbeat/cron 自主调度（OpenClaw、heartbeat-agent-framework 等, 2025–2026）与 PM-Bench 的 auto-heartbeat 基线高度重叠，属于**工程实现**而非 peer-reviewed 方法论文。*

---

## 3. 差异与优势 / 已被占据的 claim

### 仍可主张的差异
- **概念层**：将「条件记忆」作为与情节/回溯记忆**正交**的一等抽象，并用 PM-Bench 的 $D_t$/Set-F1 形式化成功标准——这在 2024–2026 记忆论文中仍稀缺。
- **架构层**：PIS + 显式生命周期 + 意图依赖监控 + lure 惩罚的**组合**针对 PM-Bench 已报告的 FP 爆炸与通道命中不足，比「把意图写进 todo 文本」或「固定周期 heartbeat」更有针对性叙事。

### 已被占据或需降调
- **「Agent 需要前瞻性/延迟意图记忆」**：PM-Bench (2026) 已系统论证并发布基准——不宜再 claim「首次发现该问题」。
- **「heartbeat/周期性自检能提升前瞻表现」**：PM-Bench 显示 optional-heartbeat **已是最佳脚手架**；auto-heartbeat 提高更新命中但 FP 激增——若 ProMem 无实测，不能 claim 全面优于 heartbeat。
- **「双存储分离情节与意图」**：Todo-ledger 基线已是近似方案；优势需靠**类型化 schema + 监控/打分 API** 的可证增益，而非概念复述。

---

## 4. Method 是否要改 + 具体建议

**必须改（否则稿件站不住）：**

1. **补齐 PM-Bench 主表数值**：当前全为 `--`，论文无法投稿。至少跑通 1–2 个骨干 + 全套基线/ablation。
2. **相对 PM-Bench 已有脚手架的量化对比**：重点报告 (i) Set-F1 vs optional-heartbeat；(ii) 通道 hit vs hierarchical union-query（高查询低转化）；(iii) FP/FN 工作点曲线——与摘要中「预期」对齐为**实测**。
3. **监控策略可学习化（可选增强）**：$\pi_{mon}$ 目前为规则+LLM；可增一小节 dev-set 调参或学习 $w(I), \eta(I,t)$，与 PM-Bench「无单一最优脚手架」结论呼应。
4. **明确 PIS 解析失败处理**：announce/改期/覆盖的指称消解是残差错误源；增加校验提示或双写 cancel 的 ablation。

**可保留但需收紧：**
- 合成条件指令套件作为**次要**迁移实验即可；主贡献应锁 PM-Bench。
- 「条件记忆」定义可保留，但避免暗示已解决 PM——PM-Bench 作者自己也强调该轴远未解决。

---

## 5. Intro / Related Work 必改要点

1. **开篇**：第一段后尽快 cite **PM-Bench (2026)** 为问题来源，将贡献定位为「在该基准上提出条件记忆抽象与 ProMem 脚手架」，而非独立发现前瞻记忆难题。
2. **Related Work 增节「前瞻记忆基准与脚手架」**：除认知科学 Virtual Week 外，单列 PM-Bench 八种配置的结果摘要（heartbeat 最强、通道/跨日/更新切片诊断），并**逐条对比** ProMem 组件与 Todo-ledger / heartbeat / union-query 的差异。
3. **与回溯记忆工作的边界句**：LoCoMo、LongMemEval、A-Mem 等仅一句定位——「优化 $sim(e,q)$，不优化 $sat(\phi,e_t)$」。
4. **工业 heartbeat 文献**：Related Work 或 Limitation 中承认 periodic wake 已是常见工程模式，强调 ProMem 的**意图条件化查询**与 **due-set 精确率控制**是相对 fixed-interval heartbeat 的设计差异。
5. **贡献列表**：删除任何「首次提出前瞻性记忆重要」表述；改为「首次将条件记忆形式化并实例化为可复现脚手架（在 PM-Bench 上验证）」——且验证需有数字支撑。

---

*评估日期：2026-07-31*
