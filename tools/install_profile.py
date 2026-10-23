# -*- coding: utf-8 -*-
"""把评测补丁（模板）填好本机路径，装进 $DSH_HOME/profiles/<配置档>/cordis.patch.yml。原来的那份先备份。

    python tools/install_profile.py --dsh-home <DSH_HOME> [--profile headless] [--base-url http://127.0.0.1:8081/v1]
                                    [--model qwen3.6-35b-a3b] [--context 32768] [--key-env LOCAL_LLAMA_KEY]
                                    [--skill-dir <目录> …] [--example sv-agent --sv-bridge <sv-bridge 路径> --python <python>]

配置档要先存在（`dsh --profile headless --help` 跑一次，DSH 会从模板建出来）。装完用 `dsh --profile <配置档> --dump-config` 看合并结果。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
LAB = pathlib.Path(__file__).resolve().parent.parent
fwd = lambda p: str(pathlib.Path(p).resolve()).replace("\\", "/")   # noqa: E731


def render(text: str, values: dict[str, str]) -> str:
    out = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)] if m.group(1) in values else m.group(0), text)
    left = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", out)))
    if left:
        raise SystemExit(f"还有占位符没填：{left}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsh-home", required=True)
    ap.add_argument("--profile", default="headless")
    ap.add_argument("--base-url", default="http://127.0.0.1:8081/v1")
    ap.add_argument("--model", default="qwen3.6-35b-a3b")
    ap.add_argument("--context", type=int, default=32768)
    ap.add_argument("--key-env", default="LOCAL_LLAMA_KEY")
    ap.add_argument("--skill-dir", action="append", default=[])
    ap.add_argument("--example", default=None)
    ap.add_argument("--sv-bridge", default=None)
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()
    target = pathlib.Path(a.dsh_home) / "profiles" / a.profile / "cordis.patch.yml"
    if not target.parent.exists():
        raise SystemExit(f"{target.parent} 不存在：先跑一次 dsh --profile {a.profile} --help 让 DSH 建出这个配置档")
    skills = [fwd(d) for d in a.skill_dir]
    values = {"LAB": fwd(LAB), "BASE_URL": a.base_url, "MODEL": a.model, "CONTEXT": str(a.context), "KEY_ENV": a.key_env,
              "SKILL_DIRS": json.dumps(skills, ensure_ascii=False), "PYTHON": fwd(a.python)}
    parts = [render((LAB / "profiles" / "headless-eval.cordis.patch.yml").read_text(encoding="utf-8"), values)]
    if a.example:
        if a.example == "sv-agent":
            if not a.sv_bridge:
                raise SystemExit("--example sv-agent 要给 --sv-bridge")
            values["SV_BRIDGE"] = fwd(a.sv_bridge)
            if not skills:                                            # SV 的技能（翻唱、视频怎么做）在 sv-bridge 里
                parts[0] = parts[0].replace("customSkillDirs: []", f"customSkillDirs: {json.dumps([values['SV_BRIDGE'] + '/dsh/skills'], ensure_ascii=False)}")
        parts.append(render((LAB / "examples" / a.example / "profile.cordis.patch.yml").read_text(encoding="utf-8"), values))
    if target.exists():
        backup = target.with_name(f"cordis.patch.yml.bak-{time.strftime('%m%d%H%M%S')}")
        shutil.copy2(target, backup)
        print(f"原来的备份到 {backup}")
    target.write_text("\n".join(parts), encoding="utf-8")
    print(f"装好了：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
