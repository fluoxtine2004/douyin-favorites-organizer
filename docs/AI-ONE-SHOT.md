# 让 AI 一句话帮你复刻

本项目自带 `AGENTS.md` + `skills/douyin-favorites-organizer/SKILL.md`，
任何主流 AI 编程助手（Claude Code、Cursor、Codex、Copilot、WorkBuddy…）都能读懂并执行。

## 一、复制这句话

**全新安装（最简单）：**

```
把 https://github.com/fluoxtine2004/douyin-favorites-organizer 装到本地，
按 AGENTS.md 跑通全流程：抓取我的抖音收藏 → 生成逐字稿和截图 → 产出网页。
遇到报错自己修，不要问我。完成后告诉我 dashboard 路径、总条数、待转写条数。
```

**只要网页不要转写（想先看效果）：**

```
把 https://github.com/fluoxtine2004/douyin-favorites-organizer 装到本地，
只跑抓取和网页生成两步（跳过转写），把 dashboard.html 打开给我看。
```

**已经有库，只想每周更新（增量）：**

```
在 douyin-favorites-organizer 目录里跑 python run.py all，
只处理新增收藏；完成后报告新增条数、待转写条数、网页卡片数，并跑一次 python run.py check。
```

## 二、AI 会做什么（你可以逐项验收）

| 阶段 | AI 的动作 | 你要提供什么 |
|---|---|---|
| 1 | `git clone` + 建虚拟环境 + 装依赖 + 装 chromium | 无 |
| 2 | 跑 `run.py fetch`，弹出浏览器 | **手机扫码登录你自己的抖音**（只能你本人做） |
| 3 | 跑 `run.py transcribe`（分批，可能数小时） | 无（可让它挂着跑） |
| 4 | 跑 `run.py build` 产出网页/笔记/周报 | 无 |
| 5 | 跑 `run.py check` 自检 | 无 |

## 三、验收清单（让 AI 逐条回报）

把下面这段也发给 AI，它会自己查完成度：

```
完成后按这个清单逐条验证并回报（不要只说"完成了"）：
1. data/favorites.json 里唯一视频条数是多少？与 dashboard 的卡片数是否一致？
2. 待转写条数是多少？如果 >0，列出前 5 条的 id 和原因。
3. 随机抽 3 篇 vault 笔记：是否都含「要点」「时间轴截图」「完整逐字稿」三段？截图文件是否真实存在（不是 0 字节）？
4. 全库是否有"字幕by某某"这类伪转写水印？（grep 一下，应为 0）
5. dashboard.html 用无头浏览器打开：卡片数 > 0？控制台有 JS 报错吗？
6. 默认排序（按收藏时间 新→旧）下前 3 条是哪三条？它们是不是你最近收藏的？
```

## 四、Agent Skills host 直接安装

```bash
npx skills add https://github.com/fluoxtine2004/douyin-favorites-organizer --skill douyin-favorites-organizer
# 或
gh skill install fluoxtine2004/douyin-favorites-organizer
```

安装后直接对 AI 说"整理我的抖音收藏"即可触发。

## 五、AI 最容易踩的坑（已经写进 AGENTS.md，可提醒它）

1. 把 `/aweme/favorite/`（点赞列表）当收藏接口用 → **必须用 `collect_stat == 1` 校验**；
2. 自己拼接口 URL → 缺签名的请求会**静默返回空**，看起来像被限流，其实要驱动页面；
3. 转写和抓取同时跑 → 长跑批处理会把新抓的数据覆盖回旧状态；
4. 生成网页后不验证 → 必须真的用浏览器打开数卡片、看控制台（历史上出现过模板转义错误导致整页空白）；
5. 把整篇逐字稿当「要点」→ 要点必须 ≤90 字 / ≤3 条，`tests/test_points_rules.py` 会守。
