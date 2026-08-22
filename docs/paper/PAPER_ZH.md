# Conditional Memory（条件记忆）：在 LLM Agent 中建模与触发延迟意图

**方法：** ProMem

---


# 摘要

大语言模型（LLM）智能体越来越多地在*回溯性*记忆（retrospective memory）上被评估——从长交互历史中检索事实以回答问题。然而，可靠的助手还必须维护*前瞻性*记忆（prospective memory）：在未来线索或时钟条件成立时应执行的延迟意图；与此同时智能体还需继续完成其他强制性活动，并在改期、取消与覆盖事件下更新意图，且不产生虚假误报。近期关于 PM-Bench [pmbench2026] 的工作表明，这种「何时行动」（when-to-act）能力远未解决：监控隐藏环境通道是严重瓶颈，跨日与更新敏感命中率仍然偏低，且没有一种通用脚手架在 Set-F1 工作点上占据主导。我们认为，缺失的抽象是*条件记忆*（conditional memory）：形式为 $(,,)$ 的结构化记录，将触发条件 $$、可执行动作 $$ 与生命周期状态 $$ 耦合在一起，而非为「大海捞针」式检索而优化的自由形式情节片段。我们形式化这一观点，并提出 **ProMem**：一种前瞻性记忆脚手架，包含 (i) 将情节性回溯库与前瞻意图库（Prospective Intention Store, PIS）分离的双存储；(ii) 覆盖 announce→active→fired/completed/canceled/modified 转移的显式生命周期管理器；(iii) 决定何时查询时钟、邮件及其他隐藏通道的主动触发监控器；以及 (iv) 在抑制诱饵的同时选择可执行候选的到期集合打分器。在 PM-Bench Virtual Week 协议上，我们预期 ProMem 将尤其在需要通道、跨日与更新敏感切片上提升 Set-F1，并相对滥发式自动心跳实现更好的精确率—召回率权衡。代码与提示将在发表时公开。

---


# 引言

在长时程上运行的 LLM 智能体通常配备记忆模块：向量库、摘要流水线、图记忆，以及检索增强生成（RAG）栈，旨在于提问时浮现正确的过去事实 [locomo2024,longmemeval2024,amem2025]。这些系统主要针对*回溯性*记忆——从聊天历史回答「发生了什么？」。然而在日常辅助中，用户也会发出延迟指令：21:00 服药、门户开放时预约时段、邮件到达后回复、计划变更则取消提醒。此处的成功并非用从干草堆中捞出一根针来衡量，而是在推进并发任务的同时*在正确的未来时刻行动*，以及在意图已被取消或线索仅为诱饵时*不行动*。

认知科学早已将回溯性回忆与*前瞻性记忆*（prospective memory, PM）区分开来——在持续活动中，依据线索或时间触发记住执行延迟意图 [einstein2005prospective,rendell2000virtual]。PM-Bench [pmbench2026] 将该问题系统化为 LLM 智能体评测：每一步智能体必须选择一项强制性进行中活动，并可选地针对真实*到期集合*（due set）$D_t$ 触发一组前瞻动作，而隐藏状态通道（时钟、邮件、门户等）除非主动查询否则不可见。经验上，前沿模型仍然脆弱：通道要求命中率接近下限，跨日与更新敏感意图常被遗漏，滥发监控查询的脚手架抬高假阳性并损害 Set-F1。在 PM-Bench 报告的八种脚手架中，optional heartbeat 目前 macro Set-F1 最高（65.1%）；auto-heartbeat 提高更新命中却淹没假阳性；层次化并集查询发出数千次通道读取却仍错过通道要求的到期项 [pmbench2026]。

我们认为，剩余差距既是架构性的，也需要在已有基准上实例化：回溯性记忆优化 $sim(e,q)$；前瞻能力需要*条件性*记录——在触发器满足前保持休眠，随后经历支持修改与取消的生命周期。我们的贡献不是「首次发现智能体需要前瞻记忆」——PM-Bench 已系统论证——而是在该基准上**实例化类型化条件记忆**脚手架。

为弥合这一差距，我们将 **条件记忆**（conditional memory）形式化为与回溯情节库正交的一等抽象——成功标准是触发满足 $sat(,e_t)$ 而非 query–document 相似度——并用 **ProMem**（图 [fig:promem-overview]）实例化：双记忆存储、意图生命周期管理器、意图条件化主动触发监控策略，以及与进行中活动选择集成的到期集合打分器。我们的贡献包括：

    
- 我们将*条件记忆*形式化为与回溯情节库正交的抽象，以到期集合 $D_t$ 与 Set-F1 为自然目标，锚定 PM-Bench 已报告的失效模式（通道监控、跨日携带、更新敏感）。
    
- 我们提出 ProMem：双存储（情节库 + 前瞻意图库 PIS）、显式生命周期转移、面向隐藏通道的意图条件化监控器 $_mon$，以及诱饵感知的到期集合打分器 $_due$——针对 todo 账本与固定间隔 heartbeat 下的 FP 爆炸与通道命中不足。
    
- 我们概述以 PM-Bench 为中心的评估协议：对齐全部八种已发表脚手架、消融隔离各 ProMem 组件，以及通道/跨日/更新敏感切片指标；数值待最终实验，**在无实测 Set-F1 前不 claim 全面优于 optional heartbeat**。

---


# 相关工作

**回溯性智能体记忆基准。**
大量工作评估智能体能否从长对话与多会话历史中检索或回忆信息。LoCoMo [locomo2024]、LongMemEval [longmemeval2024] 及相关方法 [amem2025,memorybank2023,memgpt2023] 优化 $sim(e,q)$——给定*当前*问题能否恢复正确过去事实——而非 $sat(,e_t)$，即延迟触发在步骤 $t$ 是否满足。它们并不要求在未来线索出现时执行先前宣布的动作。

**认知科学中的前瞻性记忆。**
Virtual Week 范式 [rendell2000virtual] 被 PM-Bench [pmbench2026] 改编为 LLM 智能体评测；我们继承其到期集合框架与诊断切片（通道命中、跨日、更新敏感）。

**前瞻记忆基准与脚手架。**
PM-Bench [pmbench2026] 以 Set-F1、隐藏通道、诱饵与生命周期更新操作化 LLM 前瞻记忆，评估八种脚手架：Single、Todo-ledger、Optional heartbeat、Auto-heartbeat（60m/30m）、Hierarchical union-query 等。optional heartbeat macro Set-F1 领先（65.1%）但通道命中仍低；auto-heartbeat 提高更新召回却以 FP 为代价；层次查询查询数最多但转化差；todo 账本近似双存储但缺乏类型化生命周期 API。ProMem 在该基准上实例化条件记忆：PIS 替代非结构化账本文本；$_mon$ 以意图条件化轮询替代无差别周期唤醒；$_due$ 增加 heartbeat 脚手架缺少的生命周期与诱饵惩罚。

**相关记忆线（回溯/分层）。**
In Prospect and Retrospect [inprospect2025] 面向对话 QA 反思式写读，非隐藏通道 Set-F1；HiAgent [hiagent2025] 优化分层工作记忆上下文控制；链式 recall 框架 [promptchain2025] 无 PIS 生命周期。工业 cron/heartbeat 与 PM-Bench auto-heartbeat 同轴；ProMem 主张意图条件化监控与 due-set 精确率控制，需实证验证。

**定位。**
条件记忆与 ProMem 瞄准 PM-Bench 已基准化的正交轴——随时间触发、更新与抑制意图——通过类型化脚手架实例化，而非重新发现该问题。

---


# 动机与预备知识

## 动机：从针检索到何时行动

回溯性记忆基准奖励恢复已经发生的事实。前瞻设定奖励不同能力：智能体必须 (i) 在意图宣布时编码它，(ii) 在中间步骤与跨日中保持可用，(iii) 检测触发何时满足——往往只有在查询默认隐藏的通道之后，以及 (iv) 精确执行到期动作，同时拒绝诱饵并遵守取消/改期/覆盖更新。PM-Bench [pmbench2026] 将其操作化：即便意图写入账本，智能体对非时钟通道仍监控不足（报告的最佳隐藏通道命中约 $16.7%$），在跨日承诺上挣扎，并在心跳下面临精确率—召回率两难。

这些失败表明，「在记忆中存更多文本」是错误的归纳偏置。所需的是*条件性*表示：意图并非用户问题的答案候选，而是带可变状态 $$ 的休眠策略片段「若 $$ 成立，则做 $$」。我们称此类记录为 **条件记忆**。本节其余部分形式化 PM-Bench 交互模型与我们的意图抽象；第 [sec:methods] 节再将 ProMem 呈现为围绕该抽象构建的脚手架。

## 预备知识：PM-Bench 交互模型

我们遵循 PM-Bench Virtual Week 协议 [pmbench2026]。时间在模拟周上以离散步骤 $t=1,,T$ 推进（发布设定：$T=80$ 步，不规则日程）。在步骤 $t$，智能体观察叙事 vignette $v_t$、强制性进行中活动菜单 $C_t=\A,B,C\$，以及一组匿名前瞻动作句柄 $X_t$（混合真实任务动作与*诱饵*）。状态通道集合 $H$（时钟、邮件、门户等）是*隐藏的*：仅当智能体发出监控查询时才揭示内容。

**先查询后行动协议。**
每一步流程如下：

    
- 智能体可发出零次或多次监控查询 $q_t$，并观察返回 $r_t=Read(q_t)$。
    
- 智能体提交 $a_t=(c_t,D_t)$，其中 $c_t_t$ 为进行中活动，$D_t X_t$ 为声明当前到期的前瞻动作集合。

**到期集合。**
令 $I$ 为任务定义集合。每个任务 $$ 携带触发条件与可执行动作。记 $X_t$ 为时刻 $t$ 可用的句柄。真实到期集合为

$$
D_t = \  X_t :  is still valid and its execution condition holds at t\,
$$

其中事件型任务在相关线索出现于 $v_t$ 或已查询通道返回时到期，时间型任务在模拟时钟匹配目标时间（或落入允许窗口）时到期。有效性排除已取消任务，并尊重最新的改期/覆盖。

**目标。**
PM-Bench 在轨迹上聚合集合重叠：

$$
TP=_t |D_t_t|, 
FP=_t |D_t D_t|, 
FN=_t |D_t_t|,
$$

$$
Set-F1=2 TP2 TP+FP+FN.
$$

仅精确率的指标奖励永不行动；仅召回率的指标奖励每步触发每个句柄。Set-F1 要求既命中到期项又抑制误报——这是条件记忆的自然目标。

## 条件记忆形式化

definition[条件记忆 / 意图]

意图是一个元组

$$
I = (,,,meta),
$$

其中 $$ 是关于可观察证据（叙事文本、通道返回、时钟）的触发谓词，$$ 是可执行动作句柄，$$ 是生命周期状态，$meta$ 存储标识符、宣布步骤、日程元数据，以及供 LLM 使用的自由文本释义。
definition

我们取生命周期字母表

$$
=\announced,active,fired,completed,canceled,modified\.
$$

非正式地：意图在首次陈述时进入 announced；一旦被接纳进前瞻意图库则变为 active；在 $D_t$ 中被选中时转为 fired，当环境接受执行时转为 completed；在取消事件下移至 canceled；在改期/覆盖下移至 modified（随后通常在更新 $$ 后回到 active）。

definition[条件记忆 vs.\ 情节记忆]

*情节 / 回溯*记录 $e$ 是按查询 $q$ 检索索引的内容，打分 $sim(e,q)$。*条件*记录 $I$ 是为*触发评估*而索引的内容：在步骤 $t$，问的是证据 $e_t=(v_t,r_t)$ 是否满足 $$，而非 $I$ 是否回答用户问题。两个存储可共享表层文本，但在 API、更新规则与成功度量（Set-F1 vs.\ QA 准确率）上不同。
definition

proposition[作为触发满足的到期集合]

在完美监控与忠实生命周期下，

$$
D_t = \(I) : I_t, (I)\active,modified\,  e_t(I)\,
$$

其中 $P_t$ 是时刻 $t$ 仍存储的意图集合。监控失败（$e_t$ 缺失通道事实）、陈旧 $$，或诱饵混淆会导致 $D_t D_t$。
proposition

命题 [prop:due] 隔离了为何回溯性 RAG 不足：检索可能在 $$ 为假时仍浮现意图文本（误报），或在 $$ 本应为真时未能复查通道（漏检）。条件记忆使 $$、$$ 与 $$ 显式化，从而可专门化监控、更新与打分。

---


# 提出的方法：
 ProMem

ProMem 是一种推理时脚手架，在冻结骨干之上为 LLM 智能体实现条件记忆。它包含四个组件：双记忆存储、生命周期管理器、主动触发监控器，以及到期集合打分器，在 PM-Bench 先查询后行动循环下组合（图 [fig:promem-overview]）。完整控制流见附录 [sec:Algorithm]。

## 问题陈述

给定第 3 节协议下的轨迹观察 $\o_t\$，智能体必须产生动作 $a_t=(c_t,D_t)$，在现实监控成本约束下最大化相对 $\D_t\$ 的期望 Set-F1。我们将策略分解为

$$
(a_t,q_t o_t,M_t)
=
_mon(q_t o_t,M_t) 
_due(D_t o_t,r_t,M_t) 
_act(c_t o_t,r_t,M_t),
$$

其中 $M_t=(E_t,P_t)$ 表示双记忆（情节库 $E_t$、前瞻意图库 $P_t$），$r_t$ 为查询 $q_t$ 后的通道返回，$_mon$ 为触发监控器，$_due$ 为到期集合打分器，$_act$ 选择强制性进行中活动。ProMem 规定 $M_t$ 的结构与三个因子；每个因子可通过用专门上下文提示同一骨干实现，或在 LLM 判断之上用轻量打分规则实现。

## 双记忆：情节库与前瞻意图库

**情节性回溯库 $E**$。
对情境感知或回答回溯探测有用的叙事 vignette、先前活动选择与通道返回，以带时间戳的片段（可选摘要）追加到 $E$。对 $E$ 的检索使用标准相似度或近因，且*不是*决定到期项的主路径。

**前瞻意图库（Prospective Intention Store, PIS）$P**$。
每当观察流宣布延迟任务——或引用已有任务的更新——ProMem 将意图 $I=(,,,meta)$ upsert 到 $P$。触发 $$ 表示为结构化字段加自然语言释义，覆盖 PM-Bench 类型学：

    
- *时间型：* $$ 引用时钟谓词（精确时间或窗口）。
    
- *事件 / 叙事型：* $$ 引用 $v_t$ 中的线索。
    
- *通道型：* $$ 引用特定 $h$ 上的谓词（邮件主题、门户时段等）。

跨日意图自宣布至较晚线索日均以 $=active$ 留在 $P$ 中；绝不因宣布日结束而被降级。

分离是有意为之：将意图混入扁平情节存储，迫使模型每一步重新发现「这是延迟承诺」，PM-Bench 表明这很脆弱。PIS 则向 $_mon$ 与 $_due$ 暴露开放承诺的显式清单。

## 生命周期管理器

生命周期管理器 $$ 应用确定性（或 LLM 辅助）更新

$$
(P_t+1,E_t+1)=(P_t,E_t,o_t,r_t,a_t,u_t),
$$

其中 $u_t$ 表示观察流中检测到的更新事件（取消 / 改期 / 覆盖）。

**转移概要。**

    
- announce→active：解析新意图；插入 PIS。
    
- active→fired：在 $_due$ 下 $_t$。
    
- fired→completed：环境确认成功（或当协议将触发视为终态时，ProMem 标记完成）。
    
- active→canceled：命名该意图的取消事件。
    
- active→modified$：改期/覆盖改写 $$（也可能改写 $$）；先前到期窗口作废，因此若仍产生陈旧触发则计为 FP。

因此，更新敏感正确性是一等状态机属性：取消后，无论线索多么相似，$_due$ 必须给出近零分数；改期后，仅新 $$ 可允许进入 $D_t$。仅回溯系统把新旧表述都留在片段袋中，常违反此约束。

## 主动触发监控器

隐藏通道监控是 PM-Bench [pmbench2026] 报告的瓶颈：叙事线索任务相对更容易，而即便智能体发出许多查询，通道要求命中仍偏低。因此 ProMem 将监控视为刻意策略 $_mon$，而非事后补丁。

**信息状态。**
在步骤 $t$，令 $P_t^open=\I_t:(I)\active,modified\\$。对每个开放意图，定义依赖集 $deps(I)\narrative\$，列出可能满足 $(I)$ 的证据源。监控器构造优先级列表

$$
s_mon(h t)=_I_t^open w(I) 1[h(I)] (I,t),
$$

其中 $w(I)$ 在可用时加权任务重要性/规律性，$(I,t)$ 为紧迫性先验（例如时间窗口临近、跨日意图的目标日已开始，或近期叙事提及相关实体时更高）。

**查询选择。**
$_mon$ 选择有预算的集合

$$
q_t=TopK(\h:s_mon(h t)_mon\, K_t),
$$

可选地由 LLM 调用根据 $(v_t,P_t^open)$ 增删通道。不同于每 $30$/$60$ 虚拟分钟的固定自动心跳，查询是*意图条件化*的：无开放依赖的通道不被轮询，从而降低监控开销与诱饵驱动的过度行动。不同于纯可选心跳，只要 $s_mon$ 超过阈值，默认即主动——以应对非时钟通道的监控不足。

**停止。**
在返回 $r_t$ 后，仅当新证据抬高仍未读通道的 $s_mon$ 时（例如邮件暗示门户），监控器才可发出第二轮微查询。层次化并集查询基线常因未能将额外读取转化为正确 $D_t$ 而失败；ProMem 将 $r_t$ 直接送入下方打分器。

## 到期集合打分器

给定证据 $e_t=(v_t,r_t)$ 与候选句柄 $X_t$（真实动作与诱饵），打分器 $_due$ 输出 $D_t X_t$。

**候选生成。**
对每个 $x X_t$，按句柄身份或模糊标签匹配检索匹配意图 $M(x)_t^open$。诱饵通常有 $M(x)=$，或仅与非活跃/已取消记录有弱词汇重叠。

**打分。**
对每个 $x$，

$$
s_due(x e_t)=
_I(x)
(
sat((I),e_t)
-
_life((I))
-
_lure(x)
),
$$

其中 $sat[0,1]$ 是触发 $$ 在证据 $e_t$ 下的 LLM 或规则满足分数；$pen$ 对 canceled/completed 重罚，对陈旧 modified 壳层轻罚；$lure(x)$ 在 $x$ 未锚定任何开放 $I$ 时较高。然后

$$
D_t=\x X_t:s_due(x e_t)_due\.
$$

阈值 $_due$ 刻画精确率—召回率曲线：更低值提高召回（与 FP），更高值偏向保守精确率。ProMem 在可用时于小型开发周上调 $_due$（与 $_mon$）；否则用提示自洽投票近似阈值。

**为何有助于 Set-F1。**
自动心跳提高用新鲜时钟证据评估 $sat$ 的机会，但若无 PIS 锚定，也会抬高诱饵上的虚假 $sat$。显式 $pen()$ 与 $lure(x)$ 项针对监控与意图状态解耦时观察到的 FP 爆炸 [pmbench2026]。

## 与进行中活动选择的集成

PM-Bench 要求每步有强制性进行中活动 $c_t_t$。ProMem 不取代该选择；它基于开放意图对其轻度条件化：

$$
_act(c_t) LLM(v_t,C_t,brief(P_t^open)),
$$

其中 $brief()$ 仅列出时间关键或叙事相关承诺，使模型在 vignette 允许时偏好与即将到期兼容的活动。到期决策 $D_t$ 保持分离：智能体可以（且经常必须）在同一步既推进无关进行中任务又触发到期意图——匹配人类 PM 双任务结构。

**端到端步骤。**
(1) 经 $$ 从 $o_t$ 更新 PIS/情节库（摄入宣布/更新）。(2) 运行 $_mon$ 获得 $r_t$。(3) 用 $_due$ 打分到期项。(4) 用 $_act$ 选择 $c_t$。(5) 提交 $a_t$，然后完成生命周期转移（fired/completed）。伪代码见算法 [alg:promem]。

## 相对 PM-Bench 脚手架的设计理由

    
- **vs.\ Single：** 增加外部条件状态，使骨干不必仅在上下文窗口中持有所有开放 $$。
    
- **vs.\ Todo-ledger：** 账本文本由类型化 $(,,)$ 记录取代，供监控与打分 API 消费，而非仅靠非结构化阅读。
    
- **vs.\ Heartbeats：** 监控按 $deps(I)$ 与紧迫性 $$ 分配，旨在提高每次查询的通道命中并减少 FP。
    
- **vs.\ Hierarchical union-query：** 单一协调的 PIS 避免跨子智能体碎片化承诺——PM-Bench 发现这对跨日命中有害。

---


# 实验

我们设计实验以检验条件记忆——由 ProMem 实现——是否在 PM-Bench 及相关条件指令设定上提升前瞻能力。报告单元格用 ``--'' 作为待最终运行的占位符；定性预期附于各表之后。

## 实验设置

**主基准：PM-Bench Virtual Week。**
我们在发布的 PM-Bench 周 [pmbench2026] 上评估：$7$ 天，$T=80$ 步，$81$ 个计分可执行任务（事件与时间型；规律与非规律），含通道触发、跨日与更新事件，外加诱饵动作与隐藏通道。智能体遵循官方先查询后行动协议与基于回放的评估器，使到期集合 $\D_t\$ 与打分在各系统间一致。

**指标。**

    
- **Set-F1**（主指标），累积 TP / FP / FN 如式 (eq:set-f1)。
    
- **FP / FN** 计数（工作点诊断）。
    
- **Channel hit（通道命中）**：隐藏通道要求到期项上的命中率。
    
- **Cross-day hit（跨日命中）**：在线索日之前宣布的意图上的命中率。
    
- **Update-sensitive hit（更新敏感命中）**：受取消 / 改期 / 覆盖影响的任务上的命中率。
    
- **Monitoring overhead（监控开销）**：整周发出的通道查询次数。

在可用时我们也报告叙事线索与时钟要求切片以供分析。

**骨干模型。**
遵循 PM-Bench，我们计划覆盖闭源与开源模型的多个骨干（例如 GPT 系列与开源 8B--70B 级模型）。每个骨干$$脚手架配对为单独运行；宏平均镜像该基准的报告风格。

**基线。**
我们与 PM-Bench [pmbench2026] 中研究的脚手架比较：

    
- **Single**：单一模型，除提示外无外部记忆。
    
- **Todo-ledger**：上下文内待办账本，含待处理意图、线索/时间与完成位。
    
- **Optional heartbeat（可选心跳）**：模型可启用周期性自我提醒以复查通道。
    
- **Auto-heartbeat（60m / 30m）**：固定周期唤醒。
    
- **Hierarchical union-query（层次化并集查询）**：协调器与提出查询的子智能体；并集后再最终行动。

**ProMem** 使用第 [sec:methods] 节中的双存储 + 生命周期 + $_mon$ + $_due$。

**实现说明。**
提示、PIS schema 与阈值 $(_mon,_due,K_t)$ 将在发布时于附录详述。除非另行说明，基座模型权重冻结；ProMem 为推理时控制器。

## PM-Bench 主结果

```
table[h]

*Table/Figure: PM-Bench 主结果（占位）。更高 Set-F1 / 命中更好；在 Set-F1 固定时，更低 FP 与监控开销更好。「--」= 待定。*

3pt

tabularl|ccccccc

**Method** & Set-F1$$ & FP$$ & FN$$ & Chan.\ hit$$ & Cross-day$$ & Update$$ & Queries$$ 

Single & -- & -- & -- & -- & -- & -- & -- 

Todo-ledger & -- & -- & -- & -- & -- & -- & -- 

Optional heartbeat & -- & -- & -- & -- & -- & -- & -- 

Auto-heartbeat 60m & -- & -- & -- & -- & -- & -- & -- 

Auto-heartbeat 30m & -- & -- & -- & -- & -- & -- & -- 

Hierarchical union-query & -- & -- & -- & -- & -- & -- & -- 

ProMem (ours) & -- & -- & -- & -- & -- & -- & -- 

tabular

table
```

**预期发现。**
我们预期 ProMem 通过改善相对自动心跳（历史上以提高大 FP 为代价抬高更新命中）与层次查询（高查询数、弱通道$$动作转化）的精确率—召回率工作点，达到最佳或接近最佳 **Set-F1**。增益应集中在 **通道命中** 与 **跨日命中**（意图条件化监控与持久 PIS 状态最相关），以及 **更新敏感命中**（生命周期惩罚在取消/改期后抑制陈旧触发）。监控开销应低于层次化并集查询，并理想地接近可选心跳的效率，同时超过其通道覆盖。

## 消融研究

```
table[h]

*Table/Figure: ProMem 在 PM-Bench 上的消融（占位）。每行移除一个组件。*

4pt

tabularl|ccccc

**Variant** & Set-F1 & Chan.\ hit & Cross-day & Update & Queries 

Full ProMem & -- & -- & -- & -- & -- 

  w/o PIS (flat episodic only) & -- & -- & -- & -- & -- 

  w/o proactive monitor & -- & -- & -- & -- & -- 

  w/o lifecycle updates & -- & -- & -- & -- & -- 

  Retrospective-RAG-only & -- & -- & -- & -- & -- 

tabular

table
```

**消融定义。**

    
- **w/o PIS：** 意图仅写入情节库；无类型化 $(,,)$ 存储。
    
- **w/o proactive monitor：** 无 $_mon$；仅当骨干自发请求时才查询通道（类似 Single 的监控）。
    
- **w/o lifecycle updates：** 取消/改期/覆盖文本被存储，但 $$ / $$ 不被改写——施压更新敏感 FP/FN。
    
- **Retrospective-RAG-only：** 每步检索 top-$k$ 情节片段并让模型给出到期项，无 PIS、监控策略或生命周期 API。

**预期发现。**
移除 PIS 或使用 retrospective-RAG-only 应损害跨日与整体 Set-F1（承诺被淹没）。移除主动监控应使通道命中崩溃。禁用生命周期更新应特别降低更新敏感命中，并在取消后抬高 FP。完整 ProMem 应在 Set-F1 上主导所有消融。

## 次要：合成条件指令套件

在 Virtual Week 之外，我们构建紧凑的合成套件：工具使用对话中的条件指令（例如，「当票价 $<\$X$ 时买入」；「若包裹发货则邮件通知我；若取消则什么都不做」）。指标镜像离散决策点上的 Set-F1，外加诱饵消息下的误报率。

```
table[h]

*Table/Figure: 合成条件指令套件（占位）。*

4pt

tabularl|cccc

**Method** & Set-F1$$ & FP$$ & FN$$ & False-alarm rate$$ 

Single & -- & -- & -- & -- 

Todo-ledger & -- & -- & -- & -- 

Optional heartbeat & -- & -- & -- & -- 

Retrospective-RAG-only & -- & -- & -- & -- 

ProMem (ours) & -- & -- & -- & -- 

tabular

table
```

**预期发现。**
ProMem 应可迁移：相对 RAG-only 与 Single 有更高 Set-F1 与更低误报；在条件未满足时，比心跳式复查更少过度触发。

## 工作点分析

*[图占位符]*

滥发式监控可沿召回偏重、精确率差的前沿移动。我们将绘制 Set-F1 对 FP 与对查询数的曲线。**预期发现：** ProMem 的意图条件化 $_mon$ 与诱饵感知 $_due$ 相对 auto-heartbeat-30m（高更新命中、高 FP）以及 PM-Bench 报告的多数式过度聚合，给出更优工作点。

## 失效模式讨论（预期）

我们预期在触发语言含糊、多通道交互，或骨干误解析更新指称时仍有残差错误。层次碎片化应由设计避免，但单次损坏的 PIS 写入可能持续；校验提示与取消事件双记是待测缓解手段。

---


# 结论

我们主张 LLM 智能体需要*条件记忆*——结构化延迟意图 $(,,)$——作为对为针检索优化的回溯情节存储的补充。锚定于 PM-Bench 的前瞻 Virtual Week 评估，我们提出 **ProMem**：带前瞻意图库的双存储、显式生命周期管理器、面向隐藏通道的主动触发监控器，以及与进行中活动选择集成的到期集合打分器。该设计直接针对已记录的失效模式：通道监控不足、跨日承诺薄弱、更新脆弱，以及心跳滥发下糟糕的精确率—召回率。在 PM-Bench 与合成条件指令上经验确认这些增益是我们的下一步；更广的未来工作包括学习的监控策略、多智能体共享条件记录，以及与回溯记忆更紧耦合以服务混合查询—行动工作负载。

---


# 附录

.subsection

# A. ProMem 算法

算法 [alg:promem] 总结 PM-Bench 先查询后行动协议（第 [sec:methods] 节）下的一个 Virtual Week episode。双记忆、生命周期更新、监控与到期集合打分是显式的；骨干 LLM 按需在 $ParseAnnounce$、$Sat$、$IsLure$ 与活动选择内部调用。

```
algorithm[h]

*Table/Figure: ProMem 在 PM-Bench episode 上*

**Input**: Episode horizon $T$; channel set $H$; thresholds $_mon,_due$; query budget schedule $\K_t\$; backbone LLM $f$

**Output**: Actions $\a_t=(c_t,D_t)\_t=1^T$; metrics via official evaluator

**Init**: $E_0$, $P_0$

```
algorithmic[1]
$t=1$ to $T$
 Observe $o_t(v_t,C_t,X_t)$ vignette, ongoing menu, action handles
 $(P_t,E_t)(P_t-1,E_t-1,o_t)$ 
 parse new $I=(,,,meta)$; apply cancel/reschedule/override to $,$
 $P_t^open\I_t:(I)\active,modified\\$
$h$
 $s_mon(h)_I_t^open w(I) 1[h(I)] (I,t)$

 $q_t(\h:s_mon(h)_mon\,K_t)$; optionally refine $q_t$ with $f$
 $r_t(q_t)$; $E_t_t(r_t)$
 $e_t(v_t,r_t)$
$x X_t$
 $M(x)(x,P_t^open)$
 $s_due(x)_I(x)(Sat((I),e_t)-_lifePen((I))-_lureIsLure(x))$
 if $M(x)=$, take $s_due(x) -_lureIsLure(x)$

 $D_t\x X_t:s_due(x)_due\$
 $c_t(f;v_t,C_t,Brief(P_t^open))$
 Submit $a_t(c_t,D_t)$
 $P_t(P_t,D_t)$ active→fired/completed as applicable

 **return** $\a_t\$; compute Set-F1, hits, query count with replay evaluator
algorithmic
```

algorithm
```

# B. 补充形式化说明

## B.1 触发满足

对时间型意图，$Sat(,e_t)=1$ 当且仅当时钟通道（若已读）或官方暴露的步骤时间落在目标窗口内。对事件型意图，$Sat$ 是线索描述与 $v_t$ 之间的蕴含判断。对通道型意图，除非已查询所需 $h$ 且返回匹配 $$，否则 $Sat=0$；这在打分器本身中编码了监控瓶颈。

## B.2 与 Set-F1 梯度的关系（非正式）

提高 $_due$ 降低期望 FP 并增加 FN；提高监控预算 $K_t$ 增加通道型 $Sat$ 从 $0$ 翻转为 $1$ 的机会，从而在诱饵句柄与真实任务共享词汇特征时，以一定 FP 风险降低 FN。ProMem 的 $IsLure$ 与生命周期惩罚旨在压平该 FP 风险。

# C. 实现检查清单

**PIS schema 字段。** `id`, `trigger_type`, `trigger_spec`, `action_handle`, `state`, `announce_step`, `deps`, `gloss`。

**更新事件。** 检测取消 / 改期 / 覆盖跨度；将指称映射到 `id`；改写 `trigger_spec` 或设 `state=canceled`。

**日志。** 记录 $q_t$、$r_t$、$D_t$ 与 PIS 快照，用于切片指标（通道 / 跨日 / 更新）。

**超参数（默认待定）。** $_mon$，$_due$，$K_t$，$_life$，$_lure$，紧迫性日程 $$。

# D. 扩展实验占位

```
table[h]

*Table/Figure: PM-Bench 上按骨干的 Set-F1（占位）。*

tabularl|cccc

**Scaffold** & Backbone A & Backbone B & Backbone C & Macro 

Optional heartbeat & -- & -- & -- & -- 

Todo-ledger & -- & -- & -- & -- 

ProMem & -- & -- & -- & -- 

tabular
table
```

 预期模式（来自 PM-Bench）：脚手架排名可能与骨干交互；ProMem 应通过外化 $$ 与 $$ 而非仅依赖上下文内警觉来降低方差。

---
