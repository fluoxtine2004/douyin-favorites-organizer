# 抖音改版了怎么办（SITE-CHANGE.md）

抖音前端和接口**会变**。这类工具最大的维护成本就在这里。本文档说明「哪里可能坏、怎么定位、改哪里」。

## 一、症状 → 定位

| 症状 | 最可能的原因 | 先看哪个函数 |
|---|---|---|
| 浏览器能打开抖音，但脚本抓 0 条 | 登录态过期 | 重新 `python run.py fetch` 扫码 |
| 收藏夹列表拿到了，但每个夹都是 0 条 | 接口字段改名 / 请求签名策略变了 | `scripts/fetch_gap.py` 里的 `collects/video/list` 响应处理 |
| 「全部收藏」散件抓不到 | `listcollection` 接口分页字段变了 | `fetch_gap.py` 的 union 分支 |
| 视频下载 403 | 直链字段变了或需要新签名 | `scripts/process_batch.py` 的 `download_video()` |
| 页面结构变了（点不到收藏夹卡片） | DOM 类名/结构变了 | `fetch_gap.py` 里的 `get_by_text(name, exact=True)` |
| 网页显示正常但排序乱 | 收藏顺序接口变了 | `scripts/fetch_collect_order.py` |

## 二、诊断工具（都在 `scripts/legacy/`）

```bash
python scripts/legacy/probe_xhr.py        # 监听页面发出的所有 XHR，打印接口与响应结构
python scripts/legacy/probe_dom.py        # 打印收藏夹列表页的 DOM 结构（找卡片选择器）
python scripts/legacy/probe_scroller.py   # 测试滚动容器与翻页行为
python scripts/legacy/audit_which_endpoint.py  # 对比各接口返回，确认哪个是收藏、哪个是点赞
```

**诊断原则**：先确认"页面自己发的请求"长什么样（URL、参数、响应字段），
再去改脚本去匹配它——**不要试图自己构造请求**。

## 三、三条不可动摇的约束

1. **点赞 ≠ 收藏**
   任何时候都要用 `collect_stat == 1` 做入库校验。
   历史上两次因为这个把点赞列表灌进库（一次还生成了周报），是这个项目最贵的 bug。

2. **不自己拼接口 URL**
   缺 `a_bogus` / `msToken` 签名的请求会被服务端**静默降级为空结果**（HTTP 200，`has_more=0`），
   表现得像"每个收藏夹都空了"。正确做法是 `page.on("response")` 监听页面自身的请求。

3. **不引入绕过风控的手段**
   本项目只做"驱动真实浏览器 + 复用本人登录态"。若某天必须破解签名才能用，
   那就说明这条路走到头了——请停下来，而不是加逆向代码。

## 四、改完必须做的三件事

1. 跑 `python scripts/verify_counts.py`：按**收藏夹名**（不是 collects_id）核对数量；
2. 抓一小批（`fetch_gap.py --limit 3`）先验证，再全量；
3. 跑 `python run.py check`：渲染 + 要点规则 + 笔记完整性。

## 五、已知的"正常残差"

- 某些收藏夹永远差 1–2 条：原作者已删除 / 转私密 / 被下架。接口计数保留但不再返回内容。
  判定方法：换个新会话再跑一次仍无新增 → 记为不可访问，不要一直重试。
- 纯音乐 / 无口播视频：转写为空，脚本会标记为「无语音」，不是失败。
- 图文帖：没有视频流，音频往往是 BGM，同样按「无语音」处理。
