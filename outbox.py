"""
UtiliVault — outbox.py
Durable retry queue for Drive uploads that failed because the host had no
internet.

Why this exists: the pipeline is already local-first — a card submitted from
the field app renders to local disk whether or not Drive is reachable, so the
card itself is never lost. But a failed Drive upload used to return an error
string and was never retried, so a card made during an outage stayed local
forever and the archive silently drifted out of step with Drive.

Design notes:

  * One JSON file per queued upload, in WORK_ROOT/outbox/. The API server
    (writer) and the watcher (drainer) are SEPARATE PROCESSES, so a single
    shared queue file would race — an append could be lost when the drainer
    rewrote the file. A directory of independent entries has no such race:
    enqueue creates a file, drain deletes one.
  * Uploads go through upload_tif(replace=True), which is idempotent, so a
    retry can never produce a duplicate in Drive.
  * Entries carry an exponential backoff so a long outage does not hammer the
    network every 60 seconds.
  * Entries that exhaust their attempts are kept, not deleted — a stuck card
    must stay visible rather than disappear silently.
"""
import json
import os
import time
import uuid
from pathlib import Path

from config import WORK_ROOT

OUTBOX_DIR = WORK_ROOT / "outbox"
STATE_FILE = WORK_ROOT / "outbox_state.json"

MAX_ATTEMPTS = 12           # ~ covers a multi-hour outage with backoff below
BASE_BACKOFF_S = 60         # first retry one minute after failure
MAX_BACKOFF_S = 3600        # never wait longer than an hour between tries


# --------------------------------------------------------------------------
# Queue primitives
# --------------------------------------------------------------------------
def _ensure_dir() -> Path:
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    return OUTBOX_DIR


def _write_atomic(path: Path, payload: dict) -> None:
    """Write via temp + replace so a reader never sees a half-written entry."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def enqueue(local_path: Path, folder: str, drive_name: str | None = None,
            error: str = "") -> Path:
    """Queue one file for a later upload attempt. Returns the entry path."""
    _ensure_dir()
    local_path = Path(local_path)
    entry = {
        "local_path": str(local_path),
        "folder": folder,                       # Drive folder NAME, resolved at drain
        "drive_name": drive_name or local_path.name,
        "queued_at": time.time(),
        "attempts": 0,
        "last_error": str(error)[:500],
        "next_attempt_at": 0.0,                 # 0 = eligible immediately
    }
    name = f"{int(entry['queued_at'])}_{uuid.uuid4().hex[:8]}.json"
    path = OUTBOX_DIR / name
    _write_atomic(path, entry)
    return path


def _entry_files() -> list[Path]:
    if not OUTBOX_DIR.exists():
        return []
    return sorted(OUTBOX_DIR.glob("*.json"))


def entries() -> list[dict]:
    """All queued entries (for status display). Unreadable files are skipped."""
    out = []
    for f in _entry_files():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            d["_file"] = f.name
            out.append(d)
        except Exception:                                     # noqa: BLE001
            continue
    return out


def depth() -> int:
    """How many uploads are waiting. Cheap — used by /api/health."""
    return len(_entry_files())


def stuck_count() -> int:
    return sum(1 for e in entries() if e.get("attempts", 0) >= MAX_ATTEMPTS)


def last_sync() -> float | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_sync")
    except Exception:                                         # noqa: BLE001
        return None


def _mark_sync() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(STATE_FILE, {"last_sync": time.time()})
    except Exception:                                         # noqa: BLE001
        pass


def _backoff(attempts: int) -> float:
    return min(BASE_BACKOFF_S * (2 ** max(attempts - 1, 0)), MAX_BACKOFF_S)


# --------------------------------------------------------------------------
# Draining
# --------------------------------------------------------------------------
def drain(drive, verbose: bool = True) -> dict:
    """
    Attempt every eligible queued upload. Safe to call on every watcher pass.

    Returns a summary dict: {"sent": n, "failed": n, "skipped": n, "gone": n}.
    Never raises — a drain failure must not take down the watcher loop.
    """
    from field_intake_watcher import folder_id, upload_tif

    summary = {"sent": 0, "failed": 0, "skipped": 0, "gone": 0}
    files = _entry_files()
    if not files:
        return summary

    now = time.time()
    folder_cache: dict[str, str | None] = {}
    utili_id = None

    for f in files:
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            continue

        if entry.get("next_attempt_at", 0) > now:
            summary["skipped"] += 1
            continue

        local = Path(entry["local_path"])
        if not local.exists():
            # The source file is gone (card deleted or renamed) — drop the
            # entry rather than retrying something that can never succeed.
            if verbose:
                print(f"  [Outbox] source missing, dropping: {local.name}")
            f.unlink(missing_ok=True)
            summary["gone"] += 1
            continue

        folder_name = entry["folder"]
        if folder_name not in folder_cache:
            if utili_id is None:
                utili_id = folder_id(drive, "UtiliVault")
            folder_cache[folder_name] = (
                folder_id(drive, folder_name, utili_id) if utili_id else None
            )
        dest_id = folder_cache[folder_name]

        try:
            if not dest_id:
                raise RuntimeError(f"folder not found: {folder_name}")
            # replace=True keeps this idempotent: a retry overwrites rather
            # than adding a second copy.
            upload_tif(drive, local, dest_id, replace=True)
            f.unlink(missing_ok=True)
            summary["sent"] += 1
            if verbose:
                print(f"  [Outbox] synced {local.name} -> {folder_name}")
        except Exception as e:                                # noqa: BLE001
            entry["attempts"] = entry.get("attempts", 0) + 1
            entry["last_error"] = str(e)[:500]
            entry["next_attempt_at"] = now + _backoff(entry["attempts"])
            _write_atomic(f, entry)
            summary["failed"] += 1
            if verbose and entry["attempts"] >= MAX_ATTEMPTS:
                print(f"  [Outbox] STUCK after {entry['attempts']} tries: "
                      f"{local.name} — {entry['last_error']}")

    if summary["sent"]:
        _mark_sync()
    return summary


def summary_line() -> str:
    """One-line human status, for CLI output."""
    d, s = depth(), stuck_count()
    if not d:
        ts = last_sync()
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "never"
        return f"Outbox empty (last sync: {when})"
    return f"Outbox: {d} waiting" + (f", {s} STUCK" if s else "")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Inspect or drain the UtiliVault upload outbox")
    p.add_argument("--drain", action="store_true", help="Attempt all queued uploads now")
    p.add_argument("--list", action="store_true", help="Show queued entries")
    args = p.parse_args()

    print(summary_line())
    if args.list:
        for e in entries():
            nxt = e.get("next_attempt_at", 0)
            due = time.strftime("%H:%M:%S", time.localtime(nxt)) if nxt else "now"
            print(f"  - {Path(e['local_path']).name} -> {e['folder']} "
                  f"(attempts={e.get('attempts', 0)}, next={due})")
            if e.get("last_error"):
                print(f"      last error: {e['last_error']}")
    if args.drain:
        from field_intake_watcher import get_drive
        print("[Outbox] Draining...")
        print(" ", drain(get_drive()))
        print(summary_line())
