# 快速开始（从 0 到看到网页）

全程约 20 分钟（不含转写时间）。转写是唯一慢的环节，500 条约需 10 小时，可分批跑、随时中断。

## 0. 先看效果（30 秒）

```bash
git clone https://github.com/fluoxtine2004/douyin-favorites-organizer.git
cd douyin-favorites-organizer
# 直接双击打开 demo/index.html
```

demo 用的是脱敏假数据，不需要登录抖音、不需要装任何模型。先确认这个 UI 是你想要的，再往下走。

## 1. 装环境

**Windows：**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

**macOS / Linux：**
```bash
bash install.sh
```

手动装也行：
```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/python -m playwright install chromium
```

## 2. 首次抓取（需要手机扫码）

```bash
python run.py fetch
```

会发生什么：

1. 弹出一个 Chromium 窗口，停在抖音页面；
2. 窗口里用**手机抖音 App 扫码**登录你自己的账号（这个窗口是给你登录用的）；
3. 脚本自动打开「收藏夹」页，逐个收藏夹抓取，并保存到 `data/favorites.json`；
4. 登录态会持久化在 `browser_profile/`，**以后不用再扫**（除非登录过期）。

耗时参考：70 个收藏夹 / 500 条收藏 ≈ 10–20 分钟。

> 抓完可以核对一下数量：`python scripts/verify_counts.py`
> 如果某些收藏夹差个位数，通常是原作者已删除/转私密的视频，接口不再返回但计数保留，属正常。

## 3. 转写 + 截图

```bash
python run.py transcribe --limit 60     # 先跑 60 条试试
python run.py transcribe --limit 1000   # 剩下的接着跑
```

- 每条：下载视频 → 抽音频 → whisper 转写 → 智能选帧（只挑有信息量的画面）；
- **每条落盘一次**，中断后重跑自动跳过已完成的，放心分多次跑；
- 纯音乐/无口播的视频会被标为「无语音」，这是正常的，不是失败。

首次运行会自动下载 whisper small 模型（约 460MB）。如果从 HuggingFace 拉取太慢：

```bash
pip install modelscope
python run.py fetch-model      # 走 ModelScope 镜像
```

## 4. 生成网页 / 笔记 / 周报

```bash
python run.py build
```

产物：

| 产物 | 位置 | 说明 |
|---|---|---|
| 可批注网页 | `dashboard.html` | 双击打开即可用；改动（标星/批注/改分类/待办）存浏览器本地 |
| Obsidian 笔记 | `vault/` | 一条视频一篇，含要点、时间轴、逐字稿、截图 |
| 周报 | `vault/00-周报/` | 本期新增 + 主题流向 + 可执行案例 |
| 专题聚合 | `vault/专题/` | 按主题横跨收藏夹聚合 |
| 离线站点 | `dist/`（`python run.py site`） | 纯静态，可发布到任意静态托管 |

本地预览：`python run.py serve` → 打开 http://127.0.0.1:8765/dashboard.html

## 5. 每周例行

```bash
python run.py all
```

只抓新增、只转写新增、重建网页——**增量**，不会重复处理已有内容。
想自动化：用系统任务计划（Windows「任务计划程序」/ macOS `launchd` / Linux `cron`）每周跑一次
`python run.py all` 即可。

## 6. 自检

```bash
python run.py check
```

会检查：网页能否真实渲染（卡片数 > 0、无 JS 报错）、要点是否合规（≤90 字 / ≤3 条）、笔记完整性。

## 常见下一步

- 分类不合意 → 改 `config/categories.json`（收藏夹→大类），或在网页里直接改并导出 `overrides.json`
- 想加自己的专题 → 见 `scripts/build_topics.py` 里的 `TOPICS` 列表
- 抓取失败了 → 见 [FAQ.md](FAQ.md)，特别是「登录过期」「403」
