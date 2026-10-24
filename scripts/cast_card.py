# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ⓿.₆ 角色卡：把角色固化成可复用资产

用法:
  python cast_card.py <workdir> init --name 林晚 --features "26岁女性，圆脸，黑色齐肩发…"
  python cast_card.py <workdir> show
  python cast_card.py <workdir> gen --name 林晚         # 只打印「特写锚定图」提示词，不调任何接口
  python cast_card.py <workdir> resolve --shot c05      # 查该镜用哪张锚定图
  python cast_card.py <workdir> audit                    # 检查缺图/缺字段

核心思路: 一张定稿图不够 —— 全景用主图、近景与特写用脸图，才不会「一拉近就换脸」。
anime 出片流程会按景别自动选锚定图，并把 features 拼进首帧 prompt。

🔴 本脚本**不调用任何生图接口**。特写锚定图怎么生成由你自己决定（任何可用的
   图生图工具都行）。若你有自己的命令行生图工具，把它设进环境变量即可自动调用：
     set YEMO_IMG_CMD=你的命令 {image} {prompt} {out}
   不设就只打印提示词，人工拿去用。
"""
import argparse
import json
import os
import shlex
import subprocess
import sys

CARD = "cast.json"
FAR = ("全景", "中景")
NEAR = ("近景", "特写")

FACE_PROMPT = ("同一角色的正面脸部特写，保持完全一致的五官、发型、肤色与服装领口；"
               "眼睛看镜头，表情自然；干净纯色背景，构图居中，肩部以上；"
               "{style}。角色特征：{features}。画面中不出现任何文字。")


def card_path(wd):
    return os.path.join(wd, CARD)


def load(wd):
    p = card_path(wd)
    if not os.path.exists(p):
        return {"style_lock": "", "characters": []}
    return json.load(open(p, encoding="utf-8"))


def save(wd, data):
    json.dump(data, open(card_path(wd), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def get(data, name=None):
    ch = data.get("characters", [])
    if not ch:
        return None
    if not name:
        for c in ch:
            if c.get("role") == "主角":
                return c
        return ch[0]
    for c in ch:
        if c["name"] == name:
            return c
    return None


def ref_for(wd, shot, data=None):
    """按景别选锚定图 → (图路径, 追加到 prompt 的角色特征串)。

    cast 的三种写法：
      · 写了 cast: ["林晚","周野"] → 取这些角色的锚定图与特征
      · 没写 cast                  → 兜底取主角
      · 写了 cast: []              → **本镜没有角色**（空镜/环境镜），
                                     返回空，绝不把角色设定硬塞给空镜
    """
    data = data or load(wd)
    size = shot.get("size", "中景")
    names = shot.get("cast")
    if names is not None and not names:
        return None, ""
    names = names or []
    picks, feats = [], []
    pool = [get(data, n) for n in names] if names else [get(data)]
    pool = [c for c in pool if c]
    if not pool:
        return None, ""
    for c in pool:
        key = "ref_face" if size in NEAR else "ref_main"
        p = c.get(key) or c.get("ref_main")
        if p and not os.path.isabs(p):
            p = os.path.join(wd, p)
        if p and os.path.exists(p):
            picks.append(p)
        feats.append("%s：%s" % (c["name"], c.get("features", "")))
    ref = picks[0] if picks else None
    if len(pool) == 1:
        extra = "角色设定（%s）：%s。" % (pool[0]["name"], pool[0].get("features", ""))
    else:
        extra = "同框角色：" + "；".join(feats) + "。"
    neg = "；".join(c.get("neg", "") for c in pool if c.get("neg"))
    if neg:
        extra += "禁止出现：%s。" % neg
    return ref, extra


def cmd_init(wd, a):
    data = load(wd)
    sc_p = os.path.join(wd, "shots.json")
    if a.ref is None and os.path.exists(sc_p):
        a.ref = json.load(open(sc_p, encoding="utf-8")).get("ref", "")
    c = {
        "name": a.name,
        "role": a.role,
        "ref_main": a.ref or "",
        "ref_face": "",
        "features": a.features or "（在此写死：年龄、脸型、发型、服装、配色、身高比例、标志物）",
        "voice": a.voice or "",
        "neg": a.neg or "写实人脸、换装、换发型、多余肢体",
    }
    ch = data.setdefault("characters", [])
    for i, x in enumerate(ch):
        if x["name"] == a.name:
            ch[i] = c
            break
    else:
        ch.append(c)
    save(wd, data)
    print("已写入角色卡：", card_path(wd))
    print("  角色 %s（%s）锚定图 %s" % (c["name"], c["role"], c["ref_main"] or "❌ 未设"))


def cmd_show(wd, a):
    data = load(wd)
    if not data.get("characters"):
        print("还没有角色卡。先跑：cast_card.py <workdir> init --name <角色名> --ref <定稿图>")
        return
    print("画风锁：%s" % (data.get("style_lock") or "❌ 未设"))
    print("%-8s %-6s %-10s %-12s" % ("角色", "定位", "主锚定图", "特写锚定图"))
    for c in data["characters"]:
        print("%-8s %-6s %-10s %-12s" % (
            c["name"], c.get("role", ""),
            "有" if c.get("ref_main") else "❌",
            "有" if c.get("ref_face") else "—"))
        print("    特征：%s" % c.get("features", ""))
        print("    音色：%s ／ 负向：%s" % (c.get("voice", ""), c.get("neg", "")))


def cmd_gen(wd, a):
    """打印特写锚定图的生成提示词；有 YEMO_IMG_CMD 才真的调用。"""
    data = load(wd)
    c = get(data, a.name)
    if not c:
        print("没有这个角色：", a.name)
        sys.exit(1)
    src = c.get("ref_main")
    if not src:
        print("角色缺主锚定图，无法衍生特写图")
        sys.exit(1)
    if not os.path.isabs(src):
        src = os.path.join(wd, src)
    out_dir = os.path.join(wd, "cast")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "%s_特写.png" % c["name"])
    prompt = FACE_PROMPT.format(style=data.get("style_lock") or "统一画风",
                                features=c.get("features", ""))

    tpl = os.environ.get("YEMO_IMG_CMD", "").strip()
    if not tpl:
        print("【特写锚定图 · 生成提示词】")
        print("  参考图 : %s" % src)
        print("  输出到 : %s" % out)
        print("  提示词 : %s" % prompt)
        print("\n提示：把你自己的图生图命令写进环境变量 YEMO_IMG_CMD 即可自动生成，")
        print("      命令里可用 {image} / {prompt} / {out} 三个占位符。")
        print("      例：set YEMO_IMG_CMD=mytool --ref {image} --prompt \"{prompt}\" --out {out}")
        return

    cmd = tpl.replace("{image}", src).replace("{prompt}", prompt).replace("{out}", out)
    print("调用：", cmd)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if not (os.path.exists(out) and os.path.getsize(out) > 1024):
        print("生成失败：", (r.stdout or "")[-400:], (r.stderr or "")[-300:])
        sys.exit(1)
    c["ref_face"] = os.path.relpath(out, wd).replace("\\", "/")
    save(wd, data)
    print("特写锚定图已写入角色卡：", out)


def cmd_resolve(wd, a):
    sc = json.load(open(os.path.join(wd, "shots.json"), encoding="utf-8"))
    data = load(wd)
    for s in sc["shots"]:
        if a.shot and s["id"] != a.shot:
            continue
        ref, extra = ref_for(wd, s, data)
        print("%s  景别 %s → %s" % (s["id"], s.get("size", "?"),
                                   ref or "❌ 无锚定图"))
        print("      追加设定：%s" % (extra or "—"))


def cmd_audit(wd, a):
    data = load(wd)
    ch = data.get("characters", [])
    if not ch:
        print("🔴 没有角色卡 —— 首帧将退化为纯图生图，角色会漂移")
        sys.exit(2)
    bad = 0
    if not (data.get("style_lock") or "").strip():
        print("🔴 缺 style_lock（画风锁）—— 全片画风会漂")
        bad += 1
    for c in ch:
        if not c.get("ref_main"):
            print("🔴 %s 缺主锚定图" % c["name"])
            bad += 1
        if not c.get("ref_face"):
            print("⚠️  %s 缺特写锚定图（近景/特写会换脸）→ 跑 gen --name %s"
                  % (c["name"], c["name"]))
            bad += 1
        if "（在此写死" in c.get("features", ""):
            print("🔴 %s 的特征还没填" % c["name"])
            bad += 1
    print("角色 %d 个，问题 %d 项" % (len(ch), bad))
    if bad:
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--name", required=True)
    p.add_argument("--role", default="主角")
    p.add_argument("--ref", default=None)
    p.add_argument("--features", default="")
    p.add_argument("--voice", default="")
    p.add_argument("--neg", default="")
    p.set_defaults(fn=cmd_init)

    sub.add_parser("show").set_defaults(fn=cmd_show)

    p = sub.add_parser("gen")
    p.add_argument("--name", default=None)
    p.set_defaults(fn=cmd_gen)

    p = sub.add_parser("resolve")
    p.add_argument("--shot", default=None)
    p.set_defaults(fn=cmd_resolve)

    sub.add_parser("audit").set_defaults(fn=cmd_audit)

    a = ap.parse_args()
    a.fn(a.workdir, a)


if __name__ == "__main__":
    main()
