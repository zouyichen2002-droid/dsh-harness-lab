# -*- coding: utf-8 -*-
"""假的 worker/cover_run.py（评测台用）：参数一样、进度 / 汇总 / 产物的位置和格式一样，不真的分离、扒谱。

    python cover_run_fake.py <项目文件夹> --round rNN --source <链接 | 本地音频 | 已有> [--lyrics none] [--octave-pick off] [--prefs-used …]

和真的一样会失败的情况：不是项目（没有 sv-project.json）；--source 已有、项目里却没有 素材\\原曲整首.wav；本地音频不存在。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Progress, plan, run_steps, stamp, write_json   # noqa: E402

STEPS = [("原曲", "原曲整首.wav"), ("歌词", "（评测演练）43 行、410 字"), ("分离", "核对通过"), ("补段", "补了 0 段、共 0 秒"),
         ("扒谱", "v2m_asr_主唱补段.mid"), ("强制对齐", "v2m_给原歌词_主唱补段.mid"), ("多声部", "basic_pitch_raw_主唱补段.json"),
         ("找拍子", "速度：100.00"), ("模板", "模板.svp"), ("生成工程", "")]


def tiny_svp(name: str, track: str) -> dict:
    """能被 SV 打开的最小工程：一条空人声轨、4/4、120 BPM（不带任何音频路径、歌词）。"""
    return {"version": 153, "time": {"meter": [{"index": 0, "numerator": 4, "denominator": 4}],
                                    "tempo": [{"position": 0, "bpm": 120.0}]},
            "library": [], "renderConfig": {"destination": "", "filename": name, "numChannels": 2},
            "tracks": [{"name": track, "dispColor": "ff7db235", "dispOrder": 0, "renderEnabled": False,
                        "mixer": {"gainDecibel": 0.0, "pan": 0.0, "mute": False, "solo": False, "display": True},
                        "mainGroup": {"name": "main", "uuid": "00000000-0000-4000-8000-000000000001", "parameters": {}, "vocalModes": {}, "notes": []},
                        "mainRef": {"groupID": "00000000-0000-4000-8000-000000000001", "blickAbsoluteBegin": 0, "blickAbsoluteEnd": -1,
                                    "blickOffset": 0, "pitchOffset": 0, "isInstrumental": False, "systemPitchDelta": {"dt": [], "dv": []},
                                    "database": {"name": "", "language": "", "phoneset": "", "languageOverride": "", "phonesetOverride": "", "backendType": ""},
                                    "dictionary": "", "voice": {}}, "groups": []}]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--round", required=True)
    ap.add_argument("--source", default="已有")
    ap.add_argument("--lyrics", default=None)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--language", default="auto")
    ap.add_argument("--octave-pick", default="on")
    ap.add_argument("--prefs-used", default="")
    ap.add_argument("--config", default=None)
    a = ap.parse_args()
    P = pathlib.Path(a.project).resolve()
    if not (P / "sv-project.json").exists():
        print(f"{P} 不是项目（没有 sv-project.json）")
        return 2
    name = json.loads((P / "sv-project.json").read_text(encoding="utf-8")).get("name") or P.name
    prog = Progress(P, "进度.jsonl")
    total, fail = plan()
    prog.note("开始", "开始", f"《{name}》{a.round}，声库 星尘（评测演练）")

    def failed(step: str, why: str) -> int:
        prog.note(step, "失败", why)
        write_json(P / "日志" / f"翻唱_{a.round}.json", {"结果": "失败", "步": step, "原因": why, "各步": prog.steps})
        return 1

    wav = P / "素材" / "原曲整首.wav"
    if a.source in ("", "已有") and not wav.exists():
        return failed("原曲", "项目里没有 素材\\原曲整首.wav，又没给来源（链接或本地音频）")
    if a.source not in ("", "已有") and not a.source.startswith(("http://", "https://")) and not pathlib.Path(a.source).is_file():
        return failed("原曲", f"本地音频不存在：{a.source}")
    if not wav.exists():                                          # 演练：只放一个占位文件，不下载、不转换
        wav.parent.mkdir(parents=True, exist_ok=True)
        wav.write_bytes(b"")
        write_json(P / "素材" / "source.json", {"曲名": name, "来源": a.source, "下载": "（评测演练：没有真的下载）", "时间": stamp()})

    bad = run_steps(prog, STEPS, total, fail)
    if bad:
        write_json(P / "日志" / f"翻唱_{a.round}.json", bad)
        return 1
    rdir = P / a.round
    rdir.mkdir(exist_ok=True)
    svp = rdir / f"{name}_扒谱_{a.round}.svp"
    svp.write_text(json.dumps(tiny_svp(name, f"扒谱 {a.round}（评测演练）"), ensure_ascii=False), encoding="utf-8")
    pick = "关" if a.octave_pick == "off" else "开"
    (rdir / "说明.md").write_text(f"# 《{name}》{a.round}（评测演练）\n\n- 挑八度：{pick}\n- 这是评测台的假工程，没有音符\n"
                                  + (f"- 记忆：{a.prefs_used}\n" if a.prefs_used else ""), encoding="utf-8")
    prog.note("生成工程", "完成", svp.name)
    prog.note("结束", "完成", f"共 {int(total)} 秒 → {svp.name}")
    stats = {"工程": str(svp), "扒出的音": 300, "歌词字数": 410, "改八度": 0 if pick == "关" else 7, "规矩": {}, "调式": "A 自然小调",
             "重复段八度": [], "语言": "中文", "挑八度": pick}
    if a.prefs_used:
        stats["用了的偏好"] = a.prefs_used
    write_json(P / "日志" / f"翻唱_{a.round}.json", {"结果": "完成", "总秒": total, "版本": a.round, "统计": stats, "各步": prog.steps})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
