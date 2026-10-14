# Agent 指南（AGENTS.md）

> 给 AI 编程助手看的仓库说明书。人类请先读 [README.md](README.md)。
> 最后验证：2026-10-13

## 这是什么

把**你自己账号的抖音收藏**整理成可检索的知识库：抓取 → 逐字稿 → 关键帧截图 → 可批注网页 + Obsidian 笔记 + 周报。
单人自用工具，不是爬虫框架，**不支持也不允许抓取他人内容**。

## 环境要求

- Python 3.10+（推荐 3.11/3.12）
- Windows / macOS / Linux；Windows 下用 PowerShell
- 磁盘：≥ 5GB（媒体文件随收藏量增长，500 条约 2–5GB）
- 首次需**本人手机扫码登录抖音**（浏览器窗口会弹出来）

## 安装

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

模型（可选，不装则首次转写自动从 HuggingFace 拉取）：
```bash
python run.py fetch-model      # 从 ModelScope 镜像下载到 models/
```

## 常用命令

| 目的 | 命令 |
|---|---|
| 看演示（不登录、不装模型） | 直接打开 `demo/index.html` |
| 全流程 | `python run.py all` |
| 只抓取 | `python run.py fetch` |
| 只转写 | `python run.py transcribe --limit 60` |
| 只生成网页/笔记 | `python run.py build` |
| 本地起服务预览 | `python run.py serve` |
| 自检 | `python run.py check`（或逐个 `python tests/*.py`） |

## 目录约定

```
scripts/          管线脚本（每个都能独立命令行运行）
scripts/legacy/   一次性调试探针（不参与管线，改版排障时用）
tests/            质量守门：渲染 / 要点规则 / 笔记完整性
templates/dashboard.html   核心 UI 模板（唯一需要改 UI 的文件）
config/categories.json     收藏夹 → 大类的映射（可改）
demo/                      脱敏示例数据 + 生成脚本
```

## 硬性规则（改代码必须遵守）

1. **点赞 ≠ 收藏，绝不混用接口**
   - 收藏：`/aweme/v1/web/collects/list/`、`/aweme/v1/web/collects/video/list/`、`/aweme/v1/web/aweme/listcollection/`
   - **点赞：`/aweme/v1/web/aweme/favorite/` ← 永远不要吸收它**
   - 入库判据：`aweme.collect_stat == 1`；`collect_stat == 0` 一律跳过
   - 历史上两次把点赞列表当成收藏灌进库，是全项目最贵的 bug
2. **不要自己拼接口 URL**：raw `fetch` 缺少 `a_bogus`/`msToken` 签名会被**静默降级为空结果**。
   正确做法是驱动页面（`page.on("response")` 监听页面自己发的请求）。
3. **写 `data/favorites.json` 前必须拿 `scripts/lockutil.py` 的互斥锁**，且不要并发跑写数据的脚本。
4. **长跑批处理不要与抓取同时进行**：批处理持有启动瞬间的内存快照，会把期间的新抓取结果覆盖回旧状态。
   整理前先确认无 python 进程在跑（Windows：`tasklist | findstr python`）。
5. **要点必须精炼**：单条 ≤ 90 字、最多 3 条。三处实现（`enrich.clean_points` / `generate_outputs.clean_points` /
   `build_dashboard.clean_points`）阈值必须一致，改一处要同步另两处并跑 `tests/test_points_rules.py`。
6. **生成网页后必须真实渲染验证**：跑 `tests/test_render.py`，看到「卡片数 > 0 且无 JS 报错」才算通过（曾因 JS 转义错误整页空白）。
7. **不要把个人数据提交进仓库**：`data/`、`media/`、`vault/`、`browser_profile/` 全部在 `.gitignore` 里，
   CI 有隐私扫描，命中即失败。

## 遇到抓取失败时的排查顺序

1. 页面能打开吗？→ 不行就是网络/登录态问题，重跑 `python run.py fetch`（会弹浏览器）
2. 收藏夹列表能拿到吗？→ 不能多半是登录过期，重新扫码
3. 数量对不上？→ `python scripts/verify_counts.py` 按**收藏夹名**比对（不是 collects_id）
4. 接口字段变了？→ 用 `scripts/legacy/probe_xhr.py`、`probe_dom.py` 探针重新确认，再参考 `docs/SITE-CHANGE.md`

## 不要做的事

- 不要为了"让它跑起来"而绕过登录、伪造 Cookie 或提供任何破解手段
- 不要把 `browser_profile/`（含登录态）分享或上传
- 不要把 `media/` 里的原始视频再分发（版权属于原作者）
