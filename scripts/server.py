# -*- coding: utf-8 -*-
"""
抖音收藏知识库 · 本地服务（改动自动落盘，无需导出/手工放文件）
启动：python server.py  → 浏览器打开 http://127.0.0.1:8765
功能：
  GET  /                打开知识库网页
  GET  /media/...       视频截图等静态资源
  GET  /api/load        读取当前 overrides / excluded / marks / anno / taxonomy
  POST /api/save        保存某一类改动（自动写 data/*.json，带备份）
  POST /api/rebuild     重建网页 + Obsidian + 周报
"""
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PY = sys.executable
PORT = 8765

FILES = {
    "overrides": DATA / "overrides.json",
    "excluded": DATA / "excluded.json",
    "marks": DATA / "marks.json",
    "anno": DATA / "anno.json",
    "taxonomy": DATA / "taxonomy.json",
}
_LOCK = threading.Lock()
LOG = []


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(p: Path, obj):
    with _LOCK:
        if p.exists():
            try:
                shutil.copy2(p, p.with_suffix(".bak.json"))
            except Exception:
                pass
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):  # 安静一点
        LOG.append(fmt % args)
        if len(LOG) > 200:
            del LOG[:100]

    # ---------- API ----------
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/load"):
            out = {}
            for k, p in FILES.items():
                v = read_json(p, None)
                if v is not None:
                    out[k] = v
            out["_server"] = {"root": str(ROOT), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
            return self._json(out)
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8") if n else "{}"
        try:
            payload = json.loads(raw)
        except Exception:
            return self._json({"ok": False, "err": "bad json"}, 400)

        if path.startswith("/api/save"):
            kind = payload.get("kind", "")
            body = payload.get("data")
            if kind not in FILES:
                return self._json({"ok": False, "err": "unknown kind " + kind}, 400)
            if kind == "excluded" and isinstance(body, list):
                body = {"_说明": "排除名单：不出现在网页/Obsidian/周报，重抓也会跳过。", "ids": body}
            write_json(FILES[kind], body)
            return self._json({"ok": True, "saved": str(FILES[kind]), "n": (
                len(body.get("ids", [])) if isinstance(body, dict) and "ids" in body
                else (len(body) if isinstance(body, (dict, list)) else 0))})

        if path.startswith("/api/rebuild"):
            try:
                r = subprocess.run([PY, str(ROOT / "scripts" / "build_dashboard.py")],
                                   capture_output=True, text=True, timeout=600)
                out = (r.stdout or "") + (r.stderr or "")
                g = subprocess.run([PY, str(ROOT / "scripts" / "generate_outputs.py")],
                                   capture_output=True, text=True, timeout=900)
                out += (g.stdout or "") + (g.stderr or "")
                return self._json({"ok": True, "out": out[-1500:]})
            except Exception as e:
                return self._json({"ok": False, "err": str(e)}, 500)

        return self._json({"ok": False, "err": "not found"}, 404)


def main():
    PORT_ = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else PORT
    srv = ThreadingHTTPServer(("127.0.0.1", PORT_), Handler)
    print(f"✅ 知识库服务已启动：http://127.0.0.1:{PORT_}/dashboard.html")
    print(f"   数据目录：{DATA}")
    print("   改动会自动保存到 data/，关闭窗口即停止服务。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
