# 管线说明（数据怎么流动）

## 总览

```
                 ┌─────────────────────────────────────────────┐
 抖音收藏夹  ──►  ① 抓取 fetch_gap.py                            │
 （保留你的分类）  │   浏览器驱动 + 监听页面自身 XHR               │
                 │   → data/favorites.json（唯一的真源）        │
                 └─────────────────────────────────────────────┘
                                  │
                                  ▼
                 ┌─────────────────────────────────────────────┐
                 │ ② 下载 + 转写 process_batch.py               │
                 │   直链下载 → ffmpeg 抽音频 → whisper 转写     │
                 │   → media/<id>/{video.mp4,audio.wav,kf_*.jpg}│
                 └─────────────────────────────────────────────┘
                                  │
                                  ▼
                 ┌─────────────────────────────────────────────┐
                 │ ③ 选帧 pick_frames.py                        │
                 │   场景切换检测 + 要点锚定 → 只留有信息量画面   │
                 └─────────────────────────────────────────────┘
                                  │
                                  ▼
                 ┌─────────────────────────────────────────────┐
                 │ ④ 加工 enrich.py → refill_enriched.py        │
                 │   繁→简、去语气词、分段、短总结、要点闸门      │
                 │   → data/enriched.json                      │
                 └─────────────────────────────────────────────┘
                                  │
                                  ▼
                 ┌─────────────────────────────────────────────┐
                 │ ⑤ 产出 generate_outputs.py                   │
                 │   → dashboard.html（可批注网页）              │
                 │   → vault/（Obsidian 笔记 + 专题 + 周报）     │
                 │   build_site.py → dist/（离线站点）           │
                 └─────────────────────────────────────────────┘
```

## 每一步的输入输出

| 步 | 脚本 | 输入 | 输出 | 幂等性 |
|---|---|---|---|---|
| ① 抓取 | `fetch_gap.py` | 抖音账号登录态 | `data/favorites.json`、`data/collect_order.json` | 只增不减（新结果少于旧结果一半时拒写） |
| ② 转写 | `process_batch.py` | `favorites.json` 的直链 | `media/<id>/`、回写 `transcript`/`points`/`frames` | ✅ 已处理的跳过；支持 `--limit` 分批 |
| ③ 选帧 | `pick_frames.py` | 逐字稿 + 视频 | `media/<id>/kf_*.jpg` | ✅ 已有帧则跳过（`--only-transcribed` 只补缺） |
| ④ 加工 | `enrich.py` / `refill_enriched.py` | `favorites.json` | `data/enriched.json` | ⚠️ 不要直接跑 `enrich.py`（会丢 AI 精修），用 `refill_enriched.py` 保守补齐 |
| ⑤ 产出 | `generate_outputs.py` / `build_dashboard.py` / `build_site.py` | `favorites` + `enriched` + `video_major` + `overrides` + `excluded` | `dashboard.html`、`vault/`、`dist/` | ✅ 全量重建，可反复跑 |

## 分类的优先级链

```
人工 overrides（网页里改的）  ← 最高
   > data/video_major.json（逐条分类）
      > config/categories.json（收藏夹 → 大类映射）
         > 待归类
```
同时应用于 `build_dashboard.py`（网页）与 `generate_outputs.py`（笔记归档），保证两边一致。

## 排序：收藏时间是怎么来的

抖音接口**不返回收藏时间戳**，但收藏列表按收藏时间**倒序**返回。于是：

| 信号 | 用途 |
|---|---|
| 「全部收藏」列表里的出现次序 | 桶内名次 `ci`（0 = 最近收藏） |
| 各收藏夹内名次 | 收藏夹窗口内的相对次序 |
| 每次整理的首次发现日期 | 只能确定「早于某日」时使用 |

`build_collect_index.py` 合成为 `data/collect_index.json`：`cb`（桶，越大越新）+ `ci`（桶内名次）+ `date`。
网页端排序：`cb` 降序 → `ci` 升序 → 发布时间降序。

> ⚠️ 新增或恢复条目后**必须重跑** `fetch_collect_order.py` + `build_collect_index.py`，
> 否则新条目的排序键为 -1，会被排到列表最末尾（用户体感就是"我的新收藏不见了"）。

## 数据源纪律（血泪版）

| 接口 | 是什么 | 能不能用 |
|---|---|---|
| `/aweme/v1/web/collects/list/` | 我的收藏夹列表 | ✅ |
| `/aweme/v1/web/collects/video/list/` | 某个收藏夹的内容 | ✅ |
| `/aweme/v1/web/aweme/listcollection/` | 「全部收藏」扁平列表（含未归档散件） | ✅ |
| `/aweme/v1/web/aweme/favorite/` | **点赞列表，不是收藏！** | ❌ 永远不要用 |

入库护栏：`aweme.collect_stat == 1` 才算"我收藏了"；`collect_stat == 0` 一律跳过。

## 互斥锁与并发

- 所有写 `favorites.json` 的脚本都通过 `scripts/lockutil.py` 抢锁（PID 存活检测 + 4 小时过期）。
- **不要并发跑写数据的脚本**，也不要在长跑批处理（转写）期间做抓取：
  批处理持有启动瞬间的内存快照，会把期间的新抓取结果整体覆盖回旧状态。

## 断点续跑

| 场景 | 做法 |
|---|---|
| 转写中断 | 直接再跑 `python run.py transcribe`，已完成的自动跳过 |
| 抓取中断 | 重跑 `python run.py fetch`，脚本有备份保护，不会把已抓的丢掉 |
| 产出想重建 | `python run.py build`，全量重建，安全 |
