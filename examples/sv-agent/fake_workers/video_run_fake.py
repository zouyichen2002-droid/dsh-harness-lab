# -*- coding: utf-8 -*-
"""假的 worker/video_run.py（评测台用）：参数一样、进度 / 汇总 / 产物的位置和格式一样，不真的渲染、不真的写剪映草稿。

    python video_run_fake.py <项目文件夹> --version vNN --audio <成品音频> --image <图> [--image …] --svp <工程> --drafts <草稿文件夹> [--fx …] [--side …] [--skip …]

和真的一样会失败的情况：音频、图、工程不存在；这一版的文件夹或草稿名已经用过。
产物：视频\\vNN\\<歌名>_歌词视频_vNN.mp4（空的占位）、说明.md（最后写 = 做完了）；<草稿文件夹>\\SV-Agent_<歌名>_vNN\\（只有一个说明文件）。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Progress, plan, run_steps, write_json   # noqa: E402

STEPS = [("素材", "图和成品音频拷进 视频\\vNN\\素材\\（评测演练：没拷）"), ("逐字时间", "zh：出字幕 40 行"), ("对齐", "成品和工程偏移 0"),
         ("成片", "1080p mp4（评测演练：空文件）"), ("剪映草稿", "")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--version", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--image", action="append", required=True)
    ap.add_argument("--svp", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--credit", default=None)
    ap.add_argument("--fx", default="可爱")
    ap.add_argument("--drafts", default=None)
    ap.add_argument("--side", default="auto")
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    P = pathlib.Path(a.project).resolve()
    prog = Progress(P, "视频进度.jsonl")
    total, fail = plan()
    prog.note("开始", "开始", f"《{P.name}》歌词视频 {a.version}（评测演练）")

    def failed(step: str, why: str) -> int:
        prog.note(step, "失败", why)
        write_json(P / "日志" / f"视频_{a.version}.json", {"结果": "失败", "步": step, "原因": why, "各步": prog.steps})
        return 1

    out = P / "视频" / a.version
    drafts = pathlib.Path(a.drafts) if a.drafts else None
    draft_name = f"SV-Agent_{P.name}_{a.version}"
    for what, p in [("成品音频", a.audio), *[("图", x) for x in a.image], ("工程", a.svp or "")]:
        if not p or not pathlib.Path(p).exists():
            return failed("检查", f"{what}不存在：{p}")
    if (out / "说明.md").exists() or (drafts and (drafts / draft_name).exists()):
        return failed("检查", f"{a.version} 已经用过了")
    prog.note("检查", "完成", f"工程 {pathlib.Path(a.svp).name}；音频 {pathlib.Path(a.audio).name}；画面 {len(a.image)} 个")
    bad = run_steps(prog, STEPS, total, fail)
    if bad:
        write_json(P / "日志" / f"视频_{a.version}.json", bad)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    mp4 = out / f"{P.name}_歌词视频_{a.version}.mp4"
    mp4.write_bytes(b"")
    if drafts:
        (drafts / draft_name).mkdir(parents=True, exist_ok=True)
        (drafts / draft_name / "评测演练.txt").write_text("假的剪映草稿（评测台）\n", encoding="utf-8")
    (out / "说明.md").write_text(f"# 《{P.name}》歌词视频 {a.version}（评测演练）\n\n- 成片：{mp4.name}（空文件）\n- 字幕样式：{a.fx}\n", encoding="utf-8")
    prog.note("结束", "完成", f"→ {mp4.name} + 剪映草稿「{draft_name}」")
    write_json(P / "日志" / f"视频_{a.version}.json", {
        "结果": "完成", "总秒": total, "后台用时": f"{int(total)} 秒", "成片秒": 200.0, "成片时长": "3:20", "版本": a.version, "成片": str(mp4),
        "剪映草稿": str(drafts / draft_name) if drafts else "", "工程": a.svp, "语言": "zh", "字幕行": 40, "没出字幕的行": [],
        "对齐": "成品和工程偏移 0（评测演练）", "提醒": [], "各步": prog.steps})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
