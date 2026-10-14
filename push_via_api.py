#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本目录（douyin-favorites-organizer）整个推送到 GitHub —— 只依赖 api.github.com。

为什么需要它：某些网络环境只放行 api.github.com，不放行 github.com，
于是 `git push` 会一直超时。本脚本改走 REST API（Git Blobs/Trees/Commits/Refs），
**完整支持二进制文件**（截图等），不经过 git 协议。

用法
----
1) 先到 GitHub 网页建一个**空仓库**（不要勾 Add README / .gitignore / license）：

     仓库名建议：douyin-favorites-organizer
     可见性    ：先选 Private，自测 OK 再改 Public

2) 建一个 Fine-grained personal access token：
     GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
     Repository access : 选 Only select repositories → 选中上面那个仓库
     Permissions       : Contents = Read and write   (够了)

3) 运行（token 只存在本机环境变量里，不会写进任何文件）：

     # PowerShell
     $env:GITHUB_TOKEN="github_pat_xxx"
     python push_via_api.py --owner fluoxtine2004 --repo douyin-favorites-organizer

     # bash / macOS / Linux
     GITHUB_TOKEN=github_pat_xxx python push_via_api.py --owner <you> --repo <repo>

   ⚠️ 不想把 token 放进环境变量（或 argv）时，用 `--token-file`：
     把 token 单独写进一个文件，用完删掉即可，token 不会出现在命令行历史里。

     echo github_pat_xxx > .gh_token          # 一行，注意不要有多余空格
     python push_via_api.py --owner <you> --repo <repo> --token-file .gh_token

可选参数
----
  --dir <path>     要推送的目录（默认：本脚本所在目录）
  --branch <name>  分支名（默认 main）
  --message <text> 提交信息
  --token-file <p> 从文件读 token（优先于 --token / GITHUB_TOKEN）
  --create         仓库不存在时顺手创建（**classic** token 勾了 repo 才行）
  --squash         孤儿提交强推，把历史压成一个干净 commit（新仓库首推时用）
  --public         配合 --create：建成公开仓库（默认私有）
  --description    配合 --create：写仓库描述
  --dry-run        只统计文件、不发请求（先自检用）
  --exclude <glob> 追加排除规则，可多次
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"

# 默认排除：个人数据、凭据、构建产物、媒体大文件
DEFAULT_EXCLUDE = [
    ".git/*", ".git",
    "data/*", "media/*", "vault/*", "dist/*", "models/*", "browser_profile/*",
    "产出/*", "logs/*", "_stale_notes/*",
    "__pycache__/*", "*/__pycache__/*", "*.pyc", "*.pyo",
    ".venv/*", "venv/*", "env/*", ".pytest_cache/*",
    "cookies.txt", "*.cookies",
    "seen_ids.json", "new_ids.json", "enriched.json", "excluded.json",
    "collect_index.json", "collect_order.json", "overrides.json", "llm_notes.json",
    "favorites*.json",
    "*.log", "*.mp4", "*.wav", "*.mp3", "*.m4a", "*.genie",
    ".DS_Store", "Thumbs.db",
]

# 需要保留可执行位的文件
EXECUTABLE = {"install.sh", "run.py", "push_via_api.py"}


def log(msg: str) -> None:
    print(msg, flush=True)


def api(token: str, method: str, path: str, body=None, *, ok=(200, 201, 204), soft=False):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "douyin-favorites-organizer-publisher")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
        if e.code in ok or soft:
            return e.code, payload
        raise SystemExit(
            f"\n❌ {method} {path} → HTTP {e.code}\n   {payload.get('message', raw)[:400]}"
            f"\n   文档: {payload.get('documentation_url', '')}"
        )


def is_excluded(rel: str, extra: list[str]) -> bool:
    for pat in DEFAULT_EXCLUDE + extra:
        p = pat.rstrip("/")
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, p) or rel == p:
            return True
        # 目录前缀排除（如 media/ 排除 media/x/y.jpg）
        if p and (rel == p or rel.startswith(p + "/")):
            return True
    return False


def collect(root: Path, extra_exclude: list[str]) -> list[Path]:
    files = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if is_excluded(rel, extra_exclude):
            continue
        files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="通过 GitHub REST API 推送整个目录（支持二进制）")
    ap.add_argument("--owner", required=True, help="GitHub 用户名或组织")
    ap.add_argument("--repo", required=True, help="仓库名（需已存在，建议先建空仓库）")
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parent), help="要推送的目录")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="chore: 首次发布（由 push_via_api.py 推送）")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""), help="留空则读 GITHUB_TOKEN")
    ap.add_argument("--token-file", default="", help="从文件读 token（优先于 --token / GITHUB_TOKEN）")
    ap.add_argument("--create", action="store_true",
                    help="仓库不存在时尝试创建（classic token 勾了 repo 才行；fine-grained 默认无此权限）")
    ap.add_argument("--squash", action="store_true",
                    help="用孤儿提交强推，把已有历史压成一个干净 commit（新仓库首推时用，可清掉引导提交）")
    ap.add_argument("--public", action="store_true", help="配合 --create：建成公开仓库（默认私有）")
    ap.add_argument("--description", default="", help="配合 --create：仓库描述")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--exclude", action="append", default=[], help="追加排除 glob，可多次")
    args = ap.parse_args()

    root = Path(args.dir).resolve()
    if not (root / "run.py").exists() and not (root / "README.md").exists():
        log(f"!! {root} 看起来不是项目根目录（没有 run.py / README.md）")
        return 2

    files = collect(root, args.exclude)
    total_bytes = sum(f.stat().st_size for f in files)
    log(f"=== 待推送 ===")
    log(f"目录   : {root}")
    log(f"目标   : {args.owner}/{args.repo}  (branch={args.branch})")
    log(f"文件数 : {len(files)}   合计 {total_bytes/1048576:.2f} MB")

    # 敏感路径自查（防止把个人数据推上去）
    # 只看**顶层**目录：demo/media/ 是仓库自带的脱敏示例，不算个人数据
    PERSONAL_TOP = {"data", "media", "vault", "browser_profile", "models",
                    "dist", "产出", "logs", "_stale_notes"}
    suspicious = []
    for f in files:
        parts = f.relative_to(root).as_posix().split("/")
        if len(parts) > 1 and parts[0] in PERSONAL_TOP:
            suspicious.append(f.relative_to(root).as_posix())
    if suspicious:
        log(f"!! 检测到疑似个人数据目录（顶层 {'/'.join(sorted(PERSONAL_TOP))}），已中止：")
        for s in suspicious[:8]:
            log(f"     {s}")
        if len(suspicious) > 8:
            log(f"     … 共 {len(suspicious)} 个")
        return 2

    if args.dry_run:
        for f in files[:40]:
            log(f"   {f.relative_to(root).as_posix()}  ({f.stat().st_size} B)")
        if len(files) > 40:
            log(f"   … 其余 {len(files)-40} 个")
        log("（--dry-run：未发任何请求）")
        return 0

    token = args.token
    if args.token_file:
        tf = Path(args.token_file)
        if not tf.exists():
            log(f"!! --token-file 指定的文件不存在：{tf}")
            return 2
        token = tf.read_text(encoding="utf-8").strip()
        log(f"   （token 读自 {tf.name}，{len(token)} 字符）")
    if not token:
        log("!! 缺少 token：设置环境变量 GITHUB_TOKEN，或用 --token-file 指定文件")
        return 2
    if len(token) < 20:
        log("!! token 看起来不完整（长度 < 20），请检查文件里是否只放了一行 token")
        return 2

    # 1) 校验身份 + 仓库是否存在
    st, me = api(token, "GET", "/user")
    log(f"\n① 身份：{me.get('login')}")

    st, repo = api(token, "GET", f"/repos/{args.owner}/{args.repo}", ok=(200, 404))
    if st == 404:
        if not args.create:
            log(f"!! 仓库 {args.owner}/{args.repo} 不存在。")
            log("   两个办法：① 到 https://github.com/new 建一个**空仓库**（不要勾 Add README）后重跑；")
            log("             ② 用 classic token（勾 repo）时加 --create，让本脚本顺手建。")
            return 2

        is_mine = (args.owner == me.get("login"))
        endpoint = "/user/repos" if is_mine else f"/orgs/{args.owner}/repos"
        log(f"   仓库不存在 → 尝试创建 {args.owner}/{args.repo}"
            f"（{'public' if args.public else 'private'}）…")
        st2, made = api(token, "POST", endpoint,
                        {"name": args.repo, "private": not args.public,
                         "description": args.description, "auto_init": False},
                        ok=(201, 403, 404, 422))
        if st2 == 201:
            log(f"   ✅ 已创建：{made.get('html_url')}")
            repo = made
        else:
            log(f"!! 创建失败：HTTP {st2}  {made.get('message', '')}")
            log("   多半是 token 没有建仓库的权限（fine-grained 默认就没有）。")
            log("   请到 https://github.com/new 手工建一个**空仓库**（不勾 Add README）后重跑本脚本。")
            return 2
    log(f"   仓库：{repo.get('full_name')}  private={repo.get('private')}  default={repo.get('default_branch')}")

    branch = args.branch or repo.get("default_branch") or "main"

    # 1.5) 空仓库引导
    # ⚠️ 完全空的仓库上 Git Data API（blobs/trees）会直接 409 "Git Repository is empty"，
    #    必须先用 Contents API 落一个文件把默认分支建出来。
    st, _ref = api(token, "GET", f"/repos/{args.owner}/{args.repo}/git/ref/heads/{branch}",
                   ok=(200, 404, 409))
    repo_empty = st != 200
    if repo_empty:
        log("   仓库是空的 → 先用 Contents API 建初始提交（之后会把它顶掉，只留一个干净 commit）…")
        boot = base64.b64encode(b"bootstrap; replaced by the real tree in the next step\n").decode("ascii")
        # ⚠️ Contents API 的「创建/更新文件」是 PUT（POST 会 404）
        api(token, "PUT", f"/repos/{args.owner}/{args.repo}/contents/.bootstrap",
            {"message": "chore: bootstrap empty repository", "content": boot})
        log("   ✅ 初始提交完成")

    # 2) 逐个文件建 blob（base64，二进制安全）
    log(f"\n② 上传 {len(files)} 个 blob…")
    tree = []
    for i, f in enumerate(files, 1):
        rel = f.relative_to(root).as_posix()
        content = base64.b64encode(f.read_bytes()).decode("ascii")
        for attempt in range(3):
            try:
                st, blob = api(token, "POST", f"/repos/{args.owner}/{args.repo}/git/blobs",
                               {"content": content, "encoding": "base64"})
                break
            except SystemExit:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        mode = "100755" if f.name in EXECUTABLE else "100644"
        tree.append({"path": rel, "mode": mode, "type": "blob", "sha": blob["sha"]})
        if i % 25 == 0 or i == len(files):
            log(f"   {i}/{len(files)}")

    # 3) 建 tree
    log("\n③ 建 tree…")
    st_t, t = api(token, "POST", f"/repos/{args.owner}/{args.repo}/git/trees",
                  {"tree": tree}, soft=True)
    skipped_wf: list[str] = []
    if st_t not in (200, 201):
        # 上传 .github/workflows/* 需要 token 带 `workflow` scope。
        # 没有该 scope 时 GitHub **故意返回 404**（而不是 403），很容易被误判成路径写错。
        wf = [e for e in tree if e["path"].startswith(".github/workflows/")]
        if not wf:
            raise SystemExit(f"\n❌ 建 tree 失败：HTTP {st_t}  {t.get('message', '')}")
        skipped_wf = [e["path"] for e in wf]
        log(f"   ⚠️ 提交 .github/workflows/* 被拒（GitHub 返回 {st_t}）")
        log("      原因：token 没有 `workflow` 权限。GitHub 对这种请求**故意返回 404**（非 403），")
        log("            classic token 需在 scopes 里勾上 `workflow`；fine-grained 需 Workflows=Read and write。")
        log(f"      本次跳过 {len(skipped_wf)} 个文件：{skipped_wf}")
        log("      → 稍后给 token 补上该权限后重跑，或在 GitHub 网页上手工添加这两个文件即可。")
        tree = [e for e in tree if not e["path"].startswith(".github/workflows/")]
        st_t, t = api(token, "POST", f"/repos/{args.owner}/{args.repo}/git/trees", {"tree": tree})
    log(f"   tree {t['sha'][:10]}  条目 {len(tree)}")

    # 4) 建 commit
    #    空仓库引导过的场景：用**孤儿提交**（无父）后强制覆盖 ref，最终只留一个干净的初始提交。
    st_ref, refs = api(token, "GET", f"/repos/{args.owner}/{args.repo}/git/ref/heads/{branch}",
                       ok=(200, 404, 409))
    ref_exists = (st_ref == 200)
    if repo_empty or args.squash:
        parents = []
    elif ref_exists and refs.get("object"):
        parents = [refs["object"]["sha"]]
    else:
        parents = []
    log(f"\n④ 建 commit（父提交 {len(parents)} 个）…")
    _, c = api(token, "POST", f"/repos/{args.owner}/{args.repo}/git/commits",
               {"message": args.message, "tree": t["sha"], "parents": parents})
    log(f"   commit {c['sha'][:10]}")

    # 5) 建/更新 ref
    if ref_exists:
        force = bool(repo_empty or args.squash)
        api(token, "PATCH", f"/repos/{args.owner}/{args.repo}/git/refs/heads/{branch}",
            {"sha": c["sha"], "force": force})
        log(f"\n⑤ 已{'强制覆盖（清掉引导提交）' if force else '更新'} {branch}（{c['sha'][:10]}）")
    else:
        api(token, "POST", f"/repos/{args.owner}/{args.repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": c["sha"]})
        log(f"\n⑤ 已创建 {branch}（{c['sha'][:10]}）")

    log(f"\n✅ 完成：https://github.com/{args.owner}/{args.repo}/tree/{branch}")
    if skipped_wf:
        log(f"\n⚠️  有 {len(skipped_wf)} 个文件没推上去（token 缺 `workflow` 权限）：")
        for p in skipped_wf:
            log(f"     {p}")
        log("    补上该权限后重跑本脚本即可（会在现有提交上叠加一个 commit）。")
    log("   下一步：网页上确认内容无误 → Settings 改 Public → 可选打 tag v1.0.0 发 Release。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
