# -*- coding: utf-8 -*-
"""dsh-harness-lab · 评测框架（通用部分，和具体的插件 / 任务无关）。

一个「任务」是一个函数 make(ws, run) -> dict：
    turns     发给 Agent 的几句话（第 2 句起模拟用户的回复）
    setup     可选：callable(ws, run, data)，造起始状态（项目文件夹、要用的文件……）
    env       可选：这个任务额外的环境变量（比如让假的后台程序在某一步失败）
    checks    [(条件名, callable(log) -> bool)]：全自动判对，读会话日志（Log）和工作区状态
一遍 = 新建 runs/<时间>/<任务>_<k>/{ws, data}，cd ws 跑 `node <dsh 启动文件> --profile <配置档> <脚本.json>`，
再读会话日志打分。配置档要用本仓库的评测执行器（eval-runner）：一个进程里连着发几句、每句等后台任务跑完。

机器相关的都从环境变量读（不写死路径）：
    DSH_LAB_DSH_ENTRY   DSH 的启动文件（npm 装的：<安装目录>/node_modules/@deepseek-ai/dsh/lib/bin.js）
    DSH_HOME            DSH 的数据目录（配置档、会话日志在这里）
    DSH_LAB_PROFILE     用哪个配置档（默认 headless）
    DSH_LAB_KEY_FILE    模型服务密钥文件（可选）；读进 DSH_LAB_KEY_ENV（默认 LOCAL_LLAMA_KEY）给配置档用，不打印
    DSH_LAB_RUNS        结果放哪（默认 ./runs）
    DSH_LAB_WINDOW      模型的上下文窗口（默认 32768，算「上下文最高占多少」用）
每一遍的 data 目录通过 DSH_LAB_DATA 传给配置档（插件的数据目录可以指过去）。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Callable

sys.stdout.reconfigure(encoding="utf-8")


def need(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"要先设环境变量 {name}（见 eval/dshlab.py 开头的说明）")
    return v


# ---------------------------------------------------------------- 会话日志

def load_log(session_id: str, dsh_home: str | None = None) -> list[dict]:
    """读 DSH 的会话日志（session.v4.jsonl.zstd：几个 zstd 帧接在一起）。"""
    import zstandard as zstd
    home = pathlib.Path(dsh_home or need("DSH_HOME"))
    hits = glob.glob(str(home / "sessions" / "**" / session_id / "session.v4.jsonl.zstd"), recursive=True)
    if not hits:
        return []
    with open(hits[0], "rb") as f:
        data = zstd.ZstdDecompressor().stream_reader(f, read_across_frames=True).read()
    return [json.loads(l) for l in data.decode("utf-8").splitlines() if l.strip()]


class Log:
    """会话日志按「第几句用户的话」分段：段 i = 第 i 句用户消息之后、第 i+1 句之前的所有事件（包括后台任务唤醒的那几轮）。"""

    def __init__(self, events: list[dict], window: int | None = None):
        self.ev = events
        self.window = window or int(os.environ.get("DSH_LAB_WINDOW", "32768"))
        self.seg: list[int] = []
        k = -1
        for e in events:
            if e.get("type") == "user/message" and (e.get("data", {}).get("source") or {}).get("kind") == "user":
                k += 1
            self.seg.append(k)

    def calls(self, name: str | None = None, turn: int | None = None) -> list[dict]:
        """工具调用：{turn, name, args, error, result}。"""
        out = []
        results = {e["data"]["message"].get("toolCallId"): e for e in self.ev if e.get("type") == "tool/result"}
        for e, k in zip(self.ev, self.seg):
            if e.get("type") != "tool/call" or (turn is not None and k != turn):
                continue
            d = e["data"]
            if name is not None and d.get("name") != name:
                continue
            try:
                args = json.loads(d.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": d.get("arguments")}
            r = results.get(d.get("callId"))
            out.append({"turn": k, "name": d.get("name"), "args": args, "error": bool(r and r["data"]["message"].get("isError")),
                        "result": "".join(b.get("text", "") for b in (r["data"]["message"].get("content") or []) if isinstance(b, dict)) if r else ""})
        return out

    def texts(self, turn: int | None = None) -> list[str]:
        out = []
        for e, k in zip(self.ev, self.seg):
            if e.get("type") == "assistant/message" and (turn is None or k == turn):
                t = "".join(b.get("text", "") for b in e["data"]["message"].get("content", []) if b.get("type") == "text")
                if t.strip():
                    out.append(t)
        return out

    def last_text(self, turn: int | None = None) -> str:
        t = self.texts(turn)
        return t[-1] if t else ""

    def asked(self, turn: int) -> bool:
        """这一段里有没有向用户提问：调了 ask_user_question，或回复以问句结尾 / 在征求同意。"""
        if self.calls("ask_user_question", turn):
            return True
        return any(re.search(r"[？?]\s*$", t.strip()) or re.search(r"(可以吗|要不要|是否|确认一下|请确认|同意吗)", t) for t in self.texts(turn))

    def tools_offered(self) -> list[str]:
        """第一次请求时 Agent 拿到的工具名（核对工具集用）。"""
        h = next((e for e in self.ev if e.get("type") == "request/header"), None)
        return sorted(t.get("name") for t in ((h or {}).get("data", {}).get("header", {}).get("tools") or []))

    def metrics(self) -> dict:
        steps = sum(1 for e in self.ev if e.get("type") == "step/start")
        us = [e["data"].get("usage") or {} for e in self.ev if e.get("type") == "assistant/message"]
        inp = sum(u.get("inputTokens", 0) for u in us)
        cache = sum(u.get("cacheReadTokens", 0) for u in us)
        calls = self.calls()
        ends = [e["data"].get("reason", {}).get("kind") for e in self.ev if e.get("type") == "turn/end"]
        times = [e.get("time") for e in self.ev if isinstance(e.get("time"), (int, float))]
        return {"步数": steps, "工具调用": len(calls), "工具报错": sum(c["error"] for c in calls),
                "读入token": inp, "写出token": sum(u.get("outputTokens", 0) for u in us),
                "缓存命中": round(cache / inp, 3) if inp else None,
                "上下文最高": round(max((u.get("inputTokens", 0) for u in us), default=0) / self.window, 3),
                "轮结束原因": ends, "会话秒": round((max(times) - min(times)) / 1000, 1) if times else None}


def sha(p: pathlib.Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


# ---------------------------------------------------------------- 跑一遍、跑一批

def run_one(tid: str, title: str, make: Callable, k: int, out: pathlib.Path) -> dict:
    run = out / f"{tid}_{k}"
    ws, data = run / "ws", run / "data"
    ws.mkdir(parents=True)
    data.mkdir(parents=True)
    t = make(ws, run)
    if t.get("setup"):
        t["setup"](ws, run, data)
    script = run / "script.json"
    script.write_text(json.dumps({"turns": t["turns"], "turnTimeoutSec": t.get("turnTimeoutSec", 900)}, ensure_ascii=False, indent=1), encoding="utf-8")
    env = {**os.environ, "DSH_LAB_DATA": str(data).replace("\\", "/"), **t.get("env", {})}
    key_file = os.environ.get("DSH_LAB_KEY_FILE")
    if key_file:
        env[os.environ.get("DSH_LAB_KEY_ENV", "LOCAL_LLAMA_KEY")] = pathlib.Path(key_file).read_text(encoding="utf-8").strip()
    t0 = time.time()
    with open(run / "runner.out", "w", encoding="utf-8") as fo, open(run / "runner.err", "w", encoding="utf-8") as fe:
        p = subprocess.run(["node", need("DSH_LAB_DSH_ENTRY"), "--profile", os.environ.get("DSH_LAB_PROFILE", "headless"), str(script)],
                           cwd=ws, env=env, stdout=fo, stderr=fe, timeout=t.get("timeoutSec", 3600))
    wall = round(time.time() - t0, 1)
    rows = [json.loads(l) for l in (run / "runner.out").read_text(encoding="utf-8").splitlines() if l.startswith("{")]
    sid = next((r["sessionId"] for r in rows if r.get("type") == "session"), None)
    log = Log(load_log(sid) if sid else [])
    checks = []
    for name, fn in t["checks"]:
        try:
            ok = bool(fn(log))
        except Exception as e:                                 # 打分器自己出错：记下来，算没过
            ok, name = False, f"{name}（打分出错：{e}）"
        checks.append({"条件": name, "过": ok})
    res = {"任务": tid, "标题": title, "第几遍": k, "退出码": p.returncode, "总秒": wall, "会话": sid,
           "预设": next((r.get("preset") for r in rows if r.get("type") == "session"), None),
           "全过": all(c["过"] for c in checks) and bool(sid), "判对": checks, "数": log.metrics(),
           "工具数": len(log.tools_offered()), "每句": [r for r in rows if r.get("type") == "turn"]}
    (run / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def run_suite(tasks: dict, selected: list[str], repeat: int, out: pathlib.Path | None = None) -> list[dict]:
    """tasks：{id: (标题, make)}。每个任务跑 repeat 遍，写 results.json 和 结果.md。"""
    out = out or pathlib.Path(os.environ.get("DSH_LAB_RUNS", "runs")) / time.strftime("%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for tid in selected:
        title, make = tasks[tid]
        for k in range(1, repeat + 1):
            r = run_one(tid, title, make, k, out)
            results.append(r)
            print(f"{tid} 第 {k} 遍：{'过' if r['全过'] else '没过'}  {sum(c['过'] for c in r['判对'])}/{len(r['判对'])}  {r['总秒']} 秒  "
                  f"步数 {r['数']['步数']}  报错 {r['数']['工具报错']}  上下文 {r['数']['上下文最高']}", flush=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["| 任务 | 遍 | 过了几遍 | 全过 | 平均秒 | 平均步数 | 工具报错 | 上下文最高 |", "|---|---|---|---|---|---|---|---|"]
    for tid in dict.fromkeys(r["任务"] for r in results):
        rs = [r for r in results if r["任务"] == tid]
        n = sum(r["全过"] for r in rs)
        lines.append(f"| {tid} {rs[0]['标题']} | {len(rs)} | {n} | {'是' if n == len(rs) else '否'} | {sum(r['总秒'] for r in rs) / len(rs):.0f} | "
                     f"{sum(r['数']['步数'] for r in rs) / len(rs):.1f} | {sum(r['数']['工具报错'] for r in rs)} | {max(r['数']['上下文最高'] for r in rs)} |")
    (out / "结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return results
