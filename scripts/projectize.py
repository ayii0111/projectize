#!/usr/bin/env python3
"""projectize：把當前 CC session 轉成 ~/cc-projects 下的正式專案。

子命令：
  context                      印出當前 session 資訊與本 session 動過的檔案（JSON）
  run --name N [--files ...]   搬檔案 → 背景等 CC 結束後遷移 session 資料 → 結束 CC
  finish <plan.json>           （內部用）背景 worker：等 CC 結束後搬 session 資料

只使用 Python 標準庫，相容 Python 3.9+。
"""
import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
CLAUDE_DIR = Path(_config_dir) if _config_dir else Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"
TARGET_ROOT = Path(os.environ.get("PROJECTIZE_ROOT") or Path.home() / "cc-projects")
DATA_DIR = CLAUDE_DIR / "projectize"
LOG_FILE = DATA_DIR / "projectize.log"
BACKUP_DIR = DATA_DIR / "backups"

EDIT_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)?$")
MAX_ENCODED_LEN = 200


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def log(msg: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{now_iso()}] {msg}\n")
    except OSError:
        pass


def die(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def encode_path(path: str) -> str:
    """CC 的專案目錄命名：非英數字元一律換成 '-'。"""
    return re.sub(r"[^a-zA-Z0-9]", "-", path)


def find_session_file(sid: str) -> Optional[Path]:
    """優先找 shell cwd 對應的 slug 目錄；找不到（例如 cd 過、路徑過長被截斷）再用 glob。"""
    enc = encode_path(os.getcwd())
    if len(enc) <= MAX_ENCODED_LEN:
        p = PROJECTS_DIR / enc / f"{sid}.jsonl"
        if p.is_file():
            return p
    hits = sorted(PROJECTS_DIR.glob(f"*/{sid}.jsonl"))
    return hits[0] if len(hits) == 1 else None


def session_cwd(sf: Path) -> Optional[str]:
    """session 的原始工作目錄：紀錄中第一個 cwd 欄位。"""
    for o in iter_jsonl(sf):
        cwd = o.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return None


def session_env():
    """回傳 (sid, CC pid, session 檔, 原始 cwd)。"""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    pid = os.environ.get("CLAUDE_PID")
    if not sid or not pid:
        die("找不到 CLAUDE_CODE_SESSION_ID / CLAUDE_PID，請在 CC session 內執行")
    sf = find_session_file(sid)
    if not sf:
        die(f"找不到 session 檔 {sid}.jsonl")
    cwd = session_cwd(sf)
    if not cwd:
        die("session 紀錄中找不到 cwd")
    return sid, int(pid), sf, cwd


def iter_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def touched_files(session_file: Path, cwd: str) -> List[str]:
    """從 session（含 subagent）紀錄解析 Write/Edit 過、位於 cwd 底下且仍存在的檔案。"""
    sources = [session_file]
    sub = session_file.with_suffix("")
    if sub.is_dir():
        sources += sorted(sub.rglob("*.jsonl"))
    root = Path(cwd).resolve()
    seen, out = set(), []
    for src in sources:
        for o in iter_jsonl(src):
            content = (o.get("message") or {}).get("content")
            if o.get("type") != "assistant" or not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                key = EDIT_TOOLS.get(c.get("name"))
                fp = (c.get("input") or {}).get(key) if key else None
                if not fp or fp in seen:
                    continue
                seen.add(fp)
                p = Path(fp)
                try:
                    rel = p.resolve().relative_to(root)
                except ValueError:
                    continue  # 不在 cwd 底下（例如 ~/.claude、scratchpad）
                if p.is_file():
                    out.append(str(rel))
    return sorted(out)


# ---------------------------------------------------------------- context

def cmd_context(_args) -> None:
    sid, pid, sf, cwd = session_env()
    others = [p.stem for p in sf.parent.glob("*.jsonl") if p.stem != sid]
    existing = []
    if TARGET_ROOT.is_dir():
        for d in TARGET_ROOT.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                existing.append(d.name)
    print(json.dumps({
        "ok": True,
        "session_id": sid,
        "cwd": cwd,
        "session_file": str(sf),
        "target_root": str(TARGET_ROOT),
        "existing_projects": sorted(existing),
        "touched_files": touched_files(sf, cwd),
        "other_sessions_in_cwd": len(others),
        "is_git_repo": (Path(cwd) / ".git").exists(),
    }, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- run

def cmd_run(args) -> None:
    sid, pid, sf, cwd = session_env()
    name = args.name.strip()
    if not NAME_RE.match(name):
        die(f"名稱不合法：{name}（只能用小寫英數與 -，最多一層 /）")
    target = TARGET_ROOT / name
    if target.exists() and any(target.iterdir()):
        die(f"目標目錄已存在且非空：{target}")
    if Path(cwd).resolve() == target.resolve():
        die("目標目錄就是當前目錄，不需要搬移")

    allowed = set(touched_files(sf, cwd))
    files = args.files or []
    bad = [f for f in files if f not in allowed]
    if bad:
        die(f"這些檔案不在本 session 動過的清單內：{bad}")

    plan = {
        "session_id": sid, "claude_pid": pid, "old_cwd": cwd,
        "new_cwd": str(target), "session_file": str(sf), "files": files,
        "tty": tty_of(pid),
    }
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "plan": plan}, ensure_ascii=False, indent=2))
        return

    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for rel in files:
        src, dst = Path(cwd) / rel, target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(rel)
        prune_empty_dirs(src.parent, Path(cwd))
    log(f"run sid={sid} old={cwd} new={target} moved={moved}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    plan_file = DATA_DIR / f"plan-{sid}.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "finish", str(plan_file)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(json.dumps({"ok": True, "new_cwd": str(target), "moved_files": moved,
                      "resume": resume_cmd(str(target), sid)}, ensure_ascii=False, indent=2))
    sys.stdout.flush()


def prune_empty_dirs(d: Path, stop: Path) -> None:
    """檔案搬走後，往上刪掉因此變空的目錄（不超過 cwd）。"""
    d, stop = d.resolve(), stop.resolve()
    while d != stop and stop in d.parents:
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


def tty_of(pid: int) -> Optional[str]:
    try:
        t = subprocess.run(["ps", "-o", "tty=", "-p", str(pid)], capture_output=True,
                           text=True).stdout.strip()
    except OSError:
        return None
    return f"/dev/{t}" if t and t not in ("??", "?") else None


def resume_cmd(new_cwd: str, sid: str) -> str:
    return f"cd {shlex.quote(new_cwd)} && claude --resume {sid}"


# ---------------------------------------------------------------- finish（背景 worker）

def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cmd_finish(args) -> None:
    plan_file = Path(args.plan)
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    pid = plan["claude_pid"]
    # 留一點時間讓 tool 結果寫進 session 檔，再結束 CC
    time.sleep(1.5)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(300):  # 最多等 60 秒
        if not alive(pid):
            break
        time.sleep(0.2)
    else:
        log(f"finish abort: CC pid={pid} 未結束")
        notify(plan, "⚠️ projectize：CC 未結束，session 資料未遷移，"
                     f"請手動重跑：python3 {Path(__file__).resolve()} finish {plan_file}")
        return
    time.sleep(0.5)
    try:
        migrate(plan)
    except Exception as e:  # noqa: BLE001 — 背景程序，任何錯誤都要留紀錄
        log(f"finish error: {e!r}")
        notify(plan, f"⚠️ projectize 遷移失敗：{e}（備份在 {BACKUP_DIR}）")
        return
    plan_file.unlink(missing_ok=True)
    cmd = resume_cmd(plan["new_cwd"], plan["session_id"])
    try:
        subprocess.run(["pbcopy"], input=cmd, text=True, check=False)
    except OSError:
        pass
    notify(plan, f"✓ projectize 完成：{plan['new_cwd']}\n  接續指令（已複製到剪貼簿）：\n  {cmd}")


def migrate(plan: dict) -> None:
    sid, old_cwd, new_cwd = plan["session_id"], plan["old_cwd"], plan["new_cwd"]
    sf = Path(plan["session_file"])
    old_dir = sf.parent
    new_dir = PROJECTS_DIR / encode_path(new_cwd)
    new_dir.mkdir(parents=True, exist_ok=True)

    backup = BACKUP_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{sid[:8]}"
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sf, backup / sf.name)
    if HISTORY_FILE.is_file():
        shutil.copy2(HISTORY_FILE, backup / HISTORY_FILE.name)

    # 1. session 檔與同名目錄（subagents、tool-results）
    new_sf = new_dir / sf.name
    shutil.move(str(sf), str(new_sf))
    sub = old_dir / sid
    if sub.is_dir():
        shutil.move(str(sub), str(new_dir / sid))

    # 2. 改寫 session 紀錄中的 cwd 欄位
    rewrite_cwd(new_sf, old_cwd, new_cwd)
    if (new_dir / sid).is_dir():
        for p in (new_dir / sid).rglob("*.jsonl"):
            rewrite_cwd(p, old_cwd, new_cwd)

    # 3. memory/ 用複製的，原專案保留
    mem = old_dir / "memory"
    if mem.is_dir() and not (new_dir / "memory").exists():
        shutil.copytree(mem, new_dir / "memory")

    # 4. history.jsonl：只改本 session 的輸入歷史
    rewrite_history(sid, old_cwd, new_cwd)
    log(f"migrate ok sid={sid} {old_dir} -> {new_dir} backup={backup}")


def rewrite_cwd(path: Path, old: str, new: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    for line in lines:
        if '"cwd"' in line:
            try:
                o = json.loads(line)
                if o.get("cwd") == old:
                    o["cwd"] = new
                    line = json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n"
            except ValueError:
                pass
        out.append(line)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(out), encoding="utf-8")
    os.replace(tmp, path)


def rewrite_history(sid: str, old: str, new: str) -> None:
    """其他 CC 可能同時在 append，改寫前後比對大小，有變動就重來。"""
    if not HISTORY_FILE.is_file():
        return
    for _ in range(10):
        before = HISTORY_FILE.stat().st_size
        out, changed = [], 0
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                if sid in line:
                    try:
                        o = json.loads(line)
                        if o.get("sessionId") == sid and o.get("project") == old:
                            o["project"] = new
                            line = json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n"
                            changed += 1
                    except ValueError:
                        pass
                out.append(line)
        if not changed:
            return
        tmp = HISTORY_FILE.with_name(HISTORY_FILE.name + ".projectize-tmp")
        tmp.write_text("".join(out), encoding="utf-8")
        if HISTORY_FILE.stat().st_size == before:
            os.replace(tmp, HISTORY_FILE)
            return
        tmp.unlink(missing_ok=True)
        time.sleep(0.2)
    log("history.jsonl 持續變動，略過改寫")


def notify(plan: dict, msg: str) -> None:
    log(msg.replace("\n", " "))
    tty = plan.get("tty")
    if not tty:
        return
    try:
        with open(tty, "w") as t:
            t.write(f"\n{msg}\n")
    except OSError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(prog="projectize")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("context").set_defaults(fn=cmd_context)
    r = sp.add_parser("run")
    r.add_argument("--name", required=True)
    r.add_argument("--files", nargs="*")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_run)
    f = sp.add_parser("finish")
    f.add_argument("plan")
    f.set_defaults(fn=cmd_finish)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
