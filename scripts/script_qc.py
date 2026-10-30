#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧本质检 · 夜秣AI短剧生成器 v2.0

把 references/剧本质检规则集.md 的 Q 系列规则变成能跑的机器检查。
自动扫的机器扫，扫不出来的列出人工检查项 —— 不假装全能。

用法：
  script_qc.py 剧本.md                  # 单集/多集检查（人读报告）
  script_qc.py 剧本.md --strict          # 严格档（含合规终审）
  script_qc.py 剧本.md --json            # 机器可读
  script_qc.py 剧本.md --clean -o 清稿.md # 清稿：剥掉元数据
  script_qc.py 剧本.md --cps 400         # 自定义折算字数（默认 400 字/分钟）

退出码：0 通过 / 1 有命中 / 2 打回重写
只用标准库。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ------------------------------------------------------------------ 规则词典

# Q19 套话形容词（AI 味头号特征）
CLICHE = ["声音冷得像冰", "冷得像冰", "笑意不达眼底", "不达眼底", "一字一顿", "眸色一沉",
          "眸光一暗", "眼眸微沉", "尖声", "厉声", "冷笑一声", "勾唇", "嘴角勾起",
          "眼神一凛", "神色复杂", "心中五味杂陈", "意味深长地"]

# Q21 空洞名词（不接具体事件时）
HOLLOW = ["命运", "救赎", "深渊", "执念", "宿命", "轮回", "因果"]

# Q22 解释性旁白
HEDGE = ["仿佛", "似乎", "像是", "仿佛在说", "好像", "宛如", "犹如"]

# Q8 心理描写。用正则而不是词表 —— 中文的「心里」可以插在任何位置
# （"她心里清楚" / "心里明白" / "在心里想"），词表会漏。
PSY_PAT = re.compile(
    r"(?:她|他|它|她们|他们)?\s*(?:心里|心中|心底|内心)\s*"
    r"(?:想|清楚|明白|知道|一沉|一紧|发苦|咯噔|不是滋味)"
    r"|她想|他想|心想|心里想|感觉到|意识到|回忆起|内心独白|暗自|默念")

# Q12 元数据（夹带在正文里的机器标记）
META_PAT = [
    r"【所属阶段】[^\n]*", r"【本集结算】[^\n]*", r"【阶段】[^\n]*",
    r"（伏笔[，,][^\n]*?）", r"\[连续性\][^\n]*", r"\[自检表\][^\n]*",
    r"预估\s*\d+(\.\d+)?\s*秒", r"EPISODE_ID[^\n]*", r"SCRIPT_VERSION[^\n]*",
    r"认领爽点[^\n]*", r"Continuation Capsule", r"记忆检查点",
    r"^\s*\|\s*检查项\s*\|", r"节奏标注[^\n]*",
]

# 场景行：集-场 制
SCENE_PAT = re.compile(r"^\s*(\d+)\s*[-–—]\s*(\d+)\s+([日夜晨昏黄昏凌晨])\s+([内外])\s+(.+)$")
# 台词行：人名：台词
LINE_PAT = re.compile(r"^\s*([^\s△:：]{1,8}?)\s*[：:]\s*(.+)$")
# 动作行
ACT_PAT = re.compile(r"^\s*△\s*(.+)$")
# 集分隔：独占一行的「第 N 集　标题」。
# 刻意不匹配「第 1 集约 610 字…」这种体例说明（后面跟了长内容），
# 也不匹配「（第 1 集完）」（前面有括号）。
SP = r"[ \t　]*"
EP_PAT = re.compile(r"^\s*第\s*([0-9]+)\s*集" + SP + r"(.{0,18})?" + SP + r"$")
EP_PAT2 = re.compile(r"^\s*EP\s*([0-9]+)" + SP + r"(.{0,18})?" + SP + r"$")

# 非台词行（不进对白统计）：身份卡、体例说明、场务标记
NOT_SPEAKER = {"字幕", "人物", "体例", "时长折算", "画幅", "地点", "时间", "主要人物",
               "本集", "提示", "注", "备注", "转场", "音乐", "音效", "OS", "VO"}

# Q6 用的动作动词词典 —— 中文的「，」分隔并列短语，不是复合动作。
# 只有真的出现多个谓语动词，才会在视频里糊成一团。
VERBS = ["推开", "推门", "推", "拉", "转身", "转过", "走向", "走", "跑向", "跑", "拿起",
         "放下", "站起", "站", "坐下", "坐", "蹲下", "蹲", "抬起", "抬头", "低下", "低头",
         "回头", "挥手", "挥", "抓住", "攥住", "攥", "捏", "擦拭", "擦", "摸出", "摸",
         "摘下", "摘", "穿上", "穿", "脱下", "脱", "打开", "关上", "看向", "看", "听见",
         "听", "笑", "哭", "指向", "指", "点头", "敲", "摔碎", "摔", "扔", "递给", "递",
         "接过", "接", "抱住", "抱", "扶", "跪", "扑", "闪", "躲", "追", "逃", "倒",
         "躺", "趴", "翻开", "翻", "爬", "踩", "踢", "打", "拍", "举起", "举", "握住",
         "握", "松开", "掰", "掐", "舀", "吹", "哼", "唱", "抹", "刷", "缝", "撕掉",
         "撕", "捡起", "捡", "按住", "按", "扳", "拖", "拽", "掀开", "掀", "盖上", "盖",
         "摊开", "掖", "塞", "插", "拔出", "拔", "拧", "扭", "弯腰", "弯", "俯", "仰",
         "靠", "迈", "跨", "退", "冲向", "冲", "挡", "拦", "搂", "挣脱", "颤抖", "发抖",
         "颤", "抖"]

# 歧义词：这些词里含动词字，但根本不是动作（"指腹"/"石缝"/"接着"）。
# 数动词之前先把它们从句子里挖掉，否则中文的子串匹配会疯狂误报。
AMBIG = ["指腹", "一指宽", "一指", "手指", "食指", "拇指", "指甲", "指缝", "十指", "指头",
         "指了指", "转过身", "石缝", "门缝", "缝隙", "缝里", "缝儿", "夹缝",
         "接着", "接下", "接住", "接收", "接续", "接上", "接电话",
         "看法", "看护", "说客", "坐落", "站住", "站岗", "站台上", "站台",
         "打算", "打量", "打发", "打击", "走狗", "走运", "走路", "跑腿", "跑步",
         "跑道", "开关", "开庭", "开口", "开腔", "抬头纹", "低头族", "点数"]


# ------------------------------------------------------------------ 解析


def count_verbs(seg: str) -> list:
    """数一句里的谓语动词。中文没有空格，只能靠词典 + 歧义词排除。"""
    s = seg
    for amb in AMBIG:
        s = s.replace(amb, "\u3000")
    hits = sorted({v for v in VERBS if v in s}, key=len, reverse=True)
    uniq = []
    for h in hits:  # 长词优先吃掉短词：「推开」吃掉「推」
        if not any(h in u for u in uniq):
            uniq.append(h)
    return uniq


def split_episodes(text: str) -> list:
    """把全文切成 [{no, title, lines, lead}]。lead=True 的是正文前的前导块（体例/人物表）。"""
    eps = []
    cur = {"no": 0, "title": "", "lines": [], "lead": True}
    eps.append(cur)
    for line in text.splitlines():
        m = EP_PAT.match(line) or EP_PAT2.match(line)
        if m:
            no = int(m.group(1))
            cur = {"no": no, "title": (m.group(2) or "").strip(), "lines": [], "lead": False}
            eps.append(cur)
            continue
        cur["lines"].append(line)
    return eps


def parse_dialogs(lines: list) -> list:
    """提取 (who, text, is_vo)；身份卡/体例说明不算对白"""
    out = []
    for l in lines:
        if l.strip().startswith("△"):
            continue
        m = LINE_PAT.match(l)
        if not m:
            continue
        who, txt = m.group(1).strip(), m.group(2).strip()
        if who in NOT_SPEAKER:
            continue
        # 「周桂兰（极轻）」→ who=周桂兰，括号里是表演提示
        vo = bool(re.search(r"VO|OS|画外|旁白", who + txt))
        who = re.sub(r"（[^）]*）|\([^)]*\)", "", who).strip() or who
        out.append((who, txt, vo))
    return out


def is_meta(line: str) -> bool:
    """这行是不是夹带的元数据（【所属阶段】/预估 90 秒/EPISODE_ID…）"""
    s = str(line or "").strip()
    if not s:
        return False
    return any(re.search(p, s) for p in META_PAT)


def cjk_count(s: str) -> int:
    """非空白字数（中日韩 + 拉丁词都算 1 个字）"""
    s = re.sub(r"\s+", "", s)
    return len(s)


# ------------------------------------------------------------------ 检查项


def check_ep(ep: dict, cps: int) -> list:
    """返回 [(level, rule, where, evidence, advice)]"""
    out = []
    lines = ep["lines"]
    body = [l for l in lines if l.strip()]
    join = "\n".join(lines)

    scenes = [l for l in lines if SCENE_PAT.match(l)]
    acts = [m.group(1) for l in lines if (m := ACT_PAT.match(l))]
    dialogs = parse_dialogs(lines)

    # 正文 = 去掉场景行与人物行的其余内容
    narr = [l for l in lines
            if l.strip() and not SCENE_PAT.match(l)
            and not re.match(r"^\s*人物[：:]", l)]
    n_chars = cjk_count("\n".join(narr))
    minutes = n_chars / cps if cps else 0

    tag = f"第{ep['no']}集" if ep["no"] else "全文"
    tit = f"《{ep['title']}》" if ep["title"] else ""
    lead = ep.get("lead", False)

    # ---- 结构类检查对前导块（体例/人物表）不适用，跳过
    if not lead:
        # ---- Q1 时长装得下
        if minutes > 2.3:
            out.append(("🔴", "Q1", f"{tag}{tit}",
                        f"正文 {n_chars} 字 ≈ {minutes:.1f} 分钟（按 {cps} 字/分）",
                        "超过 2 分钟。砍场或拆成两集"))
        elif 0 < minutes < 0.6 and n_chars > 50:
            out.append(("🟠", "Q1", f"{tag}{tit}",
                        f"正文 {n_chars} 字 ≈ {minutes:.1f} 分钟",
                        "偏短，可能撑不满 1 分钟"))

        # ---- Q2 场数：少于 2 场太薄，多于 6 场必超时
        #      （阈值按实测放宽：竖屏短剧一场可以撑 40 秒，冠军稿也有 2 场的集）
        if 0 < len(scenes) < 2:
            out.append(("🟠", "Q2", f"{tag}{tit}", f"只有 {len(scenes)} 场",
                        "内容偏薄，建议补到 2–5 场"))
        elif len(scenes) > 6:
            out.append(("🔴", "Q2", f"{tag}{tit}", f"共 {len(scenes)} 场",
                        "多于 6 场，1–2 分钟装不下，砍到 3–5 场"))

    # ---- Q6 动作解耦：一句话里塞太多谓语动词才会糊成一团
    #      中文的「，」分隔的多是并列短语，只有真出现多个动词才算复合动作
    for a in acts:
        for seg in re.split(r"[。！？;；]+", a):
            seg = seg.strip()
            if not seg:
                continue
            uniq = count_verbs(seg)
            if len(uniq) > 2:
                out.append(("🟠", "Q6", f"{tag}{tit}",
                            seg[:40] + ("…" if len(seg) > 40 else ""),
                            f"一句含 {len(uniq)} 个动词（{'/'.join(uniq[:5])}），"
                            "超过 2 个复合动作会肢体融化，拆成两句"))
                break  # 每集只报一条，避免刷屏
        else:
            continue
        break

    # ---- Q7 OS/VO 不超过对白的 1/3
    osvo = sum(1 for _, _, v in dialogs if v)
    plain = len(dialogs) - osvo
    if plain and osvo > plain / 2:
        out.append(("🔴", "Q7", f"{tag}{tit}",
                    f"旁白 {osvo} 句 / 对白 {plain} 句",
                    "OS/VO 超过对白的 1/3，戏被旁白撑起来了"))

    # ---- Q8 心理描写（上不了屏，一律改成动作或物件）
    m = PSY_PAT.search(join)
    if m:
        for l in lines:
            if PSY_PAT.search(l) and l.strip() and not l.strip().startswith("#"):
                out.append(("🔴", "Q8", f"{tag}{tit}",
                            l.strip()[:44] + ("…" if len(l.strip()) > 44 else ""),
                            f"命中心理描写「{m.group(0)}」，改成看得见的动作或物件"))
                break

    # ---- Q10 台词长度：25 字提醒，40 字必改
    #      （阈值取自实测：冠军稿也有 17–37 字的台词，15 字过严会误伤好稿）
    long_lines, very_long = [], []
    for who, d, _ in dialogs:
        d2 = re.sub(r"（[^）]*）|\([^)]*\)", "", d).strip()
        if len(d2) > 40:
            very_long.append(f"{who}：{d2[:24]}…({len(d2)}字)")
        elif len(d2) > 25:
            long_lines.append(f"{who}：{d2[:24]}…({len(d2)}字)")
    if very_long:
        out.append(("🔴", "Q10", f"{tag}{tit}", "；".join(very_long[:3]),
                    f"{len(very_long)} 句台词超过 40 字，必然超时，砍成短句"))
    if long_lines:
        out.append(("🟠", "Q10", f"{tag}{tit}", "；".join(long_lines[:3]),
                    f"{len(long_lines)} 句台词超过 25 字，建议砍短"))

    # ---- Q12 夹带元数据
    for pat in META_PAT:
        m = re.search(pat, join, re.M)
        if m:
            out.append(("🔴", "Q12", f"{tag}{tit}", m.group(0)[:44],
                        "正文夹带元数据，交付前必须清掉（盲评头号扣分项）"))
            break

    # ---- Q19 套话形容词
    hits = [c for c in CLICHE if c in join]
    if hits:
        cnt = sum(join.count(c) for c in hits)
        out.append(("🟠", "Q19", f"{tag}{tit}",
                    "、".join(hits[:4]) + (f" 共 {cnt} 处" if cnt > len(hits) else ""),
                    "套话形容词，删掉换成物件动作"))

    # ---- Q20 三段排比
    trio = find_trio(body)
    if trio:
        out.append(("🟠", "Q20", f"{tag}{tit}", " / ".join(x[:16] for x in trio[:3]),
                    "连续三句结构相同（排比味），打乱句式"))

    # ---- Q21 空洞名词
    hl = [h for h in HOLLOW if h in join]
    if hl:
        out.append(("🟡", "Q21", f"{tag}{tit}", "、".join(hl[:4]),
                    "空洞名词，接上具体事件，否则删掉"))

    # ---- Q22 解释性旁白
    hg = [h for h in HEDGE if h in join]
    if hg:
        out.append(("🟡", "Q22", f"{tag}{tit}", "、".join(hg[:4]),
                    "解释味，删掉让画面自己说话"))

    # ---- Q5 集尾钩子（机器判不了强弱，只做提醒；前导块跳过）
    if not lead:
        tail = [l.strip() for l in reversed(body)
                if l.strip()
                and not re.match(r"^（第\s*\d+\s*集完）", l.strip())
                and not is_meta(l)][:3]
        tail_txt = " ".join(reversed(tail))
        if tail_txt and not re.search(r"[？?！!]|\.\.\.|……", tail_txt):
            out.append(("🟡", "Q5", f"{tag}{tit}", tail_txt[:44],
                        "集尾未见明显钩子/悬念标记，人工确认是否停在揭晓前一秒"))

    return out


def find_trio(lines: list) -> list:
    """连续三句结构相同：字数接近 + 开头两字相同 + 结尾标点相同"""
    seq = [l.strip() for l in lines if l.strip()]
    seq = [s for s in seq if 6 <= len(s) <= 40]
    for i in range(len(seq) - 2):
        a, b, c = seq[i], seq[i + 1], seq[i + 2]
        if (abs(len(a) - len(b)) <= 3 and abs(len(b) - len(c)) <= 3
                and a[:2] == b[:2] == c[:2]):
            return [a, b, c]
    return []


MANUAL = [
    ("Q4", "开场 3 秒内是否有激励事件或悬念（不许铺垫）"),
    ("Q5", "每集结尾是否停在「揭晓前一秒」，而不是情绪式收尾"),
    ("Q9", "关键转折是否有可见的动作或物件承载"),
    ("Q13", "爽点是否当众落地（不在镜头外、不靠转述）"),
    ("Q14", "每个关键情绪点是否有一件物件承载"),
    ("Q15", "反派动机是否可被理解（不是纯坏）"),
    ("Q16", "配角是否有底线（有一句「可以…但不行」式的台词）"),
    ("Q17", "主角是否有具体职业（不是「厉害的人」）"),
    ("Q23", "人物是否替作者说话（总结/感慨/点题）"),
]

MANUAL_STRICT = [
    ("S 合规", "无广电 16 号令 11 条红线内容"),
    ("S 合规", "复仇结局走法律程序，不私刑"),
    ("S 合规", "巨额财物有正当去向（不炫富）"),
    ("S 合规", "虚构药名/批号不与真实药品冲突"),
    ("S 形式", "AI 生成标识预留位"),
    ("S 形式", "备案号预留位"),
]


def clean_text(text: str) -> str:
    """清稿：剥掉正文里夹带的元数据"""
    out = text
    for pat in META_PAT:
        out = re.sub(pat, "", out, flags=re.M)
    # 空行压缩到最多两个
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


# ------------------------------------------------------------------ 报告


def render(eps_n: int, findings: list, manual: list, cps: int) -> str:
    L = []
    L.append("=" * 74)
    L.append("剧本质检报告 · 夜秣AI短剧生成器")
    L.append(f"集数：{eps_n} ｜折算：{cps} 字/分钟")
    L.append("=" * 74)

    red = [f for f in findings if f[0] == "🔴"]
    org = [f for f in findings if f[0] == "🟠"]
    yel = [f for f in findings if f[0] == "🟡"]

    if not findings:
        L.append("")
        L.append("✔ 机器扫描：全部通过")
    else:
        for lv, group in (("🔴 必须改", red), ("🟠 建议改", org), ("🟡 可保留", yel)):
            if not group:
                continue
            L.append("")
            L.append(f"── {lv}（{len(group)} 条）" + "─" * 40)
            for level, rule, where, ev, adv in group:
                L.append(f"  [{rule}] {where}")
                L.append(f"      证据：{ev}")
                L.append(f"      建议：{adv}")

    L.append("")
    L.append("── 人工检查项（机器扫不出来，必须人眼过一遍）" + "─" * 22)
    for rule, desc in manual:
        L.append(f"  [{rule}] {desc}")

    L.append("")
    L.append("=" * 74)
    if len(red) >= 3:
        L.append("结论：🔴 打回重写（必改项 ≥3）")
    elif red:
        L.append(f"结论：🟠 改完再审（必改 {len(red)} 条）")
    else:
        L.append("结论：✔ 机器项通过，人工项确认后即可交付")
    L.append("=" * 74)
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="剧本质检 · 夜秣AI短剧生成器")
    ap.add_argument("script", help="剧本 .md 文件")
    ap.add_argument("--strict", action="store_true", help="严格档（含合规终审项）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--clean", action="store_true", help="清稿：剥掉元数据")
    ap.add_argument("-o", "--out", help="--clean 的输出文件")
    ap.add_argument("--cps", type=int, default=400, help="折算字数（默认 400 字/分钟）")
    ap.add_argument("--target-min", type=float, help="目标分钟数（用于时长判断）")
    a = ap.parse_args()

    p = Path(a.script)
    if not p.exists():
        print(f"[qc] 文件不存在：{p}", file=sys.stderr)
        sys.exit(2)
    text = p.read_text(encoding="utf-8", errors="replace")

    if a.clean:
        cleaned = clean_text(text)
        if a.out:
            Path(a.out).write_text(cleaned, encoding="utf-8")
            before, after = len(text), len(cleaned)
            print(f"[qc] 清稿完成 → {a.out}")
            print(f"[qc] 剥离 {before - after} 字符（{before} → {after}）")
        else:
            print(cleaned)
        raise SystemExit(0)

    eps = split_episodes(text)
    findings = []
    for ep in eps:
        findings.extend(check_ep(ep, a.cps))

    manual = list(MANUAL)
    if a.strict:
        manual += MANUAL_STRICT

    if a.json:
        print(json.dumps({
            "file": str(p),
            "episodes": len(eps),
            "cps": a.cps,
            "findings": [{"level": f[0], "rule": f[1], "where": f[2],
                          "evidence": f[3], "advice": f[4]} for f in findings],
            "manual": [{"rule": r, "desc": d} for r, d in manual],
            "red": sum(1 for f in findings if f[0] == "🔴"),
        }, ensure_ascii=False, indent=2))
    else:
        print(render(len(eps), findings, manual, a.cps))

    red = sum(1 for f in findings if f[0] == "🔴")
    if red >= 3:
        sys.exit(2)
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
