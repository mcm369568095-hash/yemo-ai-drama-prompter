# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ⓪ 一键起项目（脚手架）

给你一个能立刻跑通的空项目：复制示例分镜与角色卡，建好目录，顺手冻结资产。

用法:
  python init_workdir.py <新项目目录>
  python init_workdir.py <新项目目录> --preset suspense
  python init_workdir.py <新项目目录> --title "我的短剧" --no-example

跑完你会拿到：
  <项目>/
    shots.json          示例分镜（改成你的故事）
    cast.json           示例角色卡（改成你的角色）
    cast/定稿/          放你的角色定稿图
    prompts/            提示词输出位
    asset_lock.json     已冻结的资产
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TPL = os.path.join(ROOT, "templates")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--preset", default="drama",
                    choices=["drama", "suspense", "warm", "epic"])
    ap.add_argument("--title", default="")
    ap.add_argument("--no-example", action="store_true",
                    help="不塞示例分镜，只建空骨架")
    a = ap.parse_args()

    wd = a.workdir
    for sub in ("prompts", "ff", "clips", "cast/定稿"):
        os.makedirs(os.path.join(wd, sub), exist_ok=True)

    if not a.no_example:
        src, dst = os.path.join(TPL, "shots.example.json"), os.path.join(wd, "shots.json")
        if not os.path.exists(dst):
            sc = json.load(open(src, encoding="utf-8"))
            if a.title:
                sc["title"] = a.title
            sc["preset"] = a.preset
            json.dump(sc, open(dst, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("→ shots.json（示例分镜，预设 %s）" % a.preset)
        src, dst = os.path.join(TPL, "cast.example.json"), os.path.join(wd, "cast.json")
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
            print("→ cast.json（示例角色卡）")
    else:
        p = os.path.join(wd, "shots.json")
        if not os.path.exists(p):
            json.dump({
                "title": a.title or "未命名短剧",
                "preset": a.preset,
                "target_sec": 110,
                "ratio": "16:9",
                "style": "（这里写你的画风锁，一句话，全片复用）",
                "ref": "cast/定稿/主角定稿.png",
                "shots": [
                    {"id": "c01", "beat": "开场", "cast": [], "size_hint": "全景",
                     "sub": "（这一镜的字幕）",
                     "ff": "（首帧画面描述，别写景别）",
                     "v": "（只写动作，别写运镜）"}
                ],
            }, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("→ shots.json（空骨架）")
        p = os.path.join(wd, "cast.json")
        if not os.path.exists(p):
            json.dump({
                "style_lock": "（与 shots.json 的 style 保持一致）",
                "characters": [
                    {"name": "主角", "role": "主角", "pinyin": "Zhu Jue",
                     "ref_main": "cast/定稿/主角定稿.png", "ref_face": "",
                     "features": "（在此写死：年龄、脸型、发型、服装、配色、身高比例、标志物）",
                     "features_en": "", "voice": "", "neg": "写实照片、换装、换发型、多余肢体"}
                ],
            }, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("→ cast.json（空骨架）")

    # 顺手冻结资产（有角色特征时才有意义）
    sys.path.insert(0, HERE)
    try:
        import asset_lock
        lock = asset_lock.build(wd)
        if lock.get("chars"):
            asset_lock.save(wd, lock)
            print("→ asset_lock.json（已冻结 %d 个角色）" % len(lock["chars"]))
        else:
            print("（跳过资产冻结：cast.json 里还没有角色）")
    except Exception as e:
        print("（资产冻结跳过：%s）" % e)

    print()
    print("下一步：")
    print("  1) 把角色定稿图放进  %s/cast/定稿/" % wd)
    print("  2) 改 cast.json 的 features（特征写死）与 shots.json 的故事")
    print("  3) python %s/asset_lock.py  \"%s\" init" % (HERE, wd))
    print("  4) python %s/story_plan.py \"%s\" --preset %s --apply" % (HERE, wd, a.preset))
    print("  5) python %s/frame_prompt.py \"%s\" --apply" % (HERE, wd))
    print("  6) python %s/shot_prompt.py  \"%s\" --apply" % (HERE, wd))
    print("  7) python %s/export_prompts.py \"%s\"" % (HERE, wd))


if __name__ == "__main__":
    main()
