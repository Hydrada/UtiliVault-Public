"""
UtiliVault — api_server.py
Mobile/field HTTP API. Lets the UtiliVault mobile app submit a tie card
(form fields + a clean house photo), have it drawn IMMEDIATELY (no Vision
call — the tech typed the data), uploaded to Drive folder 14, and previewed
/ edited from the phone.

Endpoints (all JSON unless noted):
  GET  /api/health                     liveness + config info
  GET  /api/cards                      list built cards (newest first)
  GET  /api/cards/<base>               one card: submitted fields + page URLs
  GET  /api/cards/<base>/pages/<n>     page preview PNG (1=front 2=back 3=photo)
  POST /api/cards                      create/regenerate a card
        multipart/form-data: any card fields + optional `photo` file
        optional `previous_base`: when an edit renamed the card (address/reg
        changed), the old card's local + Drive files are removed.

Run:
  py api_server.py                 (default 0.0.0.0:8791)
  py api_server.py --port 9000 --no-drive

Auth: if env var UTILIVAULT_API_KEY is set, every /api request must carry
header  X-Api-Key: <that value>.  (Set the same value in the mobile app.)
"""

import argparse
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from flask import Flask, jsonify, request, send_file, abort

import outbox
from config import CLEAN_DIR, DIGITAL_DIR, MANUAL_DIR, ensure_dirs
from draw_tiecard_back import card_filename_base, process_card

ensure_dirs()

app = Flask("utilivault_api")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024   # 32 MB uploads

API_KEY = os.getenv("UTILIVAULT_API_KEY", "").strip()
DIGITAL_FOLDER = "14 - Digital Cards (With Photo, Screen Only)"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

# Fields the mobile form may send, in card-dict key form. Everything is
# optional — blanks render as blanks, exactly like a half-filled paper card.
CARD_FIELDS = [
    "address", "property_label", "reg_no", "contractor", "date", "inspected_by",
    "main_material", "main_size", "main_label",
    "service_main_to_curb", "diameter_service", "service_curb_to_house",
    "left", "right", "vertical", "curb_to_house",
    "ref_label", "ref_number", "comments",
]

_drive_lock = threading.Lock()
_drive_cache = {"drive": None, "digital_id": None, "at": 0.0}
DRIVE_ENABLED = True


# --------------------------------------------------------------------------
# Drive helpers (reuse the watcher's client + replace-on-upload)
# --------------------------------------------------------------------------
def _drive():
    """Cached Drive client + folder-14 id. Re-resolved every 30 min."""
    if not DRIVE_ENABLED:
        return None, None
    with _drive_lock:
        if _drive_cache["drive"] and time.time() - _drive_cache["at"] < 1800:
            return _drive_cache["drive"], _drive_cache["digital_id"]
        from field_intake_watcher import get_drive, folder_id
        drive = get_drive()
        utili_id = folder_id(drive, "UtiliVault")
        digital_id = folder_id(drive, DIGITAL_FOLDER, utili_id) if utili_id else None
        _drive_cache.update(drive=drive, digital_id=digital_id, at=time.time())
        return drive, digital_id


def _drive_upload(path: Path) -> str:
    """Upload (replace) one TIF into folder 14. Returns a status string.

    On failure the card is queued in the outbox instead of being abandoned:
    the file already exists locally, and the watcher retries the upload once
    connectivity returns. Without this a card made during an internet outage
    would never reach Drive.
    """
    try:
        drive, digital_id = _drive()
        if not drive or not digital_id:
            if not DRIVE_ENABLED:
                return "drive-off"
            outbox.enqueue(path, DIGITAL_FOLDER, error="folder-14-not-found")
            return "queued"
        from field_intake_watcher import upload_tif
        upload_tif(drive, path, digital_id, replace=True)
        return "uploaded"
    except Exception as e:                                    # noqa: BLE001
        try:
            outbox.enqueue(path, DIGITAL_FOLDER, error=str(e))
            return "queued"
        except Exception:                                     # noqa: BLE001
            return f"error: {e}"


def _drive_delete(names: list[str]) -> None:
    """Best-effort delete of old files in folder 14 (after a rename-edit)."""
    try:
        drive, digital_id = _drive()
        if not drive or not digital_id:
            return
        for name in names:
            safe = name.replace("'", "\\'")
            hits = drive.files().list(
                q=f"name='{safe}' and '{digital_id}' in parents and trashed=false",
                fields="files(id)").execute()["files"]
            for h in hits:
                drive.files().delete(fileId=h["id"]).execute()
    except Exception as e:                                    # noqa: BLE001
        print(f"[WARN] Drive cleanup failed: {e}")


# --------------------------------------------------------------------------
# Local card store helpers
# --------------------------------------------------------------------------
def _meta_path(base: str) -> Path:
    return MANUAL_DIR / f"{base}_card.json"


def _page_files(base: str) -> list[Path]:
    """Existing page PNGs for a card, in page order (front, back, photo)."""
    pages = [MANUAL_DIR / f"{base}_front.png", MANUAL_DIR / f"{base}_back.png",
             DIGITAL_DIR / f"{base}_photo.png"]
    return [p for p in pages if p.exists()]


def _clean_photo_for(base: str) -> Path | None:
    for ext in IMAGE_EXTS:
        p = CLEAN_DIR / f"{base}{ext}"
        if p.exists():
            return p
    return None


def _card_summary(base: str) -> dict:
    meta = {}
    mp = _meta_path(base)
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            meta = {}
    back = MANUAL_DIR / f"{base}_back.png"
    # Watcher-built cards have no meta json; their base is "{address} {reg}".
    m = re.match(r"^(.*\S)\s+(\d{3,6})$", base)
    return {
        "base": base,
        "address": meta.get("address") or (m.group(1) if m else base),
        "reg_no": meta.get("reg_no") or (m.group(2) if m else ""),
        "date": meta.get("date") or "",
        "pages": len(_page_files(base)),
        "has_photo_page": (DIGITAL_DIR / f"{base}_photo.png").exists(),
        "updated": back.stat().st_mtime if back.exists() else 0,
        "source": meta.get("_source", "watcher"),
    }


def _delete_local(base: str) -> None:
    for d, patterns in ((MANUAL_DIR, ("_front.png", "_back.png", "_card.json", ".tif")),
                        (DIGITAL_DIR, ("_photo.png", "_DIGITAL.tif"))):
        for suffix in patterns:
            p = d / f"{base}{suffix}"
            if p.exists():
                p.unlink()
    photo = _clean_photo_for(base)
    if photo:
        photo.unlink()


_SAFE_BASE = re.compile(r"^[^<>:\"/\\|?*]+$")


def _check_base(base: str) -> str:
    base = base.strip()
    if not base or not _SAFE_BASE.match(base) or ".." in base:
        abort(400, "bad card id")
    return base


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
@app.before_request
def _auth():
    # OPTIONS = CORS preflight; browsers send it without custom headers, so
    # it must pass unauthenticated or web clients can never reach the API.
    if API_KEY and request.path.startswith("/api") and request.method != "OPTIONS":
        if request.headers.get("X-Api-Key", "") != API_KEY:
            return jsonify(error="bad or missing X-Api-Key"), 401
    return None


@app.errorhandler(Exception)
def _json_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    import traceback
    traceback.print_exc()
    return jsonify(error=str(e)), 500


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Api-Key"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return jsonify(ok=True, service="utilivault-api",
                   drive="on" if DRIVE_ENABLED else "off",
                   auth="key required" if API_KEY else "open",
                   cards=len(list(MANUAL_DIR.glob("*_back.png"))),
                   # Cards rendered locally but not yet pushed to Drive. Non-zero
                   # means the host lost internet; the watcher retries on its pass.
                   pending_sync=outbox.depth(),
                   stuck_sync=outbox.stuck_count(),
                   last_sync=outbox.last_sync())


@app.get("/api/cards")
def list_cards():
    bases = sorted({p.name[:-len("_back.png")] for p in MANUAL_DIR.glob("*_back.png")})
    cards = [_card_summary(b) for b in bases]
    cards.sort(key=lambda c: c["updated"], reverse=True)
    return jsonify(cards=cards)


@app.get("/api/cards/<base>")
def get_card(base):
    base = _check_base(base)
    pages = _page_files(base)
    if not pages:
        abort(404, "card not found")
    meta = {}
    if _meta_path(base).exists():
        meta = json.loads(_meta_path(base).read_text(encoding="utf-8"))
    return jsonify(
        base=base, fields={k: meta.get(k, "") for k in CARD_FIELDS},
        page_urls=[f"/api/cards/{base}/pages/{i+1}" for i in range(len(pages))],
        summary=_card_summary(base))


@app.get("/api/cards/<base>/pages/<int:n>")
def get_page(base, n):
    base = _check_base(base)
    pages = _page_files(base)
    if not 1 <= n <= len(pages):
        abort(404, "no such page")
    return send_file(pages[n - 1], mimetype="image/png", max_age=0)


@app.post("/api/cards")
def create_card():
    # Accept multipart/urlencoded form (photo + fields) or bare JSON.
    src = request.form if request.form else (request.get_json(silent=True) or {})

    card = {k: str(src.get(k, "")).strip() for k in CARD_FIELDS}
    card = {k: v for k, v in card.items() if v}
    if not (card.get("address") or card.get("reg_no")):
        abort(400, "need at least an address or a reg number")
    # Current field work is performed by Demo Contractor and inspected by Morgan. The
    # form may still intentionally provide a different non-blank value.
    card.setdefault("contractor", "Demo Contractor")
    card.setdefault("inspected_by", "Morgan")

    base = card_filename_base(card)
    previous_base = str(src.get("previous_base", "")).strip()

    # Edit renamed the card -> clear out the old name locally + in Drive.
    if previous_base and previous_base != base and _SAFE_BASE.match(previous_base):
        old_photo = _clean_photo_for(previous_base)   # reuse old photo if none sent
        reuse = None
        if old_photo and "photo" not in request.files:
            reuse = CLEAN_DIR / f"{base}{old_photo.suffix.lower()}"
            reuse.write_bytes(old_photo.read_bytes())
        _delete_local(previous_base)
        _drive_delete([f"{previous_base}_DIGITAL.tif", f"{previous_base}.tif"])

    # Save the uploaded clean photo (it becomes page 3 of the digital card).
    display_photo = None
    up = request.files.get("photo")
    if up and up.filename:
        ext = Path(up.filename).suffix.lower() or ".jpg"
        if ext not in IMAGE_EXTS:
            abort(400, f"unsupported photo type {ext}")
        for old_ext in IMAGE_EXTS:                     # one photo per card
            old = CLEAN_DIR / f"{base}{old_ext}"
            if old.exists():
                old.unlink()
        display_photo = CLEAN_DIR / f"{base}{ext}"
        up.save(display_photo)
    else:
        display_photo = _clean_photo_for(base)         # regenerate keeps photo

    # Draw the card RIGHT NOW — no Vision call, the tech typed the data.
    paths = process_card(dict(card), front_path=None, folder_name=None,
                         photo_path=None, display_photo_path=display_photo)

    # Remember what was submitted so Edit can prefill the form later.
    card["_source"] = "mobile"
    _meta_path(base).write_text(json.dumps(card, indent=2), encoding="utf-8")

    # Push the card to Drive folder 14. Always under the {base}_DIGITAL.tif
    # name so photo/no-photo regenerations of the same card replace cleanly.
    if paths.get("digital_tif"):
        to_drive = Path(paths["digital_tif"])
    else:
        to_drive = DIGITAL_DIR / f"{base}_DIGITAL.tif"
        to_drive.write_bytes(Path(paths["tif"]).read_bytes())
    drive_status = _drive_upload(to_drive)

    pages = _page_files(base)
    return jsonify(
        base=base,
        pages=len(pages),
        page_urls=[f"/api/cards/{base}/pages/{i+1}" for i in range(len(pages))],
        drive=drive_status,
        printable_tif=str(paths.get("tif", "")),
        digital_tif=str(paths.get("digital_tif", "")),
    ), 201


def main():
    global DRIVE_ENABLED
    p = argparse.ArgumentParser(description="UtiliVault mobile/field API server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--no-drive", action="store_true",
                   help="Skip all Drive uploads (local-only testing)")
    args = p.parse_args()
    DRIVE_ENABLED = not args.no_drive

    print(f"[API] UtiliVault field API on http://{args.host}:{args.port}")
    print(f"[API] Cards dir: {MANUAL_DIR}")
    print(f"[API] Drive upload: {'ON -> ' + DIGITAL_FOLDER if DRIVE_ENABLED else 'OFF'}")
    print(f"[API] Auth: {'X-Api-Key required' if API_KEY else 'open (set UTILIVAULT_API_KEY to lock)'}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
