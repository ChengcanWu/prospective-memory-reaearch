# Prospective Memory

在 [PM-Bench](https://github.com/genglinliu/PMBench) 上评估 LLM agent 的前瞻记忆：延迟意图何时执行、如何改期/取消，以及是否主动查询隐藏通道。

本仓库当前快照是 **intention v5.0**（结构化意图库 + Scene Judge）。主实验是 `--setup intention`；baseline 可直接对照。Mem0 / A-Mem 对照代码在树里，但第三方库没有一并打包，clone 后默认跑不了。

deepseek-chat 上该版大约：Set-F1 74.3%，Hit 64.2%，Time hit 79.2%，Update miss 55.6%，Cross-day miss 42.9%。版本说明见 [`docs/notes/intention.md`](docs/notes/intention.md)，实现对照见 [`docs/notes/intention_impl.md`](docs/notes/intention_impl.md)。

## 环境要求

- Python 3.10+
- 一次完整周实验会多次调用 LLM，需要自备 API key（时间和费用都不低）

## 快速开始

在仓库根目录：

```bash
# 1. 解压基准数据（zip 顶层是 PMBench/ 与 TriggerBench-Official/）
mkdir -p data
unzip data.zip -d data

# 2. 安装依赖（intention / baseline 只需 openai）
pip install -r requirements.txt

# 3. 填 API key（.env 已被 gitignore，不要提交）
cp .env.example .env
# 编辑 .env：至少填 DEEPSEEK_API_KEY 或 QWEN_API_KEY

# 4. 确认 provider 已读到 key
python code/run_pm_memory.py --list-providers

# 5. 跑结构化意图库（当前主实验，整周 LLM）
python code/run_pm_memory.py --provider deepseek --setup intention
```

产物默认写到 `data/PMBench/runs/`。可用 baseline 对照：

```bash
python code/run_pm_memory.py --provider deepseek --setup baseline
python scripts/smoke_llm.py --provider deepseek   # 只测 API 连通，不跑整周
```

`--setup mem0` / `--setup amem` 还需要自行放入 `third_party/mem0-main`、`third_party/A-mem-main` 并安装其依赖；本快照只带了 `third_party/amem-paper/memory_layer.py`。

## 目录

```text
.
├── code/                      # 实验入口与记忆后端
│   ├── run_pm_memory.py
│   ├── llm_env.py             # 从仓库根 .env 读 API
│   └── pm_memory/             # intention / baseline / mem0 / amem
├── scripts/                   # 分析、probe、连通性检查
├── docs/notes/                # 实验记录与 intention 实现说明
├── docs/paper/                # 论文草稿
├── docs/literature/           # 文献笔记与 PDF
├── research/                  # 更早整理的文献笔记
├── data.zip                   # PM-Bench / TriggerBench，需解压到 data/
├── data/slices/               # 切片占位；完整基准不在 git 树里
├── third_party/amem-paper/    # A-Mem 实验用 memory_layer
├── .env.example
└── requirements.txt
```

解压后 runner 依赖这些路径：

- `data/PMBench/data/synthetic_week_v9.json`
- `data/PMBench/sim/pm_bench.py`

## 密钥

`.env.example` 里的空字段需要自己填。不要把真实 key 写进 git。

```text
DEEPSEEK_API_KEY=...
# 或
QWEN_API_KEY=...
```

模型 / URL 可用 CLI 覆盖，例如 `--model deepseek-chat`、`--base-url https://api.deepseek.com/v1`。

## 本快照刻意没有带上的东西

- `data/PMBench` 的 git 历史（用 `data.zip` 代替）
- 指向开发机绝对路径的 `third_party/mem0-main`、`A-mem-main` 符号链接
- 单元测试目录（README 旧稿里的 `tests/test_bugfixes.py` 不存在）
