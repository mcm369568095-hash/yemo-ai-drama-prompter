# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ② 导出《视频提示词清单》（本技能的主交付物）

把 shots.json + cast.json + prompts/ 合成一份**人可读、勾选即用**的 Markdown：

  · 镜号总表（景别/运镜/光位/构图/时长/转场/字幕）
  · 每一镜：首帧图提示词 + 视频提示词（代码块，复制即投）
  · 资产冻结块与指纹（改一个字都能看出哪几镜要重刷）
  · 成本试算（付费镜数 × 秒数 × 单价）

用法:
  python export_prompts.py <workdir>                      # 输出 视频提示词清单.md
  python export_prompts.py <workdir> --out 别的名字.md
  python export_prompts.py <workdir> --price 0.5          # 视频单价（元/秒），默认 0.5
  python export_prompts.py <workdir> --paid "c01,c05,c12" # 只给这些镜算钱（其余走本地兜底）
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asset_lock  # noqa: E402
import shot_prompt  # noqa: E402
import frame_prompt  # noqa: E402


def read_prompt(wd, kind, sid):
    p = os.path.join(wd, "prompts", "%s_%s.txt" % (kind, sid))
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--out", default="视频提示词清单.md")
    ap.add_argument("--price", type=float, default=0.5, help="视频单价 元/秒")
    ap.add_argument("--paid", default="", help="付费镜号，逗号分隔；不填=全片按付费算")
    ap.add_argument("--ratio", default="16:9")
    a = ap.parse_args()

    wd = a.workdir
    sc = json.load(open(os.path.join(wd, "shots.json"), encoding="utf-8"))
    shots = sc["shots"]
    lock = asset_lock.load(wd) or asset_lock.build(wd)
    cards = None
    try:
        import cast_card
        cards = cast_card.load(wd)
    except Exception:
        pass

    paid = [x.strip() for x in a.paid.split(",") if x.strip()]
    title = sc.get("title") or sc.get("topic") or "未命名短剧"
    total = sum(float(s.get("dur", 0) or 0) for s in shots)
    paid_shots = [s for s in shots if (not paid or s["id"] in paid)]
    paid_sec = sum(float(s.get("dur", 0) or 0) for s in paid_shots)
    est = paid_sec * a.price

    L = []
    L.append("# 《%s》视频提示词清单" % title)
    L.append("")
    L.append("> 由「夜秣AI短剧生成器」导出。共 **%d 镜**，总长约 **%.0f 秒**，"
             "导演预设 `%s`。" % (len(shots), total, sc.get("preset", "drama")))
    if sc.get("subtitle"):
        L.append("> %s" % sc["subtitle"])
    L.append("")
    L.append("**怎么用**：首帧提示词 → 交给图生图/文生图工具出第一帧；"
             "视频提示词 → 连同首帧一起交给视频模型。逐镜复制即可。")
    L.append("")

    # ── 一、资产冻结块 ────────────────────────────────────────────────
    L.append("## 一、资产冻结块（逐字复用，一个字都不许改）")
    L.append("")
    L.append("画风锁 `[%s]`　%s" % (lock["style"]["fp"], lock["style"]["text"]))
    L.append("")
    L.append("| 角色 | 指纹 | 冻结特征 |")
    L.append("|---|---|---|")
    for n, c in lock.get("chars", {}).items():
        L.append("| %s | `%s` | %s |" % (n, c["fp"], c["text"]))
    L.append("")
    L.append("技术负向：`%s`" % lock.get("neg_tech", ""))
    L.append("")
    L.append("肯定式稳定约束：`%s`" % lock.get("pos_stable", ""))
    L.append("")

    # ── 二、镜号总表 ──────────────────────────────────────────────────
    L.append("## 二、分镜总表")
    L.append("")
    L.append("| 镜号 | 节拍 | 景别 | 运镜 | 光位 | 构图 | 时长 | 转场 | 字幕 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s in shots:
        L.append("| `%s` | %s | %s | %s | %s | %s | %ss | %s | %s |" % (
            s["id"], s.get("beat", ""), s.get("size", ""), s.get("cam", ""),
            s.get("light", ""), s.get("compose", ""), s.get("dur", ""),
            s.get("trans", ""), (s.get("sub", "") or "").replace("|", "｜")))
    L.append("")

    # ── 三、逐镜提示词 ────────────────────────────────────────────────
    L.append("## 三、逐镜提示词")
    L.append("")
    for s in shots:
        sid = s["id"]
        L.append("### `%s` · %s" % (sid, s.get("beat", "")))
        L.append("")
        L.append("- 景别 `%s`｜运镜 `%s`｜光位 `%s`｜构图 `%s`｜时长 `%ss`｜转场 `%s`%s"
                 % (s.get("size", ""), s.get("cam", ""), s.get("light", ""),
                    s.get("compose", ""), s.get("dur", ""), s.get("trans", ""),
                    ("｜音效 `%s`" % s["sfx"]) if s.get("sfx") else ""))
        if s.get("sub"):
            L.append("- 字幕：%s" % s["sub"])
        L.append("")

        fp = read_prompt(wd, "f", sid)
        if not fp:
            try:
                fp = frame_prompt.build(wd, s, lock, cards, a.ratio)["prompt"]
            except Exception:
                fp = str(s.get("ff", ""))
        L.append("**① 首帧图提示词**")
        L.append("")
        L.append("```text")
        L.append(fp)
        L.append("```")
        L.append("")

        vp = read_prompt(wd, "v", sid)
        if not vp:
            try:
                vp = shot_prompt.build(wd, s, lock)
            except Exception:
                vp = str(s.get("v", ""))
        L.append("**② 视频提示词**")
        L.append("")
        L.append("```text")
        L.append(vp)
        L.append("```")
        L.append("")

    # ── 四、成本试算 ──────────────────────────────────────────────────
    L.append("## 四、成本试算")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    L.append("| 镜数 | %d |" % len(shots))
    L.append("| 总时长 | %.0f 秒 |" % total)
    L.append("| 付费镜 | %d 镜 / %.0f 秒 |" % (len(paid_shots), paid_sec))
    L.append("| 视频单价 | ¥%.2f / 秒 |" % a.price)
    L.append("| **瞬时净成本** | **¥%.1f** |" % est)
    L.append("| 建议预算（含 15%% 返工） | ¥%.1f |" % (est * 1.15))
    L.append("")
    L.append("> 🔴 按经验，一镜平均要生成 **3~4 次**才换到 1 条可用；"
             "上面是「一遍过」的理想值，真实预算请按建议预算留。")
    L.append("")
    L.append("> 💡 省钱四招：① 钱只买「情感峰顶」，过渡镜用本地推拉兜底；"
             "② 每镜先跑 4~6 秒小样验方向，再上长镜；"
             "③ 提交即计费、没有撤回，提示词先写清楚；"
             "④ 别走中转站，官方直连往往便宜好几倍。")
    L.append("")

    out = os.path.join(wd, a.out)
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("已导出 →", out)
    print("  %d 镜 / 总长 %.0fs / 付费 %d 镜 %.0fs / 净成本 ¥%.1f"
          % (len(shots), total, len(paid_shots), paid_sec, est))


if __name__ == "__main__":
    main()
