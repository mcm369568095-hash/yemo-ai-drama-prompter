# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ⓿ 导演层：按预设自动派发每镜的景别 / 运镜 / 光位 / 构图 / 时长 / 转场

用法:
  python story_plan.py <workdir> --preset drama            # 干跑，打印派发表 + 体检报告
  python story_plan.py <workdir> --preset drama --apply    # 写回 shots.json
  python story_plan.py <workdir> --check                   # 只体检现有分镜，不改

设计依据: references/导演层预设库.md
核心作用: 治「全片一个景别、一个机位、一种光」；单镜时长压到 3~6s。

为什么需要它:
  模型不会自己安排镜头。你不派发，它就默认给你「人物正面站一排的中景」，
  拍 24 镜就是 24 张换了衣服的静态合影。导演层的职责就一句话——
  **把「什么样的剧情，配什么样的镜头」固化成表，脚本按表派发，人只审节奏。**
"""
import argparse
import json
import os
import re
import sys

# ── 预设表（与 references/导演层预设库.md 一一对应）─────────────────────
PRESETS = {
    "drama": {
        "name": "剧情叙事",
        "ratio": {"全景": 15, "中景": 28, "近景": 34, "特写": 18, "空镜": 5},
        "light": [["窗边漫射", "室内暖灯"], ["午后侧光", "柔和顶光"],
                  ["冷调逆光", "高对比轮廓"], ["暮色柔光", "夜灯暖斑"]],
        "dur": {"base": 4.0, "mood": 5.5, "hit": 3.0},
    },
    "suspense": {
        "name": "悬念反转",
        "ratio": {"全景": 18, "中景": 20, "近景": 30, "特写": 25, "空镜": 7},
        "light": [["阴云冷调", "灰蓝低照"], ["冷调顶光", "暗角侧光"],
                  ["雨夜冷硬", "冷光暗角"], ["破晓微光", "冷转暖过渡"]],
        "dur": {"base": 3.5, "mood": 5.0, "hit": 2.5},
    },
    "warm": {
        "name": "温情治愈",
        "ratio": {"全景": 16, "中景": 30, "近景": 34, "特写": 14, "空镜": 6},
        "light": [["晨光柔侧", "窗边漫射"], ["午后暖阳", "树影斑驳"],
                  ["金色逆光", "暖色轮廓光"], ["夕照余晖", "暮色柔光"]],
        "dur": {"base": 4.5, "mood": 6.0, "hit": 3.0},
    },
    "epic": {
        "name": "史诗宏大",
        "ratio": {"全景": 32, "中景": 28, "近景": 24, "特写": 8, "空镜": 8},
        "light": [["破晓微光", "晨雾逆光"], ["正午硬光", "清朗顺光"],
                  ["庄严逆光", "高对比轮廓"], ["暖金长影", "落日平行光"]],
        "dur": {"base": 5.0, "mood": 6.0, "hit": 3.5},
    },
}

# ── 运镜池：L0 静 / L1 缓 / L2 中 / L3 快 / L4 冲击（带方向，便于交替）──────
CAM = {
    "drama": {
        "L0": ["固定微晃"],
        "L1": ["缓推", "缓拉"],
        "L2": ["左移跟", "右移跟"],
        "L3": ["急推", "缓升"],
        "L4": ["快摇"],
    },
    "suspense": {
        "L0": ["固定", "轻微手持"],
        "L1": ["缓推", "缓拉"],
        "L2": ["手持左跟", "手持右跟"],
        "L3": ["手持急推", "俯冲下压"],
        "L4": ["zoom_punch", "快速甩镜"],
    },
    "warm": {
        "L0": ["固定微晃"],
        "L1": ["缓推", "缓拉"],
        "L2": ["横移左跟", "横移右跟"],
        "L3": ["快速横移", "跟拍上升"],
        "L4": ["甩镜", "弹跳急推"],
    },
    "epic": {
        "L0": ["固定对称", "固定微晃"],
        "L1": ["缓推"],
        "L2": ["横摇左", "横摇右"],
        "L3": ["仰角缓升", "缓推"],
        "L4": ["快速拉升", "仰角冲击推"],
    },
}

# ── 构图池：按景别分组（相邻镜不得重复）──────────────────────────────────
COMPOSE = {
    "全景": ["大全景平视", "俯拍全景", "远景带前景遮挡", "低角度全景"],
    "中景": ["平视三分法", "仰拍中景", "侧逆中景", "框架式（门框）", "背影中景"],
    "近景": ["过肩近景", "侧脸近景", "正面近景浅景深", "贴地近景", "越肩视线引导"],
    "特写": ["面部特写", "手部细节特写", "物件特写（关键道具）", "眼神大特写"],
    "空镜": ["空场景空镜", "环境细节空镜", "天光空镜", "地景空镜"],
}

SUBJECT_RATIO = {"全景": 25, "中景": 45, "近景": 60, "特写": 80, "空镜": 0}
ORDER = ["全景", "中景", "近景", "特写", "空镜"]
HIT_AT = 0.72          # 情感高点位置（0~1）
MARK = "【镜头】"       # ff 里镜头语言后缀的分隔标记（保证幂等）


def strip_mark(text):
    """剥离上一次派发追加的镜头后缀，保证可重复执行。"""
    if not text:
        return ""
    i = text.find(MARK)
    return (text[:i] if i >= 0 else text).rstrip()


SIZE_WORD = re.compile(r"(大?全景|中景|近景|特写|远景|空镜|中近景|远景构图)\s*(构图)?\s*[：:]")


def strip_size_words(text):
    """剥掉原 ff 里自带的景别声明（如「全景构图：」）—— 景别一律由导演层说了算，
    否则会和【镜头】后缀打架，模型不知道该听谁的。"""
    return SIZE_WORD.sub("", text or "").strip()


def tension_at(i, n):
    """位置 → 张力值 0~1（越高越接近情感高点）。"""
    if n <= 1:
        return 1.0
    p = i / (n - 1.0)
    return max(0.0, 1.0 - abs(p - HIT_AT) / 0.38)


def assign_sizes(n, ratio, hints=None):
    """按配比 + 剧情位置派发景别，保证相邻不同。

    hints（分镜里的 size_hint）：**作者写死的拍摄意图，一律优先采纳** ——
    即便超出预设配比也不拒绝（导演层是助手，不是独裁者），相应核减配额。
    踩坑记录：c02「一起去看象」是有人的镜头，却被自动派成空镜，
    内容与景别打架。作者知道每镜该拍什么，自动派发只兜底。
    """
    hints = list(hints or [None] * n)
    quota = {k: max(1, round(n * v / 100.0)) for k, v in ratio.items()}
    while sum(quota.values()) > n:                      # 超额时从最大项削
        k = max(quota, key=lambda x: quota[x])
        quota[k] -= 1
    while sum(quota.values()) < n:                      # 不足时补中景
        quota["中景"] = quota.get("中景", 0) + 1

    sizes = [None] * n
    # 0) 作者指定优先（可为负配额 = 作者超额，后续不再分给自动位）
    for i, h in enumerate(hints):
        if h in COMPOSE:
            sizes[i] = h
            quota[h] = quota.get(h, 0) - 1

    # 1) 固定位：开场交代、收束定调、高潮特写（作者指定处不覆盖）
    if n >= 4:
        if sizes[0] is None:
            sizes[0] = "全景"
            quota["全景"] -= 1
        if sizes[-1] is None:
            sizes[-1] = "近景"
            quota["近景"] -= 1
    hit = int(round((n - 1) * HIT_AT))
    if sizes[hit] is None:
        sizes[hit] = "特写"
        quota["特写"] -= 1

    def take(kinds):
        for k in kinds:
            if quota.get(k, 0) > 0:
                quota[k] -= 1
                return k
        return None

    # 2) 高潮邻域：越靠近高点越近（特写/近景）
    for i in range(n):
        if sizes[i]:
            continue
        t = tension_at(i, n)
        if t >= 0.72:
            pick = take(["特写", "近景", "中景"])
        elif t >= 0.45:
            pick = take(["近景", "中景", "特写"])
        elif t < 0.28 and quota.get("空镜", 0) > 0 and 0 < i < n - 1:
            pick = take(["空镜"])                       # 低张力处插环境空镜
        elif i < n * 0.3:
            pick = take(["全景", "中景"])
        else:
            pick = take(["中景", "近景", "全景"])
        sizes[i] = pick or "中景"

    # 3) 消相邻冲突：与后一个可互换的镜交换（优先动「非作者指定」的那一个）
    for i in range(1, n):
        if sizes[i] != sizes[i - 1]:
            continue
        cands = [j for j in range(i + 1, n)
                 if sizes[j] != sizes[i]
                 and (j + 1 >= n or sizes[j + 1] != sizes[i])
                 and sizes[j - 1] != sizes[i]]
        cands.sort(key=lambda j: (hints[j] is not None, j))
        if cands:
            j = cands[0]
            sizes[i], sizes[j] = sizes[j], sizes[i]
            continue
        tgt = i if hints[i] is None else (i - 1 if hints[i - 1] is None else None)
        if tgt is not None:                     # 兜底：找一个配额允许的替身
            for k in ORDER:
                if k != sizes[tgt] and quota.get(k, 0) > 0:
                    quota[k] -= 1
                    sizes[tgt] = k
                    break
    return sizes, quota


def assign_cams(n, preset):
    """按张力派发运镜档位。

    硬约束：L4 全片 ≤3 次且**不得连用**；同一档位不得连用 3 次；运镜名方向交替。
    """
    pool = CAM[preset]
    ts = [tension_at(i, n) for i in range(n)]
    l4 = set(sorted(range(n), key=lambda i: -ts[i])[:3])
    cams, prev_dir = [], None

    def lv_of(x):
        return x.split(" ")[0]

    for i in range(n):
        t = ts[i]
        order = []
        if i in l4 and t >= 0.8:
            order.append("L4")
        if t >= 0.6:
            order.append("L3")
        if t >= 0.30:
            order.append("L2")
        order.append("L0" if i in (0, n - 1) else "L1")
        order += ["L2", "L1", "L3", "L0"]                 # 兜底候选
        lv = None
        for cand in order:
            if cand == "L4" and any(lv_of(c) == "L4" for c in cams[-2:]):
                continue                                  # L4 前后各留一镜缓冲
            if len(cams) >= 2 and lv_of(cams[-1]) == cand and lv_of(cams[-2]) == cand:
                continue                                  # 同档位不连用 3 次
            lv = cand
            break
        lv = lv or "L1"
        opts = pool[lv]
        pick = opts[i % len(opts)]
        if prev_dir and len(opts) > 1 and pick == prev_dir:
            pick = opts[(i + 1) % len(opts)]              # 防连续同向
        prev_dir = pick
        cams.append("%s %s" % (lv, pick))
    return cams


def assign_lights(n, preset):
    """四段光位，段内轮换、相邻不同。"""
    seqs = PRESETS[preset]["light"]
    out = []
    for i in range(n):
        seg = min(len(seqs) - 1, int(i / max(n, 1) * len(seqs)))
        opts = seqs[seg] + seqs[max(0, seg - 1)]
        pick = opts[i % len(opts)]
        if out and pick == out[-1]:
            pick = opts[(i + 1) % len(opts)]
        out.append(pick)
    return out


def assign_composes(n, sizes):
    out, prev = [], None
    for i, sz in enumerate(sizes):
        opts = COMPOSE[sz]
        pick = opts[(i // 2) % len(opts)]
        if pick == prev:
            pick = opts[(i // 2 + 1) % len(opts)]
        prev = pick
        out.append(pick)
    return out


# 中文旁白语速（字/秒，含标点停顿）。
# 实测校准：成人叙事旁白 ≈4.0 字/秒（儿童童声慢得多，约 3.6）。
# 宁可给足余量 —— 多逗号的短句比长句慢得多。
SUB_CPS = 4.0


def min_dur(text):
    """这一镜的字幕至少需要多少秒才念得完（含 0.6s 前导停顿）。"""
    t = re.sub(r"[，。！？、：；「」『』《》…—,.!?;:\s]", "", text or "")
    return len(t) / SUB_CPS + 0.6 if t else 0.0


def assign_durs(n, preset, shots=None, sub_cps=None):
    """派发时长：张力定基调，**字幕字数设下限**（治「字幕一闪而过、根本念不完」）。"""
    global SUB_CPS
    if sub_cps:
        SUB_CPS = float(sub_cps)
    d = PRESETS[preset]["dur"]
    out = []
    for i in range(n):
        t = tension_at(i, n)
        if t >= 0.85:
            base = d["hit"]
        elif i >= n - 2:
            base = d["mood"]
        else:
            base = d["base"]
        jitter = ((hash(("d", i)) % 7) - 3) * 0.1          # 确定性微抖动
        v = round(max(2.5, min(6.5, base + jitter)), 1)
        if shots is not None:
            need = min_dur(shots[i].get("sub", ""))
            if need > v:
                v = round(min(6.5, need), 1)
        out.append(v)
    return out


def assign_trans(n, ts):
    """默认硬切；段落边界溶解；段落收尾淡黑；情绪转折甩。"""
    out = []
    seg = n / 3.0
    for i in range(n):
        if i == 0:
            out.append("open")
        elif i == n - 1:
            out.append("fadeblack")
        elif abs(i - seg) < 0.6 or abs(i - 2 * seg) < 0.6:
            out.append("fade")
        elif ts[i] - ts[i - 1] > 0.32:
            out.append("slideleft" if i % 2 else "slideright")
        else:
            out.append("hard")
    return out


def plan(wd, preset, apply_it, sub_cps=None):
    path = os.path.join(wd, "shots.json")
    sc = json.load(open(path, encoding="utf-8"))
    shots = sc["shots"]
    n = len(shots)

    hints = [s.get("size_hint") for s in shots]
    sizes, leftover = assign_sizes(n, PRESETS[preset]["ratio"], hints)
    cams = assign_cams(n, preset)
    lights = assign_lights(n, preset)
    comps = assign_composes(n, sizes)
    durs = assign_durs(n, preset, shots, sub_cps)
    trans = assign_trans(n, [tension_at(i, n) for i in range(n)])

    for i, s in enumerate(shots):
        s["size"], s["cam"] = sizes[i], cams[i]
        s["light"], s["compose"] = lights[i], comps[i]
        s["dur"], s["trans"] = durs[i], trans[i]
        s.setdefault("sfx", "")
        # 镜头语言后缀（幂等）
        base = strip_size_words(strip_mark(s.get("ff", "")))
        sfx = s.get("sfx", "")
        tail = "%s%s｜%s｜%s｜%s｜主体占画面 %d%%（以本节为准，覆盖前文任何构图描述）" % (
            MARK, sizes[i], comps[i], cams[i], lights[i], SUBJECT_RATIO[sizes[i]])
        if sfx:
            tail += "｜音效 %s" % sfx
        s["ff"] = (base + "\n" + tail).strip() if base else tail

    if apply_it:
        json.dump(sc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return sc, sizes, cams, lights, comps, durs, trans


def audit(sc, preset, target=110):
    shots = sc["shots"]
    n = len(shots)
    lines = []
    miss = [k for k in ("size", "cam", "light", "compose", "dur")
            if any(k not in s for s in shots)]
    if miss:
        lines.append("🔴 分镜尚未派发（缺字段：%s）" % "、".join(miss))
        lines.append("   先跑：python story_plan.py <workdir> --preset <key> --apply")
        return lines, 0

    def stat(key):
        c = {}
        for s in shots:
            v = str(s.get(key, "")).split(" ", 1)[-1]
            c[v] = c.get(v, 0) + 1
        return c

    sz = stat("size")
    ratio = PRESETS[preset]["ratio"]
    lines.append("景别分布：")
    for k in ORDER:
        got = sz.get(k, 0)
        want = round(n * ratio[k] / 100.0)
        flag = "" if abs(got - want) <= max(1, n * 0.08) else "  ⚠️ 偏差"
        lines.append("  %-4s %2d 镜（目标 %2d）%s" % (k, got, want, flag))

    same_sz = sum(1 for i in range(1, n)
                  if shots[i]["size"] == shots[i - 1]["size"])
    same_li = sum(1 for i in range(1, n)
                  if shots[i]["light"] == shots[i - 1]["light"])
    l4 = sum(1 for s in shots if str(s["cam"]).startswith("L4"))
    lights_kinds = len(set(s["light"] for s in shots))
    comps_kinds = len(set(s["compose"] for s in shots))
    durs = [float(s["dur"]) for s in shots]
    avg = sum(durs) / n
    var = (sum((x - avg) ** 2 for x in durs) / n) ** 0.5
    total = sum(durs)

    lines.append("相邻同景别 %d 处（应为 0）" % same_sz)
    lines.append("相邻同光位 %d 处（应为 0）" % same_li)
    lines.append("冲击镜 L4 共 %d 次（应 ≤3）" % l4)
    lines.append("光位种类 %d 种（应 ≥4）／构图种类 %d 种（应 ≥5）"
                 % (lights_kinds, comps_kinds))
    hint_n = sum(1 for s in shots if s.get("size_hint"))
    if hint_n:
        lines.append("作者指定景别 %d 镜（优先采纳，配比相应核减）" % hint_n)
    lines.append("镜数 %d ／ 平均 %.1fs ／ 最长 %.1fs ／ 总长约 %.0fs"
                 % (n, avg, max(durs), total))
    tight = [(s["id"], float(s["dur"]), min_dur(s.get("sub", "")))
             for s in shots if min_dur(s.get("sub", "")) > float(s["dur"]) + 0.05]
    if tight:
        lines.append("🔴 字幕念不完 %d 镜：%s（按 %.1f 字/秒算）"
                     % (len(tight),
                        "、".join("%s %.1fs<%0.1fs" % t for t in tight[:6]), SUB_CPS))
    if total < target * 0.85:
        need = int(round(target / max(avg, 0.1)))
        lines.append("⚠️ 总长偏短：短剧甜区 %d~%ds，当前 %.0fs。"
                     % (int(target * 0.9), int(target * 1.1), total))
        lines.append("   按平均 %.1fs/镜 算，需 %d 镜 —— 建议再拆 %d 个情节节拍"
                     % (avg, need, max(1, need - n)))
    elif total > target * 1.25:
        lines.append("⚠️ 总长偏长（%.0fs）：检查是否有可合并的重复节拍" % total)

    score = 100.0
    score -= same_sz * 8 + same_li * 4
    score -= max(0, 4 - lights_kinds) * 6
    score -= max(0, 5 - comps_kinds) * 5
    score -= max(0, l4 - 3) * 5
    score -= 8 if var < 0.4 else 0
    score -= 6 if avg > 7 else 0
    score = int(max(0, min(100, round(score))))

    verdict = "✅ 可进入出片" if score >= 70 else "🔴 不许出片，先改分镜"
    lines.append("")
    lines.append("镜头多样性评分：%d / 100　%s" % (score, verdict))
    if score < 70:
        lines.append("扣分项：%s" % ("；".join(
            [x for x in [
                "相邻同景别 %d 处" % same_sz if same_sz else "",
                "相邻同光位 %d 处" % same_li if same_li else "",
                "光位只有 %d 种" % lights_kinds if lights_kinds < 4 else "",
                "构图只有 %d 种" % comps_kinds if comps_kinds < 5 else "",
                "冲击镜超量 %d 次" % l4 if l4 > 3 else "",
                "镜长过于平均" if var < 0.4 else "",
            ] if x]) or "—"))
    return lines, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--preset", default="drama", choices=list(PRESETS))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--target-sec", type=float, default=110,
                    help="短剧目标时长（秒），用于镜数建议")
    ap.add_argument("--sub-cps", type=float, default=0,
                    help="旁白语速（字/秒），不填用默认 4.0；童声建议 3.6")
    a = ap.parse_args()

    wd = a.workdir
    path = os.path.join(wd, "shots.json")
    if not os.path.exists(path):
        print("找不到 shots.json：", path)
        sys.exit(1)

    if a.check:
        sc = json.load(open(path, encoding="utf-8"))
        preset = sc.get("preset", a.preset)
    else:
        sc, sizes, cams, lights, comps, durs, trans = plan(
            wd, a.preset, a.apply, a.sub_cps or None)
        sc["preset"] = a.preset
        preset = a.preset
        print("预设：%s（%s）" % (a.preset, PRESETS[a.preset]["name"]))
        print("%-5s %-6s %-14s %-8s %-5s %-10s" %
              ("镜号", "景别", "运镜", "光位", "时长", "转场"))
        for s in sc["shots"]:
            print("%-5s %-6s %-14s %-8s %-5s %-10s" %
                  (s["id"], s["size"], s["cam"], s["light"], s["dur"], s["trans"]))
        print()
        if a.apply:
            json.dump(sc, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("已写回", path, "（含 preset 字段）")
        else:
            print("干跑模式，未写盘。确认后加 --apply")

    lines, score = audit(sc, preset, a.target_sec)
    print("\n─── 分镜体检 ───")
    for l in lines:
        print(l)
    if a.check and score < 70:
        sys.exit(2)


if __name__ == "__main__":
    main()
