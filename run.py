# -*- coding: utf-8 -*-
"""抖音收藏知识库 · 统一入口

用法：
  python run.py all                 # 抓取 → 转写 → 生成（推荐首次）
  python run.py fetch               # 只抓取收藏夹（保留原分类）
  python run.py transcribe --limit 60
  python run.py build               # 生成网页 / Obsidian 笔记 / 周报
  python run.py site                # 打包离线站点 dist/
  python run.py serve               # 本地起服务预览（默认 8765 端口）
  python run.py check               # 跑全部自检
  python run.py fetch-model         # 从 ModelScope 下载 whisper 模型
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"


def run(script: str, *args, allow_fail: bool = False) -> int:
    path = SCRIPTS / script
    if not path.exists():
        print(f"!! 找不到脚本：{path}")
        return 1
    print(f"\n=== {script} {' '.join(args)} ===", flush=True)
    r = subprocess.run([sys.executable, str(path), *args])
    if r.returncode != 0 and not allow_fail:
        print(f"!! {script} 退出码 {r.returncode}，后续步骤已跳过")
        sys.exit(r.returncode)
    return r.returncode


def cmd_fetch():
    print("提示：会弹出浏览器窗口，首次请用手机扫码登录你自己的抖音账号。")
    run("fetch_gap.py")                 # 抓取（保留收藏夹结构 + 补缺口）
    run("fetch_collect_order.py", "--fast", allow_fail=True)   # 收藏顺序（失败不致命）


def cmd_transcribe(limit="60"):
    run("process_batch.py", "--limit", str(limit))
    run("pick_frames.py", "--only-transcribed", allow_fail=True)


def cmd_build():
    run("final_clean.py", allow_fail=True)
    run("clean_fake_transcripts.py", allow_fail=True)
    run("refill_enriched.py", allow_fail=True)
    run("generate_outputs.py")          # 内部会调用 build_dashboard.py
    run("clean_fake_notes.py", allow_fail=True)
    run("recover_notes.py", allow_fail=True)
    run("build_dashboard.py")
    run("build_collect_index.py", allow_fail=True)
    run("build_dashboard.py")
    print(f"\n✅ 完成：{(ROOT / 'dashboard.html')}")


def cmd_check():
    names = ["test_render.py", "test_points_rules.py", "test_notes_integrity.py", "final_verify.py"]
    ok = True
    for n in names:
        p = ROOT / "tests" / n
        if not p.exists():
            p = SCRIPTS / n
        if not p.exists():
            continue
        r = subprocess.run([sys.executable, str(p)], capture_output=True, text=True)
        flag = "✅" if r.returncode == 0 else "❌"
        print(f"{flag} {n}")
        if r.returncode != 0:
            ok = False
            print((r.stdout or "")[-600:])
    print("\n自检结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


def cmd_fetch_model():
    """从 ModelScope 镜像下载 faster-whisper small 到 models/（HuggingFace 直连常不可用）。"""
    target = ROOT / "models" / "faster-whisper-small"
    if (target / "model.bin").exists():
        print(f"✅ 模型已存在：{target}")
        return
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("需要 modelscope：pip install modelscope")
        sys.exit(1)
    target.parent.mkdir(parents=True, exist_ok=True)
    p = snapshot_download("pengzhendong/faster-whisper-small", local_dir=str(target))
    print(f"✅ 模型已下载：{p}")


def main():
    args = [a for a in sys.argv[1:]]
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]

    def opt(name, default):
        return rest[rest.index(name) + 1] if name in rest else default

    if cmd == "all":
        cmd_fetch()
        cmd_transcribe(opt("--limit", "100"))
        cmd_build()
    elif cmd == "fetch":
        cmd_fetch()
    elif cmd == "transcribe":
        cmd_transcribe(opt("--limit", "60"))
    elif cmd == "build":
        cmd_build()
    elif cmd == "site":
        run("build_site.py")
    elif cmd == "serve":
        run("server.py", *rest)
    elif cmd == "check":
        sys.exit(cmd_check())
    elif cmd == "fetch-model":
        cmd_fetch_model()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
