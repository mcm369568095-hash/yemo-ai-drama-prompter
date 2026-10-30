#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连载记忆 · 夜秣AI短剧生成器 v2.0

短剧最大的敌人不是单集写不好，是第 40 集忘了第 3 集埋的伏笔。
本脚本把跨集信息外置成硬盘：七份记忆文件 + 断线检查 + 断点续写。

用法：
  series_bible.py <workdir> init --title "七格药盒" --episodes 60
  series_bible.py <workdir> status            # 写到哪了，下一步做什么
  series_bible.py <workdir> qc                # 断线伏笔 / 时间倒流 / 人设漂移
  series_bible.py <workdir> add-foreshadow --content "翡翠镯子" --plant 12 --payoff 56
  series_bible.py <workdir> advance --ep 25   # 更新进度

只用标准库。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BIBLE_DIR = "bible"
STATE = "_state.json"

FILES = {
    "01_故事圣经.md": """# 01 · 故事圣经 ·《{title}》

> 每 5 集刷新一次。这一份是全剧的宪法，改它之前先想清楚。

## 一句话
（谁 + 被怎么了 + 要干什么）

## 时钟
（倒计时 / 周期拆封 / 阶梯升级 / 双线汇合 —— 选一个，写出它在画面上长什么样）

## 引擎
（每一轮的循环：对手出手 → 主角拆招 → 多出线索 → 下一个人急着出手）

## 分卷
| 卷 | 集 | 主题 | 这一卷要解决什么 |
|---|---|---|---|
| 第一卷 | 1–10 | | 立住规则 + 主卡点 |
| 第二卷 | 11–30 | | 升级 + 中段反转 |
| 第三卷 | 31–46 | | 战场搬家 |
| 第四卷 | 47–60 | | 兑现伏笔 + 结局 |

## 付费卡点
| 卡点 | 集 | 停在哪里 | 观众此刻欠着什么 |
|---|---|---|---|
| 卡点①（主） | 第 10 集 | | |
| 卡点② | 第 29 集 | | |
| 卡点③ | 第 46 集 | | |

## 结局承诺
（真凶落网 / 主角拿回什么 / **巨额财物的正当去向**）

## 最后更新
{date}
""",
    "02_角色档案.md": """# 02 · 角色档案 ·《{title}》

> 每人一份八要素，缺项即不合格。

## 【角色名】· 女主 · 年龄

**表面身份**：（别人眼里她是谁，别人怎么称呼她）
**真实过去**：（具体到数字和时间）
**为什么留下**：（动机，**钱要排在最后**）
**能力（她的武器）**：（2–3 条，具体到"一眼看出瓶签不对"）
**底线**：（她绝不做的事 —— 后面会让她付出代价）
**弱点**：（习惯性的自我毁灭模式，前期必吃亏）
**弧线**：（四级台阶 + 最后一个选择）
**标志物**：（2–3 件，后面必须变成物证）
**说话方式**：（短句 / 引条款 / 不解释 / 被逼急了只报事实）

---

## 公平时钟线索表（真凶用）

| 集 | 线索 |
|---|---|
| EP03 | |
| EP06 | |

## 最后更新
{date}
""",
    "03_伏笔表.md": """# 03 · 伏笔表 ·《{title}》

> 状态：⏳ 待兑现 / ✅ 已兑现 / ❌ 已断线

| ID | 内容 | 埋下集 | 兑现集 | 状态 |
|---|---|---|---|---|

> 用 series_bible.py <workdir> add-foreshadow --content "…" --plant 12 --payoff 56 登记；
> 空表不丢人，60 集没伏笔才丢人。

## 最后更新
{date}
""",
    "04_人物关系图.md": """# 04 · 人物关系图 ·《{title}》

> 谁和谁是什么关系，谁欠谁。

| A | 关系 | B | 欠什么 | 变化时集 |
|---|---|---|---|---|
|  |  |  |  |  |

## 最后更新
{date}
""",
    "05_时间线.md": """# 05 · 时间线 ·《{title}》

> 剧情天数 → 集号 → 发生了什么。天数必须单调递增。

| 天数 | 集 | 发生了什么 |
|---|---|---|
| 第 1 天 | EP01 | |

## 最后更新
{date}
""",
    "06_物品账本.md": """# 06 · 物品账本 ·《{title}》

> 每个物件出现在哪几集、当前在谁手里、状态如何。

| 物件 | 出现集 | 当前持有 | 状态 |
|---|---|---|---|
|  |  |  |  |

## 最后更新
{date}
""",
    "07_出场登记.md": """# 07 · 出场登记 ·《{title}》

> 角色在哪些集出场、说了什么关键的话（防称呼漂移）。

| 集 | 角色 | 称呼 | 关键台词/动作 |
|---|---|---|---|
|  |  |  |  |

## 最后更新
{date}
""",
}


def bible_path(wd: Path) -> Path:
    return wd / BIBLE_DIR


def state_path(wd: Path) -> Path:
    return bible_path(wd) / STATE


def load_state(wd: Path) -> dict:
    p = state_path(wd)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(wd: Path, st: dict) -> None:
    p = state_path(wd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_init(wd: Path, a) -> None:
    b = bible_path(wd)
    b.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    for name, tpl in FILES.items():
        f = b / name
        if f.exists() and not a.force:
            print(f"   {name} 已存在，跳过（--force 覆盖）")
            continue
        f.write_text(tpl.format(title=a.title or "未命名", date=date), encoding="utf-8")
        print(f"→ bible/{name}")
    st = load_state(wd)
    st.update({
        "title": a.title or "未命名",
        "total_episodes": a.episodes,
        "current_ep": st.get("current_ep", 0),
        "created": st.get("created", date),
        "updated": date,
    })
    save_state(wd, st)
    print(f"\n连载记忆已建立：《{st['title']}》 全 {a.episodes} 集")
    print("下一步：写 01_故事圣经.md，定时钟与引擎，再排卡点")


def parse_table(md: str) -> list:
    """解析 markdown 表格为 [{列名: 值}]"""
    rows = [l.strip() for l in md.splitlines()
            if l.strip().startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", l.strip())]
    if len(rows) < 2:
        return []
    head = [c.strip() for c in rows[0].strip("|").split("|")]
    out = []
    for r in rows[1:]:
        cells = [c.strip() for c in r.strip("|").split("|")]
        if len(cells) != len(head):
            continue
        out.append(dict(zip(head, cells)))
    return out


def ep_num(v: str):
    m = re.search(r"(\d+)", str(v))
    return int(m.group(1)) if m else None


def cmd_qc(wd: Path, a) -> None:
    b = bible_path(wd)
    if not b.exists():
        print(f"[bible] 未初始化：{b}", file=sys.stderr)
        sys.exit(2)
    st = load_state(wd)
    cur = int(st.get("current_ep", 0))
    print(f"连载质检 ·《{st.get('title','未命名')}》")
    print("=" * 70)

    issues, warns, oks = [], [], []

    # ---- 伏笔断线
    fp = b / "03_伏笔表.md"
    if fp.exists():
        rows = parse_table(fp.read_text(encoding="utf-8"))
        for r in rows:
            fid = r.get("ID", "?")
            stt = r.get("状态", "")
            plant, payoff = ep_num(r.get("埋下集", "")), ep_num(r.get("兑现集", ""))
            if "✅" in stt:
                continue
            if payoff is not None and cur and payoff < cur:
                issues.append(f"F ｜ {fid}「{r.get('内容','')}」应在 EP{payoff} 兑现，"
                              f"已写到 EP{cur} 未兑现 → 断线伏笔")
            if plant is not None and payoff is not None and payoff < plant:
                issues.append(f"F ｜ {fid} 兑现集 EP{payoff} 早于埋下集 EP{plant} → 顺序错误")
        # 模板里的空占位行不算数，只看真正填了内容的
        filled = [r for r in rows if r.get("内容", "").strip()]
        if not filled:
            warns.append("伏笔表还是空的 —— 60 集的剧没有伏笔，中段必塌")
        else:
            oks.append(f"伏笔 {len(filled)} 条，已兑现 "
                       f"{sum(1 for r in filled if '✅' in r.get('状态',''))} 条")

    # ---- 时间线倒流
    tp = b / "05_时间线.md"
    if tp.exists():
        rows = parse_table(tp.read_text(encoding="utf-8"))
        days, eps = [], []
        for r in rows:
            d = ep_num(r.get("天数", "")) or ep_num(r.get("日", ""))
            e = ep_num(r.get("集", ""))
            if d is not None:
                days.append(d)
            if e is not None:
                eps.append(e)
        bad_d = [i for i in range(1, len(days)) if days[i] < days[i - 1]]
        bad_e = [i for i in range(1, len(eps)) if eps[i] < eps[i - 1]]
        if bad_d:
            issues.append(f"T ｜ 时间线天数在第 {[i+1 for i in bad_d]} 行倒流（{days}）")
        if bad_e:
            issues.append(f"T ｜ 时间线集号在第 {[i+1 for i in bad_e]} 行倒流（{eps}）")
        if days and not bad_d:
            oks.append(f"时间线 {len(days)} 行，天数单调递增")

    # ---- 卡点位置
    sp = b / "01_故事圣经.md"
    if sp.exists():
        txt = sp.read_text(encoding="utf-8")
        rows = parse_table(txt)
        cards = [ep_num(r.get("集", "")) for r in rows
                 if "卡点" in str(r.get("卡点", "")) + str(r.get("序号", ""))]
        cards = [c for c in cards if c]
        if cards:
            first = min(cards)
            if not (8 <= first <= 12):
                warns.append(f"第一个付费卡点在 EP{first}，行业惯例是 EP10（±2）")
            else:
                oks.append(f"付费卡点 {len(cards)} 个，首个在 EP{first}")
            if len(cards) < 3:
                warns.append(f"只有 {len(cards)} 个卡点，60 集建议 3 个（10 / 29 / 46）")
        else:
            warns.append("故事圣经里没有卡点表 —— 卡点不排，节奏必散")
        if "时钟" in txt and len(txt.split("## 时钟")[1].split("##")[0].strip()) < 30:
            warns.append("时钟段太短 —— 没有可见时钟，中段必塌")

    # ---- 物品账本
    ip = b / "06_物品账本.md"
    if ip.exists():
        rows = parse_table(ip.read_text(encoding="utf-8"))
        empty = [r for r in rows if not r.get("当前持有", "").strip()]
        if empty:
            warns.append(f"物品账本有 {len(empty)} 件物件没记持有状态")

    for o in oks:
        print(f"  ✔ {o}")
    if warns:
        print()
        for w in warns:
            print(f"  🟠 {w}")
    if issues:
        print()
        for i in issues:
            print(f"  🔴 {i}")
    print("=" * 70)
    if issues:
        print(f"结论：🔴 {len(issues)} 条断线，改完再往下写")
        sys.exit(1)
    if warns:
        print(f"结论：🟠 {len(warns)} 条提醒")
        sys.exit(0)
    print("结论：✔ 连载状态健康")
    sys.exit(0)


def cmd_status(wd: Path, a) -> None:
    b = bible_path(wd)
    if not b.exists():
        print(f"[bible] 未初始化，先跑：series_bible.py {wd} init --title <剧名>",
              file=sys.stderr)
        sys.exit(2)
    st = load_state(wd)
    cur, total = int(st.get("current_ep", 0)), int(st.get("total_episodes", 60))
    title = st.get("title", "未命名")

    # 推断卷
    vol = "?"
    for lo, hi, nm in ((1, 10, "第一卷"), (11, 30, "第二卷"),
                       (31, 46, "第三卷"), (47, 999, "第四卷")):
        if lo <= (cur or 1) <= hi:
            vol, nxt = nm, (cur or 0) + 1
            break

    print(f"《{title}》连载状态")
    print("=" * 70)
    print(f"├─ 进度：EP{cur} / {total}（{vol}）")
    print(f"├─ 下一步：EP{cur + 1}")

    fp = b / "03_伏笔表.md"
    if fp.exists():
        rows = parse_table(fp.read_text(encoding="utf-8"))
        # 只显示真正填了内容的行：模板里的空占位行不该冒出来
        pend = [r for r in rows
                if "✅" not in r.get("状态", "") and r.get("内容", "").strip()]
        if pend:
            print("├─ 待兑现伏笔：")
            for r in pend[:5]:
                plant, payoff = ep_num(r.get("埋下集", "")), ep_num(r.get("兑现集", ""))
                span = ""
                if plant and payoff:
                    span = f"（埋 EP{plant} → 兑 EP{payoff}）"
                elif plant:
                    span = f"（埋于 EP{plant}，未定兑现集）"
                print(f"│    {r.get('ID','?')} {r.get('内容','')[:20]}{span}")
        else:
            print("├─ 待兑现伏笔：无（伏笔表还是空的，写大纲时同步登记）")

    # 下一个卡点
    sp = b / "01_故事圣经.md"
    if sp.exists():
        cards = sorted({c for c in
                        (ep_num(r.get("集", "")) for r in
                         parse_table(sp.read_text(encoding="utf-8"))) if c})
        nxt_card = next((c for c in cards if c > cur), None)
        if nxt_card:
            print(f"├─ 下一个卡点：EP{nxt_card}（还有 {nxt_card - cur} 集）")

    # 过期产物
    shots = wd / "shots.json"
    pdir = wd / "prompts"
    if shots.exists() and pdir.exists():
        smt = shots.stat().st_mtime
        stale = []
        for f in sorted(pdir.rglob("v_*.txt")):
            if f.stat().st_mtime < smt:
                stale.append(f.relative_to(wd).as_posix())
        if stale:
            print(f"└─ 过期产物：{len(stale)} 份（shots.json 已改，提示词要重刷）")
            for s in stale[:4]:
                print(f"     ⚠️ {s}")
        else:
            print("└─ 过期产物：无")
    else:
        print("└─ 过期产物：无（还没进分镜阶段）")
    print("=" * 70)


def cmd_advance(wd: Path, a) -> None:
    st = load_state(wd)
    st["current_ep"] = a.ep
    st["updated"] = datetime.now().strftime("%Y-%m-%d")
    save_state(wd, st)
    print(f"[bible] 进度 → EP{a.ep}")
    if a.ep in (10, 29, 46):
        print(f"🔔 EP{a.ep} 是付费卡点集：必须停在揭晓前一秒")


def cmd_add_fs(wd: Path, a) -> None:
    b = bible_path(wd)
    fp = b / "03_伏笔表.md"
    if not fp.exists():
        print("[bible] 伏笔表不存在，先 init", file=sys.stderr)
        sys.exit(2)
    txt = fp.read_text(encoding="utf-8")
    rows = parse_table(txt)
    nid = "F%02d" % (len(rows) + 1)
    line = f"| {nid} | {a.content} | EP{a.plant} | EP{a.payoff} | ⏳ |"
    # 插到表格最后一行之后
    lines = txt.splitlines()
    idx = max(i for i, l in enumerate(lines) if l.strip().startswith("|"))
    lines.insert(idx + 1, line)
    fp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[bible] 已登记 {nid}：{a.content}（埋 EP{a.plant} → 兑 EP{a.payoff}）")


def main() -> None:
    ap = argparse.ArgumentParser(description="连载记忆 · 夜秣AI短剧生成器")
    ap.add_argument("workdir")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("init")
    p.add_argument("--title", required=True)
    p.add_argument("--episodes", type=int, default=60)
    p.add_argument("--force", action="store_true")

    sub.add_parser("qc")
    sub.add_parser("status")

    p = sub.add_parser("advance")
    p.add_argument("--ep", type=int, required=True)

    p = sub.add_parser("add-foreshadow")
    p.add_argument("--content", required=True)
    p.add_argument("--plant", type=int, required=True)
    p.add_argument("--payoff", type=int, required=True)

    a = ap.parse_args()
    wd = Path(a.workdir)

    if a.cmd == "init":
        cmd_init(wd, a)
    elif a.cmd == "qc":
        cmd_qc(wd, a)
    elif a.cmd == "status":
        cmd_status(wd, a)
    elif a.cmd == "advance":
        cmd_advance(wd, a)
    elif a.cmd == "add-foreshadow":
        cmd_add_fs(wd, a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
