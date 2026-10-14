# -*- coding: utf-8 -*-
"""
构建可上线产物 → dist/
  · index.html   界面（数据外置为 data.json，便于缓存与增量更新）
  · data.json    视频数据（供前端与小程序共用同一份 API 数据结构）
  · media/*.jpg  仅打包被引用的截图，并压缩到 720px / q72
  · sw.js + manifest.webmanifest  离线缓存与移动端安装
  · api/mock/*.json  小程序/外部消费用的只读接口样例（与 data.json 同源）
用法：python build_site.py
"""
import json
import os
import re
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MAXW = 720
QUALITY = 72



# ---------- 云服务（可选：登录 + 分类/标签/标记/批注持久化）----------
# 默认**不开启**：产出纯静态站，网页上的改动只存在浏览器 localStorage 里。
# 想开「多端同步」时才配置下面两个环境变量（值来自你自己的云托管实例）：
#   DYKB_ENDPOINT  例如 https://your-app.example.com
#   DYKB_KEY       该实例的 publishable key（可公开，非密钥）
PUBLIC_CONFIG = {
    "endpoint": os.environ.get("DYKB_ENDPOINT", "").strip(),
    "publishableKey": os.environ.get("DYKB_KEY", "").strip(),
}
CLOUD_ENABLED = bool(PUBLIC_CONFIG["endpoint"] and PUBLIC_CONFIG["publishableKey"])

CLOUD_JS = """
// ===== 云服务层：登录后分类/标签/标记/批注全部云端持久化 =====
const PUBLIC_CONFIG = __PUBLIC_CONFIG__;
let cloud = null, cloudUser = null, cloudOn = false;
function cloudInit(){
  if(!window.WorkBuddyCloud) { console.warn("cloud sdk not loaded"); return; }
  cloud = WorkBuddyCloud.createWorkBuddyCloud({
    endpoint: PUBLIC_CONFIG.endpoint,
    publishableKey: PUBLIC_CONFIG.publishableKey
  });
}
async function cloudLoad(){
  if(!cloud) return;
  try{
    const r = await cloud.auth.getSession();
    const d = r && (r.data !== undefined ? r.data : r);
    cloudUser = d && d.session ? d.session : (d && d.user ? d : null);
  }catch(e){ cloudUser = null; }
  if(!cloudUser){ cloudOn=false; authBtn(); return; }
  cloudOn = true;
  authBtn();
  const { data, error } = await cloud.database.from("edits").select("kind,doc");
  if(error){ toast("云端读取失败：" + (error.message||"")); return; }
  (data||[]).forEach(r=>{
    if(r.kind==="overrides") ovr = Object.assign({}, r.doc||{}, ovr);
    else if(r.kind==="excluded") dels = Array.from(new Set(dels.concat((r.doc&&r.doc.ids)||[])));
    else if(r.kind==="marks") marks = Object.assign({}, r.doc||{}, marks);
    else if(r.kind==="anno") anno = Object.assign({}, r.doc||{}, anno);
    else if(r.kind==="taxonomy") for(const k in (r.doc||{})){ if(!k.startsWith("_")) TAXO[k] = r.doc[k]; }
  });
  save(LS_OVR,ovr); save(LS_MARK,marks); localStorage.setItem(LS_DEL, JSON.stringify(dels));
  authBtn(); render();
}
async function cloudSave(kind, doc){
  if(!cloudOn || !cloud) return;
  try{
    const { error } = await cloud.database.from("edits").upsert({ kind: kind, doc: doc }, { onConflict: "owner_id,kind" });
    if(error) toast("云端保存失败：" + (error.message||""));
  }catch(e){ toast("云端保存异常"); }
}
function authBtn(){
  const el = document.getElementById("auth-btn");
  if(!el) return;
  if(cloudOn && cloudUser){
    const em = (cloudUser.user && (cloudUser.user.email || cloudUser.user.phone)) || "已登录";
    el.textContent = "☁️ " + em + " · 退出登录";
    el.classList.add("on");
  } else {
    el.textContent = (typeof cloud === "undefined" || !cloud) ? "⚠️ 云端未加载（点此重试）" : "🔑 登录";
    el.classList.remove("on");
  }
}
function authClick(){
  if(cloudOn && cloudUser){ doLogout(); return; }
  if(!cloud){ location.reload(); return; }
  showLogin();
}
async function doLogout(){
  try{ await cloud.auth.signOut(); }catch(e){}
  cloudOn = false; cloudUser = null;
  try{ localStorage.removeItem(LS_OVR); localStorage.removeItem(LS_MARK); localStorage.removeItem(LS_DEL); }catch(e){}
  toast("已退出登录，改动保存已停止"); authBtn(); render();
}
function showLogin(){
  const m = document.getElementById("login-mask");
  if(m) m.style.display = "flex";
}
function hideLogin(){ const m=document.getElementById("login-mask"); if(m) m.style.display="none"; }
async function doPwdLogin(){
  const email=(document.getElementById("lg-email").value||"").trim();
  const pwd=document.getElementById("lg-pwd").value||"";
  if(!email||!pwd){ toast("请填写邮箱和密码"); return; }
  const { data, error } = await cloud.auth.signInWithPassword({ email: email, password: pwd });
  if(error){ toast("登录失败：" + (error.message||"")); return; }
  hideLogin(); toast("登录成功"); cloudLoad();
}
let otpState = null;
async function doSendOtp(){
  const email=(document.getElementById("lg-email").value||"").trim();
  if(!email){ toast("请先填邮箱"); return; }
  const { data, error } = await cloud.auth.sendOtp({ email: email });
  if(error){ toast("验证码发送失败：" + (error.message||"")); return; }
  otpState = { verificationId: data.verificationId, isExistingUser: data.isExistingUser, email: email };
  toast(data.isExistingUser ? "验证码已发送，请查收邮箱" : "验证码已发送；首次登录将用上面的密码完成注册");
  document.getElementById("otp-row").style.display="flex";
}
async function doOtpLogin(){
  const email=(document.getElementById("lg-email").value||"").trim();
  const token=(document.getElementById("lg-otp").value||"").trim();
  const pwd=document.getElementById("lg-pwd").value||"";
  if(!token){ toast("请填写验证码"); return; }
  if(!otpState){ toast("请先点「发送验证码」"); return; }
  const payload = { verificationId: otpState.verificationId, token: token, email: otpState.email || email,
                    isExistingUser: otpState.isExistingUser };
  if(!otpState.isExistingUser){ if(!pwd){ toast("首次注册请先填密码"); return; } payload.password = pwd; }
  const { error } = await cloud.auth.verifyOtp(payload);
  if(error){ toast("验证失败：" + (error.message||"")); return; }
  otpState = null; hideLogin(); toast("登录成功"); cloudLoad();
}
window.addEventListener("load", function(){
  try{ cloudInit(); }catch(e){}
  if(cloud){ cloudLoad(); }
  authBtn();
});
"""

LOGIN_HTML = """
<div class="login-mask" id="login-mask" style="display:none">
  <div class="login-card">
    <h3>登录后可云端保存</h3>
    <p class="login-tip">登录后，分类 / 分级 / 标签 / 标记 / 批注会保存在云端，换设备也能看到。</p>
    <input id="lg-email" type="email" placeholder="邮箱" autocomplete="email">
    <input id="lg-pwd" type="password" placeholder="密码" autocomplete="current-password">
    <button class="primary" onclick="doPwdLogin()">登录</button>
    <div class="login-hr"><span>或使用邮箱验证码</span></div>
    <div class="otp-row" id="otp-row" style="display:none">
      <input id="lg-otp" placeholder="6 位验证码">
      <button onclick="doOtpLogin()">验证并登录</button>
    </div>
    <button class="ghost" onclick="doSendOtp()">发送验证码到邮箱</button>
    <button class="ghost skip" onclick="hideLogin()">先看看（不登录，改动只存本机）</button>
  </div>
</div>
<style>
.login-mask{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;z-index:99;}
.login-card{background:#fff;border-radius:14px;padding:22px 24px;width:340px;box-shadow:0 12px 40px rgba(0,0,0,.18);}
.login-card h3{font-size:16px;margin-bottom:6px;}
.login-tip{font-size:12.5px;color:#6b7280;margin-bottom:14px;line-height:1.6;}
.login-card input{width:100%;border:1px solid #e6e8eb;border-radius:9px;padding:9px 11px;margin-bottom:9px;font-size:14px;font-family:inherit;}
.login-card button{width:100%;border:none;border-radius:9px;padding:9px;font-size:14px;cursor:pointer;margin-bottom:8px;}
.login-card button.primary{background:#4f46e5;color:#fff;}
.login-card button.ghost{background:#fff;border:1px solid #e6e8eb;color:#374151;}
.login-card button.skip{border:none;color:#9ca3af;font-size:12.5px;margin:2px 0 0;}
.login-hr{text-align:center;color:#9ca3af;font-size:12px;margin:8px 0;}
.otp-row{display:flex;gap:8px;}
.otp-row input{flex:1;margin-bottom:0;}
.otp-row button{width:auto;padding:9px 12px;background:#eef2ff;color:#4338ca;}
</style>
"""


def log(m):
    print(m, flush=True)


def main():
    # 本回合已触发过批量删除守卫，这里不再清理旧文件，直接覆盖写入（media/api 目录保留）
    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "media").mkdir(parents=True, exist_ok=True)
    (DIST / "api").mkdir(parents=True, exist_ok=True)

    html = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\[.*?\]);\n", html, re.S)
    data = json.loads(m.group(1))
    log(f"读取数据：{len(data)} 条")

    # 1) 抽出 DATA 外置（data.json 便于静态托管缓存/增量更新）
    #    ★ 同时**内联一份兜底数据**：用 file:// 直接双击打开（或预览面板以 file 协议加载）时
    #      `fetch("data.json")` 会被浏览器直接拒绝（URL scheme "file" is not supported），
    #      旧实现只会弹「数据加载失败」+ 整页空白。带了兜底，离线双击也能正常看全站。
    #      （2026-10-08 用户报「数据加载失败」→ 复现确认就是这个原因）
    html_site = html.replace(m.group(0), "let DATA = [];\n")
    # 启动时优先拉 data.json（静态托管下可增量更新），失败则用内嵌快照
    html_site = html_site.replace(
        "window.addEventListener(\"load\", boot);",
        "const DATA_INLINE = " + m.group(1) + ";\n"
        "window.addEventListener(\"load\", function(){\n"
        "  fetch(\"data.json\")\n"
        "    .then(function(r){ if(!r.ok) throw new Error(\"HTTP \"+r.status); return r.json(); })\n"
        "    .then(function(j){ DATA = j; render(); })\n"
        "    .catch(function(){\n"
        "      if (DATA_INLINE && DATA_INLINE.length){\n"
        "        DATA = DATA_INLINE; render();\n"
        "        try{ var b=document.getElementById(\"badge\");\n"
        "             if(b) b.textContent = \"📴 离线模式（内嵌数据） · \"+DATA.length+\" 条收藏\"; }catch(e){}\n"
        "      } else { toast(\"数据加载失败\"); }\n"
        "    });\n"
        "  boot();\n});")
    # 在线（非本地服务）模式提示
    html_site = html_site.replace('<h1>📚 抖音收藏知识库</h1>',
                                  '<h1>📚 抖音收藏知识库</h1>')
    html_site = html_site.replace("<head>", "<head>\n"
        '<link rel="manifest" href="manifest.webmanifest">\n'
        '<meta name="theme-color" content="#4f46e5">\n'
        '<meta name="description" content="抖音收藏知识库：短总结、要点、关键帧时间轴与逐字稿">')
    # 4) 云端登录 + 云持久化（**可选**：仅在配置了 DYKB_ENDPOINT / DYKB_KEY 时注入）
    if CLOUD_ENABLED:
        _sdk = ROOT / "assets" / "cloud-sdk.js"
        if _sdk.exists():
            # 把 SDK 直接内联进页面：不依赖任何外部请求，最稳
            _sdk_tag = "<script>\n" + _sdk.read_text(encoding="utf-8", errors="ignore") + "\n</script>"
        else:
            _sdk_tag = ('<script src="https://cdn.jsdelivr.net/npm/'
                        '@tencent-ai/workbuddy-cloud-sdk@dev/lib/index.global.js"></script>')
        html_site = html_site.replace('<head>', '<head>\n' + _sdk_tag, 1)
        html_site = html_site.replace(
            '<span class="badge" id="badge"></span>',
            '<span class="badge" id="badge"></span>'
            '<button id="auth-btn" class="auth-btn" onclick="authClick()">🔑 登录</button>', 1)
        html_site = html_site.replace(
            '</head>',
            '<style>\n'
            '.auth-btn{border:1px solid #e6e8eb;background:#fff;color:#4f46e5;border-radius:9px;'
            'padding:7px 13px;font-size:13.5px;cursor:pointer;font-family:inherit;}\n'
            '.auth-btn.on{background:#eef2ff;border-color:#c7d2fe;}\n'
            '</style>\n</head>', 1)
        html_site = html_site.replace('</body>', LOGIN_HTML + '\n</body>', 1)
        _cloud_block = ('<script>\n'
                        + CLOUD_JS.replace('__PUBLIC_CONFIG__', json.dumps(PUBLIC_CONFIG))
                        + '\n</script>')
        html_site = html_site.replace('</body>', _cloud_block + '\n</body>', 1)
        # 云端可用时：保存走云端，不再依赖本地服务
        html_site = html_site.replace(
            'function apiSave(kind, data){\n  if(!ONLINE) return;',
            'function apiSave(kind, data){\n  if(typeof cloudSave==="function"){ cloudSave(kind, data); }\n'
            '  if(!ONLINE) return;')
        log("已注入云服务层（DYKB_ENDPOINT 已配置）")
    else:
        log("未配置云服务（DYKB_ENDPOINT / DYKB_KEY 为空）→ 输出纯静态站；"
            "网页改动只存本机 localStorage，不依赖任何后端")
    (DIST / "index.html").write_text(html_site, encoding="utf-8")

    # 2) 图片：仅打包被引用的，并压缩
    used, saved, failed = set(), 0, 0
    for v in data:
        for f in v.get("frames") or []:
            url = f.get("url") or ""
            if url.startswith("media/"):
                used.add(url)
    log(f"引用截图：{len(used)} 张")
    for rel in used:
        src = ROOT / rel
        dst = DIST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if src.exists():
                im = Image.open(src).convert("RGB")
                if im.width > MAXW:
                    im = im.resize((MAXW, int(im.height * MAXW / im.width)), Image.LANCZOS)
                im.save(dst, "JPEG", quality=QUALITY, optimize=True, progressive=True)
                saved += 1
            else:
                failed += 1
        except Exception:
            try:
                shutil.copy2(src, dst)
                saved += 1
            except Exception:
                failed += 1
    size = sum(p.stat().st_size for p in (DIST / "media").rglob("*.jpg"))
    log(f"图片完成：{saved} 张（缺失 {failed}），合计 {size / 1048576:.1f} MB")

    # 3) data.json（前端与小程序共用）
    (DIST / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # 4) 只读 API 样例：供小程序 / 第三方消费
    videos, cats = [], {}
    for v in data:
        cats.setdefault(v.get("major") or "待归类", 0)
        cats[v["major"]] += 1
        videos.append({
            "id": v["id"], "title": v["title"], "summary": v.get("summary", ""),
            "major": v.get("major"), "lv2": v.get("lv2", ""), "lv3": v.get("lv3", ""),
            "tags": v.get("tags", []), "folder": v.get("folder"), "author": v.get("author"),
            "duration": v.get("duration"), "url": v.get("url"),
            "cover": v.get("cover", ""), "points": v.get("points", []),
            "frames": [{"url": f.get("url"), "t": f.get("t")} for f in (v.get("frames") or [])],
        })
    api = {"version": 1, "generated_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
           "total": len(videos), "categories": cats, "videos": videos}
    (DIST / "api" / "videos.json").write_text(json.dumps(api, ensure_ascii=False, indent=1),
                                              encoding="utf-8")

    # 5) PWA：manifest + 极简 service worker
    (DIST / "manifest.webmanifest").write_text(json.dumps({
        "name": "抖音收藏知识库", "short_name": "收藏知识库", "start_url": "./index.html",
        "display": "standalone", "background_color": "#f7f8fa", "theme_color": "#4f46e5",
        "icons": []
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (DIST / "sw.js").write_text(
        "const C='dykb-v1';\n"
        "self.addEventListener('install',e=>{self.skipWaiting();});\n"
        "self.addEventListener('activate',e=>{self.clients.claim();});\n"
        "self.addEventListener('fetch',e=>{\n"
        "  const u=new URL(e.request.url);\n"
        "  if(u.pathname.endsWith('data.json')||u.pathname.endsWith('.jpg')){\n"
        "    e.respondWith(caches.open(C).then(c=>c.match(e.request).then(r=>r||fetch(e.request)\n"
        "      .then(n=>{c.put(e.request,n.clone());return n;}).catch(()=>r))));\n"
        "  }\n"
        "});\n", encoding="utf-8")

    # 6) 部署说明
    (DIST / "README.md").write_text(
        "# 抖音收藏知识库 · 部署说明\n\n"
        "## 这是什么\n"
        "静态站点：`index.html`（界面）+ `data.json`（数据）+ `media/`（关键帧截图）+ `api/videos.json`（只读接口）。\n\n"
        "## 本地预览\n"
        "```bash\npython -m http.server 8080   # 然后访问 http://localhost:8080\n```\n\n"
        "## 静态托管\n"
        "把 `dist/` 整个目录上传到任意静态托管（对象存储 + CDN / CloudBase 静态托管 / Vercel 等）即可，\n"
        "无需后端。接口 `api/videos.json` 可直接被小程序 `wx.request` 消费。\n\n"
        "## 数据更新\n"
        "重新运行 `python scripts/build_site.py` 后覆盖上传即可（data.json 与 media/ 增量变化）。\n\n"
        "## 小程序接入\n"
        "1) 用同一份 `api/videos.json` 作为数据源（建议放入云开发数据库或对象存储）；\n"
        "2) 页面结构：列表页（标题+短总结+分类标签）→ 详情页（短总结/要点/时间轴/逐字稿）；\n"
        "3) 需要 AppID 与微信开发者工具上传、审核发布（这一步需要你提供 AppID）。\n\n"
        "## 在线编辑说明\n"
        "纯静态托管不支持写回。需要「线上改分类/标签并多端同步」时，接入后端（云数据库 + 登录）即可，\n"
        "本项目的 `overrides/excluded/marks/anno/taxonomy` 五个 JSON 就是后端表结构的原型。\n",
        encoding="utf-8")

    total = sum(p.stat().st_size for p in DIST.rglob("*") if p.is_file())
    log(f"✅ 构建完成：{DIST}  合计 {total / 1048576:.1f} MB")
    for p in sorted(DIST.rglob("*")):
        if p.is_file() and p.parent == DIST:
            log(f"   {p.name}  {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
