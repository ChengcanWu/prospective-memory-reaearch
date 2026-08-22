# Prospective Memory

在 PM-Bench 上评估 LLM agent 的前瞻记忆（prospective memory）：延迟意图何时执行、如何改期/取消，以及是否主动查询隐藏通道。

主方法是 `--setup intention`（结构化意图库）。同时保留 baseline / Mem0 / A-Mem 对照。

## 目录结构

```text
.
├── code/                  # 源码与主入口
│   ├── run_pm_memory.py   # 实验 runner
│   ├── llm_env.py         # 从仓库根 .env 读 API
│   └── pm_memory/         # 记忆后端（intention / mem0 / amem）
├── tests/                 # 不连网的单元测试
├── scripts/               # 批量实验、LLM 连通性检查
├── docs/
│   ├── notes/             # 实验记录与实现说明
│   ├── paper/             # 论文草稿
│   └── literature/        # 相关论文笔记与 PDF
├── data/                  # 基准仓库（含子模块）与实验产物
│   ├── PMBench/
│   └── TriggerBench-Official/
└── third_party/           # 第三方记忆库
    ├── mem0-main          # 符号链接
    ├── A-mem-main         # 符号链接
    └── amem-paper/        # 实验用的 A-Mem memory_layer
```

`data/PMBench` 与 `data/TriggerBench-Official` 是独立 git 仓库（gitlink）。实验日志写在 `data/PMBench/runs/`。

## 环境

```bash
cp .env.example .env   # 填入 API key
pip install -r requirements.txt
```

Mem0 / A-Mem 还需各自依赖，见 `third_party/mem0-main` 与 `third_party/A-mem-main`。

## 运行

```bash
# 已配置的 provider
python code/run_pm_memory.py --list-providers

# 结构化意图库（当前主实验）
python code/run_pm_memory.py --provider deepseek --setup intention

# 对照
python code/run_pm_memory.py --provider deepseek --setup baseline
python code/run_pm_memory.py --provider deepseek --setup mem0
python code/run_pm_memory.py --provider deepseek --setup amem

# 单测（不调用 LLM）
python tests/test_bugfixes.py
```

实现细节见 [`docs/notes/intention_impl.md`](docs/notes/intention_impl.md)，版本实验记录见 [`docs/notes/intention.md`](docs/notes/intention.md)。
