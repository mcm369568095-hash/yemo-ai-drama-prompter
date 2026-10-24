# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ⓿.₆₅ 资产锁定（Asset Lock）

> 铁律：**不锁定全部资产，一个镜头也不生成。**
> 「模型没有记忆，少描述一句，下一镜它就换脸换衣服。」
> 人物描述词一旦冻结，每个分镜提示词里**一字不许改**。

用法:
  python asset_lock.py <workdir> init            # 从 cast.json 冻结 → asset_lock.json
  python asset_lock.py <workdir> show            # 看冻结块与指纹
  python asset_lock.py <workdir> audit           # 资产齐备性门禁（缺项 exit 2）
  python asset_lock.py <workdir> verify          # 校验 prompts/*.txt 指纹是否过期
  python asset_lock.py <workdir> sync            # cast.json 改了之后重新冻结（并重算指纹）

产物 `asset_lock.json`：
  {
    "locked_at": "...",
    "style": {"text": "...", "fp": "ab12cd34"},
    "chars": {"林晚": {"text": "...", "en": "", "pinyin": "Lin Wan", "fp": "..."}},
    "neg_tech": "…（只对字幕/水印/文字有效的技术负向）",
    "pos_stable": "…（肯定式稳定约束，画面上想「不要」什么必须改成肯定式）"
  }

🔴 三条纪律：
  1. 冻结后**所有**首帧/视频 prompt 里的角色描述，一律用 `block_for()` 取，逐字不变。
  2. 改了 cast.json 必须 `sync`，再跑 `shot_prompt.py --apply` 重刷 prompt，`verify` 才过得去。
  3. 🔴🔴 参考图只给**单人**（主锚定=全身，特写锚定=脸）。
     三视图／多人合影/全家福会被模型整片复刻构图，是血案级踩坑。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cast_card  # noqa: E402

LOCK = "asset_lock.json"
PR_DIR = "prompts"

# 技术负向：只对「字幕 / 水印 / 文字 / logo / 畸形」有效。
# 🔴 画面上想「不要」什么（换脸、换装、加人）用否定词**无效**，必须改肯定式（见 POS_STABLE）。
NEG_TECH = ("text, letters, captions, subtitles, watermark, logo, signature, "
            "extra limbs, extra fingers, distorted face, malformed hands")

# 肯定式稳定约束：把「不要换脸」翻译成「必须保持一致」
POS_STABLE = ("Keep every character's face, hairstyle, outfit, colors and body proportions "
              "exactly identical to the reference image from the first frame to the last; "
              "the number of characters in frame stays constant; "
              "motion follows real physics; no morphing, no identity drift.")


def fp(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()[:8]


def lock_path(wd):
    return os.path.join(wd, LOCK)


def load(wd):
    p = lock_path(wd)
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def build(wd):
    """从 cast.json 冻结资产（不修改 cast.json）"""
    cards = cast_card.load(wd)
    sc_p = os.path.join(wd, "shots.json")
    style = cards.get("style_lock", "")
    if not style and os.path.exists(sc_p):
        style = json.load(open(sc_p, encoding="utf-8")).get("style", "")
    chars = {}
    for c in cards.get("characters", []):
        chars[c["name"]] = {
            "text": (c.get("features") or "").strip(),
            "en": (c.get("features_en") or "").strip(),
            "pinyin": (c.get("pinyin") or "").strip(),
            "fp": fp((c.get("features") or "").strip()),
        }
    return {
        "locked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "style": {"text": style.strip(), "fp": fp(style.strip())},
        "chars": chars,
        "neg_tech": NEG_TECH,
        "pos_stable": POS_STABLE,
    }


def save(wd, data):
    json.dump(data, open(lock_path(wd), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def header(lock, names=None):
    """prompt 头部指纹行：verify 靠它判断 prompt 是否过期"""
    s = "style=%s" % lock["style"]["fp"]
    if names:
        s += " " + " ".join("%s=%s" % (n, lock["chars"][n]["fp"])
                            for n in names if n in lock["chars"])
    return "[ASSET-LOCK %s]" % s


def block_for(lock, names, lang="zh"):
    """取冻结块 —— 逐字复用，永不在别处重写角色描述"""
    out = []
    for n in names or []:
        c = lock.get("chars", {}).get(n)
        if not c:
            continue
        if lang == "en" and c.get("en"):
            out.append("%s: %s" % (n, c["en"]))
        else:
            out.append("%s：%s" % (n, c["text"]))
    return "；".join(out)


def cmd_init(wd, a):
    data = build(wd)
    if not data["chars"]:
        print("🔴 %s 里没有角色卡 —— 空锁等于没锁，不许往下走" % os.path.join(wd, "cast.json"))
        sys.exit(2)
    save(wd, data)
    print("已冻结资产 →", lock_path(wd))
    print("  风格 fp=%s  %s" % (data["style"]["fp"], data["style"]["text"][:40]))
    for n, c in data["chars"].items():
        print("  角色 %-6s fp=%s  %s" % (n, c["fp"], c["text"][:36]))
    print("\n下一步：shot_prompt.py <workdir> --apply   （把冻结块写进每镜 prompt）")


def cmd_show(wd, a):
    lock = load(wd)
    if not lock:
        print("还没有资产锁。先跑：asset_lock.py <workdir> init")
        sys.exit(1)
    print("冻结于 %s" % lock.get("locked_at", "?"))
    print("风格 [%s] %s" % (lock["style"]["fp"], lock["style"]["text"]))
    print("角色：")
    for n, c in lock["chars"].items():
        print("  %-6s [%s] %s" % (n, c["fp"], c["text"]))
        if c.get("en"):
            print("         EN: %s" % c["en"])
    print("肯定式稳定：%s" % lock.get("pos_stable", ""))
    print("技术负向　：%s" % lock.get("neg_tech", ""))


def cmd_audit(wd, a):
    """资产齐备性门禁 —— 缺一项就不许出图/出片"""
    cards = cast_card.load(wd)
    ch = cards.get("characters", [])
    lock = load(wd)
    bad = 0
    if not ch:
        print("🔴 没有角色卡 —— 不可能保住人物一致性")
        sys.exit(2)
    if not (cards.get("style_lock") or "").strip():
        print("🔴 缺 style_lock（画风锁）—— 全片画风会漂")
        bad += 1
    if not lock:
        print("🔴 没跑过资产冻结 → asset_lock.py <workdir> init")
        bad += 1
    elif a.strict:
        for n, c in lock["chars"].items():
            src = next((x for x in ch if x["name"] == n), None)
            if src and fp((src.get("features") or "").strip()) != c["fp"]:
                print("🔴 %s 的特征已改动但未 sync → asset_lock.py <workdir> sync" % n)
                bad += 1
    for c in ch:
        nm = c["name"]
        rp = c.get("ref_main") or ""
        if rp and not os.path.isabs(rp):
            rp = os.path.join(wd, rp)
        if not (rp and os.path.exists(rp)):
            print("🔴 %s 缺主锚定图（全身/定稿）" % nm)
            bad += 1
        rf = c.get("ref_face") or ""
        if rf and not os.path.isabs(rf):
            rf = os.path.join(wd, rf)
        if not (rf and os.path.exists(rf)):
            print("🔴 %s 缺特写锚定图（近景/特写必换脸）" % nm)
            bad += 1
        if "（在此写死" in (c.get("features") or ""):
            print("🔴 %s 的特征还没填（冻结块是空的 = 没锁）" % nm)
            bad += 1
    print("资产：角色 %d 个，问题 %d 项%s"
          % (len(ch), bad, "" if not bad else " —— 不许往下走"))
    if bad:
        sys.exit(2)


def cmd_verify(wd, a):
    """校验已落盘的 prompt 是否还在用当前冻结块。

    · `v_*.txt`（视频提示词）**必须**带资产指纹头，指纹对不上 = 过期 → 拦下。
    · `f_*.txt`（首帧图提示词）不带指纹头，改用**时间戳**判过期：
      资产锁比它新，就说明角色特征可能已改，提示重刷。
    """
    lock = load(wd)
    if not lock:
        print("🔴 没有资产锁")
        sys.exit(2)
    pdir = os.path.join(wd, PR_DIR)
    if not os.path.isdir(pdir):
        print("🔴 没有 prompts/ 目录 —— 先跑 shot_prompt.py <workdir> --apply")
        sys.exit(2)

    files = sorted(f for f in os.listdir(pdir) if f.endswith(".txt"))
    if not files:
        print("🔴 prompts/ 是空的")
        sys.exit(2)

    v_files = [f for f in files if f.startswith("v_")]
    f_files = [f for f in files if f.startswith("f_")]
    bad = 0

    if not v_files:
        print("🔴 没有 v_*.txt（视频提示词）—— 先跑 shot_prompt.py <workdir> --apply")
        sys.exit(2)

    want = {lock["style"]["fp"]} | {c["fp"] for c in lock["chars"].values()}
    for f in v_files:
        head = open(os.path.join(pdir, f), encoding="utf-8").readline()
        if "ASSET-LOCK" not in head:
            print("🔴 %s 没有资产指纹头" % f)
            bad += 1
            continue
        cur = set(re.findall(r"=(\w{8})", head.rstrip("]\n")))
        stale = cur - want
        if stale:
            print("🔴 %s 指纹过期（%s）→ shot_prompt.py <workdir> --apply --force" % (f, " ".join(stale)))
            bad += 1

    # 首帧提示词：时间戳判过期
    stale_f = []
    if f_files:
        lock_mt = os.path.getmtime(lock_path(wd))
        for f in f_files:
            if os.path.getmtime(os.path.join(pdir, f)) < lock_mt:
                stale_f.append(f)

    print("校验视频提示词 %d 份，过期 %d 份；首帧提示词 %d 份，疑似过期 %d 份"
          % (len(v_files), bad, len(f_files), len(stale_f)))
    if stale_f:
        print("⚠️  资产锁比这些首帧提示词新，角色特征可能已改 → "
              "frame_prompt.py <workdir> --apply --force　（%s）"
              % " ".join(stale_f[:8]))
    if bad:
        sys.exit(2)


def cmd_sync(wd, a):
    old = load(wd)
    new = build(wd)
    changed = []
    if old:
        if old["style"]["fp"] != new["style"]["fp"]:
            changed.append("风格")
        for n, c in new["chars"].items():
            o = old.get("chars", {}).get(n)
            if not o or o["fp"] != c["fp"]:
                changed.append(n)
    save(wd, new)
    print("已重新冻结 →", lock_path(wd))
    if changed:
        print("🔴 变更：%s → 必须重刷 prompt（shot_prompt.py <workdir> --apply --force）" % "、".join(changed))
    else:
        print("无变更。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    p = sub.add_parser("audit")
    p.add_argument("--strict", action="store_true")
    p.set_defaults(fn=cmd_audit)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    sub.add_parser("sync").set_defaults(fn=cmd_sync)

    a = ap.parse_args()
    a.fn(a.workdir, a)


if __name__ == "__main__":
    main()
