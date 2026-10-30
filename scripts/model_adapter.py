#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多模型提示词适配器 · 夜秣AI短剧生成器 v2.0

同一条镜头，按目标视频模型吐出该模型的母语。
四套模板全部为夜秣原创：通用四段式 / Seedance 七段式 / MiniMax H3 六段式 / 可灵 五段式 / Wan / Veo。

用法：
  model_adapter.py <workdir> --list                    # 列出所有模板
  model_adapter.py <workdir> --model seedance          # 干跑，打印全部镜头
  model_adapter.py <workdir> --model minimax --apply   # 写到 prompts/minimax/
  model_adapter.py <workdir> --model kling --apply --force
  model_adapter.py <workdir> --convert v_c01.txt --model seedance   # 已有四段式文本转外壳

只用标准库。依赖 shots.json + asset_lock.json（先跑过 story_plan 与 asset_lock）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asset_lock  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ------------------------------------------------------------------ 模板注册表

TEMPLATES = {
    "seedance": {
        "name": "Seedance 2.5 / 2.0（即梦）七段式",
        "blocks": ["参考", "主体", "背景", "时间线", "运镜", "风格", "音频"],
        "note": "素材上限：图 ≤9 / 视频 ≤3 / 音频 ≤3 / 合计 ≤12。10 秒以上必须按时间段分写。",
        "seg": 5,          # 15 秒档建议切 5 段
        "max_sec": 30,
    },
    "minimax": {
        "name": "MiniMax H3 六段式",
        "blocks": ["主体", "动作", "场景", "运镜", "时长", "音频"],
        "note": "对白用 <d>...</d> 标签包裹；Ref2VA 每段 4–15 秒、含 2–4 个镜头。",
        "seg": 3,
        "max_sec": 15,
    },
    "kling": {
        "name": "可灵 Kling 六段式",
        "blocks": ["主体描述", "动作描述", "场景描述", "运镜", "时长", "负面提示"],
        "note": "可灵对负面提示词响应良好 —— 少数真听得懂否定的模型，别浪费。",
        "seg": 3,
        "max_sec": 10,
    },
    "wan": {
        "name": "通义万相 Wan 六段式",
        "blocks": ["主体", "动作", "场景", "运镜", "时长", "音频"],
        "note": "",
        "seg": 3,
        "max_sec": 10,
    },
    "veo": {
        "name": "Veo / Sora 五段式",
        "blocks": ["画面", "动作", "镜头", "风格", "约束"],
        "note": "",
        "seg": 3,
        "max_sec": 20,
    },
    "generic": {
        "name": "通用四段式（本技能原创，默认）",
        "blocks": ["画面", "动作", "镜头", "约束"],
        "note": "模型只抓前 30 字：把「谁在场」放最前，「不要什么」放最后。控制在 600 字内。",
        "seg": 3,
        "max_sec": 8,
    },
}

DEFAULT_MODEL = "generic"

# 内容约束（所有模型共用）
NEG = "无字幕、无水印、无文字、无 logo、无畸形肢体"

# ------------------------------------------------------------------ 中文映射

SIZE_ZH = {
    "大远景": "大远景，人物在环境中很小",
    "远景": "远景，完整展现环境与人物位置",
    "全景": "全景，人物全身与环境可见",
    "中景": "中景，人物腰部以上",
    "近景": "近景，人物胸部以上",
    "特写": "特写，人物肩部以上，面部清晰",
    "大特写": "大特写，面部或物件局部特写",
    "空镜": "空镜，画面中没有人物",
}

CAM_ZH = {
    "L0": "固定机位，镜头完全静止",
    "L1": "极缓慢推近，机位轻微前移",
    "L2": "缓慢平移，横向跟随",
    "L3": "中速推进，镜头明显前移",
    "L4": "快速冲击式运镜，短促有力",
}


def zh_size(v: str) -> str:
    v = str(v or "")
    # 派发值可能是 "L2 中速推进" 这类，取其中的景别词
    for k, s in SIZE_ZH.items():
        if k in v:
            return SIZE_ZH[k]
    return "中景，人物腰部以上"


def zh_cam(v: str) -> str:
    v = str(v or "L0")
    m = re.search(r"L([0-4])", v)
    if m:
        return CAM_ZH.get("L" + m.group(1), CAM_ZH["L0"])
    return "%s（一镜只许一种运镜）" % v if v else CAM_ZH["L0"]


def zh_light(v: str) -> str:
    v = str(v or "").strip()
    return v or "柔和自然光"


def zh_compose(v: str) -> str:
    v = str(v or "").strip()
    return v or "居中构图"


# ------------------------------------------------------------------ 分段


def join_zh(*parts) -> str:
    """中文智能拼接：自动处理句号，避免出现「文字。。全景」这种双句号"""
    seq = [str(p or "").strip() for p in parts]
    seq = [p for p in seq if p]
    if not seq:
        return ""
    s = seq[0]
    for p in seq[1:]:
        s = s + p if re.search(r"[。．.！？!?；;]$", s) else s + "。" + p
    return s


def split_acts(v: str) -> list:
    """把 v 拆成动作句。

    两级切分：先按换行，再按句号 —— 因为 shot 的 v 常写成一整段，
    不按句号切开的话，5 秒的镜头只会分到 1 段，等于没切。
    """
    out = []
    for line in str(v or "").replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            continue
        # 纯环境/氛围句不进时间轴（否则会出现「第 3 秒：柔和晨光」这种空动作段）
        if re.match(r"^(柔和|温暖|冷|光|晨|午|黄昏|夜|空气|氛围|光影)", line) and len(line) < 20:
            continue
        for seg in re.split(r"(?<=[。．.!！?？])\s*", line):
            seg = seg.strip()
            if seg:
                out.append(seg)
    return out


def timeline(dur: float, acts: list, segs: int) -> str:
    """把动作按时间轴分段"""
    if not acts:
        acts = ["画面保持轻微的自然呼吸感"]
    if dur <= 4:
        n = min(1, segs)
    elif dur <= 8:
        n = min(2, segs)
    else:
        n = segs
    n = max(1, min(n, len(acts) or 1))
    # 动作多于段数时，后面的动作并进最后一段
    per = dur / n
    parts = []
    for i in range(n):
        a = acts[i] if i < len(acts) else None
        if i == n - 1 and len(acts) > n:
            a = " ".join(acts[i:])
        t0, t1 = round(per * i, 1), round(per * (i + 1), 1)
        parts.append("第%.1f–%.1f秒：%s" % (t0, t1, a))
    return " ".join(parts)


# ------------------------------------------------------------------ 渲染


def load_cast_refs(wd) -> dict:
    """直接从 cast.json 读每个角色的单图锚定路径。

    🔴 不从 asset_lock 取 —— 锁里只存了特征指纹，没存图路径。
    """
    p = Path(wd) / "cast.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {c["name"]: c["ref_main"]
            for c in d.get("characters", [])
            if c.get("name") and c.get("ref_main")}


def build_refs(shot: dict, lock: dict, sc: dict = None) -> list:
    """收集本镜要挂的参考图。

    🔴 只收**单人的干净单图锚定**（ref_main）—— 多视图设定图 / 三视图 / 合影
    喂进去会被模型整板复刻成多人合影，是血案级踩坑。
    """
    refs = []
    chars = lock.get("chars") or {}
    for n in (shot.get("cast") or []):
        rp = str((chars.get(n) or {}).get("ref_main", "") or "").strip()
        if rp and rp not in refs:
            refs.append(rp)
    if not refs:  # 角色卡没配图，退回项目主参考图
        rp = str((sc or {}).get("ref", "") or "").strip()
        if rp:
            refs.append(rp)
    return refs


def blocks_for(model: str, shot: dict, lock: dict, sc: dict = None) -> dict:
    """生成各段落的内容；不同模板共用这些素材，只是编排不同"""
    dur = float(shot.get("dur", 4) or 4)
    names = shot.get("cast") or []
    blk = asset_lock.block_for(lock, names, lang="zh")
    style = str(lock.get("style", {}).get("text", "")).strip()

    # 🔴 ff 里被 story_plan 追加了「\n【镜头】…」一行（那是给 frame_prompt 用的），
    #    这里只取画面描述本体，否则七段式里会莫名多出一个【镜头】段。
    ff = re.split(r"\n?【镜头】", str(shot.get("ff", "")).strip())[0].strip()
    acts = split_acts(shot.get("v", ""))
    sfx = str(shot.get("sfx", "")).strip()

    size = zh_size(shot.get("size", ""))
    cam = zh_cam(shot.get("cam", ""))
    light = zh_light(shot.get("light", ""))
    comp = zh_compose(shot.get("compose", ""))

    # 主体：角色冻结块（逐字复用，绝不改写）
    subject = blk if blk else "本镜为空镜，画面中没有人物"
    if blk:
        subject = "%s。五官、发型、服装、体型比例与参考图完全一致" % blk

    # 场景/光位/构图归「背景」，运镜 + 景别归「运镜」—— 别让两处重复打架
    scene = join_zh(ff if ff else "室内场景", light, comp)
    tl = timeline(dur, acts, TEMPLATES[model]["seg"])
    audio = "环境音：%s。无对白（对白后期另配）" % sfx if sfx else "无对白（对白后期另配）"

    refs = build_refs(shot, lock, sc)
    ref_parts = ["@Image%d %s（角色参考图）" % (i + 1, r) for i, r in enumerate(refs)]
    if len(refs) > 9:  # Seedance 官方上限：图片 ≤9
        ref_parts.append("[WARN] 参考图 %d 张 > 9，超出素材上限" % len(refs))
    return {
        "参考": " ".join(ref_parts)
        if ref_parts else "（本镜无可复用素材时留空；空镜不需要参考图）",
        "主体": subject,
        "背景": scene,
        "时间线": tl,
        "运镜": join_zh(cam, size),
        "风格": style if style else "统一的写实风格，全片色调一致",
        "音频": audio,
        # 六段式 / 五段式 用得到的别名
        "动作": tl,
        "场景": scene,
        "时长": "%.1f 秒" % dur,
        "画面": "%s。%s" % (subject, scene),
        "镜头": "%s，%s，%s，%.1f 秒" % (size, cam, light, dur),
        "约束": "%s。%s" % (style if style else "全片风格统一", NEG),
        "负面提示": "模糊、低画质、变形、多余肢体、水印、文字、字幕",
        "主体描述": subject,
        "动作描述": tl,
        "场景描述": scene,
    }


def render(model: str, shot: dict, lock: dict, sc: dict = None) -> str:
    t = TEMPLATES[model]
    data = blocks_for(model, shot, lock, sc)
    lines = [asset_lock.header(lock, shot.get("cast") or [])]
    for b in t["blocks"]:
        lines.append("【%s】%s" % (b, data.get(b, "")))
    # 时长上限告警
    dur = float(shot.get("dur", 4) or 4)
    if dur > t["max_sec"]:
        lines.append("[WARN] 本镜 %.1fs 超过 %s 的 %ss 单段上限，必须拆镜或分段提交"
                     % (dur, t["name"], t["max_sec"]))
    return "\n".join(lines)


# ------------------------------------------------------------------ 文本转外壳


def convert_text(text: str, model: str) -> str:
    """把已有的四段式文本换成目标模型外壳（ff/v 缺失时的兜底）"""
    got = {}
    for m in re.finditer(r"【(.+?)】\s*([^\n]*(?:\n(?!【)[^\n]*)*)", text):
        got[m.group(1).strip()] = m.group(2).strip()
    t = TEMPLATES[model]
    lines = []
    if "参考" in t["blocks"]:
        lines.append("【参考】%s" % got.get("画面", "")[:0] or "【参考】（留空）")
    mapping = {
        "主体": got.get("画面", ""), "背景": got.get("画面", ""),
        "时间线": got.get("动作", ""), "运镜": got.get("镜头", ""),
        "风格": got.get("约束", ""), "音频": got.get("约束", ""),
        "动作": got.get("动作", ""), "场景": got.get("画面", ""),
        "时长": "", "画面": got.get("画面", ""), "镜头": got.get("镜头", ""),
        "约束": got.get("约束", ""), "负面提示": "模糊、变形、水印、文字、字幕",
        "主体描述": got.get("画面", ""), "动作描述": got.get("动作", ""),
        "场景描述": got.get("画面", ""),
    }
    for b in t["blocks"]:
        lines.append("【%s】%s" % (b, mapping.get(b, "")))
    return "\n".join(lines)


# ------------------------------------------------------------------ 命令


def cmd_list() -> None:
    print("多模型提示词模板 · 夜秣AI短剧生成器")
    print("=" * 72)
    for k, t in TEMPLATES.items():
        mark = "（默认）" if k == DEFAULT_MODEL else ""
        print(f"\n▶ {k} · {t['name']}{mark}")
        print(f"  段落：{' → '.join(t['blocks'])}")
        print(f"  单段上限：{t['max_sec']}s ｜建议切段：{t['seg']}")
        if t["note"]:
            print(f"  注意：{t['note']}")
    print("\n" + "=" * 72)
    print("用法：model_adapter.py <workdir> --model seedance --apply")


def main() -> None:
    ap = argparse.ArgumentParser(description="多模型提示词适配器")
    ap.add_argument("workdir", nargs="?", help="项目目录")
    ap.add_argument("--list", action="store_true", help="列出所有模板")
    ap.add_argument("--model", default=DEFAULT_MODEL, choices=list(TEMPLATES),
                    help="目标模型（默认 generic）")
    ap.add_argument("--apply", action="store_true", help="写到 prompts/<model>/")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    ap.add_argument("--convert", metavar="FILE", help="把已有四段式文本转成目标模板")
    ap.add_argument("--sids", nargs="*", help="只处理指定镜号")
    a = ap.parse_args()

    if a.list or not a.workdir:
        cmd_list()
        return

    wd = Path(a.workdir)
    sp = wd / "shots.json"
    if not sp.exists():
        print(f"[adapter] 缺少 shots.json：{sp}", file=sys.stderr)
        sys.exit(2)

    sc = json.loads(sp.read_text(encoding="utf-8"))
    lock = asset_lock.load(str(wd))
    if not lock:
        print("⚠️  没跑过资产冻结，现算一份（建议先 asset_lock.py <workdir> init）",
              file=sys.stderr)
        lock = asset_lock.build(str(wd))

    # 锁里没有图路径，从 cast.json 补上（只补缺失的，不覆盖）
    for n, rp in load_cast_refs(wd).items():
        if n in (lock.get("chars") or {}):
            lock["chars"][n].setdefault("ref_main", rp)

    if a.convert:
        txt = Path(a.convert).read_text(encoding="utf-8", errors="replace")
        print(convert_text(txt, a.model))
        return

    want = a.sids or [s.get("id") for s in sc.get("shots", [])]
    todo = [s for s in sc.get("shots", []) if s.get("id") in want]

    t = TEMPLATES[a.model]
    outdir = wd / "prompts" / a.model
    if a.apply:
        outdir.mkdir(parents=True, exist_ok=True)

    nwarn = 0
    for s in todo:
        p = render(a.model, s, lock, sc)
        if "[WARN]" in p:
            nwarn += 1
        if a.apply:
            out = outdir / ("v_%s.txt" % s.get("id"))
            if out.exists() and not a.force:
                print(f"   {out.name} 已存在，跳过（--force 覆盖）")
                continue
            out.write_text(p + "\n", encoding="utf-8")
            print(f"→ {out.relative_to(wd)}  {s.get('beat','')}")
        else:
            print("=" * 68)
            print("%s  %s  %ss  %s" % (s.get("id"), s.get("beat", ""),
                                       s.get("dur", "?"), s.get("size", "")))
            print(p)

    print(f"\n共 {len(todo)} 镜 → {t['name']}，超段长告警 {nwarn} 条")
    if nwarn:
        print("🔴 有镜头超过该模型单段上限：宁可多切镜，不要长镜头塞动作")
    if a.apply:
        print(f"产物目录：{outdir}")
        print("下一步：asset_lock.py <workdir> verify")


if __name__ == "__main__":
    main()
