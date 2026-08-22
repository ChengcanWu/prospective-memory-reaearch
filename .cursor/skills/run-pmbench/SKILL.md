---
name: run-pmbench
description: >-
  Run or summarize PM-Bench memory experiments (intention / baseline / mem0 / amem),
  read *.score.md, and locate run artifacts. Use when the user asks to 跑实验,
  对照分数, 看 score, list providers, or reproduce a PM-Bench run.
---

# 跑 PM-Bench / 读结果

未明确要求时 **不要** 启动完整周 LLM run。先 `python scripts/analyze_intention_run.py` 看已有分数；改进闭环见 skill `intention-iterate`。

## 入口

工作目录为仓库根。密钥来自 `.env`（见 `.env.example`）。

```bash
python code/run_pm_memory.py --list-providers
python code/run_pm_memory.py --provider deepseek --setup intention
python code/run_pm_memory.py --provider qwen --setup baseline
python code/run_pm_memory.py --provider deepseek --setup mem0
python code/run_pm_memory.py --provider deepseek --setup amem
python scripts/smoke_llm.py --provider deepseek
```

`--setup` 必填（除 `--list-providers`）。模型/URL 用 `--model` / `--base-url` 覆盖 `.env`。

Intention 常用开关：`--no-force-check-time`、`--no-intention-llm-update`、`--no-intention-llm-extract`、`--no-intention-llm-match`。

Mem0 + DeepSeek 会自动走 Qwen embedding，需 `MEM0_EMBED_API_KEY`。

连通性：`python scripts/smoke_llm.py --provider <name>`。

## 产物

默认 `data/PMBench/runs/<setup>/<model>/<run_name>/`（runner 按 `out_dir` / provider 再分子目录）。一次 intention run 常见文件（同一目录、同一 stem；`run.log` 常在上一级模型目录）：

| 文件 | 内容 | 低分时怎么用 |
| --- | --- | --- |
| `*.score.md` | Set-F1 / Hit / Time hit / Update miss / Cross-day miss / state÷clock | 只用来选 family，不要停在这里 |
| `*.jsonl` | 逐步 `choice` / `task_ids` | 这条 GT 有没有被点 |
| `*.intentions.json` / `.md` | 意图库终态快照 | 跑完后库里还在不在、status |
| `*.intentions.steps.jsonl` | 每步 recall/encode | 该 `day`+`sN` 的库、注入、Update、标 done；recall 含 `filter_trace` |
| `*.intentions.filters.md` | 每步 time/event/watch 与代码筛掉了谁 | `python scripts/show_intention_filter.py --day Wednesday --step s4` |
| `*.memory.jsonl` | session 注入、是否 `force_check_time` | choose 实际看见了什么 |
| `run.log` | 逐步 vignette / 菜单 / 动作 | 场景和选项原文 |

分数低时：`python scripts/analyze_intention_run.py --run <dir>` 取 examples，再按 `task_id` / `dN_sM` 去上述日志里追，对照 `intention.md` 计划是否真的跑到了（skill `intention-iterate` Step 1b）。不要为了分析重跑整周。

对照历史数字时读 `docs/notes/intention.md` 与 `docs/notes/report.md`，不要只报最新一次绝对值。

## 批量脚本

`scripts/run_all_memory_exps.sh` 绑了另一台机器上的 venv 路径，默认不要跑；用户要批量时先改 `VENV`。
