# 短剧提示词模板（四段式）—— 直接抄

> 视频模型读提示词的耐心，比你想的短得多。
> 一段 500 字不分段的散文，它只会抓住前 30 个字。
> **分段 + 标时间轴**，才是让模型「听话」的唯一办法。

---

## 一、四段式结构

```text
[ASSET-LOCK style=xxxxxxxx 林晚=yyyyyyyy 周野=zzzzzzzz]   ← 指纹头（可追溯）

[SETUP] {画风锁}。画面角色（逐字冻结，永不改写）：{角色特征块}

[0.0-1.5s] {开场动作 —— 复杂动作必须放在这一段}
[1.5-3.0s] {发展动作}
[3.0-4.5s] {收束动作 —— 或"动作自然走到结尾，人物落定"}

[LINE] {角色} (Pinyin) says in Mandarin {台词}            ← 可选

[LOOK & SOUND] {景别}, {构图}, {运镜}, {光位}. {环境氛围}. Ambient sound: {音效}. No native dialogue (voice-over is added in post).

[CONSTRAINTS] {肯定式稳定约束} No subtitles, no watermark, no text, no logo.
```

---

## 二、七条铁律（每条都对应一次翻车）

| # | 铁律 | 为什么 |
|---|---|---|
| 1 | **英文写描述，中文说台词** | 模型吃英文更稳；台词用中文 + 拼音注音，专治发音跑偏 |
| 2 | **情绪不写抽象词** | 它不懂「悲伤」，懂「低头、肩膀轻颤、手指攥住衣角」 |
| 3 | **一镜只许一种运镜** | 写两种，模型会给你一个四不像的抖动 |
| 4 | **画面上的「不要」一律改肯定式** | 「不要换脸」无效，要写「五官/发型/服装/比例与参考图完全一致」 |
| 5 | **否定词只留给字幕/水印/文字/畸形** | 这几类模型是真听得懂否定的 |
| 6 | **单镜 3~6 秒，复杂动作放开场** | 长镜必崩，模型撑不住后段 |
| 7 | **原生对白做不出来就改镜头设计** | 不靠后期配音救场；写死 `No native dialogue` |

---

## 三、四类句子的对照写法

### 3.1 人物（一致性）
| ❌ 别写 | ✅ 要写 |
|---|---|
| 一个漂亮的女孩 | 26岁女性，圆脸，黑色齐肩发中分，米白色针织开衫，左腕戴银色细表，身高约 165 |
| 不要换脸 | 五官、发型、服装、配色与参考图从第一帧到最后一帧完全一致 |

### 3.2 场景（一致性）
| ❌ 别写 | ✅ 要写 |
|---|---|
| 一个老房子 | 九十年代筒子楼，褪色绿漆木门，门框贴过对联留下浅色印子，走廊尽头一扇铁窗 |
| 背景乱七八糟别放东西 | 背景保持简洁，只有一张木桌与一盏台灯，画面中不出现任何文字 |

### 3.3 动作（一致性）
| ❌ 别写 | ✅ 要写 |
|---|---|
| 她很伤心地哭了 | 她低头，肩膀轻颤，手指攥住衣角，视线垂向地面，呼吸变慢 |
| 镜头推近，同时她转身，相机也跟着摇 | 只留一个：`Camera slowly pushes in.` |

### 3.4 镜头（导演性）
| 维度 | 可选值 |
|---|---|
| 景别 | extreme wide / wide / medium / medium close-up / close-up |
| 构图 | low angle / high angle / over-the-shoulder / symmetrical / eye level |
| 运镜 | pushes in / pulls back / tracks left / tracks right / rises / whip / locked-off |
| 光位 | backlit rim light / soft morning light / dusk light / cool blue light / golden warm light |

> 景别、构图、运镜、光位这四项**不用自己写** —— 导演层已经算好并追加到 `ff` 末尾，
> 你在 `v` 里只管写动作就好。

---

## 四、时间轴怎么切

- **≤4 秒** → 切 2 段
- **>4 秒** → 切 3 段

不足的段落由脚本自动补：
- 中间段：`The action continues smoothly, no new action begins.`
- 末段：`The motion continues naturally to its end; the characters settle into their final pose with subtle breathing, no new action begins.`

🔴 **纯光影/氛围句不要放进时间轴**。写「第 3 秒：柔和晨光」这种空动作段，
模型会给你一个三秒没动的镜头。氛围句归 `[LOOK & SOUND]`。

---

## 五、两条最容易犯的错

1. **`v` 字段里写运镜** —— 会和导演层派发的运镜打架。`v` 里只写动作。
2. **`ff` 字段里写景别** —— 「全景构图：…」会被导演层剥掉。景别由 `story_plan.py` 说了算。
