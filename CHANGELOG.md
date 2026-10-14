# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] — 2026-10-13

首个公开版本。把「自己账号的抖音收藏」变成可检索知识库的完整管线。

### 管线
- **抓取**：驱动真实浏览器监听页面自身请求（`fetch_gap.py` / `fetch_favorites.py`），
  保留原收藏夹结构；`collect_stat == 1` 硬护栏确保**只收收藏、不碰点赞**。
- **转写**：本地 faster-whisper（small）逐字稿，VAD 过滤；无语音/纯音乐内容打 `no_transcript` 豁免，
  不采信 whisper 幻觉出的字幕水印。
- **选帧**：场景切换检测 + 要点锚定，只截有信息量的画面（`pick_frames.py`）。
- **分类**：收藏夹 → 大类两级，视频级分类优先（`config/categories.json` + 网页导出 `overrides.json`）。
- **生成**：可批注网页（`templates/dashboard.html`）+ Obsidian 笔记 + 专题聚合 + 周/季/年总结。
- **打包**：`dist/` 纯静态站点，可直接托管到任意静态服务。

### 交互
- 排序：按收藏时间 / 发布时间，双向切换；收藏时间由「全部收藏列表出现次序 + 夹内名次 + 首次入库日期」合成。
- 标注：⭐标重要 / 🔔加入回顾 / ✕删除 / 🏷改分类 / ✅加待办；改动存本地并可导出回写。
- 侧栏每日推荐（每日一视频 + 一个可执行案例）。

### 工程
- 要点护栏三处同源（≤90 字、最多 3 条），有单元测试守着（`tests/test_points_rules.py`）。
- 网页生成后强制真实渲染验证（`tests/test_render.py`），避免整页空白静默失败。
- CI：隐私扫描 + 语法编译 + 核心模块 import + demo 构建冒烟。
- `push_via_api.py`：在只放行 `api.github.com` 的网络里也能发布（走 REST，支持二进制）。

### 已知限制
- 抖音不返回「收藏时间戳」，收藏时间只能推算（已在文档中说明推导方式）。
- 接口会改版；改版时用 `scripts/legacy/` 下的探针重新确认字段，参考 `docs/SITE-CHANGE.md`。
- 仅限整理本人账号的收藏，详见 `DISCLAIMER.md`。
