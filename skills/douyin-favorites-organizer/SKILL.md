---
name: douyin-favorites-organizer
description: 抖音收藏夹批量整理：抓取收藏（保留原有收藏夹分类）→ 下载视频 → 本地 whisper 逐字稿 + 关键帧截图 → 生成可批注网页、Obsidian 笔记与周/季/年总结。当用户要求整理、备份、总结抖音收藏，或把收藏视频转成文字稿、做成可检索知识库时使用。
license: MIT
metadata:
  version: "1.0.0"
  updated: 2026-10-13
---

# 抖音收藏夹整理（Douyin Favorites Organizer）

把使用者**本人账号**的抖音收藏整理成可检索的知识库：保留原收藏夹分类 → 逐字稿 → 关键帧截图 → 可批注网页 + Obsidian 笔记 + 周报。

> ⚠️ 边界：只整理使用者自己的收藏。不抓他人内容，不提供任何绕过风控的手段。详见仓库 `DISCLAIMER.md`。
> 仓库内 `AGENTS.md` 是给 AI 助手的完整说明书，**先读它**。

## 环境准备

```bash
pip install -r requirements.txt
python -m playwright install chromium
# 可选：模型走国内镜像
pip install modelscope && python run.py fetch-model
```

## 标准流水线

| 步 | 命令 | 说明 |
|---|---|---|
| 1 抓取 | `python run.py fetch` → `scripts/fetch_gap.py` | 有头浏览器，**首次需用户本人扫码**；登录态持久化在 `browser_profile/` |
| 2 转写 | `python run.py transcribe --limit 60` → `scripts/process_batch.py` | 直链下载 → ffmpeg 抽音频 → faster-whisper → 抽帧；每条落盘一次，可中断续跑 |
| 3 选帧 | `scripts/pick_frames.py [--only-transcribed]` | 场景切换检测 + 要点锚定，只挑有信息量的画面 |
| 4 加工 | `scripts/refill_enriched.py` | 保守补齐 `data/enriched.json`（**不要直接跑 `enrich.py`**，会丢 AI 精修内容） |
| 5 产出 | `python run.py build` → `scripts/generate_outputs.py` + `build_dashboard.py` | 网页 + Obsidian 笔记 + 专题 + 周报（`generate_outputs` 内部会调 `build_dashboard`） |
| 6 排序索引 | `scripts/fetch_collect_order.py --fast` + `scripts/build_collect_index.py` | 合成收藏时间排序键。**新增条目后必须重跑**，否则新条目排到列表最末 |
| 7 打包 | `scripts/build_site.py` | 生成离线站点 `dist/` |
| 8 自检 | `python run.py check` | 渲染（卡片数>0、无 JS 报错）+ 要点规则 + 笔记完整性 |

分步说明见 `docs/PIPELINE.md`；出问题先看 `docs/FAQ.md` 与 `docs/SITE-CHANGE.md`。

## 数据源纪律（最重要的两条）

1. **点赞 ≠ 收藏，绝不混用**
   - 收藏：`collects/list`、`collects/video/list`、`aweme/listcollection`
   - **点赞：`/aweme/v1/web/aweme/favorite/` ← 永远不要吸收**
   - 入库护栏：`aweme.collect_stat == 1` 才是"我收藏了"，`collect_stat == 0` 一律跳过
2. **不要自己拼接口 URL**：缺 `a_bogus`/`msToken` 签名的请求会被服务端**静默降级为空结果**（HTTP 200 但 `has_more=0`），
   容易误判成"被限流"。正确做法是用 Playwright **驱动页面**，监听页面自身发出的 XHR。

## 抓取要点

- 收藏夹列表页滚动会**自动**为每个收藏夹发首页预览（约 10 条）；只有预览不足的收藏夹才需要逐个点开翻页
- 点收藏夹卡片必须用 `page.get_by_text(name, exact=True)`（`exact=False` 会点到视频标题里的同名字符串）
- 同名收藏夹用 `.nth(k)` 依次尝试；**按夹名合并**（同名取并集）是安全的
- 找卡片时的滚动要 `window.scrollTo` + `mouse.wheel` 双保险（页面用内部滚动容器）
- `favorites.json` 的收藏夹以**名字**为键，核对数量要按名字比对（`scripts/verify_counts.py` 已处理）

## 并发与安全

- 所有写 `data/favorites.json` 的脚本都通过 `scripts/lockutil.py` 抢锁；**不要并发跑写数据的脚本**
- **不要在长跑转写期间做抓取**：批处理持有启动瞬间的内存快照，会把期间的新抓取结果覆盖回旧状态
- 写 `favorites.json` 前必须备份；新结果少于旧结果一半时拒绝覆盖

## 呈现层设计（使用者关注点）

- **列表页简洁**：改写后的标题 + 一句话总结 + 大类/收藏夹/时长标签；不显示逐字稿
- **详情页详细**：要点、**重要节点时间轴（时间点 ↔ 截图 ↔ 当时原话）**、完整逐字稿（可折叠、点行复制时间点）、批注区
- **要点必须精炼**：单条 ≤90 字、最多 3 条。三处实现（`enrich` / `generate_outputs` / `build_dashboard`）阈值必须一致，
  由 `tests/test_points_rules.py` 守——改任一处都要同步另两处
- 排序默认「按收藏时间 新→旧」（口径见下方"收藏时间"）

## 收藏时间怎么来的

接口**不返回收藏时间戳**，但收藏列表按收藏时间**倒序**返回，所以"出现次序"就是收藏先后：

1. 「全部收藏」列表（`aweme/listcollection`）里出现次序 → 桶内名次 `ci`（0 = 最近）；各收藏夹内名次同理
2. 历史快照的"首次入库日期" = 该次整理首次发现的日期（粗粒度上界）

`build_collect_index.py` 合成 `data/collect_index.json`（`cb` 桶 + `ci` 名次 + `date`），
网页排序：`cb` 降序 → `ci` 升序 → 发布时间降序。

## 交付前必须真实渲染验证

生成的 `dashboard.html` 必须用无头浏览器打开、数 `.row` 卡片、点进详情检查时间轴与截图、检查 `pageerror`。
**"卡片数 > 0 且无 JS 报错"才算通过** —— 历史上有过模板 JS 转义错误导致整页空白、而字符串检查看不出来的事故。
`tests/test_render.py` 已实现该检查。

## 分类可编辑

优先级链：**人工 overrides（网页里改的）> `data/video_major.json`（逐条分类）> `config/categories.json`（收藏夹映射）> 待归类**。
网页详情页可改大类/收藏夹并「导出分类修改」，覆盖到 `data/overrides.json` 即生效。

## 删除与排除

`data/excluded.json`（`{ids: [...]}`）在网页与笔记生成时都会被跳过。
批量清理务必用强特征正则，**并排除"氛围类"收藏夹**（伴学/音乐/白噪音/健身），否则会误删助眠与跟练内容；
删除前把命中条目录到 `data/removed_*.json` 备份。

## 已知陷阱

1. `yt-dlp` 下抖音会 403（需签名）→ 用抓取时捕获的 `play_addr` 直链 + cookie 下载；直链有时效，**先抓后下**
2. Playwright 自带 ffmpeg 是精简版（只支持 webm/vp8）→ 用 `imageio-ffmpeg` 的完整版
3. HuggingFace 直连常不通 → 从 ModelScope 下载模型后用本地路径加载
4. 静音/纯音乐视频转写为空，会被标记跳过 —— 属正常，不要当失败反复重试
5. 长时间后台跑转写，会话中断会使进程被结束 —— 但脚本每条落盘，重跑自动续上
