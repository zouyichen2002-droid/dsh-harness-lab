# dsh-harness-lab

在 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（DSH）上学 harness agent 的实验室：用**本地模型**、**真实任务**，一次只改 harness 的一处，用同一套评测前后各跑一遍，看改动到底有没有用。

> English summary: a lab for learning agent harness engineering on top of DeepSeek Harness (DSH) with a local model (Qwen3.6-35B-A3B on llama.cpp). It contains a job-aware multi-turn headless runner for DSH, a session-log based scoring framework, a profile patch that reproduces the web surface's tool set in headless mode, and a worked example suite of 12 tasks taken from real conversations with a singing-synthesis cover workflow. Experiments change one harness layer at a time and are scored against the same baseline.

## 里面有什么

| 位置 | 是什么 |
|---|---|
| `eval-runner/` | 评测执行器（DSH 插件，替换 headless-runner）：一个进程里按脚本连着发几句话；每句等这个会话的后台任务跑完、被唤醒的那一轮也空闲才往下；新会话照网页版挂上默认预设 |
| `eval/dshlab.py` | 评测框架：读 DSH 会话日志（`session.v4.jsonl.zstd`）、按「第几句用户的话」分段、算指标（步数、工具报错、token、缓存命中、上下文占用）、跑任务、汇总 |
| `profiles/` | headless 配置档的评测补丁（模板）：本地模型、精简预设、停掉 headless 多挂的 10 个工具、换执行器 |
| `tools/install_profile.py` | 把模板填好本机路径，装进 `$DSH_HOME/profiles/<配置档>/` |
| `examples/sv-agent/` | 真实例子：12 个任务（10 个写好了）、造起始状态的工具、假的后台 Worker、挂 SV 插件的补丁 |
| `docs/` | 每一步一页：`00-评测台.md`（为什么、怎么搭、搭的时候发现了什么），之后每个实验一页 |

## 怎么用

要先有：Node 22.19+ / 24、DSH（`npm i @deepseek-ai/dsh@0.2.0-rc.2`）、一个 OpenAI 兼容的本地模型服务、Python 3.11+（`pip install zstandard`）。

```bash
# 1. 让 DSH 建出 headless 配置档（第一次）
dsh --profile headless --help

# 2. 装评测补丁（例子要再给 sv-bridge 的路径：https://github.com/zouyichen2002-droid/SV-Agent）
python tools/install_profile.py --dsh-home <DSH_HOME> --example sv-agent --sv-bridge <sv-bridge 路径>

# 3. 跑（本地模型要开着）
export DSH_HOME=<DSH_HOME>
export DSH_LAB_DSH_ENTRY=<DSH 安装目录>/node_modules/@deepseek-ai/dsh/lib/bin.js
export DSH_LAB_KEY_FILE=<模型服务密钥文件>      # 可选：读进 LOCAL_LLAMA_KEY，不打印
export SV_BRIDGE=<sv-bridge 路径>
python examples/sv-agent/tasks.py --tasks t01,t03 --repeat 3
```

结果在 `runs/<时间>/`：每一遍一个文件夹（工作区、数据、脚本、执行器输出、`result.json`），汇总在 `results.json` 和 `结果.md`。

写自己的任务：一个函数 `make(ws, run) -> {"turns": [...], "setup": fn, "env": {...}, "checks": [(名字, fn(log) -> bool), ...]}`，交给 `dshlab.run_suite`。`log` 是 `dshlab.Log`：`calls(工具名, 第几句)`、`texts()`、`last_text()`、`asked(第几句)`、`metrics()`。

## 现在到哪了

- 评测台搭好了、不开模型空跑过（执行器、预设、工具集、打分器都验过），见 [docs/00-评测台.md](docs/00-评测台.md)
- 还没跑基线

## 许可

MIT © 2026 小鳄鱼aligator。DSH 本身是 MIT（deepseek-ai/deepseek-harness），本仓库不包含它的代码，只通过它的公开插件接口和配置补丁使用它。
