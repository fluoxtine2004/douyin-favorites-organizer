# -*- coding: utf-8 -*-
"""
整理管线：favorites.json + categories.json
  → vault/  Obsidian 笔记（每视频一 note，已存在的跳过以保护用户批注）
  → vault/00-周报/Week XXXX-Www.md
  → dashboard.html（本地可批注网页，内嵌真实数据）
用法：python generate_outputs.py [--week-label "首次全量"]
"""
import html
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "favorites.json"
CFG_FILE = ROOT / "config" / "categories.json"
VAULT = ROOT / "vault"
DASH = ROOT / "dashboard.html"

FORBIDDEN = r'[\\/:*?"<>|\r\n#^\[\]]'

# 要点护栏：单条 ≤90 字、最多 3 条；超过 200 字的整段文稿直接判定为脏数据丢弃
POINT_HARD_MAX = 90
POINT_DROP_OVER = 200
POINT_MAX_N = 3


def clean_points(pts):
    out = []
    for p in (pts or []):
        s = re.sub(r"\s+", " ", str(p)).strip()
        if not s or len(s) > POINT_DROP_OVER:
            continue
        if len(s) > POINT_HARD_MAX:
            s = s[:POINT_HARD_MAX].rstrip("，,、。 ") + "…"
        out.append(s)
        if len(out) >= POINT_MAX_N:
            break
    return out


def safe_name(s, maxlen=80):
    s = re.sub(FORBIDDEN, " ", str(s)).strip()
    return (s[:maxlen]).strip() or "untitled"


def build_note_names(videos):
    """给每条视频算一个**全局唯一**的笔记文件名。

    ⚠ 坑位 AE（2026-10-11）：抖音里有大量标题完全一样的视频（实测 21 条都叫「(无标题)」），
       旧实现只用 safe_name(title) 当文件名 → 互相覆写，最后只剩最后一条的内容，
       导致「有逐字稿的笔记逐字稿段必须完整」的全库不变量失败。
    去重规则：同一 basename 出现 >1 次时，**所有**同名条目都在尾部追加 `_<id 后 6 位>`，
    保证不再有任何覆写（包括那些暂时没内容、后续转写完成才会建笔记的条目）。
    """
    from collections import Counter
    base = {v["id"]: safe_name(v.get("title", "")) for v in videos}
    cnt = Counter(base.values())
    names = {}
    for v in videos:
        vid = v["id"]
        b = base[vid]
        if cnt[b] > 1:
            names[vid] = f"{b}_{str(vid)[-6:]}.md"
        else:
            names[vid] = f"{b}.md"
    return names


def iso_year_week(d: date):
    yy, ww, _ = d.isocalendar()
    return yy, ww


def load():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    cfg = json.loads(CFG_FILE.read_text(encoding="utf-8"))
    return data, cfg


def folder_major(fname: str, cfg) -> str:
    mapping = cfg.get("mapping", {})
    if fname in mapping:
        return mapping[fname]
    rules = cfg.get("rules", {})
    for major, kws in rules.items():
        if any(k.lower() in fname.lower() for k in kws):
            return major
    return "待归类"


def gen_note(video, folder_name, major, captured_at):
    """生成单条视频的 Obsidian 笔记"""
    title = video["title"]
    link = video["url"]
    points = clean_points(video.get("points"))
    transcript = video.get("transcript") or ""
    frames = video.get("frames") or []

    if points:
        pts_md = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(points))
    else:
        pts_md = "> [!warning] 待转写\n> 逐字稿与要点将在本周批次处理中生成（下载 → 语音转写 → AI 摘要）。"

    if transcript:
        trans_md = "\n".join("> " + ln for ln in transcript.splitlines())
    else:
        trans_md = "> （待转写）"

    if frames:
        fr_md = "\n\n".join(
            f"![[{Path(f['url']).parent.name}/{Path(f['url']).name}]]\n*{f.get('cap', '')}*"
            for f in frames if f.get("url"))
    else:
        fr_md = "（待生成）"

    lines = [
        "---",
        f'标题: "{title.replace(chr(34), "")}"',
        f"作者: {video.get('author','')}",
        f"收藏夹: {folder_name}",
        f"大类: {major}",
        f"原链接: {link}",
        f"抓取时间: {captured_at}",
        f'时长: "{video.get("duration","")}"',
        "tags: [抖音收藏, " + major + "]",
        "---",
        "",
        f"# {title}",
        "",
        f"> [!info] 视频信息\n> 作者：{video.get('author','')} ｜ 时长：{video.get('duration','')} ｜ "
        f"[▶ 原视频链接]({link})",
        "",
        "## 🎯 AI 要点",
        "",
        pts_md,
        "",
        "## 📄 逐字稿",
        "",
        "> [!abstract]- 整理后的全文（点击展开）",
        trans_md,
        "",
        "## 📸 关键帧截图",
        "",
        fr_md,
        "",
    ]
    return "\n".join(lines)


ANNO_MARK = "## ✍️ 我的批注"
POINTS_HEAD = "## 🎯 AI 要点"
TRANS_HEAD = "## 📄 逐字稿"


def refresh_points(old: str, pts_md: str) -> str:
    """把已有笔记里的「## 🎯 AI 要点」段落换成最新要点，其余内容（逐字稿/截图/批注）原样保留。

    为什么需要：upsert_note 对"已含内容"的笔记是跳过的（保护用户批注），
    所以要点的历史脏数据（整篇文稿）不会被自动覆盖——这里只做定点替换。
    """
    i = old.find(POINTS_HEAD)
    if i < 0:
        return old
    j = old.find("\n## ", i + len(POINTS_HEAD))
    if j < 0:
        return old
    return old[:i] + POINTS_HEAD + "\n\n" + pts_md + "\n" + old[j:]


def replace_transcript(old: str, trans_md: str) -> str:
    """把已有笔记里的「## 📄 逐字稿」段落整体换成最新逐字稿，其余原样保留。

    ⚠ 为什么需要（坑位 AD）：clean_fake_notes 的段落判伪用的是「碎片占比 ≥60%」，
       一些真实逐字稿（如 whisper 分句很碎的生活 vlog：「哇 / 好可愛 / 什麼」）会被
       误判成伪转写 → 逐字稿段被整段替换成占位说明，而 favorites.json 里的真实逐字稿仍在。
       本函数在重建时把「笔记逐字稿段缺行 / 变成占位说明」的笔记用原文修回来，
       但**绝不覆盖**真正无语音的豁免条目（那类 favorites 里本来就没有 transcript）。
    """
    i = old.find(TRANS_HEAD)
    if i < 0:
        return old
    # 段落体：跳过标题行与紧随的空行
    body_start = i + len(TRANS_HEAD)
    while body_start < len(old) and old[body_start] in "\r\n":
        body_start += 1
    j = old.find("\n## ", i + len(TRANS_HEAD))
    if j < 0:
        j = len(old)
    cur = old[body_start:j].strip()
    want = trans_md.strip()
    if cur == want:
        return old
    return old[:body_start] + want + "\n" + old[j:]


def upsert_note(note_file, video, folder_name, major, captured_at):
    """写笔记：新文件直接写；已存在则回填占位内容并刷新要点（保留用户批注区）"""
    body = gen_note(video, folder_name, major, captured_at)
    anno_tail = ANNO_MARK + "\n\n> [!note] 我的批注\n> - \n"
    if not note_file.exists():
        note_file.write_text(body + "\n" + anno_tail, encoding="utf-8")
        return "new"
    old = note_file.read_text(encoding="utf-8")
    if "（待转写）" not in old and "（待生成）" not in old:
        # 已含内容：不整体覆盖，但把「AI 要点」同步成最新（防脏数据残留）
        changed = False
        pts = clean_points(video.get("points"))
        if pts:
            pts_md = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(pts))
            new = refresh_points(old, pts_md)
            if new != old:
                old = new
                changed = True
        # 逐字稿段修复（坑位 AD）：只对「favorites.json 里确有逐字稿」的条目做，
        # 真无语音的豁免条目本来就没有 transcript，会被 gen_note 写成「（待转写）」，
        # 那种情况不在这里处理（否则会把合法的无语音说明盖掉）。
        if video.get("transcript"):
            trans_md = "\n".join("> " + ln for ln in video["transcript"].splitlines())
            new = replace_transcript(old, trans_md)
            if new != old:
                old = new
                changed = True
        if changed:
            note_file.write_text(old, encoding="utf-8")
            return "points"
        return "skip"
    if ANNO_MARK in old:
        anno_tail = ANNO_MARK + old.split(ANNO_MARK, 1)[1]
    note_file.write_text(body + "\n" + anno_tail, encoding="utf-8")
    return "updated"


def gen_weekly_report(week_label, folders_info):
    """生成周报 Markdown（AI 总结部分留给 agent 补写）"""
    today = date.today()
    yy, ww = iso_year_week(today)
    total = sum(f["count"] for f in folders_info)
    # 坑位 R：「新增收藏」= 本期**真正新收藏**（data/new_ids.json），不是「本期整理了多少条」。
    # 旧实现写 total → 周报头部显示「新增收藏: 1470」这种明显虚报。
    new_n, new_date = 0, ""
    try:
        _nj = json.loads((ROOT / "data" / "new_ids.json").read_text(encoding="utf-8"))
        new_n = len(_nj.get("ids") or [])
        new_date = _nj.get("date") or ""
    except Exception:
        pass
    if new_date and week_label in ("", "首次全量", "本周"):
        week_label = f"增量（{new_date}）"
    lines = [
        "---",
        f'标题: "Week {yy}-W{ww} 抖音收藏周报"',
        f"周期: {week_label}",
        f"新增收藏: {new_n}（本期整理 {total} 条）",
        "---",
        "",
        f"# 📋 Week {yy}-W{ww} 周报",
        "",
        f"本期整理 **{total}** 条收藏，分布在 {len(folders_info)} 个收藏夹。",
        "",
        "## 各收藏夹新增",
        "",
        "| 收藏夹 | 大类 | 条数 |",
        "|---|---|---|",
    ]
    for f in folders_info:
        lines.append(f"| {f['name']} | {f['major']} | {f['count']} |")
    summary_file = ROOT / "data" / "weekly_summary.txt"
    if summary_file.exists():
        # 周报主体直接由四段式（学习的/执行的/了解的/可运行的）构成，不再额外包裹
        lines += [
            "",
            summary_file.read_text(encoding="utf-8").strip(),
            "",
        ]
    lines += [
        "",
        "## ✍️ 本周批注汇总",
        "",
        "（你在网页/Obsidian 里写的批注会自动汇总到这里）",
        "",
    ]
    return "\n".join(lines), f"Week {yy}-W{ww}.md"


DASH_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>抖音收藏知识库</title>
<style>
  :root{--bg:#f6f7f9;--card:#fff;--border:#e5e7eb;--text:#1f2937;--muted:#6b7280;
    --primary:#4f46e5;--primary-light:#eef2ff;--chip:#f3f4f6;--note-bg:#fffbeb;--note-border:#f59e0b;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);font-size:15px;}
  header{background:var(--card);border-bottom:1px solid var(--border);padding:16px 24px;position:sticky;top:0;z-index:10;}
  .h-top{display:flex;align-items:center;gap:14px;flex-wrap:wrap;}
  .h-top h1{font-size:19px;margin-right:auto;}
  .badge{font-size:12px;background:var(--primary-light);color:var(--primary);padding:3px 10px;border-radius:999px;font-weight:600;}
  .search{flex:1;min-width:200px;max-width:340px;display:flex;}
  .search input{flex:1;border:1px solid var(--border);border-radius:8px 0 0 8px;padding:8px 12px;font-size:14px;outline:none;}
  .search input:focus{border-color:var(--primary);}
  .btn{border:none;background:var(--primary);color:#fff;padding:8px 14px;font-size:14px;cursor:pointer;border-radius:0 8px 8px 0;}
  nav{display:flex;gap:6px;margin-top:12px;flex-wrap:wrap;}
  nav button{border:none;background:transparent;padding:7px 14px;font-size:14px;border-radius:8px;cursor:pointer;color:var(--muted);}
  nav button.active{background:var(--primary-light);color:var(--primary);font-weight:600;}
  nav button .cnt{font-size:11px;margin-left:4px;color:var(--muted);}
  main{max-width:980px;margin:20px auto;padding:0 16px;}
  .stats{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;}
  .stat{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px 18px;flex:1;min-width:130px;}
  .stat b{font-size:22px;color:var(--primary);display:block;}
  .stat span{font-size:12px;color:var(--muted);}
  .summary-card{background:linear-gradient(135deg,#eef2ff,#fdf4ff);border:1px solid var(--border);border-radius:14px;padding:18px 22px;margin-bottom:18px;white-space:pre-wrap;line-height:1.9;}
  .toolbar{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;}
  .toolbar button{border:1px solid var(--border);background:#fff;border-radius:8px;padding:7px 14px;font-size:13px;cursor:pointer;color:var(--text);}
  .toolbar button:hover{border-color:var(--primary);color:var(--primary);}
  .video-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:14px;}
  .v-head{display:flex;gap:12px;align-items:flex-start;}
  .cover{width:120px;height:72px;border-radius:8px;flex-shrink:0;object-fit:cover;background:linear-gradient(135deg,#6366f1,#8b5cf6);}
  .v-meta{flex:1;min-width:0;}
  .v-meta h3{font-size:15px;line-height:1.45;margin-bottom:6px;font-weight:600;}
  .chips{display:flex;gap:6px;flex-wrap:wrap;}
  .chip{font-size:12px;background:var(--chip);padding:2px 9px;border-radius:999px;color:var(--muted);}
  .chip.folder{background:#ecfdf5;color:#059669;}
  .chip.major{background:var(--primary-light);color:var(--primary);}
  .points{margin:8px 0 0 18px;line-height:1.8;font-size:13.5px;color:#374151;}
  .v-actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center;}
  .link{font-size:13px;color:var(--primary);text-decoration:none;}
  .anno-btn{font-size:13px;border:1px solid var(--primary);color:var(--primary);background:#fff;border-radius:8px;padding:4px 12px;cursor:pointer;margin-left:auto;}
  .anno-btn:hover{background:var(--primary-light);}
  .anno-btn.has{background:var(--note-bg);border-color:var(--note-border);}
  details{margin-top:10px;border-top:1px dashed var(--border);padding-top:10px;}
  summary{cursor:pointer;font-size:13px;color:var(--muted);user-select:none;}
  summary:hover{color:var(--primary);}
  .transcript{margin-top:10px;font-size:13.5px;line-height:1.9;color:#374151;white-space:pre-wrap;}
  .frames{display:flex;gap:8px;margin-top:12px;overflow-x:auto;padding-bottom:4px;}
  .frame{flex-shrink:0;width:150px;}
  .frame img{width:150px;height:84px;border-radius:8px;object-fit:cover;}
  .frame .cap{font-size:11px;color:var(--muted);margin-top:4px;text-align:center;}
  .anno-area{margin-top:12px;background:var(--note-bg);border:1px solid var(--note-border);border-radius:10px;padding:12px;display:none;}
  .anno-area.open{display:block;}
  .anno-area textarea{width:100%;min-height:64px;border:1px solid var(--note-border);border-radius:8px;padding:8px;font-size:14px;font-family:inherit;resize:vertical;outline:none;background:#fff;}
  .save-row{display:flex;gap:8px;margin-top:8px;}
  .save-row button{border:none;border-radius:8px;padding:6px 14px;font-size:13px;cursor:pointer;}
  .save-anno{background:var(--note-border);color:#fff;}
  .cancel-anno{background:var(--chip);color:var(--text);}
  .anno-item{background:#fff;border:1px solid var(--note-border);border-radius:8px;padding:8px 10px;margin-top:8px;font-size:13.5px;line-height:1.7;position:relative;}
  .anno-item .del{position:absolute;top:6px;right:8px;border:none;background:none;color:#dc2626;cursor:pointer;font-size:12px;}
  .anno-item .t{font-size:11px;color:var(--muted);display:block;margin-top:4px;}
  .empty{text-align:center;color:var(--muted);padding:48px 0;}
  .pending{font-size:13px;color:var(--muted);background:var(--chip);border-radius:8px;padding:8px 12px;margin-top:8px;}
</style>
</head>
<body>
<header>
  <div class="h-top">
    <h1>📚 抖音收藏知识库</h1>
    <span class="badge" id="badge"></span>
    <div class="search"><input id="q" placeholder="搜索标题 / 收藏夹 / 作者…"><button class="btn" onclick="render()">搜索</button></div>
  </div>
  <nav id="tabs"></nav>
</header>
<main>
  <div class="stats" id="stats"></div>
  <div id="weekly"></div>
  <div class="toolbar">
    <button onclick="exportAnno()">⬇️ 导出批注 JSON</button>
    <button onclick="importAnno()">⬆️ 导入批注</button>
    <button onclick="clearAnno()">🗑️ 清空批注</button>
  </div>
  <input type="file" id="importFile" accept=".json" style="display:none">
  <div id="list"></div>
</main>
<script>
const MAJORS = __MAJORS__;
const DATA = __DATA__;
const WEEKLY = __WEEKLY__;
const LS_KEY = "dy_anno_v1";
let anno = (()=>{try{return JSON.parse(localStorage.getItem(LS_KEY)||"{}");}catch(e){return{};}})();
let curTab = "summary";
function saveAnnoStore(){localStorage.setItem(LS_KEY,JSON.stringify(anno));}
function fmt(d){const p=n=>String(n).padStart(2,"0");return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate())+" "+p(d.getHours())+":"+p(d.getMinutes());}
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function renderTabs(){
  const t=document.getElementById("tabs");
  let h='<button class="'+(curTab==="summary"?"active":"")+'" onclick="setTab(\\'summary\\')">📋 本期总结</button>';
  MAJORS.forEach(m=>{const c=DATA.filter(v=>v.major===m).length;
    if(c)h+='<button class="'+(curTab===m?"active":"")+'" onclick="setTab(\\''+m+'\\')">'+m+'<span class="cnt">'+c+'</span></button>';});
  t.innerHTML=h;
}
function setTab(m){curTab=m;renderTabs();render();}
function card(v){
  const notes=anno[v.id]||[];
  const pts = v.points && v.points.length
    ? '<ul class="points">'+v.points.map(p=>'<li>'+esc(p)+'</li>').join("")+'</ul>'
    : '<div class="pending">⏳ 逐字稿与要点待转写（本周批次处理中生成）</div>';
  const trans = v.transcript
    ? '<div class="transcript">'+esc(v.transcript)+'</div>' : '';
  const frames = (v.frames&&v.frames.length)
    ? '<div class="frames">'+v.frames.map(f=>'<div class="frame">'+(f.url?'<img loading="lazy" src="'+f.url+'">':'')+'<div class="cap">'+esc(f.cap||"")+'</div></div>').join("")+'</div>'
    : '';
  const annoList = notes.map((n,i)=>'<div class="anno-item">✍️ '+esc(n.text).replace(/\\n/g,"<br>")+'<button class="del" onclick="delAnno(\\''+v.id+'\\','+i+')">删除</button><span class="t">'+n.time+'</span></div>').join("");
  return '<div class="video-card"><div class="v-head">'
    +(v.cover?'<img class="cover" loading="lazy" src="'+v.cover+'" onerror="this.style.display=\\'none\\'">':'')
    +'<div class="v-meta"><h3>'+esc(v.title)+'</h3><div class="chips">'
    +'<span class="chip major">'+v.major+'</span>'
    +'<span class="chip folder">📁 '+esc(v.folder)+'（原收藏夹）</span>'
    +'<span class="chip">👤 '+esc(v.author||"未知作者")+'</span>'
    +(v.duration?'<span class="chip">⏱ '+v.duration+'</span>':'')
    +'</div>'+pts+'</div></div>'
    +((trans||frames)?'<details><summary>📄 展开逐字稿与关键帧截图</summary>'+trans+frames+'</details>':'')
    +'<div class="v-actions"><a class="link" href="'+v.url+'" target="_blank">▶ 原视频</a>'
    +'<button class="anno-btn '+(notes.length?"has":"")+'" onclick="toggleAnno(\\''+v.id+'\\')">✍️ 批注'+(notes.length?'（'+notes.length+'）':'')+'</button></div>'
    +'<div class="anno-area" id="aa-'+v.id+'"><textarea id="ta-'+v.id+'" placeholder="写下你的想法、疑问、行动项…"></textarea>'
    +'<div class="save-row"><button class="save-anno" onclick="saveOne(\\''+v.id+'\\')">保存批注</button>'
    +'<button class="cancel-anno" onclick="toggleAnno(\\''+v.id+'\\')">收起</button></div>'
    +'<div id="anl-'+v.id+'">'+annoList+'</div></div></div>';
}
function toggleAnno(id){const el=document.getElementById("aa-"+id);
  if(el.classList.toggle("open")){document.getElementById("ta-"+id).focus();el.scrollIntoView({behavior:"smooth",block:"nearest"});}}
function saveOne(id){const t=document.getElementById("ta-"+id);if(!t.value.trim()){t.focus();return;}
  (anno[id]=anno[id]||[]).push({text:t.value.trim(),time:fmt(new Date())});
  saveAnnoStore();t.value="";render();
  setTimeout(()=>{const el=document.getElementById("aa-"+id);if(el)el.classList.add("open");},0);}
function delAnno(id,i){anno[id].splice(i,1);if(!anno[id].length)delete anno[id];saveAnnoStore();render();}
function exportAnno(){if(!Object.keys(anno).length){alert("还没有批注可导出");return;}
  const b=new Blob([JSON.stringify(anno,null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="抖音收藏批注_备份.json";a.click();}
function importAnno(){document.getElementById("importFile").click();}
document.getElementById("importFile").addEventListener("change",e=>{
  const f=e.target.files[0];if(!f)return;const r=new FileReader();
  r.onload=()=>{try{anno=Object.assign(anno,JSON.parse(r.result));saveAnnoStore();render();alert("导入成功");}catch(err){alert("文件格式不对");}};
  r.readAsText(f);e.target.value="";});
function clearAnno(){if(confirm("确定清空所有批注？此操作不可恢复。")){anno={};saveAnnoStore();render();}}
function render(){
  const q=(document.getElementById("q").value||"").trim().toLowerCase();
  document.getElementById("badge").textContent=DATA.length+" 条 · "+(WEEKLY.label||"");
  document.getElementById("stats").innerHTML=
    '<div class="stat"><b>'+DATA.length+'</b><span>本期收藏</span></div>'
    +'<div class="stat"><b>'+new Set(DATA.map(v=>v.folder)).size+'</b><span>原收藏夹</span></div>'
    +'<div class="stat"><b>'+MAJORS.filter(m=>DATA.some(v=>v.major===m)).length+'</b><span>大类</span></div>'
    +'<div class="stat"><b>'+Object.values(anno).reduce((s,a)=>s+a.length,0)+'</b><span>我的批注</span></div>';
  const wk=document.getElementById("weekly");
  if(curTab==="summary"&&WEEKLY.text){wk.innerHTML='<div class="summary-card">📋 '+esc(WEEKLY.text)+'</div>';}
  else wk.innerHTML="";
  const list=document.getElementById("list");
  let items=curTab==="summary"?DATA:DATA.filter(v=>v.major===curTab);
  if(q)items=DATA.filter(v=>(v.title+(v.folder||"")+(v.author||"")).toLowerCase().includes(q));
  list.innerHTML=items.length?items.map(card).join(""):'<div class="empty">没有匹配的内容</div>';
}
renderTabs();render();
</script>
</body>
</html>
"""


def gen_dashboard(majors, videos, weekly_text, label):
    dash = (DASH_TEMPLATE
            .replace("__MAJORS__", json.dumps(majors, ensure_ascii=False))
            .replace("__WEEKLY__", json.dumps({"text": weekly_text, "label": label}, ensure_ascii=False))
            .replace("__DATA__", json.dumps(videos, ensure_ascii=False)))
    DASH.write_text(dash, encoding="utf-8")


def main():
    week_label = "首次全量"
    if "--week-label" in sys.argv:
        week_label = sys.argv[sys.argv.index("--week-label") + 1]

    data, cfg = load()
    majors = [m for m in cfg.get("majors", []) if m != "待归类"] + ["待归类"]

    # 视频级大类映射（AI 逐条分类结果，优先级高于收藏夹映射）
    vmaj_file = ROOT / "data" / "video_major.json"
    # 排除名单（网页删除 / 批量清理）
    excluded = set()
    _xp = ROOT / "data" / "excluded.json"
    if _xp.exists():
        try:
            excluded = set(json.loads(_xp.read_text(encoding="utf-8")).get("ids", []))
        except Exception:
            excluded = set()
    # 人工分类修正（网页导出的 overrides.json）
    ovr = {}
    _op = ROOT / "data" / "overrides.json"
    if _op.exists():
        try:
            ovr = json.loads(_op.read_text(encoding="utf-8"))
            ovr = {k: v for k, v in ovr.items() if not str(k).startswith("_")}
        except Exception:
            ovr = {}
    vmaj = {}
    if vmaj_file.exists():
        try:
            vmaj = json.loads(vmaj_file.read_text(encoding="utf-8")).get("map", {})
        except Exception:
            vmaj = {}

    videos = []
    folders_info = []
    captured = data.get("fetched_at", time.strftime("%Y-%m-%d %H:%M"))
    excluded_titles = set()
    for f in data.get("folders", []):
        for _v in f.get("videos", []):
            if _v.get("id") in excluded:
                excluded_titles.add(_v.get("title", ""))
    for f in data.get("folders", []):
        fname = f.get("name", "")
        folder_default = folder_major(fname, cfg)
        # 排除名单内的条目：不建笔记、不计入收藏夹统计（与网页 build_dashboard 口径保持一致）
        folder_videos = [v for v in f.get("videos", []) if v.get("id") not in excluded]
        if not folder_videos:
            continue
        folders_info.append({"name": fname, "major": folder_default, "count": len(folder_videos)})
        for v in folder_videos:
            _o = ovr.get(v["id"]) or {}
            major = _o.get("major") or vmaj.get(v["id"]) or folder_default
            if _o.get("folder"):
                fname = _o["folder"]
            videos.append({
                "id": v["id"],
                "title": v.get("title", ""),
                "url": v.get("url", ""),
                "cover": v.get("cover", ""),
                "author": v.get("author", ""),
                "duration": v.get("duration", ""),
                "folder": fname,
                "major": major,
                "points": v.get("points", []),
                "transcript": v.get("transcript", ""),
                "no_transcript": bool(v.get("no_transcript")),
                # 截图路径转为相对路径，网页才能正常显示
                "frames": [
                    {"url": (lambda p: p.relative_to(ROOT).as_posix()
                             if str(p).startswith(str(ROOT)) else str(p))(Path(fr.get("url", ""))),
                     "cap": fr.get("cap", "")}
                    for fr in (v.get("frames") or []) if fr.get("url")
                ],
            })

    # ---- Obsidian 笔记（已含内容的跳过以保护用户批注；占位符状态则回填逐字稿）----
    new_notes = updated_notes = pts_notes = pending_skip = 0
    note_names = build_note_names(videos)
    for v in videos:
        # 只给「有内容」的视频建笔记（有逐字稿，或已判定无语音豁免）。
        # 仅入库、尚未转写的先不建占位笔记 —— 否则 1000+ 篇空笔记会把 vault 淹掉。
        if not v.get("transcript") and not v.get("no_transcript"):
            pending_skip += 1
            continue
        note_dir = VAULT / v["major"]
        note_dir.mkdir(parents=True, exist_ok=True)
        note_file = note_dir / note_names[v["id"]]
        r = upsert_note(note_file, v, v["folder"], v["major"], captured)
        if r == "new":
            new_notes += 1
        elif r == "updated":
            updated_notes += 1
        elif r == "points":
            pts_notes += 1

    # ---- 周报 ----
    report, report_name = gen_weekly_report(week_label, folders_info)
    rp_dir = VAULT / "00-周报"
    rp_dir.mkdir(parents=True, exist_ok=True)
    rp_file = rp_dir / report_name
    # 周报是生成物：每次覆盖写入（用户批注请写在各条视频笔记的「我的批注」区）
    rp_file.write_text(report, encoding="utf-8")

    # ---- 汇总文本（网页 + 控制台）----
    by_major = {}
    for v in videos:
        by_major[v["major"]] = by_major.get(v["major"], 0) + 1
    dist = " / ".join(f"{m} {n}" for m, n in sorted(by_major.items(), key=lambda x: -x[1]))
    # ---- 清理：同一视频若在大类调整前生成过旧笔记（残留副本），只保留当前大类下的那份 ----
    current_by_name = {}
    for v in videos:
        current_by_name[safe_name(v["title"])] = v["major"]
    removed = 0
    for md in VAULT.rglob("*.md"):
        if md.parent == VAULT or md.parent.name == "00-周报":
            continue
        name = md.stem
        want = current_by_name.get(name)
        if want and md.parent.name != want:
            try:
                txt = md.read_text(encoding="utf-8")
            except Exception:
                continue
            if "tags: [抖音收藏," in txt:  # 只删我们生成的笔记
                md.unlink()
                removed += 1

    # ---- 清理「孤儿」生成笔记：视频已不在库里，或标题已变导致文件名对不上 ----
    # 这些不会显示在网页里，但会残留在 vault（要点是历史脏数据）。
    # 一律移出 vault 到 _stale_notes/（不删除，保留可追溯）。
    QUAR = ROOT / "_stale_notes"
    # 用与建笔记时同一套命名（含重名去重后缀），否则去重后的笔记会被当成孤儿误移走
    by_id_name = {v["id"]: Path(note_names[v["id"]]).stem for v in videos}
    moved = 0
    for md in list(VAULT.rglob("*.md")):
        if md.parent == VAULT or md.parent.name in ("00-周报", "专题"):
            continue
        try:
            txt = md.read_text(encoding="utf-8")
        except Exception:
            continue
        if "tags: [抖音收藏," not in txt:
            continue
        m = re.search(r"原链接: https://www\.douyin\.com/video/(\d+)", txt)
        vid = m.group(1) if m else None
        if vid and vid in by_id_name and md.stem == by_id_name[vid]:
            continue                      # 正常笔记
        QUAR.mkdir(parents=True, exist_ok=True)
        dst = QUAR / md.name
        k = 1
        while dst.exists():
            dst = QUAR / f"{md.stem} ({k}).md"
            k += 1
        try:
            shutil.move(str(md), str(dst))
            moved += 1
        except Exception:
            pass
    summary_file = ROOT / "data" / "weekly_summary.txt"
    if summary_file.exists():
        # 由 agent 撰写的本周小总结（自动更新时覆盖写入）
        weekly_text = summary_file.read_text(encoding="utf-8").strip()
    else:
        weekly_text = (
            f"{week_label}：共整理 {len(videos)} 条收藏，{len(folders_info)} 个收藏夹。\n"
            f"大类分布：{dist}\n"
            "逐字稿与关键帧截图将在下载/转写批次完成后补充到每条卡片中。"
        )
    # 网页改由 build_dashboard.py 生成（列表简洁 + 详情详细 + 节点对齐）
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_dashboard.py")], check=False)
        # 生成后必须做真实渲染验证（避免 JS 语法错误导致空白页）
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_render.py")],
                           capture_output=True, text=True, timeout=300)
        out = (r.stdout or "") + (r.stderr or "")
        if "列表卡片数: 0" in out or "PAGEERROR" in out or "CONSOLE:" in out:
            print("!! 网页渲染验证未通过，请检查：")
            print("\n".join(out.splitlines()[:12]))
        else:
            for line in out.splitlines():
                if line.startswith(("列表卡片数", "JS 报错")):
                    print("   " + line)
        # 专题笔记（AI/MCP/Skills、求职、理财…）
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_topics.py")], check=False)
    except Exception as e:
        print(f"!! 网页生成/验证失败：{e}")

    print(f"✅ Obsidian 笔记：新建 {new_notes} 篇 / 回填逐字稿 {updated_notes} 篇 / "
          f"要点刷新 {pts_notes} 篇 / 清理旧副本 {removed} 篇 / 移出孤儿 {moved} 篇 / "
          f"跳过待转写 {pending_skip} 条（尚无内容，不建占位笔记）")
    print(f"✅ 周报：{rp_file}")
    print(f"✅ 网页：{DASH}")
    print(f"   大类分布：{dist}")


if __name__ == "__main__":
    main()
