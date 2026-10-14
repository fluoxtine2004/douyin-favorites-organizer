# legacy/ —— 一次性调试与探针脚本

这些脚本**不参与日常管线**，是排查、探测、修数据时写的一次性工具。保留它们的原因：
抖音前端与接口会改版，这些探针是**定位问题最快的工具**（见 `docs/SITE-CHANGE.md`）。

> ⚠️ 注意：作者私有工作区里还有一批探针脚本**没有随本仓库发布** ——
> 因为它们内嵌了真实收藏夹的视频 id（或本机路径、测试账号信息）。
> 需要时按同样思路自己写一个即可，模板可参考下面的现成探针。

## 常用探针

| 脚本 | 用途 |
|---|---|
| `probe_xhr.py` | 监听页面发出的所有 XHR，打印接口 URL 与响应结构 |
| `probe_dom.py` | 打印收藏夹列表页 DOM，用于找卡片选择器 |
| `probe_scroller.py` | 测试滚动容器与翻页行为 |
| `probe_collect_order.py` / `probe_collect_time.py` | 探测收藏顺序 / 收藏时间能否推导 |
| `audit_which_endpoint.py` | 对比各接口返回，确认哪个是收藏、哪个是**点赞** |
| `audit_favorite_vs_digg.py` | 点赞 vs 收藏字段差异对照（事故复盘用） |
| `audit_find_collect_api.py` | 从页面流量里定位「收藏」接口 |
| `audit_collect_stat.py` / `audit_stat_guard.py` | 校验 `collect_stat == 1` 护栏是否生效 |
| `audit_listcollection.py` | 检查「全部收藏」并集接口 |
| `inspect_api.py` / `debug_click.py` | 早期调试脚本 |
| `fetch_api.py` / `fetch_api2.py` / `fetch_api3.py` | 早期尝试直接调接口（**已失效**，留作反例：raw fetch 会被静默降级为空） |
| `diag_all9.py` / `diag_one.py` / `check_suspect.py` / `check_counts.py` | 针对性诊断与对账 |
| `clean_digg_contamination.py` | 历史事故清理：把误入库的**点赞**数据剔除 |
| `strip_digg.py` | 移除条目里的点赞相关字段 |
| `clean_fake_favorites.py` / `find_fake_transcripts.py` | 清理伪转写（水印文本） |
| `recon_new_collects.py` / `ingest_from_probe.py` / `merge_after_fetch.py` | 抓取结果对账与灌库 |
| `restore_transcript_notes.py` / `refetch_urls.py` / `finalize_9.py` | 定点修复工具 |
| `shot_new_features.py` | 给新版 UI 截图 |
| `verify_all.py` / `_verify_purity.py` | 数据纯净度校验 |
| `auto_taxonomy.py` / `weekly_v2.py` | 早期分类 / 周报实验版本 |

## 使用注意

- 这些脚本大多**会读你的 `data/`**，部分会写文件，跑之前先看清楚；
- 它们没有单元测试覆盖，可能因接口改版而失效 —— 失效时对照 `docs/SITE-CHANGE.md` 自行修；
- 新增一次性脚本请放这里，别混进 `scripts/` 根目录。
