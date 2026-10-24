# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ①.₅ 首帧图提示词

**为什么首帧要单独成一份提示词？**
因为「图生视频」的画风同源性，全靠这一帧。首帧一旦糊或跳，
后面整条片子都是飘的 —— 而首帧本身是拿**文生图/图生图**做的，
它吃的提示词跟视频模型吃的那段，不是同一种写法：

  · 视频提示词要写「动作 + 时间轴 + 运镜」（见 shot_prompt.py）
  · 首帧提示词要写「这一秒画面的静态构图」——只描述一张照片

本脚本把三件事拼成首帧提示词：
  ① 逐字冻结的角色特征（asset_lock.block_for，一个字都不许自己写）
  ② 分镜里的 ff（画面描述 + 导演层追加的景别/构图/运镜/光位后缀）
  ③ 技术负向（不出现文字/水印/畸形）

用法:
  python frame_prompt.py <workdir> [sid ...]            # 干跑：打印首帧 prompt
  python frame_prompt.py <workdir> --apply              # 落盘 prompts/f_cNN.txt
  python frame_prompt.py <workdir> --apply --force      # 覆盖
  python frame_prompt.py <workdir> --json               # 额外落盘首帧任务表 frame_jobs.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asset_lock   # noqa: E402
import cast_card    # noqa: E402

PR_DIR = "prompts"

# 画幅提示：首帧比例必须与出片画幅严格同比例，否则会被裁切、构图走样
RATIO_HINT = {
    "16:9": "画面比例 16:9，横构图。",
    "9:16": "画面比例 9:16，竖构图。",
    "1:1":  "画面比例 1:1，方形构图。",
    "3:4":  "画面比例 3:4，竖构图。",
    "4:3":  "画面比例 4:3，横构图。",
}


def build(wd, shot, lock=None, cards=None, ratio="16:9"):
    lock = lock or asset_lock.load(wd) or asset_lock.build(wd)
    cards = cards if cards is not None else cast_card.load(wd)
    names = shot.get("cast") or []

    ref, extra = cast_card.ref_for(wd, shot, cards)
    blk = asset_lock.block_for(lock, names)
    if not extra and blk:
        extra = "角色设定（%s）。" % blk

    ff = str(shot.get("ff", "")).strip()
    style = lock.get("style", {}).get("text", "")
    parts = []
    if extra:
        parts.append(extra)
    if ff:
        parts.append(ff)
    if style and style not in ff:
        parts.append("%s。" % style)
    parts.append(RATIO_HINT.get(ratio, ""))
    neg = lock.get("neg_tech", "")
    body = "\n".join(p for p in parts if p).strip()
    if neg:
        body += "\n【负向】%s" % neg
    return {"id": shot["id"], "beat": shot.get("beat", ""),
            "ref_image": ref or shot.get("ref") or (
                json.load(open(os.path.join(wd, "shots.json"), encoding="utf-8")).get("ref")
                if os.path.exists(os.path.join(wd, "shots.json")) else ""),
            "ratio": ratio,
            "size": shot.get("size", ""),
            "dur": shot.get("dur", ""),
            "prompt": body}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ratio", default="16:9",
                    choices=list(RATIO_HINT))
    ap.add_argument("--json", action="store_true",
                    help="额外落盘 frame_jobs.json（可交给任意图生图/文生图工具批处理）")
    a = ap.parse_args()

    wd = a.workdir
    sc = json.load(open(os.path.join(wd, "shots.json"), encoding="utf-8"))
    lock = asset_lock.load(wd)
    if not lock:
        print("⚠️  没跑过资产冻结，现算一份（建议先 asset_lock.py <workdir> init）")
        lock = asset_lock.build(wd)
    cards = cast_card.load(wd)

    want = a.sids or [s["id"] for s in sc["shots"]]
    todo = [s for s in sc["shots"] if s["id"] in want]
    pdir = os.path.join(wd, PR_DIR)
    if a.apply:
        os.makedirs(pdir, exist_ok=True)

    jobs = []
    for s in todo:
        j = build(wd, s, lock, cards, a.ratio)
        jobs.append(j)
        if a.apply:
            out = os.path.join(pdir, "f_%s.txt" % s["id"])
            if os.path.exists(out) and not a.force:
                print("   %s 已存在，跳过（--force 覆盖）" % out)
                continue
            open(out, "w", encoding="utf-8").write(j["prompt"] + "\n")
            print("→ %s  %s" % (out, s.get("beat", "")))
        else:
            print("=" * 68)
            print("%s  %s  %s  ref=%s" % (s["id"], s.get("beat", ""),
                                          j["size"], os.path.basename(j["ref_image"] or "无")))
            print(j["prompt"])

    if a.apply and a.json:
        jp = os.path.join(wd, "frame_jobs.json")
        json.dump({"ratio": a.ratio, "jobs": jobs}, open(jp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n首帧任务表 →", jp)
        print("（每项含 prompt / ref_image / ratio，直接喂给你自己的图生图工具即可）")

    print("\n共 %d 镜" % len(todo))
    if a.apply:
        print("下一步：shot_prompt.py <workdir> --apply   （生成对应的视频提示词）")


if __name__ == "__main__":
    main()
