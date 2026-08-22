## memory机制

### baseline

每步把全部对话历史都放到prompt里

### mem0

- 写入（Extraction）：对话结束后，LLM提取关键事实存入向量库 + 图谱 + SQL
- 检索（Retrieval）：下次提问时，通过语义搜索 + BM25（关键词） + 实体匹配 + （时序推理），从记忆中召回最相关的内容注入 prompt

### A-mem

1. 写入：将情节与已执行动作存成结构化memory（时间戳、上下文、原文、关键词、标签）
2. 存储：建立链接：向量相似度初筛top-k临近候选+llm判断是否建立链接
3. 检索：向量检索(top_k)+top_k的邻居记忆
4. 更新：新记忆与旧记忆建立连接时，可以刷新对旧记忆的理解

## 修改历史


| 改动                                               | 实验分数（Set-F1）                                                                               | 结果分析                                                                                                               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| 仅 baseline：全周对话历史进 prompt，无外部记忆                  | DS **67.2**；Qwen **69.0**                                                                  | 对照锚点：分数几乎全靠「全历史 + 模型自身查询」。                                                                                         |
| 重写 `pm_memory`，决策前 RECALL、choose 后 ENCODE；仍保留全历史 | DS：BL 71.2 / Mem0 68.1 / A-Mem 64.2；Qwen：BL 68.6 / Mem0 68.1                               | **记忆几乎未注入**（Mem0 召回 0/89 非空）。分数接近 baseline 噪声，**不能**说明记忆有效。                                                        |
| 修 A-Mem links、Mem0 空抽取 fallback、session 解析等，读写打通 | DS：BL **67.7** / Mem0 **58.2** / A-Mem **62.2**；Qwen：BL 65.3 / Mem0 **68.6** / A-Mem 39.6* | **首次有效对照**。DS 上记忆生效后反而掉分（update miss↑、FA↑）：语义召回过期/相似线索干扰到期判断。Qwen+Mem0 唯一小幅赢（+3.3pp，FP↓、跨天略好）。A-Mem* 超时/崩 JSON，无效。 |
| 默认砍掉全周历史；只留 compact 当前步 + `[Relevant_memories]`  | DS：Mem0 **50.0** / A-Mem **52.6**；Qwen：Mem0 **62.9**（FA 33.8%）                             | 失去时间线与查询示范后更差。DS 再跌约 8–10pp；Qwen Hit 略升但误报爆炸，F1 仍低于 fixed。说明「靠记忆替代历史」当前站不住。                                        |
| A-Mem 改产品仓去重 + 短便签格式（少塞 context/keywords）        | DS：A-Mem **49.2**                                                                          | 注入更短、重复更少，但未改善「是否到期」；信息变少，分数再 −3.4pp。                                                                              |
| A-Mem 改回论文全文召回；Mem0/A-Mem 都 scrub 历史 `task_id`   | DS：Mem0 **41.4** / A-Mem **54.1**                                                          | 去 task_id 减少错误菜单锚点，但也丢掉可用线索 → Mem0 再崩。论文全文让 A-Mem 略回升（+4.9），仍远低于 baseline 67.7。                                    |


核心改动：全历史+记忆-->记忆

## 实验结果

场景：`synthetic_week_v9`；记忆 setup 为 compact（当日 plan + 当前步 + 检索记忆，非全历史）；Mem0 为关闭 `infer=False` raw fallback 后的重跑；A-Mem `top_k=5`。


| 模型            | Setup    | Set-F1    | Hit   | Event / Time hit | FA/step | update miss | cross-day miss | state / clock |
| ------------- | -------- | --------- | ----- | ---------------- | ------- | ----------- | -------------- | ------------- |
| deepseek-chat | baseline | **67.7%** | 55.6% | 63.2% / 37.5%    | 6.2%    | 55.6%       | 57.1%          | 9 / 7         |
| deepseek-chat | Mem0     | **48.7%** | 34.6% | 47.4% / 4.2%     | 6.2%    | 100.0%      | 57.1%          | 0 / 0         |
| deepseek-chat | A-Mem    | **54.1%** | 40.7% | 52.6% / 12.5%    | 8.8%    | 100.0%      | 42.9%          | 0 / 0         |
| qwen3.5-397b  | baseline | **65.3%** | 58.0% | 59.6% / 54.2%    | 15.0%   | 66.7%       | 71.4%          | 26 / 24       |
| qwen3.5-397b  | Mem0     | **63.6%** | 60.5% | 61.4% / 58.3%    | 26.2%   | 77.8%       | 28.6%          | 16 / 11       |
| qwen3.5-397b  | A-Mem    | **67.1%** | 60.5% | 57.9% / 66.7%    | 18.8%   | 66.7%       | 71.4%          | 17 / 14       |


- ds偏保守，qwen更敢执行
- ds、qwen查询次数显著降低
- mem0可以一定程度降低qwen的cross-day miss
- ds的update miss显著提高
- 误报增多



## 结果分析

1. 召回的只是语义相似记忆，反而误导agent
  e.g. 已做完的事仍被当成记忆注入
2. query次数为0:无序相似召回，没有baseline的全历史时间线，所有线索地位等同；缺少过往历史查询示范
3. 检索不到update信息：根据当前场景观察检索，改期信息查询不到

以周六 d6_s6（mailroom 海报筒）为例：vignette 是 tube on shelf，该做 Pick up the poster tube；召回却是：
周三已 did: Pick up the handout packet
周四已 did: Collect the parcel
周一已 did: Grab the grocery bag / Return the library book
各种「parcel / pickup / shelf / delivery」相似情节

## 改进方案

写入：外部memory上存：摘要；触发事件；相关channel+channel状态+状态对应时间；任务状态（pending / done / canceled ） ；时间（跨天任务时间也标注跨天）

更新：判断observation里是否有cancel/reschedule,若出现立刻更新记忆库对应任务

检索：

1. 找到status=pending;
2. 查时间，用时间筛一遍time-based的; （时间筛）
3. 用当前observation筛event-based的；（event筛）
4. 查询相关channel状态，更新到memory里，并筛选到期任务；（channel筛）
5. 把今日代办+可能到期与当前action menu对比，与任务叙述对齐再注入

- 直接调用一些工具？  
e.g.  
time-based任务记录到日历里，日历有提醒功能直接提醒agent  
event-based让event状态更新时提醒agent

### 方案评价

**方向正确，且对准了实验根因。** Mem0/A-Mem 优化的是「语义相关情节是否召回」；PM-Bench 需要的是「条件意图是否仍有效 + 此刻是否到期」。该方案把记忆从 episode store 改成 prospective intention store，和详细报告 §4.2 一致。

| 点 | 判断 |
|---|---|
| 结构化字段（summary / trigger / channel / status / time） | 必要。没有 status，done 线索会继续当 due 注入（周六 parcel 例）。 |
| observation 上立刻 cancel/reschedule/override | 必要。专治 update miss。 |
| pending → 时间筛 → event 筛 → channel 筛 → menu 对齐 | 正确检索顺序；比 top-k 向量相似更贴近到期判定。 |
| 「日历/事件提醒工具」 | 概念对，但不要接真实日历 API。本 bench 等价物是 TIME-DUE / EVENT-CUED 注入 + CHECK channels 提示 `query_state`；heartbeat 可后期叠加。 |

注意：抽取不能读 scenario GT；channel 未查询前只能标「建议 query」；首版用规则抽取，复杂句可再加 LLM。

### 已落地实现

- 新 backend：`code/pm_memory/intention_store.py`
- runner：`--setup intention`
- session：intention 召回传入 day/time/observation/menu/messages
- 单测：`IntentionStoreTests`

```bash
python code/run_pm_memory.py --provider deepseek --setup intention
python code/run_pm_memory.py --provider qwen --setup intention
```

产物：`*.intentions.json` + `*.memory.jsonl`。

