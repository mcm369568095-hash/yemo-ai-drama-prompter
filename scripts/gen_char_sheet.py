# -*- coding: utf-8 -*-
"""夜秣 · 人物定稿图生成器（多视图角色设定图）

输入用户的角色描述 → 产出一张「多视图角色设定图」（角色圣经 / 定稿图），
并顺势生成两张干净单图锚定（全身主锚定 + 特写锚定），写进 cast.json，
供下游 asset_lock / 首帧图生图使用。

🔴 为什么要多视图设定图 + 干净单图两套：
  把多视图板直接喂给 --edit 会被整板复刻成多人合影（见技能踩坑清单）。
  所以：设定图给人看 / 做一致性圣经；真正出图出片只用「干净单图锚定」。

用法:
  # 结构化填槽
  python gen_char_sheet.py <workdir> init --name 林晚 --role 主角 \
      --archetype "知性清冷办公室御姐" \
      --style "韩系3D二次元OC建模，OC渲染人物设定稿" \
      --face "淡粉清透妆容，碎刘海，无框细边眼镜" \
      --hair "黑色半扎高马尾长发" \
      --outfit "藏青色无袖高领紧身背心，灰色褶皱包臀短裙，白色挂绳工牌，黑色透肤丝袜，黑色一字带细高跟凉鞋" \
      --skin "冷白细腻肌肤" \
      --light "影棚柔和柔光，浅灰色纯色简约背景，面料细节清晰"

  # JSON 填槽
  python gen_char_sheet.py <workdir> init --name 林晚 --spec-json spec.json

  # 整段粘贴（自动抽取槽位）
  python gen_char_sheet.py <workdir> init --name 林晚 --free "角色设定图 多视图排版 ……"

  python gen_char_sheet.py <workdir> show
  python gen_char_sheet.py <workdir> audit
  python gen_char_sheet.py <workdir> gen --name 林晚        # 调 YEMO_SHEET_CMD 出图

出图开关: 设置环境变量 YEMO_SHEET_CMD 后，init/gen 会真的调图生图。
  命令模板可用 {prompt} {out} {size} 三个占位符。
  例: set YEMO_SHEET_CMD=python qiuqiu_generate.py --prompt "{prompt}" --size {size} --output {out}
不设就只写 prompt 文件 + 打印，人工拿去任意图生图工具出图。
"""
import argparse
import json
import os
import subprocess
import sys

CARD = "cast.json"

# 多视图设定图（角色圣经）模板——固定骨架 + 可变槽位
SHEET_TPL = (
    "角色设定图。\n"
    "多视图排版：画面划分为四宫格 + 左下角 Q 版 ——\n"
    "  ① 脸部特写（肩部以上，居中）\n"
    "  ② 正面全身（完整全身出镜，双脚入画）\n"
    "  ③ 侧面全身（90° 侧身，展示轮廓与服装侧面线条）\n"
    "  ④ 背面全身（展示后背设计与发型后视图）；\n"
    "  画面左下角附带 Q 版迷你小人插图（二头身 chibi，同款服装）。\n"
    "{archetype}\n"
    "{style}\n"
    "面部与妆容：{face}。\n"
    "发型：{hair}。\n"
    "服装：{outfit}。\n"
    "肤质：{skin}。\n"
    "灯光与背景：{light}。\n"
    "其他特征：{extra}。\n"
    "完整全身出镜，面料细节清晰，画面中不出现任何文字，8k，超精细，OC 渲染人物设定稿。"
)

# 干净单图锚定（真正喂 --edit 的）
BODY_TPL = (
    "single full-body portrait of one {archetype}, {style}。\n"
    "面部与妆容：{face}；发型：{hair}；服装：{outfit}；肤质：{skin}。\n"
    "{light}。其他特征：{extra}。\n"
    "single character only, centered, complete full body including feet, "
    "plain clean background, no layout grid, no text, no other people, 8k, ultra detailed。"
)
FACE_TPL = (
    "close-up face portrait of one {archetype}, {style}。\n"
    "面部与妆容：{face}；发型：{hair}；肤质：{skin}。\n"
    "{light}。其他特征：{extra}。构图居中，肩部以上，single character, no text, 8k, ultra detailed。"
)

DEFAULT_NEG = "换脸、换发型、换装、多余肢体、多人合影、文字、低清、畸形"


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


def fill(tpl, s):
    """填模板，空槽位直接丢弃该行，避免留下占位符。"""
    out = []
    for line in tpl.split("\n"):
        if "{archetype}" in line and not s.get("archetype"):
            continue
        if "{style}" in line and not s.get("style"):
            continue
        if "{face}" in line and not s.get("face"):
            continue
        if "{hair}" in line and not s.get("hair"):
            continue
        if "{outfit}" in line and not s.get("outfit"):
            continue
        if "{skin}" in line and not s.get("skin"):
            continue
        if "{light}" in line and not s.get("light"):
            continue
        if "{extra}" in line and not s.get("extra"):
            continue
        out.append(line.format(**s))
    return "\n".join(out)


def build_spec(a):
    """把三种输入方式归一成一个 slots 字典。"""
    s = {k: "" for k in ("archetype", "style", "face", "hair", "outfit", "skin", "light", "extra")}
    if a.spec_json:
        d = json.load(open(a.spec_json, encoding="utf-8"))
        for k in ("archetype", "style", "face", "hair", "outfit", "skin", "light", "extra"):
            s[k] = d.get(k, "")
        return s
    if a.free:
        # 整段粘贴：按关键词粗略抽取已知槽位，剩余塞进 extra（兜底进 prompt，绝不丢信息）
        import re
        txt = a.free
        # 排版 boilerplate（固定骨架，不是角色 DNA，必须剔除）
        boiler = ["角色设定图", "多视图排版", "脸部特写", "正面全身", "侧面全身",
                  "背面全身", "画面左下角", "Q版迷你小人插图", "Q版", "迷你小人", "附带",
                  "完整全身出镜", "面料细节清晰", "8k", "超精细", "OC渲染人物设定稿",
                  "人物设定稿", "设定稿"]
        for b in boiler:
            txt = txt.replace(b, " ")
        # 常见服装/配饰词（眼镜归面容，不放这）
        outfit_hits = re.findall(
            r"([^，,。\n]*(?:背心|上衣|衬衫|裙|裤|鞋|袜|丝袜|工牌|挂绳|领|外套|大衣|围巾|帽|包|发)[^，,。\n]*)",
            txt)
        if outfit_hits:
            s["outfit"] = "，".join(h.strip(" ，,") for h in outfit_hits)
        # 发型（含刘海）
        m = re.search(r"([^，,。\n]*(?:发|马尾|麻花|丸子|长发|短发|刘海)[^，,。\n]*)", txt)
        if m:
            s["hair"] = m.group(1).strip(" ，,")
        # 肤质
        m = re.search(r"([^，,。\n]*(?:肌肤|皮肤|冷白|暖白)[^，,。\n]*)", txt)
        if m:
            s["skin"] = m.group(1).strip(" ，,")
        # 风格
        m = re.search(r"([^，,。\n]*(?:OC|二次元|3D|建模|渲染|风格|韩系|写实|插画)[^，,。\n]*)", txt)
        if m:
            s["style"] = m.group(1).strip(" ，,")
        # 面容/妆容（含眼镜）
        m = re.search(r"([^，,。\n]*(?:妆容|妆|腮红|唇|眼|眉|无框|细边|眼镜)[^，,。\n]*)", txt)
        if m:
            s["face"] = m.group(1).strip(" ，,")
        # 灯光/背景
        m = re.search(r"([^，,。\n]*(?:影棚|柔光|灯光|背景|纯色|简约|棚拍)[^，,。\n]*)", txt)
        if m:
            s["light"] = m.group(1).strip(" ，,")
        # 剩余：能抽的定位放 archetype，其余全进 extra（兜底）
        rest = txt
        for v in (s["outfit"], s["hair"], s["skin"], s["style"], s["face"], s["light"]):
            rest = rest.replace(v, "")
        rest = re.sub(r"[，,]{2,}", "，", rest).strip(" ，,。\n")
        if rest:
            if not s["archetype"]:
                # 取第一个逗号前的短句当定位，剩下的进 extra
                head,_,tail = rest.partition("，")
                s["archetype"] = head.strip(" ，,")[:40]
                rest = tail.strip(" ，,。\n")
            s["extra"] = rest
        return s
    # 结构化
    for k in ("archetype", "style", "face", "hair", "outfit", "skin", "light", "extra"):
        v = getattr(a, k, "") or ""
        s[k] = v.strip()
    return s


def features_str(s):
    """写死进 cast.json 的角色 DNA（下游 asset_lock 逐字复用）。"""
    parts = [s["archetype"], s["face"], s["hair"], s["outfit"], s["skin"], s["light"], s.get("extra", "")]
    return "；".join(p for p in parts if p)


def gen_image(cmd_tpl, prompt, out, size):
    if not os.path.isabs(out):
        out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cmd = (cmd_tpl.replace("{prompt}", prompt)
           .replace("{out}", out)
           .replace("{size}", size))
    print("  ▶ 出图：%s" % cmd[:120])
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok = os.path.exists(out) and os.path.getsize(out) > 1024
    if not ok:
        print("  ⚠️ 生成失败：", (r.stdout or "")[-300:], (r.stderr or "")[-200:])
        return False
    return True


def cmd_init(wd, a):
    s = build_spec(a)
    sheet = fill(SHEET_TPL, s)
    body = fill(BODY_TPL, s)
    face = fill(FACE_TPL, s)

    sheet_dir = os.path.join(wd, "cast", "定稿")
    os.makedirs(sheet_dir, exist_ok=True)
    name = a.name
    paths = {
        "sheet": os.path.join(sheet_dir, "%s_设定图.png" % name),
        "body": os.path.join(sheet_dir, "%s_全身.png" % name),
        "face": os.path.join(sheet_dir, "%s_特写.png" % name),
    }
    for kind, p in paths.items():
        txt = {"sheet": sheet, "body": body, "face": face}[kind]
        open(p.replace(".png", "_prompt.txt"), "w", encoding="utf-8").write(txt)

    # 写进 cast.json
    data = load(wd)
    feat = features_str(s)
    c = {
        "name": name,
        "role": a.role,
        "ref_sheet": "",          # 多视图圣经（人看 / 一致性校验）
        "ref_main": "",           # 干净全身单图（喂首帧 --edit）
        "ref_face": "",           # 干净特写单图（近景/特写）
        "features": feat or "（在此写死：年龄、脸型、发型、服装、配色、身高比例、标志物）",
        "voice": a.voice or "",
        "neg": a.neg or DEFAULT_NEG,
    }
    ch = data.setdefault("characters", [])
    for i, x in enumerate(ch):
        if x["name"] == name:
            ch[i] = c
            break
    else:
        ch.append(c)
    save(wd, data)

    print("✅ 已写入角色卡：", card_path(wd))
    print("   角色 %s（%s）" % (name, a.role))
    print("   特征 DNA：%s" % (feat or "（未填，下面用 --free/--spec-json 补）"))
    print("   提示词文件：")
    for kind, p in paths.items():
        print("     %s → %s" % (kind, p.replace(".png", "_prompt.txt")))

    # 出图（有命令才真出）
    cmd_tpl = os.environ.get("YEMO_SHEET_CMD", "").strip()
    if not cmd_tpl:
        print("\n提示：没设 YEMO_SHEET_CMD，已写好 3 份 prompt 文件，人工拿去出图即可。")
        print("      想自动出图：set YEMO_SHEET_CMD=<你的文生图命令 {prompt} {out} {size}>")
        return
    sizes = {"sheet": a.sheet_size, "body": a.body_size, "face": a.face_size}
    for kind, p in paths.items():
        txt = {"sheet": sheet, "body": body, "face": face}[kind]
        if gen_image(cmd_tpl, txt, p, sizes[kind]):
            if kind == "sheet":
                c["ref_sheet"] = os.path.relpath(p, wd).replace("\\", "/")
            elif kind == "body":
                c["ref_main"] = os.path.relpath(p, wd).replace("\\", "/")
            else:
                c["ref_face"] = os.path.relpath(p, wd).replace("\\", "/")
    save(wd, data)
    print("\n✅ 三图已出：", c["ref_sheet"], c["ref_main"], c["ref_face"])


def cmd_show(wd, a):
    data = load(wd)
    if not data.get("characters"):
        print("还没有角色卡。先跑：gen_char_sheet.py <workdir> init --name <角色名> --free \"...\"")
        return
    print("%-8s %-6s %-10s %-10s %-10s" % ("角色", "定位", "设定图", "全身锚定", "特写锚定"))
    for c in data["characters"]:
        print("%-8s %-6s %-10s %-10s %-10s" % (
            c["name"], c.get("role", ""),
            "有" if c.get("ref_sheet") else "—",
            "有" if c.get("ref_main") else "❌",
            "有" if c.get("ref_face") else "—"))
        print("    特征 DNA：%s" % c.get("features", ""))


def cmd_audit(wd, a):
    data = load(wd)
    ch = data.get("characters", [])
    if not ch:
        print("🔴 没有角色卡 —— 首帧将退化为纯文生图，角色会漂移")
        sys.exit(2)
    bad = 0
    for c in ch:
        if not c.get("ref_main"):
            print("🔴 %s 缺全身锚定图（ref_main）—— 首帧无法 --edit 定稿" % c["name"])
            bad += 1
        if not c.get("ref_face"):
            print("⚠️  %s 缺特写锚定图（ref_face）—— 近景/特写会换脸" % c["name"])
            bad += 1
        if not c.get("ref_sheet"):
            print("⚠️  %s 缺多视图设定图（ref_sheet）—— 没有角色圣经，一致性只能靠文字" % c["name"])
            bad += 1
        if "（在此写死" in c.get("features", ""):
            print("🔴 %s 的特征 DNA 还没填" % c["name"])
            bad += 1
    print("角色 %d 个，问题 %d 项" % (len(ch), bad))
    if bad:
        sys.exit(2)


def cmd_gen(wd, a):
    """只对已有 prompt 文件补出图（不重算 prompt）。"""
    cmd_tpl = os.environ.get("YEMO_SHEET_CMD", "").strip()
    if not cmd_tpl:
        print("没设 YEMO_SHEET_CMD，无法自动出图。先 set 再跑 gen。")
        sys.exit(1)
    data = load(wd)
    c = get(data, a.name)
    if not c:
        print("没有这个角色：", a.name)
        sys.exit(1)
    sheet_dir = os.path.join(wd, "cast", "定稿")
    name = c["name"]
    jobs = [
        ("sheet", "%s_设定图" % name, a.sheet_size, "ref_sheet"),
        ("body", "%s_全身" % name, a.body_size, "ref_main"),
        ("face", "%s_特写" % name, a.face_size, "ref_face"),
    ]
    for kind, base, size, key in jobs:
        ptxt = os.path.join(sheet_dir, base + "_prompt.txt")
        png = os.path.join(sheet_dir, base + ".png")
        if not os.path.exists(ptxt):
            print("⚠️ 缺 prompt 文件：%s（先跑 init）" % ptxt)
            continue
        if c.get(key) and os.path.exists(os.path.join(wd, c[key])) and not a.force:
            print("已存在，跳过：%s" % base)
            continue
        prompt = open(ptxt, encoding="utf-8").read()
        if gen_image(cmd_tpl, prompt, png, size):
            c[key] = os.path.relpath(png, wd).replace("\\", "/")
    save(wd, data)
    print("✅ 补图完成：", c.get("ref_sheet"), c.get("ref_main"), c.get("ref_face"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--name", required=True)
    p.add_argument("--role", default="主角")
    p.add_argument("--archetype", default="")
    p.add_argument("--style", default="")
    p.add_argument("--face", default="")
    p.add_argument("--hair", default="")
    p.add_argument("--outfit", default="")
    p.add_argument("--skin", default="")
    p.add_argument("--light", default="")
    p.add_argument("--spec-json", dest="spec_json", default="")
    p.add_argument("--free", default="")
    p.add_argument("--voice", default="")
    p.add_argument("--neg", default="")
    p.add_argument("--sheet-size", default="1536x1024")
    p.add_argument("--body-size", default="1024x1536")
    p.add_argument("--face-size", default="1024x1536")
    p.set_defaults(fn=cmd_init)

    sub.add_parser("show").set_defaults(fn=cmd_show)
    sub.add_parser("audit").set_defaults(fn=cmd_audit)

    p = sub.add_parser("gen")
    p.add_argument("--name", default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--sheet-size", default="1536x1024")
    p.add_argument("--body-size", default="1024x1536")
    p.add_argument("--face-size", default="1024x1536")
    p.set_defaults(fn=cmd_gen)

    a = ap.parse_args()
    a.fn(a.workdir, a)


if __name__ == "__main__":
    main()
