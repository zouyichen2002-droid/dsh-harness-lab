# -*- coding: utf-8 -*-
"""评测用的假 Worker 共用部分（学 harness · 评测台，2026-10-23）。

真 Worker（worker/cover_run.py、worker/video_run.py）要跑十几分钟；评测评的是 Agent 怎么用工具，不评扒谱 / 渲染本身 →
假 Worker 照真 Worker 和插件之间的契约写文件（进度一行一个 JSON、跑完写汇总），插件分不出真假，插件代码不用改。

环境变量（启动 DSH 时设，插件起子进程时原样传下来）：
    SV_EVAL_SECONDS   整个任务假装跑多久（秒，默认 20）
    SV_EVAL_FAIL      在哪一步失败（步名，比如「分离」）；不设就成功
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")


def stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Progress:
    """照真 Worker 的格式往 日志\\<进度文件> 追加：{"时间", "秒", "步", "状态", "说明"}。"""

    def __init__(self, project: pathlib.Path, name: str):
        self.file = project / "日志" / name
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self.steps: list[dict] = []

    def note(self, step: str, state: str, why: str = "") -> None:
        row = {"时间": stamp(), "秒": round(time.time() - self.t0, 1), "步": step, "状态": state, "说明": why}
        self.steps.append(row)
        with self.file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{row['秒']:7.1f}s] {step} {state} {why}", flush=True)


def plan() -> tuple[float, str | None]:
    secs = float(os.environ.get("SV_EVAL_SECONDS", "20"))
    fail = os.environ.get("SV_EVAL_FAIL") or None
    return max(0.0, secs), fail


def run_steps(prog: Progress, steps: list[tuple[str, str]], total: float, fail: str | None) -> dict | None:
    """一步一步假装跑；到了 fail 那一步写「失败」、返回失败的汇总，否则返回 None。"""
    each = total / max(1, len(steps))
    for step, done_note in steps:
        prog.note(step, "开始", "（评测演练）")
        time.sleep(each)
        if fail and step == fail:
            why = f"（评测演练：故意在「{step}」失败）退出码 1"
            prog.note(step, "失败", why)
            return {"结果": "失败", "步": step, "原因": why, "各步": prog.steps}
        prog.note(step, "完成", done_note)
    return None


def write_json(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
