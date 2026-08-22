# Cursor 项目级 `.cursor` 长程任务与自动记忆配置说明

这份文档总结了一套适用于 **项目级 Cursor 工作区** 的配置方案，目标不是只让 Agent “多跑几轮”，而是让它在一个仓库里能够：

- 自动续跑长任务
- 自动从终端提取失败摘要
- 自动更新 `scratchpad` 的关键区块
- 自动生成按轮次累积的 run memory
- 在几个小时无人值守时仍保持相对稳定的任务节奏

本文分为三部分：

1. 原理说明
2. 参数设置
3. 使用流程

---

## 1. 原理说明

### 1.1 这套机制解决什么问题

默认情况下，Cursor Agent 一轮结束后就停下。对于需要：

- 多轮改代码
- 多轮跑测试
- 按日志不断修复
- 持续几个小时推进的大任务

默认行为往往不够。项目级 `.cursor/` 配置的核心目标是让 Agent 在任务未完成时自动继续，并把失败和验证逐步沉淀成结构化工作记忆。

### 1.2 这套机制由哪些文件组成

最小组成如下：

```text
.cursor/
├── hooks.json
├── hooks/
│   └── grind.py
├── scratchpad.md
└── rules/
    └── grind.mdc
```

作用分工：

- `hooks.json`：声明 stop hook 和循环边界
- `hooks/grind.py`：自动续跑、日志提取、scratchpad 自动更新、run memory 落盘
- `scratchpad.md`：当前任务的结构化工作记忆
- `rules/grind.mdc`：告诉 Agent 多步任务必须维护 scratchpad

### 1.3 stop hook 如何形成循环

工作机制是：

1. Agent 一轮结束
2. Cursor 触发 `stop` hook
3. `grind.py` 读取 `.cursor/scratchpad.md`
4. 若 `STATUS` 仍是 `in_progress`，则输出：

```json
{ "followup_message": "..." }
```

5. Cursor 自动把这条消息作为下一轮用户消息再次提交
6. Agent 继续工作
7. 直到 `STATUS` 变成 `DONE`
8. hook 输出 `{}`，对话正常结束

### 1.4 为什么要用 scratchpad

`scratchpad` 不是普通笔记，而是这个任务的：

- 目标面板
- 当前步骤面板
- 失败面板
- 验证面板
- 负知识面板

它承载的是**任务级工作记忆**，而不是长期知识库。

### 1.5 当前自动化版本已经做到什么

当前版本的 `grind.py` 已经不是“只会自动续跑”的 stop hook，而是一个更完整的无人值守任务循环器。它会：

1. 检查 `STATUS`
2. 自动继续未完成任务
3. 优先读取 `Last Failure`
4. 若 `Last Failure` 仍是模板占位：
   - 先读当前工作区的**活跃终端**
   - 读不到高质量错误，再退回到当前工作区的其他最近终端
5. 自动过滤部分终端噪音：
   - `node_modules`
   - `Add-Content`
   - `timeout_millis`
   - `No failure here`
   - `Everything OK`
6. 自动把错误沉淀到 `Last Failure`
7. 自动补全或刷新：
   - `Current Step`
   - `Validation`
   - `Learnings / Do Not Repeat`
8. 每轮写一份 run memory 到：

```text
.cursor/run-memory/
```

### 1.6 现在有哪些内容是自动的

当前自动化覆盖：

- `Last Failure`
- `Current Step` 候选
- `Validation`
- 部分 `Learnings / Do Not Repeat`
- 每轮 run memory 记录

其中：

- `Last Failure` 来自最近高信号日志
- `Current Step` 优先取第一条未勾选 Checklist；否则根据错误生成一个最小修复方向
- `Validation` 根据最近终端命令、退出状态和错误摘要自动写回
- `Learnings` 只做保守推断，例如：
  - 路径类错误
  - timeout 类错误
  - 权限 / 连接类错误
  - 缺依赖 / 缺模块类错误

### 1.7 这套机制适合怎样的任务

特别适合：

- 修 bug
- 跑测试
- 对终端错误做多轮修复
- 项目级重构
- 夜间无人值守推进

不太适合：

- 单轮就能完成的小任务
- 只问答不改代码的任务
- 需要大量人工判断业务方向的开放性任务

### 1.8 当前能达到的程度

如果满足下面这些条件：

- `Goal` 写得清楚
- `Checklist` 拆得比较细
- 有稳定的验证命令或终端报错
- 任务主要是修 bug / 修测试 / 修环境 / 修路径 / 修依赖
- `loop_limit` 设置得足够高（例如 `20` 或 `30`）

那么当前版本已经可以达到：

- **连续几个小时推进单个项目任务**
- **在用户离线或睡觉时继续多轮修复**
- **自动记录每轮失败与验证轨迹**
- **把终端错误沉淀成结构化任务记忆**
- **在第二天保留可回看的 run memory**

更保守地说，它已经具备：

- “夜间长程推进能力”
- 但还不是“完全自治、可以无限放心托管一整夜的自治系统”

#### 可以放心交给它的场景

- 有明确报错的 bug fix
- 有清楚输入输出的测试修复
- 有明确验证命令的环境问题
- 有稳定 terminal 反馈的路径/依赖问题

#### 仍然容易跑偏的场景

- 高度开放的产品设计题
- 需要大量人工业务判断的规划题
- 没有稳定验证命令的复杂重构
- 多系统耦合、错误来源高度不确定的场景

### 1.9 它离理想目标还差哪些

理想中的目标不是“多跑几轮”，而是：

- 真正的 overnight autonomous mode
- 能稳定工作一整夜
- 自动归档、自动收尾、自动切到下一轮
- 连续多轮同类错误时会自动降风险、缩范围
- 能区分“应该继续修”与“应该停下来等人介入”

当前版本距离这个理想状态，还差几个关键能力：

#### 1. 自动收尾与重置

现在任务完成后，仍需要：

- 把 `STATUS` 改成 `DONE`
- 再把 scratchpad 重置回模板

如果不做，下一任务会被旧任务污染。

#### 2. 防空转保护

当前版本虽然能连续推进，但如果：

- 连续多轮命中同一类错误
- 或同一验证反复失败

它还没有内建“自动降级策略”，例如：

- 自动缩小范围
- 自动切换更保守策略
- 自动提示“已连续 N 轮无实质进展”

#### 3. 更强的根因判断

现在的：

- `Root-cause guess`
- `Fix attempt`
- `Learnings`

都还是启发式生成，不是严格的因果判断。

#### 4. 跨任务长期知识库

当前只有：

- `scratchpad`
- `run-memory`

它们更像任务级记忆，还不是长期、可检索、跨任务复用的知识系统。

### 1.10 这不是永久知识库

这套机制提供的是**任务级工作记忆**，不是跨任务、跨仓库的长期知识库。

它的定位是：

- 一个任务里持续数小时地保留上下文和失败轨迹
- 任务结束后应归档或重置
- 否则会污染下一个任务

---

## 2. 参数设置

### 2.1 `hooks.json` 示例

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "command": "python -X utf8 .cursor/hooks/grind.py",
        "timeout": 20,
        "loop_limit": 5
      }
    ]
  }
}
```

### 2.2 参数说明

#### `command`

```json
"command": "python -X utf8 .cursor/hooks/grind.py"
```

作用：

- 在 stop 时执行 `grind.py`
- `-X utf8` 用于减少 Windows 编码问题

#### `timeout`

```json
"timeout": 20
```

作用：

- 限制 hook 最长运行时间

建议：

- `10 ~ 30` 秒通常够用
- 当前版本 hook 会读 scratchpad、扫终端、写 run memory，保守建议不要低于 `10`

风险：

- 太短：hook 处理不完
- 太长：每轮结束时等待时间变长

#### `loop_limit`

```json
"loop_limit": 5
```

作用：

- 限制 stop hook 自动 follow-up 的最大轮数

建议：

- `5`：保守默认
- `20` / `30` / `50`：更适合长程无人值守任务
- `null`：无限自动续跑

风险：

- `5` 太小：长任务容易半路停下
- `30` 左右：较平衡
- `null` 风险最大：如果 Agent 忘了写 `DONE`，会一直跑，带来费用、失控循环和错误放大

### 2.3 `scratchpad.md` 模板

推荐模板：

```md
# Scratchpad

STATUS: idle

多步实现任务开始时，把 STATUS 改成 `in_progress` 并填写下面各节。
全部完成后改成 `DONE`。普通问答保持 `idle`，stop hook 不会自动续跑。

## Goal

（空）

## Checklist

- [ ]

## Current Step

（当前正在推进的唯一下一步）

## Last Failure

- Error / symptom: （最近一次关键报错或失败现象）
- Root-cause guess: （当前对原因的判断）
- Evidence: （日志 / 测试 / 文件路径）
- Fix attempt: （这轮准备怎么改）

## Learnings / Do Not Repeat

- （已证伪的方法、不要再试的路）

## Validation

- Last check run: （最近跑了什么验证）
- Result: （pass / fail + 摘要）
- Next check: （下一次准备跑什么）

## Notes

（空）
```

### 2.4 `grind.py` 自动更新策略

当前版本的自动更新策略如下：

#### `Last Failure`

优先级：

1. 使用用户或 Agent 已写入的 `Last Failure`
2. 否则从活跃终端抓错误
3. 否则从当前工作区其他终端抓错误
4. 若抓到，则自动写回 `Last Failure`

#### `Current Step`

优先级：

1. 保留已有真实内容
2. 若仍是模板占位，则优先选择第一条未勾选 Checklist
3. 若 Checklist 也不够，则根据当前错误生成一个“最小修复 + 最小验证”的候选步骤

#### `Validation`

自动写回：

- `Last check run`
- `Result`
- `Next check`

依据：

- 活跃命令 / 最近命令
- 最近错误摘要
- 最近退出码

#### `Learnings / Do Not Repeat`

只做保守自动追加，不会做太激进的推理。

例如：

- 路径错误 -> 不要在未确认目录存在前反复重跑
- timeout -> 不要直接全量重跑长耗时验证
- 连接/权限错误 -> 先检查外部条件
- 缺依赖 -> 先补齐环境前置条件

### 2.5 `run-memory` 目录

当前版本会在每轮 stop hook 结束时写一份：

```text
.cursor/run-memory/<timestamp>-loop-xx.json
```

这份文件会记录：

- loop 次数
- hook 状态
- 当前工作区
- 使用了哪个终端
- 抓到的失败摘要
- 当轮的 Goal / Current Step / Last Failure / Learnings / Validation

它的作用是：

- 为长程任务提供轮次历史
- 便于第二天人工回看
- 减少只靠一个 scratchpad 的信息损耗

### 2.6 `.cursor/rules/grind.mdc`

规则文件的作用是告诉 Agent：

- 多步任务必须维护 scratchpad
- 没完成不能随意停
- 长程任务应围绕 `Goal / Checklist / Current Step / Last Failure / Validation` 推进

没有规则文件时，hook 可以续跑，但 Agent 不一定会稳定按这套节奏行事。

---

## 3. 使用流程

### 3.1 一个新项目从零开始如何配置

如果一个人第一次用 Cursor 打开一个新文件夹，而 `.cursor/` 完全是空的，推荐按以下步骤：

1. 创建目录：

```text
.cursor/
.cursor/hooks/
.cursor/rules/
```

2. 写入 `hooks.json`
3. 写入 `hooks/grind.py`
4. 写入 `scratchpad.md`
5. 写入 `rules/grind.mdc`
6. 重开 Cursor 或等待 hooks 自动热加载

### 3.2 开始一个长程任务时，scratchpad 该怎么填

#### 第一步：把状态改成运行中

把：

```md
STATUS: idle
```

改成：

```md
STATUS: in_progress
```

#### 第二步：填写任务目标

```md
## Goal

修复 Nemi Coach 真实 pytest 空跑问题，并让 run-pytest 正常返回 cases。
```

#### 第三步：拆 Checklist

```md
## Checklist

- [ ] 复现 PATH_INVALID
- [ ] 找到 snapshot source 失效原因
- [ ] 修复路径问题
- [ ] 重跑真实 pytest
- [ ] 验证 cases 正常返回
```

#### 第四步：写一个唯一的当前步骤

```md
## Current Step

检查最近一次真实 pytest 使用的 snapshot root 是否已经漂移
```

如果这里不写，hook 会尝试自动填，但手工写通常更准。

#### 第五步：如果已经知道失败，可先手工填 `Last Failure`

```md
## Last Failure

- Error / symptom: PATH_INVALID Snapshot source must be a real readable directory.
- Root-cause guess: canonical_root 指向已失效的 zip mirror。
- Evidence: QA run 0 条结果，pytest 未实际开始 collect。
- Fix attempt: 重导入项目并校验 snapshot source。
```

如果你不填，hook 会尝试自动从终端生成并回填。

### 3.3 任务运行中，哪些内容会自动维护

当前版本的目标就是尽可能减少夜里手工介入。

如果你睡觉或暂时离开，系统会尽量自动做这些事：

- 自动续跑
- 自动提取最近错误
- 自动沉淀 `Last Failure`
- 自动更新 `Validation`
- 自动从 Checklist 里挑下一步，写入 `Current Step`
- 自动追加保守型 `Learnings`
- 自动写 run memory

这意味着：

- 你不需要半夜起来手动补 `Last Failure`
- 也不需要每轮手动写验证结果
- 但如果白天在场，手动补充更高质量的 `Root-cause guess` 和 `Fix attempt` 仍然值得

### 3.4 用户在场时推荐每轮做什么

人在场时，最佳实践仍然是：

1. 如果发现新错误，精修 `Last Failure`
2. 如果某个方法被证伪，写进 `Learnings / Do Not Repeat`
3. 如果当前步骤完成，勾选一项 Checklist
4. 把 `Current Step` 调整成新的唯一下一步
5. 把最近验证结果检查一遍，必要时微调 `Validation`

### 3.5 如果完全不手动更新，会发生什么

当前版本不是“完全失明式自动化”，而是“自动兜底 + 可人工增强”。

如果用户完全不补：

1. hook 仍会继续工作
2. `Last Failure` 会自动从日志沉淀
3. `Validation` 会自动更新
4. `Current Step` 会从 Checklist 或错误中自动推导
5. `Learnings` 会根据错误类型保守追加
6. 每轮信息会写进 `run-memory`

因此它已经适合睡觉期间继续推进长程任务。

### 3.6 任务跑完后，scratchpad 如何重置

任务完成后，至少做两步：

#### 第一步：改成完成

```md
STATUS: DONE
```

这样 stop hook 才会输出 `{}`，不再继续续跑。

#### 第二步：重置为模板

建议清空：

- `Goal`
- `Checklist`
- `Current Step`
- `Last Failure`
- `Learnings / Do Not Repeat`
- `Validation`
- `Notes`

然后把 `STATUS` 改回：

```md
STATUS: idle
```

否则下一个任务会被上一个任务污染。

### 3.7 最推荐的收尾方式

比“直接清空”更好的方式是：

1. 保留 `.cursor/run-memory/` 中的历史轮次
2. 如有必要，另存一份本次 `scratchpad` 为归档
3. 再把主 `scratchpad.md` 重置成模板

例如：

```text
.cursor/scratchpad.md
.cursor/run-memory/2026-08-18T16-07-39-loop-01.json
.cursor/run-memory/2026-08-18T16-22-10-loop-02.json
```

### 3.8 安全风险与注意事项

#### 风险 1：`loop_limit = null`

效果：

- 无限自动续跑

风险：

- Agent 忘了写 `DONE` 会一直运行
- 费用不可控
- 错误可能反复放大
- 第二天醒来可能已经走偏很多轮

建议：

- 默认不要用 `null`
- 更推荐 `20`、`30`、`50`

#### 风险 2：过度依赖自动推理

效果：

- hook 可以自动补很多内容

风险：

- 自动补的 `Root-cause guess` 只是启发式，不是事实证明
- `Learnings` 也只是保守总结，不应被视为绝对真理

建议：

- 自动化负责“不断推进”
- 人在场时负责“提升判断质量”

#### 风险 3：Checklist 太粗

效果：

- Agent 不知道什么是最小下一步

风险：

- 自动循环会浪费在大而空的步骤上

建议：

- Checklist 拆成 3 到 10 个可验证小项
- `Current Step` 永远只保留一个动作

#### 风险 4：任务结束后不重置 scratchpad

风险：

- 旧任务污染新任务
- 下一个 follow-up 会引用错误的失败、验证和步骤

建议：

- 任务结束立即 `DONE`
- 再重置为 `idle` 模板

---

## 建议的默认配置

对于大多数希望让 Cursor 跑长任务的人，推荐：

- `timeout: 20`
- `loop_limit: 20`（如果任务明显偏长）
- 结构化 `scratchpad` 模板
- 开启自动日志沉淀
- 开启 `run-memory`

如果只是轻量尝试：

- `loop_limit: 5`

如果是夜间无人值守但又不想失控：

- `loop_limit: 20 ~ 30`

---

## 一句话总结

这套项目级 `.cursor` 配置的本质，不只是让 Agent “自动继续”，而是把：

**终端日志 -> 结构化 scratchpad -> 下一轮动作 -> run memory 归档**

这个闭环自动化起来。

它已经可以支持几个小时的连续项目工作；只要任务开始前正确填写 `Goal` 与 `Checklist`，任务结束后正确 `DONE` 并重置，整套机制就能显著提高 Cursor 处理长程任务的连续性、可回溯性和自动化程度。
