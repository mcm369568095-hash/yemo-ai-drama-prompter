#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段路由器 · 夜秣AI短剧生成器 v2.0

技能文件多不怕，怕的是不知道该读哪个。本脚本解决「现在该读什么」。

用法：
  drama_router.py --list                    # 列出 9 个阶段与用途
  drama_router.py --need "我要选题"          # 按需求路由到文件
  drama_router.py --need "60集分集大纲付费卡点"
  drama_router.py <workdir>                 # 看项目进度，下一步该做什么
  drama_router.py <workdir> --next          # 只打印下一步命令
  drama_router.py --where "手上有分镜表"     # 按现有物判断阶段

只用标准库。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SK = Path(__file__).resolve().parent
ROOT = SK.parent

# ---------------------------------------------------------------- 阶段注册表
# key = 阶段号，stages/ 下的文件名前缀
STAGES = [
    ("00", "market",     "选题 · IP 评估",       "选题卡.md",
     ["选题", "题材", "立项", "IP", "评估", "能不能拍", "写什么", "创意", "点子", "方向", "卖点", "爽文"]),
    ("01", "adaptation", "改编（小说 → 剧本）",  "01_原作事实账本.md / 02_改编方案.md",
     ["改编", "小说", "网文", "长文", "原著", "改成剧本", "小说改", "章节"]),
    ("02", "character",  "人物 · 角色资产",      "人物小传.md / cast.json / cast/定稿/",
     ["人物", "角色", "小传", "人设", "角色卡", "定稿", "角色图", "设定图", "三视图", "cast", "角色圣经"]),
    ("03", "structure",  "结构 · 集纲 · 钩子",   "分集大纲.md",
     ["大纲", "集纲", "分集", "钩子", "卡点", "付费", "60集", "结构", "节奏", "分卷", "节拍"]),
    ("04", "drafting",   "剧本 · 对白",          "剧本.md",
     ["剧本", "对白", "台词", "写第", "场号", "正文", "台本"]),
    ("05", "revision",   "审稿 · 质检 · 去AI味", "审稿报告.md",
     ["审稿", "质检", "检查", "去AI", "AI味", "改稿", "诊断", "挑毛病", "看看", "合规", "清稿"]),
    ("06", "storyboard", "分镜 · 镜头设计",      "shots.json",
     ["分镜", "镜头", "景别", "运镜", "导演", "拆镜", "storyboard", "派发"]),
    ("07", "prompt",     "视频 / 图像提示词",     "prompts/ + 视频提示词清单.md",
     ["提示词", "prompt", "seedance", "即梦", "minimax", "可灵", "kling", "图生视频", "首帧"]),
    ("08", "production", "出片 · 配音 · 剪辑",   "ff/ + clips/",
     ["出片", "生成视频", "成本", "配音", "剪辑", "装配", "成片", "mp4", "渲染"]),
]

# 每个阶段要读的 references（按需加载，不是全读）
REF_MAP = {
    "00": ["爆款选题与爽感公式.md"],
    "01": ["爆款选题与爽感公式.md"],
    "02": ["人物塑造与对白.md", "连载一致性记忆.md"],
    "03": ["短剧节奏与付费卡点.md", "连载一致性记忆.md"],
    "04": ["人物塑造与对白.md", "短剧节奏与付费卡点.md"],
    "05": ["剧本质检规则集.md", "去AI味与合规.md"],
    "06": ["导演层预设库.md", "镜头语法.md"],
    "07": ["多模型提示词模板.md", "提示词模板.md"],
    "08": ["多模型提示词模板.md"],
}

# 阶段 → 核心命令（跑得动的那部分）
CMD_MAP = {
    "00": [],
    "01": [],
    "02": ['gen_char_sheet.py "$WD" init --name <名> --role <角色> --free "<设定>"',
           'cast_card.py "$WD" init --name <名> --ref cast/定稿/<名>_全身.png --features "<特征>"',
           'asset_lock.py "$WD" init',
           'series_bible.py "$WD" init --title "<剧名>" --episodes 60'],
    "03": ['series_bible.py "$WD" qc'],
    "04": [],
    "05": ['script_qc.py <剧本.md>',
           'script_qc.py <剧本.md> --clean -o <剧本_清稿.md>',
           'series_bible.py "$WD" qc'],
    "06": ['init_workdir.py "$WD" --title "<剧名>" --preset drama',
           'story_plan.py "$WD" --preset drama --apply',
           'story_plan.py "$WD" --check'],
    "07": ['frame_prompt.py "$WD" --apply',
           'shot_prompt.py  "$WD" --apply --model seedance',
           'model_adapter.py "$WD" --model minimax --apply',
           'asset_lock.py   "$WD" verify',
           'export_prompts.py "$WD" --price 0.5',
           'review_board.py "$WD" -o 评审看板.html'],
    "08": ['export_prompts.py "$WD" --price 0.5 --paid "c02,c05"'],
}

# 项目文件 → 已完成到哪个阶段
ARTIFACT_MAP = [
    ("07", ["prompts"]),                       # 提示词已生成 → 到 07
    ("06", ["shots.json"]),                    # 分镜表 → 到 06
    ("05", ["审稿报告.md", "剧本_清稿.md"]),
    ("04", ["剧本.md", "剧本"]),
    ("03", ["分集大纲.md", "大纲.md"]),
    ("02", ["人物小传.md", "cast.json"]),
    ("01", ["01_原作事实账本.md", "改编方案.md"]),
    ("00", ["选题卡.md"]),
]


def stage_file(no: str, slug: str) -> Path:
    return ROOT / "stages" / f"{no}-{slug}.md"


def ref_path(name: str) -> Path:
    return ROOT / "references" / name


def show_list() -> None:
    print("夜秣AI短剧生成器 · 九阶段")
    print("=" * 72)
    print(f"{'阶段':<4}{'名称':<22}{'主产物':<30}")
    print("-" * 72)
    for no, slug, name, out, _ in STAGES:
        print(f"{no:<4}{name:<22}{out:<30}")
    print("-" * 72)
    print("路由：drama_router.py --need \"我要做60集分集大纲和付费卡点\"")


def route_by_need(text: str) -> list:
    t = text.lower()
    hits = []
    for no, slug, name, out, kws in STAGES:
        score = sum(1 for k in kws if k.lower() in t)
        if score:
            hits.append((score, no, slug, name, out))
    hits.sort(reverse=True)
    return hits


def show_need(text: str) -> None:
    hits = route_by_need(text)
    if not hits:
        print(f"[router] 没匹配到阶段：{text}")
        print("[router] 试试这些词：选题 / 改编 / 人物 / 大纲 / 剧本 / 审稿 / 分镜 / 提示词 / 出片")
        sys.exit(1)

    print(f"[router] 需求：{text}")
    print("=" * 72)
    top = hits[0]
    # top = (score, no, slug, name, out)：段号是 [1]，[0] 是匹配分，别搞混
    print(f"▶ 主阶段：{top[1]}. {top[3]}")
    print()
    print("── 要读的文件 ──")
    sf = stage_file(top[1], top[2])
    print(f"  1. stages/{top[1]}-{top[2]}.md   {'（存在）' if sf.exists() else '（缺失！）'}")
    for i, r in enumerate(REF_MAP.get(top[1], []), start=2):
        print(f"  {i}. references/{r}   {'（存在）' if ref_path(r).exists() else '（缺失！）'}")
    print()
    if CMD_MAP.get(top[1]):
        print("── 可用命令 ──")
        for c in CMD_MAP[top[1]]:
            print(f"  $PY $SK/{c}")
    print()
    if len(hits) > 1:
        others = [h for h in hits[1:] if h[0] > 0]
        if others:
            print("── 可能也相关 ──")
            for h in others[:3]:
                print(f"  {h[1]}. {h[3]}   → stages/{h[1]}-{h[2]}.md")
    print("=" * 72)


def detect_stage(wd: Path) -> tuple:
    """按工作目录里已存在的产物，判断现在到哪一步。"""
    for no, names in ARTIFACT_MAP:
        for n in names:
            p = wd / n
            if p.exists():
                if p.is_dir() and not any(p.iterdir()):
                    continue
                return no
    return None


def show_workdir(wd: Path, next_only: bool) -> None:
    if not wd.exists():
        print(f"[router] 目录不存在：{wd}")
        sys.exit(2)

    cur = detect_stage(wd)
    idx = 0 if cur is None else int(cur)
    nxt = min(idx + (0 if cur is None else 1), 8)

    if next_only:
        no, slug, name, out, _ = STAGES[nxt]
        print(f"# 下一步：{no}. {name}")
        print(f"# 读：stages/{no}-{slug}.md")
        for r in REF_MAP.get(no, []):
            print(f"#     references/{r}")
        for c in CMD_MAP.get(no, []):
            print(f'$PY "$SK"/{c}')
        raise SystemExit(0)

    print(f"项目：{wd.name}")
    print("=" * 72)
    print("进度：")
    for no, slug, name, out, _ in STAGES:
        i = int(no)
        if cur is None:
            mark = " " if i != 0 else "▶"
        else:
            mark = "✔" if i < idx else ("▶" if i == idx else " ")
        have = "有产物" if any((wd / x).exists() for x in [out.split(" ")[0].rstrip("/")]) else ""
        print(f"  {mark} {no} {name:<22} {have}")
    print()
    no, slug, name, out, _ = STAGES[nxt]
    print(f"▶ 下一步（阶段 {no} · {name}）")
    print(f"  读：stages/{no}-{slug}.md")
    for r in REF_MAP.get(no, []):
        print(f"      references/{r}")
    if CMD_MAP.get(no):
        print("  命令：")
        for c in CMD_MAP[no]:
            print(f'    $PY "$SK"/{c}')
    print("=" * 72)


def show_where(text: str) -> None:
    """按手上已有的产物判断阶段。"""
    hits = route_by_need(text)
    if not hits:
        print(f"[router] 没识别出手上的产物：{text}")
        sys.exit(1)
    top = hits[0]
    idx = int(top[1])
    nxt = min(idx + 1, 8)
    print(f"[router] 手上有：{top[3]}")
    no, slug, name, _, _ = STAGES[nxt]
    print(f"▶ 下一步是阶段 {no} · {name}")
    print(f"  读：stages/{no}-{slug}.md")
    for r in REF_MAP.get(no, []):
        print(f"      references/{r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="夜秣AI短剧生成器 · 阶段路由器")
    ap.add_argument("workdir", nargs="?", help="项目目录（看进度用）")
    ap.add_argument("--list", action="store_true", help="列出九个阶段")
    ap.add_argument("--need", metavar="TEXT", help="按需求路由，例如 --need '60集大纲 付费卡点'")
    ap.add_argument("--where", metavar="TEXT", help="按手上的产物判断下一步")
    ap.add_argument("--next", action="store_true", help="配合 workdir：只打印下一步")
    a = ap.parse_args()

    if a.list:
        show_list()
        return
    if a.need:
        show_need(a.need)
        return
    if a.where:
        show_where(a.where)
        return
    if a.workdir:
        show_workdir(Path(a.workdir), a.next)
        return
    show_list()


if __name__ == "__main__":
    main()
