"""Platform-neutral runtime safety and health state for the Drive watcher."""

from __future__ import annotations

import argparse
import json
import os
import socket
import tempfile
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import config


_RUNTIME_ROOT = getattr(config, "ROOT", config.PROJECT_ROOT)
STATE_DIR = Path(os.getenv("UTILIVAULT_STATE_DIR", str(_RUNTIME_ROOT / "state")))
STATE_FILE = STATE_DIR / "watcher-status.json"
LOCK_FILE = STATE_DIR / "watcher.lock"


class AlreadyRunning(RuntimeError):
    """Raised when another watcher process owns the host-local lock."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, value: dict) -> None:
    """Durably replace a JSON file without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


@contextmanager
def single_instance(path: Path = LOCK_FILE) -> Iterator[None]:
    """Hold a non-blocking advisory lock for one watcher process per host."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            if handle.tell() == 0 and path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise AlreadyRunning(str(path)) from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise AlreadyRunning(str(path)) from exc
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def emit_event(event: str, **fields) -> None:
    """Write one structured event without card addresses or credential data."""
    payload = {"timestamp": _utc_now(), "event": event, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


class WatcherState:
    """Small atomic status ledger; Drive remains the source of truth."""

    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.data = self._load()
        self.run_id: str | None = None
        self.errors = 0
        self.processed = 0

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.data.setdefault("schema_version", 1)
        atomic_write_json(self.path, self.data)

    def begin_run(self, mode: str) -> str:
        self.errors = 0
        self.processed = 0
        self.run_id = uuid.uuid4().hex
        self.data["last_run"] = {
            "run_id": self.run_id,
            "mode": mode,
            "host": socket.gethostname(),
            "started_at": _utc_now(),
            "finished_at": None,
            "status": "running",
            "processed": 0,
        }
        self._save()
        emit_event("run_started", run_id=self.run_id, mode=mode)
        return self.run_id

    def item(self, file_id: str, source: str, stage: str, *, version: str | None = None,
             error_type: str | None = None) -> None:
        items = self.data.setdefault("items", {})
        record = {
            "source": source,
            "stage": stage,
            "updated_at": _utc_now(),
        }
        if version:
            record["drive_version"] = str(version)
        if error_type:
            record["error_type"] = error_type
        if stage == "failed":
            self.errors += 1
        items[file_id] = record
        # Bound local status growth; archived source files no longer appear in intake.
        if len(items) > 1000:
            oldest = sorted(items, key=lambda key: items[key].get("updated_at", ""))
            for key in oldest[: len(items) - 1000]:
                del items[key]
        self._save()
        emit_event(
            "item_transition",
            run_id=self.run_id,
            file_id=file_id,
            source=source,
            stage=stage,
            error_type=error_type,
        )

    def finish_run(self, status: str, processed: int = 0,
                   error_type: str | None = None) -> None:
        run = self.data.setdefault("last_run", {})
        run.update(
            finished_at=_utc_now(),
            status=status,
            processed=processed,
        )
        if error_type:
            run["error_type"] = error_type
        else:
            run.pop("error_type", None)
        self._save()
        emit_event(
            "run_finished",
            run_id=self.run_id,
            status=status,
            processed=processed,
            error_type=error_type,
        )


def read_health(path: Path = STATE_FILE, max_age_seconds: int = 900) -> tuple[dict, bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"healthy": False, "reason": "status_missing_or_invalid"}, False
    run = data.get("last_run") or {}
    finished = run.get("finished_at")
    if not finished:
        return {"healthy": False, "reason": "no_finished_run", "last_run": run}, False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(finished.replace("Z", "+00:00"))).total_seconds()
    except (TypeError, ValueError):
        return {"healthy": False, "reason": "invalid_finished_at", "last_run": run}, False
    healthy = run.get("status") == "success" and age <= max_age_seconds
    return {
        "healthy": healthy,
        "reason": "ok" if healthy else ("last_run_failed" if run.get("status") != "success" else "last_run_stale"),
        "age_seconds": round(age),
        "last_run": run,
    }, healthy


def notify_if_configured(payload: dict) -> bool:
    url = os.getenv("UTILIVAULT_ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return False
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return 200 <= response.status < 300


def main() -> int:
    parser = argparse.ArgumentParser(description="UtiliVault watcher health monitor")
    parser.add_argument("command", choices=("status", "monitor"))
    parser.add_argument("--max-age", type=int, default=900, help="Maximum healthy age in seconds")
    args = parser.parse_args()
    payload, healthy = read_health(max_age_seconds=args.max_age)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.command == "monitor" and not healthy:
        try:
            notify_if_configured(payload)
        except Exception as exc:  # monitoring must still return unhealthy
            emit_event("alert_failed", error_type=type(exc).__name__)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
