# -*- coding: utf-8 -*-
"""夜秣AI短剧生成器 · ① 逐镜视频提示词（四段式 + 资产冻结块 + 四条 lint）

这是本技能的**心脏**：把一镜的「人物 + 场景 + 动作 + 镜头」，
写成视频模型真正读得懂的一段话。

借鉴漫剧实战（官方提示词手册 / 长片开源方法论）校准后的打法是：

| 铁律 | 落地方式 |
|---|---|
| 资产先行，冻结块逐字复用 | 角色描述全部来自 `asset_lock.block_for()`，自己一个字都不写 |
| 三视图劝退，只用「脸 + 全身」 | 参考图由 cast_card 按景别给（本脚本不碰图，只管文本） |
| 英文写描述，中文说台词 | 主体英文；台词行 `Name (Pinyin) says in Mandarin {…}` |
| 否定约束只对字幕/音频有效 | 画面上的「不要」一律转肯定式（POS_STABLE） |
| 情绪不写抽象词 | `EMOTION2ACT` 词典命中即报警并给物理动作替代表达 |
| 一镜只许一种运镜 | lint 数运镜动词，>1 报警；复杂动作必须放开场 |
| 原生对白做不出就改镜头设计 | 台词行可选（shot["line"]），提示不靠后期配音救 |

四段结构：
  [ASSET-LOCK …]      指纹头（verify 靠它判过期）
  [SETUP]            画风锁 + 逐字冻结的角色特征
  [0.0-1.7s] …       时间轴（动作按秒切段，复杂动作放开场）
  [LINE]             台词（可选，中文 + 拼音注音）
  [LOOK & SOUND]     景别/构图/运镜/光位 + 环境声
  [CONSTRAINTS]      肯定式稳定约束 + 技术负向

用法:
  python shot_prompt.py <workdir> [sid ...]            # 干跑：打印 prompt + lint
  python shot_prompt.py <workdir> --apply              # 落盘 prompts/v_cNN.txt
  python shot_prompt.py <workdir> --apply --force      # 覆盖已存在的
  python shot_prompt.py <workdir> --lang en            # 冻结块用英文（需 cast.json 填 features_en）
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asset_lock  # noqa: E402

PR_DIR = "prompts"

# ── 运镜：中文派发名 → 英文句（只取一句，一镜一运镜）────────────────
CAM_EN = [
    (("zoom_punch", "弹跳急推", "快推"), "A quick zoom punch toward the subject."),
    (("甩镜", "快摇", "快速甩"), "Camera whips quickly to the side."),
    (("俯冲下压", "快速拉升", "急升"), "Camera cranes down fast toward the scene."),
    (("仰角冲击推",), "Camera tilts up and pushes in hard."),
    (("急推", "手持急推"), "Camera pushes in quickly."),
    (("缓推",), "Camera slowly pushes in."),
    (("缓拉",), "Camera slowly pulls back."),
    (("缓升", "仰角缓升", "跟拍上升"), "Camera rises slowly."),
    (("横摇左", "左移跟", "手持左跟", "横移左"), "Camera tracks left, following the subject."),
    (("横摇右", "右移跟", "手持右跟", "横移右"), "Camera tracks right, following the subject."),
    (("快速横移",), "Camera moves sideways quickly."),
    (("固定对称",), "Locked-off camera, perfectly still."),
    (("固定", "微晃", "轻微手持"), "Static camera with a very subtle handheld sway."),
]

SIZE_EN = [
    (("大全景", "远景"), "extreme wide shot"),
    (("全景",), "wide shot"),
    (("中近景", "近景"), "medium close-up"),
    (("中景",), "medium shot"),
    (("特写",), "close-up"),
    (("空镜",), "empty environment shot, no characters"),
]

COMPOSE_EN = [
    (("过肩",), "over-the-shoulder framing"),
    (("越肩",), "over-the-shoulder eyeline framing"),
    (("仰", "低角"), "low angle"),
    (("俯", "高角"), "high angle"),
    (("对称",), "symmetrical composition"),
    (("侧逆", "侧脸", "侧"), "three-quarter side angle"),
    (("平视三分法",), "eye-level rule-of-thirds framing"),
    (("框架", "门框"), "framed-in-doorway composition"),
    (("背影",), "medium shot from behind"),
    (("贴地",), "ground-level framing"),
    (("浅景深",), "frontal framing with shallow depth of field"),
    (("眼神",), "extreme close-up on the eyes"),
    (("手部",), "close-up on the hands"),
    (("物件", "道具"), "close-up on the key prop"),
    (("面部",), "close-up on the face"),
    (("天光",), "sky-light empty shot"),
    (("地景",), "ground-level landscape empty shot"),
    (("环境细节",), "close-up on an environment detail"),
    (("空场景", "空镜"), "empty environment, no characters"),
    (("带前景遮挡",), "wide shot with foreground occlusion"),
    (("平视",), "eye level"),
    (("平",), "eye level"),
]

LIGHT_EN = [
    (("冷调逆光",), "cool backlit rim light"),
    (("晨光柔侧", "晨雾逆光"), "soft diffused morning light"),
    (("窗边漫射", "漫射"), "soft diffused window light"),
    (("室内暖灯", "暖灯"), "warm indoor lamplight"),
    (("夜灯暖斑", "暖斑"), "warm pools of lamplight at night"),
    (("破晓微光", "破晓"), "first light of dawn"),
    (("正午硬光", "硬光"), "hard midday light"),
    (("清朗顺光",), "clear frontal daylight"),
    (("明快侧光",), "bright side light"),
    (("午后暖阳", "午后侧光", "午后"), "warm afternoon light"),
    (("树影斑驳", "跳跃光斑", "光斑"), "dappled light through leaves"),
    (("聚光高亮", "聚光"), "tight spotlight"),
    (("金色逆光", "庄严逆光", "逆光"), "golden backlit rim light"),
    (("暖色轮廓光", "高对比轮廓"), "high-contrast warm rim light"),
    (("夕照余晖",), "afterglow of sunset"),
    (("暖金长影",), "long warm golden shadows"),
    (("暮色柔光", "暮", "夕阳", "落日", "夕照"), "soft dusk light"),
    (("雨夜冷硬",), "cold hard light on a rainy night"),
    (("阴云冷调", "灰蓝低照", "灰蓝"), "overcast cool light"),
    (("冷调顶光", "冷调"), "cool top light"),
    (("冷光暗角", "暗角"), "cool light with deep vignette"),
    (("冷转暖",), "cool-to-warm transition light"),
    (("烛",), "warm candlelight"),
    (("柔和顶光", "顶光"), "soft top light"),
    (("侧光", "侧逆"), "side light"),
    (("暖",), "warm light"),
    (("冷", "阴"), "cool blue light"),
    (("夜", "暗"), "dim low-key light"),
]

# ── 情绪抽象词 → 物理动作（模型读不懂「悲伤」，读得懂「低头、肩膀轻颤」）──
EMOTION2ACT = {
    "悲伤": "低头、肩膀轻颤、手指无意识攥住衣角 ｜ EN: lowers his head, shoulders trembling, fingers gripping his hem",
    "难过": "嘴角向下、视线垂地、呼吸变慢 ｜ EN: mouth turns down, eyes drop to the ground, breathing slows",
    "高兴": "嘴角上扬、眼睛弯起、脚步轻快带小跳 ｜ EN: smiles, eyes curve, steps turn bouncy",
    "开心": "嘴角上扬、手臂自然摆动、身体微前倾 ｜ EN: smiles, arms swing naturally, body leans slightly forward",
    "激动": "双手握拳抬到胸前、身体前倾 ｜ EN: fists clenched at chest, body leans in",
    "愤怒": "眉头紧锁、下巴绷紧、拳头攥紧 ｜ EN: brows knitted, jaw tight, fists closed",
    "生气": "眉头紧锁、抿嘴、手拍桌面 ｜ EN: frowns, lips pressed, hand slaps the table",
    "焦急": "来回踱步、频繁看向门外、手指反复搓动 ｜ EN: paces, glances at the door repeatedly, rubs his fingers",
    "着急": "脚步加快、频频回头、手心搓动 ｜ EN: quickens his pace, looks back often, rubs his palms",
    "害怕": "身体后缩、双手抱肩、呼吸急促 ｜ EN: shrinks back, arms wrapped around himself, breathing fast",
    "感动": "眼眶发红、轻轻点头、嘴角微颤 ｜ EN: eyes redden, nods gently, lips tremble",
    "惊讶": "眉毛抬高、嘴巴微张、身体定住半秒 ｜ EN: eyebrows lift, mouth slightly open, body freezes for half a second",
    "犹豫": "手指停在半空、视线左右游移、欲言又止 ｜ EN: hand frozen mid-air, eyes darting, starts to speak then stops",
    "得意": "下巴微抬、嘴角一侧上扬、双手背在身后 ｜ EN: chin lifts, one side of the mouth curls up, hands behind his back",
    "沉思": "手指抵住下巴、视线放空、身体静止 ｜ EN: fingers pressed to his chin, unfocused gaze, body still",
    "紧张": "呼吸变浅、手指反复捏衣角、眼神快速左右扫 ｜ EN: breathing turns shallow, fingers knead his hem, eyes dart side to side",
    "崩溃": "膝盖一软跪下去、双手撑地、肩膀剧烈起伏 ｜ EN: knees buckle, hands hit the ground, shoulders heave",
    "sad": "lowers his head, shoulders trembling slightly",
    "angry": "frowns tightly, jaw clenched, fists closed",
    "happy": "mouth curves up, steps light and bouncy",
    "nervous": "paces back and forth, rubs his fingers repeatedly",
    "surprised": "eyebrows lift, mouth slightly open, body freezes for a moment",
}

# 画面语义的否定式（非字幕/水印类）—— 命中即提示改肯定式
BAN_WORDS = ("不要出现", "不要有", "禁止出现", "不能有", "不许有", "no extra people",
             "don't change", "do not change", "no morphing", "without changing")
TECH_NEG_OK = ("字幕", "水印", "文字", "logo", "subtitle", "watermark", "text", "caption")

CAM_RE = re.compile(r"^(camera|static camera|handheld|the camera|a quick zoom)", re.I)
TAIL_RE = re.compile(r"(one continuous shot|no cuts|identical appearance)", re.I)
# 纯环境/光影句：不该占时间轴的位置，归到 [LOOK & SOUND]
ENV_RE = re.compile(r"^(gentle|soft|warm|cool|golden|morning|afternoon|dusk|dim|bright|the air)", re.I)


# ── 文本工具 ────────────────────────────────────────────────────────
def pick(table, text):
    for keys, val in table:
        if isinstance(keys, str):          # 容错：单 key 写成了字符串
            keys = (keys,)
        for k in keys:
            if k in text:
                return val
    return ""


def cam_en(shot):
    """优先用分镜里派发的 cam（唯一权威），正文里自带的运镜句只作兜底"""
    cam = shot.get("cam", "")
    e = pick(CAM_EN, cam)
    if e:
        return e
    for line in str(shot.get("v", "")).split("\n"):
        if CAM_RE.match(line.strip()):
            return line.strip()
    return "Static camera, gentle and steady."


def split_v(v):
    """把作者写的 v 拆成 动作句（cam 句与尾注句剥离）"""
    acts, cams = [], []
    for line in str(v or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if CAM_RE.match(line):
            cams.append(line)
            continue
        if TAIL_RE.search(line):
            continue
        acts += [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    return acts, cams


def timeline(dur, acts):
    """时间轴：复杂动作放开场；段内不足则用「延续收束」模板补"""
    segs = 2 if dur <= 4 else 3
    cut = []
    for i in range(segs):
        a = round(dur * i / segs, 1)
        b = round(dur * (i + 1) / segs, 1)
        cut.append((a, b))
    body = []
    for i, (a, b) in enumerate(cut):
        if i < len(acts):
            txt = acts[i]
        elif i == len(cut) - 1:
            txt = ("The motion continues naturally to its end; the characters settle into "
                   "their final pose with subtle breathing, no new action begins.")
        else:
            txt = "The action continues smoothly, no new action begins."
        body.append("[%.1f-%.1fs] %s" % (a, b, txt))
    return body


def lint(sid, shot, prompt):
    msgs = []
    v = str(shot.get("v", ""))
    low = (v + " " + str(shot.get("ff", ""))).lower()
    # 1) 运镜唯一性
    hits = [w for w in ("push in", "pull back", "pulls back", "pans", "tilts", "tracks",
                        "crane", "zoom", "handheld", "whips", "orbit")
            if w in low]
    if len(hits) > 1:
        msgs.append("运镜 %d 种（%s）→ 一镜只许一种运镜，多余的删掉" % (len(hits), "/".join(hits)))
    # 2) 抽象情绪词
    for k, act in EMOTION2ACT.items():
        if k in v or k in str(shot.get("ff", "")):
            msgs.append("抽象情绪词「%s」→ 改写为物理动作：%s" % (k, act))
    # 3) 画面否定式
    for w in BAN_WORDS:
        if w in low and not any(t in low for t in TECH_NEG_OK):
            msgs.append("画面否定式「%s」→ 否定只对字幕/水印有效，画面上要改成肯定式" % w)
    # 4) 时长
    if float(shot.get("dur", 0)) > 6.5:
        msgs.append("时长 %.1fs > 6.5s → 长镜必崩，建议拆镜" % float(shot["dur"]))
    for m in msgs:
        print("   [lint] %s %s" % (sid, m))
    return msgs


def build(wd, shot, lock=None, lang="zh"):
    """生成一镜的最终视频 prompt"""
    lock = lock or asset_lock.load(wd) or asset_lock.build(wd)
    dur = float(shot.get("dur", 4) or 4)
    names = shot.get("cast") or []
    blk = asset_lock.block_for(lock, names, lang=lang)
    style = lock.get("style", {}).get("text", "")

    acts, _ = split_v(shot.get("v", ""))
    # 纯光影/氛围句挪出时间轴（否则会出现「第 3 秒：柔和晨光」这种空动作段）
    env = [a for a in acts
           if ENV_RE.match(a) and re.search(r"light|dust|air|shadow|glow", a, re.I)]
    acts = [a for a in acts if a not in env]
    if not acts:
        acts = [str(shot.get("v", "")).strip() or "The scene breathes with subtle motion."]
    body = timeline(dur, acts)

    look = ", ".join(x.rstrip("。. ") for x in (
        pick(SIZE_EN, shot.get("size", "")),
        pick(COMPOSE_EN, shot.get("compose", "")) or shot.get("compose", ""),
        cam_en(shot),
        pick(LIGHT_EN, shot.get("light", "")) or "soft warm light",
    ) if x)
    if env:
        look += ". " + " ".join(e.rstrip(". ") for e in env)
    look = look.rstrip(". ")
    snd = "Ambient sound: %s. " % shot["sfx"] if shot.get("sfx") else ""
    snd += "No native dialogue (voice-over is added in post)."

    style = style.rstrip("。. ")
    lines = [
        asset_lock.header(lock, names),
        "[SETUP] %s. Cast on screen (locked verbatim, never paraphrase): %s"
        % (style or "consistent stylized animation", blk or "no characters in this shot"),
    ]
    lines += body
    line = shot.get("line")
    if line:
        who = (names[0] if names else "旁白")
        py = lock.get("chars", {}).get(who, {}).get("pinyin", "")
        lines.append("[LINE] %s%s says in Mandarin {%s}"
                     % (who, " (%s)" % py if py else "", line))
    lines.append("[LOOK & SOUND] %s. %s" % (look, snd))
    lines.append("[CONSTRAINTS] %s No subtitles, no watermark, no text, no logo."
                 % lock.get("pos_stable", ""))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("sids", nargs="*")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    a = ap.parse_args()

    wd = a.workdir
    sc = json.load(open(os.path.join(wd, "shots.json"), encoding="utf-8"))
    lock = asset_lock.load(wd)
    if not lock:
        print("⚠️  没跑过资产冻结，现算一份（建议先 asset_lock.py <workdir> init）")
        lock = asset_lock.build(wd)

    want = a.sids or [s["id"] for s in sc["shots"]]
    todo = [s for s in sc["shots"] if s["id"] in want]
    pdir = os.path.join(wd, PR_DIR)
    if a.apply:
        os.makedirs(pdir, exist_ok=True)
    nmsg = 0
    for s in todo:
        p = build(wd, s, lock, a.lang)
        nmsg += len(lint(s["id"], s, p))
        if a.apply:
            out = os.path.join(pdir, "v_%s.txt" % s["id"])
            if os.path.exists(out) and not a.force:
                print("   %s 已存在，跳过（--force 覆盖）" % out)
                continue
            open(out, "w", encoding="utf-8").write(p + "\n")
            print("→ %s  %s" % (out, s.get("beat", "")))
        else:
            print("=" * 68)
            print("%s  %s  %ss  %s" % (s["id"], s.get("beat", ""),
                                       s.get("dur", "?"), s.get("size", "")))
            print(p)
    print("\n共 %d 镜，lint 提示 %d 条" % (len(todo), nmsg))
    if a.apply:
        print("下一步：asset_lock.py <workdir> verify   （指纹不过期才准出片）")


if __name__ == "__main__":
    main()
