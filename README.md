# 夜秣AI短剧生成器

> 给一段故事，还你一整套开箱即用的 AI 短剧分镜提示词包。

![Version](https://img.shields.io/badge/version-1.1.0-blue) ![Platform](https://img.shields.io/badge/平台-WorkBuddy-purple) ![Store](https://img.shields.io/badge/SkillHub-已上架-green) ![License](https://img.shields.io/badge/license-MIT-green)
![微信搜一搜 · 夜秣AI搞钱](assets/wechat-search.jpg)

**夜秣AI短剧生成器**是一个 AI 短剧分镜提示词生产技能，跑在 [WorkBuddy](https://www.workbuddy.cn) 里。输入一段故事、一个剧本、一篇文章，甚至一句主题，产出一整套**可直接投喂 AI 视频模型**的分镜提示词包。

## 🌟 我们的核心优势

普通 AI 给「一张图的提示词」，夜秣给「一整套能拍的分镜包」。别人翻车的地方，是我们的主场：

| 做 AI 短剧的塌方点 | 夜秣AI短剧生成器怎么接住 |
|---|---|
| 人物每帧换脸换装，观众出戏 | **资产冻结**：角色特征写死 + 指纹校验，跨镜一致 |
| 全片一个景别平推到底，像 PPT | **导演层**：自动派发景别/运镜/光位/构图/时长/转场，并逐镜打分 |
| 提示词不会写，只能抄模板 | **四段式逐镜提示词 + 首帧图提示词**：复制就能用 |
| 角色定稿图难画，下游还对不上 | **人物定稿图生成器**：文字→多视图角色圣经 + 干净单图锚定，喂给资产冻结闭环 |

> 一句话：**不是帮你"写一条提示词"，而是替你把整部短剧"分镜化"。**

## ✨ 它治什么病

做 AI 短剧的人，都栽在这四件事上：

| 痛点 | 本技能的解法 |
|---|---|
| 😵 人物每帧换脸换装 | **资产冻结**：角色特征写死 + 指纹校验，跨镜一致 |
| 🎥 全片一个景别平推到底 | **导演层**：自动派发景别 / 运镜 / 光位 / 构图 / 时长 / 转场，并逐镜打分 |
| 📝 提示词不会写 | **四段式逐镜提示词** + 首帧图提示词，复制就能用 |
| 🧑‍🎨 角色定稿图难画 | **人物定稿图生成器**：文字描述 → 多视图角色设定图（角色圣经）+ 干净单图锚定 |

## 🤖 适用平台

本技能为 **WorkBuddy SKILL 格式**，开箱即用：

- ✅ **WorkBuddy**（官方支持，技能市场一键装）
- ✅ **OpenClaw** 等智能体平台（兼容 SKILL 规范，直接加载即可）

> 只要是支持 SKILL / 智能体技能规范的平台，都能跑起来。

## 📜 原创声明

本技能由 **夜秣** 原创（早期 SkillHub 账号名为「行空小马」，后统一更名，为同一人）。

## 🚀 快速开始

**方式一：SkillHub 一键装（推荐）**

在 WorkBuddy 的 SkillHub 技能市场搜索 `yemo-ai-drama-prompter`，或直接下载：

```
https://api.skillhub.cn/api/v1/download?slug=yemo-ai-drama-prompter
```

**方式二：手动安装**

```bash
git clone https://github.com/mcm369568095-hash/yemo-ai-drama-prompter.git
```

## 📖 怎么用

对 WorkBuddy 说一句：

- 「把这篇故事变成 AI 短剧分镜」
- 「用这个梗概生成一条短剧的提示词包」
- 「给主角生成一套角色定稿图」

产出物：导演分镜方案 → 逐镜四段式提示词 → 首帧图提示词 → 一份勾选即用的人可读清单。

## 📁 目录结构

```
夜秣AI短剧生成器/
├── SKILL.md                  # 技能主流程
├── scripts/                  # 分镜/角色/导出脚本
├── providers/                # 视频模型接入配置（自定义你的生图/生视频渠道）
├── templates/                # 角色 & 分镜模板
└── references/               # 导演预设 / 镜头语法 / 提示词模板
```

## 📜 License

[MIT](./LICENSE) © 夜秣

---

## 📮 关注公众号「夜秣AI搞钱」

![扫码关注·夜秣AI搞钱](assets/wechat-qr.jpg)

> 更多 AI 实战技能与拆解，微信搜一搜「夜秣AI搞钱」。
