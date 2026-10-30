#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评审看板 · 夜秣AI短剧生成器 v2.0

把 shots.json 变成单文件离线 HTML：全片一格一眼过 + 镜头多样性体检。
双击就能看，不需要联网，不需要任何前端依赖。

用法：
  review_board.py <workdir>                    # 生成到 <workdir>/评审看板.html
  review_board.py <workdir> -o 看板.html
  review_board.py <workdir> --with-prompts     # 卡片里带上视频提示词

只用标准库。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SIZE_ORDER = ["大远景", "远景", "全景", "中景", "近景", "特写", "大特写", "空镜"]

CSS = """
:root{
  --bg:#f6f7f9; --card:#ffffff; --line:#e3e6ea; --ink:#1b2430;
  --ink2:#59636f; --ink3:#8b95a1; --accent:#2f6bff; --ok:#17915f;
  --warn:#c8811a; --bad:#c0392b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:28px 24px 60px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--ink2);font-size:13px;margin-bottom:22px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;margin-bottom:18px}
.panel h2{font-size:15px;margin:0 0 12px;color:var(--ink)}
.kv{display:flex;gap:26px;flex-wrap:wrap;margin-bottom:14px}
.kv div{font-size:12px;color:var(--ink2)}
.kv b{display:block;font-size:19px;color:var(--ink);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--ink3);font-weight:500;font-size:11.5px}
td b{font-weight:600}
.bar{height:7px;border-radius:4px;background:var(--accent);display:inline-block;
  vertical-align:middle;min-width:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:13px 14px}
.card .top{display:flex;align-items:baseline;gap:8px;margin-bottom:8px}
.cid{font:600 13px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--accent)}
.beat{font-size:13px;font-weight:600;flex:1}
.dur{font-size:11.5px;color:var(--ink3);font-family:ui-monospace,monospace}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}
.chip{font-size:11px;padding:2px 7px;border-radius:20px;background:#eef1f5;
  color:var(--ink2)}
.chip.s{background:#e8f0ff;color:#1f52c9}
.chip.c{background:#eaf7f0;color:#12734d}
.chip.l{background:#fff4e3;color:#9c6212}
.chip.t{background:#f2eafa;color:#6b3fa0}
.sub2{font-size:12.5px;color:var(--ink2);margin-bottom:8px;min-height:20px}
.cast{font-size:11.5px;color:var(--ink3)}
.mono{font:11px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink2);
  white-space:pre-wrap;word-break:break-word;background:#fafbfc;border:1px solid var(--line);
  border-radius:6px;padding:8px 9px;margin-top:8px;max-height:190px;overflow:auto}
.flag{font-size:11.5px;margin-top:7px;padding:5px 8px;border-radius:6px}
.flag.bad{background:#fdecea;color:var(--bad)}
.flag.warn{background:#fff6e6;color:var(--warn)}
.flag.ok{background:#eaf7f0;color:var(--ok)}
.verdict{font-size:13px;padding:9px 12px;border-radius:8px;margin-bottom:16px}
.verdict.ok{background:#eaf7f0;color:#0f6b47}
.verdict.bad{background:#fdecea;color:var(--bad)}
.foot{color:var(--ink3);font-size:11.5px;margin-top:18px;text-align:center}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def dist(items: list, key: str, order=None) -> list:
    c = Counter(str(x.get(key, "") or "—") for x in items)
    keys = order or sorted(c, key=lambda k: -c[k])
    for k in keys:
        c.setdefault(k, 0)
    return [(k, c[k]) for k in keys if c[k]]


def bar_rows(pairs: list, total: int) -> str:
    mx = max((n for _, n in pairs), default=1)
    out = []
    for k, n in pairs:
        w = int(120 * n / mx) if mx else 0
        out.append("<tr><td style='width:74px'>%s</td>"
                   "<td><span class='bar' style='width:%dpx'></span></td>"
                   "<td style='width:74px'><b>%d</b> <span style='color:#8b95a1'>"
                   "%.0f%%</span></td></tr>" % (esc(k), w, n, 100.0 * n / total if total else 0))
    return "".join(out)


def shot_flags(s: dict) -> list:
    f = []
    d = float(s.get("dur", 0) or 0)
    if d > 6.5:
        f.append(("bad", "时长 %.1fs > 6.5s → 长镜必崩，建议拆镜" % d))
    cam = str(s.get("cam", ""))
    if cam.startswith("L4"):
        f.append(("warn", "L4 冲击运镜（全片 ≤3 次且不连用）"))
    if not str(s.get("size", "")).strip():
        f.append(("warn", "未派发景别"))
    return f


def build(sc: dict, with_prompts: bool, wd: Path) -> str:
    shots = sc.get("shots", [])
    n = len(shots)
    total_sec = sum(float(s.get("dur", 0) or 0) for s in shots)

    kinds = {
        "景别": len(set(s.get("size", "") for s in shots)),
        "构图": len(set(s.get("compose", "") for s in shots)),
        "光位": len(set(s.get("light", "") for s in shots)),
    }
    score = min(100, int(
        (min(kinds["景别"], 6) / 6 * 34) +
        (min(kinds["构图"], 5) / 5 * 33) +
        (min(kinds["光位"], 4) / 4 * 33)))

    # 相邻重复
    adj_s = sum(1 for i in range(1, n) if shots[i].get("size") == shots[i - 1].get("size"))
    adj_l = sum(1 for i in range(1, n) if shots[i].get("light") == shots[i - 1].get("light"))
    l4 = sum(1 for s in shots if str(s.get("cam", "")).startswith("L4"))

    problems = []
    if score < 70:
        problems.append("多样性评分 %d < 70，不许进入出片环节" % score)
    if adj_s:
        problems.append("%d 处相邻两镜同景别" % adj_s)
    if adj_l:
        problems.append("%d 处相邻两镜同光位" % adj_l)
    if l4 > 3:
        problems.append("L4 冲击运镜 %d 次 > 3" % l4)
    bad_dur = sum(1 for s in shots if float(s.get("dur", 0) or 0) > 6.5)
    if bad_dur:
        problems.append("%d 镜时长 > 6.5s" % bad_dur)

    H = []
    H.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    H.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    H.append("<title>%s · 评审看板</title><style>%s</style></head><body><div class='wrap'>"
             % (esc(sc.get("title", "短剧")), CSS))
    H.append("<h1>%s · 评审看板</h1>" % esc(sc.get("title", "短剧")))
    H.append("<div class='sub'>共 %d 镜 ｜ 派发后总时长 %.1fs ｜ 画幅 %s ｜ 预设 %s</div>"
             % (n, total_sec, esc(sc.get("ratio", "—")), esc(sc.get("preset", "—"))))

    if problems:
        H.append("<div class='verdict bad'>🔴 " + "；".join(esc(p) for p in problems) + "</div>")
    else:
        H.append("<div class='verdict ok'>✔ 镜头多样性评分 %d，体检通过</div>" % score)

    # 体检面板
    H.append("<div class='panel'><h2>镜头多样性体检</h2>")
    H.append("<div class='kv'>")
    H.append("<div>多样性评分<b>%d / 100</b></div>" % score)
    H.append("<div>景别种类<b>%d</b></div>" % kinds["景别"])
    H.append("<div>构图种类<b>%d</b></div>" % kinds["构图"])
    H.append("<div>光位种类<b>%d</b></div>" % kinds["光位"])
    H.append("<div>L4 冲击<b>%d / 3</b></div>" % l4)
    H.append("<div>平均时长<b>%.1fs</b></div>" % (total_sec / n if n else 0))
    H.append("</div>")
    H.append("<table><tr><th style='width:38%'>景别分布</th>"
             "<th style='width:38%'>运镜分布</th><th>光位分布</th></tr>")
    H.append("<tr><td valign='top'><table>%s</table></td>"
             % bar_rows(dist(shots, "size", SIZE_ORDER), n))
    H.append("<td valign='top'><table>%s</table></td>" % bar_rows(dist(shots, "cam"), n))
    H.append("<td valign='top'><table>%s</table></td>" % bar_rows(dist(shots, "light"), n))
    H.append("</tr></table></div>")

    # 卡片网格
    H.append("<div class='grid'>")
    for s in shots:
        sid = s.get("id", "?")
        H.append("<div class='card'>")
        H.append("<div class='top'><span class='cid'>%s</span>"
                 "<span class='beat'>%s</span>"
                 "<span class='dur'>%ss</span></div>"
                 % (esc(sid), esc(s.get("beat", "")), esc(s.get("dur", "?"))))
        H.append("<div class='chips'>")
        if s.get("size"):
            H.append("<span class='chip s'>%s</span>" % esc(s["size"]))
        if s.get("cam"):
            H.append("<span class='chip c'>%s</span>" % esc(s["cam"]))
        if s.get("light"):
            H.append("<span class='chip l'>%s</span>" % esc(s["light"]))
        if s.get("compose"):
            H.append("<span class='chip'>%s</span>" % esc(s["compose"]))
        if s.get("trans"):
            H.append("<span class='chip t'>%s</span>" % esc(s["trans"]))
        H.append("</div>")
        if s.get("sub"):
            H.append("<div class='sub2'>%s</div>" % esc(s["sub"]))
        cast = s.get("cast") or []
        H.append("<div class='cast'>%s</div>"
                 % ("同框：" + "、".join(esc(c) for c in cast) if cast else "空镜（无人物）"))
        if with_prompts:
            vp = wd / "prompts" / ("v_%s.txt" % sid)
            if vp.exists():
                H.append("<div class='mono'>%s</div>"
                         % esc(vp.read_text(encoding="utf-8", errors="replace").strip()))
        for lv, msg in shot_flags(s):
            H.append("<div class='flag %s'>%s</div>" % (lv, esc(msg)))
        H.append("</div>")
    H.append("</div>")

    H.append("<div class='foot'>夜秣AI短剧生成器 · 评审看板 ｜ 单文件离线，可直接分享</div>")
    H.append("</div></body></html>")
    return "".join(H)


def main() -> None:
    ap = argparse.ArgumentParser(description="评审看板 · 夜秣AI短剧生成器")
    ap.add_argument("workdir")
    ap.add_argument("-o", "--out", help="输出 HTML 文件")
    ap.add_argument("--with-prompts", action="store_true", help="卡片里带上视频提示词")
    a = ap.parse_args()

    wd = Path(a.workdir)
    sp = wd / "shots.json"
    if not sp.exists():
        print(f"[board] 缺少 shots.json：{sp}", file=sys.stderr)
        sys.exit(2)
    sc = json.loads(sp.read_text(encoding="utf-8"))

    out = Path(a.out) if a.out else wd / "评审看板.html"
    out.write_text(build(sc, a.with_prompts, wd), encoding="utf-8")

    n = len(sc.get("shots", []))
    missing = sum(1 for s in sc.get("shots", []) if not str(s.get("size", "")).strip())
    print(f"→ {out}  （{n} 镜）")
    if missing:
        print(f"🟠 {missing} 镜还没派发，先跑：story_plan.py <workdir> --preset <预设> --apply")
    else:
        print("双击打开即可全片一眼过")


if __name__ == "__main__":
    main()
