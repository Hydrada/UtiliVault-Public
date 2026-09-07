"""
UtiliVault — field_intake_watcher.py
Watches the Drive "11 - Field Intake" folder and the Demo Contractor Jobs project intake
folder for curb photos dropped from the field (phone Google Drive app). For
each new photo:
  1. Downloads it
  2. Reads the house appearance + any handwritten measurements (Claude Vision)
  3. Draws the tie-card back page (recognizable house + ties + measurements)
  4. Uploads the finished card to "10 - Manually Drawn"
  5. Moves the original photo to "8 - Originals" so the intake folder stays clean

Run this on the always-on home PC (it polls on an interval). The technician
never touches a command line — they drop a photo from their phone and the
finished card appears in Drive minutes later.

Usage:
  py field_intake_watcher.py                 # poll every 60s, forever
  py field_intake_watcher.py --once          # single pass then exit
  py field_intake_watcher.py --interval 120  # custom poll interval (seconds)
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, str(Path(__file__).parent))
from draw_tiecard_back import apply_photo, process_card
from drive_document_completion import sync_document_completion, sync_project_documents
from drive_reference_docs import load_reference_index

from config import FIELD_WORK_DIR as WORK_DIR
from cloud_runtime import AlreadyRunning, WatcherState, emit_event, single_instance
from google_drive_auth import get_google_docs, get_google_drive
WORK_DIR.mkdir(parents=True, exist_ok=True)

INTAKE_FOLDER = "11 - Field Intake (Drop Curb Photos Here)"
OUTPUT_FOLDER = "12 - Field Intake Completed"
ORIGINALS_FOLDER = "8 - Originals (Processed, For Cross-Reference)"
DIGITAL_FOLDER = "14 - Digital Cards (With Photo, Screen Only)"
CLEAN_INPUT_FOLDER = "15 - Clean Display Photos (Drop Here)"
PROJECT_INTAKE_FOLDER = "Tiecard Picture Intake"
PROJECT_INTAKE_FOLDER_ID = os.getenv(
    "PROJECT_PICTURE_INTAKE_FOLDER_ID",
    "YOUR_PROJECT_PICTURE_INTAKE_FOLDER_ID",
)
DEMO_PROJECTS_FOLDER_ID = os.getenv(
    "DEMO_PROJECTS_FOLDER_ID",
    "YOUR_PROJECTS_FOLDER_ID",
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def get_drive():
    return get_google_drive()


def folder_id(drive, name, parent=None):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent:
        q += f" and '{parent}' in parents"
    r = drive.files().list(q=q, fields="files(id)").execute()
    return r["files"][0]["id"] if r["files"] else None


def download(drive, file_id, dest):
    req = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    dest.write_bytes(buf.read())


def move_file(drive, file_id, new_parent, old_parent):
    drive.files().update(fileId=file_id, addParents=new_parent,
                         removeParents=old_parent, fields="id").execute()


def upload_tif(drive, path: Path, folder_id: str, replace: bool = True):
    """
    Upload a finished TIF into the given Drive folder. With replace=True (the
    default), update the primary same-name Drive file in place. Only redundant
    older duplicates are trashed after the replacement succeeds.
    """
    from googleapiclient.http import MediaFileUpload
    dupes = []
    if replace:
        safe = path.name.replace("'", "\\'")
        dupes = drive.files().list(
            q=f"name='{safe}' and '{folder_id}' in parents and trashed=false",
            fields="files(id,createdTime)",
            orderBy="createdTime",
        ).execute()["files"]
    media = MediaFileUpload(str(path), mimetype="image/tiff", resumable=True)
    if dupes:
        up = drive.files().update(
            fileId=dupes[0]["id"],
            body={"name": path.name},
            media_body=media,
            fields="id,name",
        ).execute()
        for duplicate in dupes[1:]:
            drive.files().update(
                fileId=duplicate["id"], body={"trashed": True}, fields="id"
            ).execute()
        action = "Updated"
    else:
        meta = {"name": path.name, "parents": [folder_id]}
        up = drive.files().create(
            body=meta, media_body=media, fields="id,name"
        ).execute()
        action = "Uploaded"
    print(f"  [Drive] {action} TIFF: {up['name']}")
    return up


def process_intake_once(drive, intake_id, originals_id, digital_id=None,
                        reference_folder_id=None, docs=None, output_id=None,
                        state: WatcherState | None = None) -> int:
    r = drive.files().list(
        q=f"'{intake_id}' in parents and trashed=false",
        fields="files(id,name,mimeType,version)", pageSize=200
    ).execute()
    files = [f for f in r["files"]
             if Path(f["name"]).suffix.lower() in IMAGE_EXTS]

    if not files:
        return 0

    reference_index = None
    if reference_folder_id:
        try:
            reference_index = load_reference_index(drive, reference_folder_id)
            print(f"[Reference] Loaded {len(reference_index.by_address)} project address(es)")
        except Exception as exc:
            print(f"[WARN] Could not load Demo Contractor project documents: {exc}")

    print(f"[Intake] {len(files)} new photo(s) to process")
    for f in files:
        name = f["name"]
        print(f"\n{'='*60}\n[Field Card] {name}\n{'='*60}")
        local = WORK_DIR / name
        try:
            if state:
                state.item(f["id"], "field_intake", "download", version=f.get("version"))
            download(drive, f["id"], local)
            # The card starts empty; the photo supplies house + measurements.
            # The reg no must come from the photo itself ("REG ####"). The
            # filename stem is only a last-resort fallback, applied inside
            # process_card when nothing is written on the photo — never
            # pre-seed reg_no here or the photo-read value gets discarded.
            card = {"_reg_fallback": Path(name).stem}
            if reference_index:
                # Read the photo once, then use its address/registry to find the
                # matching street document before rendering the card.
                card = apply_photo(card, local)
                card["_photo_path"] = str(local)
                reference_index.enrich(card)
                paths = process_card(card, front_path=None,
                                     folder_name=None, photo_path=None)
            else:
                paths = process_card(card, front_path=None,
                                     folder_name=None, photo_path=local)
            # Also build a print-ready 6x4 PDF and file it to folder 13
            try:
                from make_print_pdf import make_pdf, upload_pdf, PDF_DIR
                from draw_tiecard_back import card_filename_base
                fp = paths.get("front_png"); bp = paths.get("back_png")
                if fp and bp:
                    base = card_filename_base(card)
                    pdf_path = PDF_DIR / f"{base}_PRINT.pdf"
                    make_pdf(fp, bp, pdf_path)
                    upload_pdf(pdf_path)
            except Exception as e:
                print(f"  [WARN] print PDF step: {e}")
            if output_id:
                upload_tif(drive, paths["tif"], output_id)
            if digital_id:
                dtif = paths.get("digital_tif")
                if not dtif:
                    raise RuntimeError("required digital TIFF was not rendered")
                upload_tif(drive, dtif, digital_id)
            if docs and card.get("_reference_document_id") and card.get("address"):
                promoted = sync_document_completion(
                    docs,
                    card["_reference_document_id"],
                    {card["address"]: "Yes"},
                )
                print(f"  [Document] Pictures: Yes for {card['address']}")
                if promoted:
                    print(f"  [Document] Moved to Completed: {', '.join(promoted)}")
            # Archive the original photo out of the intake folder
            move_file(drive, f["id"], originals_id, intake_id)
            if state:
                state.item(f["id"], "field_intake", "archived", version=f.get("version"))
            print(f"  [Done] Card filed; print PDF filed; original moved to Originals.")
        except Exception as e:
            if state:
                state.item(
                    f["id"], "field_intake", "failed",
                    version=f.get("version"), error_type=type(e).__name__,
                )
            print(f"  [ERROR] {name}: {e}")
    return len(files)


def process_display_photos_once(drive, clean_id, digital_id, archive_id,
                                state: WatcherState | None = None) -> int:
    """
    Second pass: match CLEAN display photos (address in red) dropped in folder
    15 to cards already built from the annotated field photos, rebuild the
    digital 3-page TIF with the clean photo, and replace the card in folder 14.
    A photo with no matching card yet is left in place to retry next pass.
    """
    from match_display_photos import (
        read_address, index_existing_cards, find_card, _card_from_base,
    )
    from draw_tiecard_back import render_photo_page, save_digital_outputs
    from PIL import Image

    r = drive.files().list(
        q=f"'{clean_id}' in parents and trashed=false",
        fields="files(id,name,mimeType,version)", pageSize=200).execute()
    files = [f for f in r["files"]
             if Path(f["name"]).suffix.lower() in IMAGE_EXTS]
    if not files:
        return 0

    cards = index_existing_cards()
    print(f"[Display] {len(files)} clean photo(s) to match against {len(cards)} built card(s)")
    done = 0
    for f in files:
        name = f["name"]
        local = WORK_DIR / name
        try:
            if state:
                state.item(f["id"], "clean_display", "download", version=f.get("version"))
            download(drive, f["id"], local)
            address = read_address(local)
            ref = find_card(address, cards) if address else None
            if not ref:
                print(f"  [Display] no card yet for '{address or name}' — leaving for retry")
                continue
            card = _card_from_base(ref["base"], local)
            photo_img = render_photo_page(card)
            front_img = Image.open(ref["front_png"])
            back_img = Image.open(ref["back_png"])
            paths = save_digital_outputs(card, front_img, back_img, photo_img)
            if not digital_id:
                raise RuntimeError("digital output folder is required")
            upload_tif(drive, paths["digital_tif"], digital_id, replace=True)
            if archive_id:
                move_file(drive, f["id"], archive_id, clean_id)
            if state:
                state.item(f["id"], "clean_display", "archived", version=f.get("version"))
            print(f"  [Display] {name} -> {ref['base']} (digital card updated with clean photo)")
            done += 1
        except Exception as e:
            if state:
                state.item(
                    f["id"], "clean_display", "failed",
                    version=f.get("version"), error_type=type(e).__name__,
                )
            print(f"  [ERROR] display photo {name}: {e}")
    return done


def _mark_pictures_yes(docs, card: dict) -> None:
    document_id = card.get("_reference_document_id")
    address = card.get("address")
    if not docs or not document_id or not address:
        return
    promoted = sync_document_completion(docs, document_id, {address: "Yes"})
    print(f"  [Document] Pictures: Yes for {address}")
    if promoted:
        print(f"  [Document] Moved to Completed: {', '.join(promoted)}")


def process_project_photos_once(
    drive,
    intake_id,
    originals_id,
    digital_id=None,
    reference_folder_id=None,
    docs=None,
    output_id=None,
    state: WatcherState | None = None,
) -> int:
    """Attach Demo Contractor intake photos as digital previews, like folder 15.

    Street-document jobs already have LS/RS/MC/HS on the Google Doc. Photos
    dropped in Tiecard Picture Intake are the clean house shots (address in
    red), not annotated measurement photos. Match them to the existing card
    and rebuild page 3; if no card exists yet, draw it from the street doc
    and still use the raw photo as the digital preview.
    """
    from match_display_photos import (
        find_card,
        index_existing_cards,
        read_address,
        _card_from_base,
    )
    from draw_tiecard_back import render_photo_page, save_digital_outputs
    from PIL import Image

    r = drive.files().list(
        q=f"'{intake_id}' in parents and trashed=false",
        fields="files(id,name,mimeType,version)",
        pageSize=200,
    ).execute()
    files = [f for f in r["files"] if Path(f["name"]).suffix.lower() in IMAGE_EXTS]
    if not files:
        return 0

    reference_index = None
    if reference_folder_id:
        try:
            reference_index = load_reference_index(drive, reference_folder_id)
            print(
                f"[Reference] Loaded {len(reference_index.by_address)} project address(es)"
            )
        except Exception as exc:
            print(f"[WARN] Could not load Demo Contractor project documents: {exc}")

    cards = index_existing_cards()
    print(f"[Project photos] {len(files)} photo(s) to match against {len(cards)} built card(s)")
    done = 0
    for f in files:
        name = f["name"]
        local = WORK_DIR / name
        try:
            if state:
                state.item(f["id"], "project_picture", "download", version=f.get("version"))
            download(drive, f["id"], local)
            address = read_address(local)
            if not address:
                print(f"  [Project photos] no address on '{name}' — leaving for retry")
                continue
            card = {"address": address, "_display_photo_path": str(local)}
            existing = find_card(address, cards)
            if existing:
                if reference_index:
                    reference_index.enrich(card)
                preview = _card_from_base(existing["base"], local)
                if not preview.get("address"):
                    preview["address"] = address
                photo_img = render_photo_page(preview)
                if photo_img is None:
                    print(f"  [Project photos] {name}: no photo page rendered — leaving")
                    continue
                front_img = Image.open(existing["front_png"])
                back_img = Image.open(existing["back_png"])
                paths = save_digital_outputs(preview, front_img, back_img, photo_img)
                print(f"  [Project photos] {name} -> {existing['base']} (digital preview updated)")
            else:
                # New card: read handwriting/house from this photo, then fill
                # remaining blanks from the street doc. Photo-read values win.
                card = apply_photo(card, local)
                card["_photo_path"] = str(local)
                if reference_index:
                    reference_index.enrich(card)
                paths = process_card(
                    card,
                    front_path=None,
                    folder_name=None,
                    photo_path=None,
                    display_photo_path=local,
                )
                if output_id:
                    upload_tif(drive, paths["tif"], output_id, replace=True)
                print(f"  [Project photos] {name} -> drew {address} from street doc + photo")
            dtif = paths.get("digital_tif")
            if digital_id:
                if not dtif:
                    raise RuntimeError("required digital TIFF was not rendered")
                upload_tif(drive, dtif, digital_id, replace=True)
            _mark_pictures_yes(docs, card)
            move_file(drive, f["id"], originals_id, intake_id)
            if state:
                state.item(f["id"], "project_picture", "archived", version=f.get("version"))
            done += 1
        except Exception as e:
            if state:
                state.item(
                    f["id"], "project_picture", "failed",
                    version=f.get("version"), error_type=type(e).__name__,
                )
            print(f"  [ERROR] project photo {name}: {e}")
    return done


def _configured_folder(drive, env_name: str, folder_name: str,
                       parent_id: str | None = None) -> str | None:
    configured = os.getenv(env_name, "").strip()
    return configured or folder_id(drive, folder_name, parent_id)


def _read_only_check(drive, docs, folders: dict[str, str | None]) -> int:
    """Validate access and folder wiring without downloading or changing files."""
    counts = {}
    for label, folder in folders.items():
        if not folder:
            counts[label] = None
            continue
        result = drive.files().list(
            q=f"'{folder}' in parents and trashed=false",
            fields="files(id,mimeType)",
            pageSize=200,
        ).execute()
        counts[label] = len(result.get("files", []))

    docs_ok = False
    reference_folder = folders.get("reference")
    if docs and reference_folder:
        result = drive.files().list(
            q=(f"'{reference_folder}' in parents and trashed=false and "
               "mimeType='application/vnd.google-apps.document'"),
            fields="files(id)",
            pageSize=1,
        ).execute()
        documents = result.get("files", [])
        if documents:
            response = docs.documents().get(
                documentId=documents[0]["id"], fields="documentId"
            ).execute()
            docs_ok = bool(response.get("documentId"))
    print(json.dumps({"read_only": True, "folder_counts": counts, "docs_api": docs_ok}, sort_keys=True))
    return 0 if all(value is not None for value in counts.values()) and docs_ok else 1


def _cloud_production_guard() -> None:
    if os.getenv("UTILIVAULT_CLOUD_RUNTIME", "").strip().lower() not in {"1", "true", "yes"}:
        return
    environment = os.getenv("UTILIVAULT_ENVIRONMENT", "test").strip().lower()
    enabled = os.getenv("UTILIVAULT_PRODUCTION_WATCHER_ENABLED", "").strip()
    if environment == "production" and enabled != "ONE_WATCHER_CONFIRMED":
        raise RuntimeError(
            "cloud production is disabled; stop the Windows task, verify it is stopped, "
            "then set UTILIVAULT_PRODUCTION_WATCHER_ENABLED=ONE_WATCHER_CONFIRMED"
        )


def _run(args, state: WatcherState) -> int:
    if not args.read_only_check:
        _cloud_production_guard()
    drive = get_drive()
    try:
        docs = get_google_docs()
    except Exception as exc:
        docs = None
        print(f"[WARN] Google Docs automation disabled: {exc}")
    utili_id = os.getenv("UTILIVAULT_ROOT_FOLDER_ID", "").strip() or folder_id(drive, "UtiliVault")
    intake_id = _configured_folder(drive, "FIELD_INTAKE_FOLDER_ID", INTAKE_FOLDER, utili_id)
    project_intake_id = os.getenv("PROJECT_PICTURE_INTAKE_FOLDER_ID", "").strip() or PROJECT_INTAKE_FOLDER_ID
    originals_id = _configured_folder(drive, "FIELD_ORIGINALS_FOLDER_ID", ORIGINALS_FOLDER, utili_id)
    output_id = _configured_folder(drive, "FIELD_OUTPUT_FOLDER_ID", OUTPUT_FOLDER, utili_id)
    digital_id = _configured_folder(drive, "FIELD_DIGITAL_FOLDER_ID", DIGITAL_FOLDER, utili_id)
    clean_id = _configured_folder(drive, "CLEAN_PHOTO_INPUT_FOLDER_ID", CLEAN_INPUT_FOLDER, utili_id)
    reference_id = os.getenv("DEMO_PROJECTS_FOLDER_ID", "").strip() or DEMO_PROJECTS_FOLDER_ID

    folders = {
        "field_intake": intake_id,
        "project_picture_intake": project_intake_id,
        "originals": originals_id,
        "printable_output": output_id,
        "digital_output": digital_id,
        "clean_photo_input": clean_id,
        "reference": reference_id,
    }
    if args.read_only_check:
        return _read_only_check(drive, docs, folders)

    intake_sources = [
        (INTAKE_FOLDER, intake_id),
        (PROJECT_INTAKE_FOLDER, project_intake_id),
    ]
    intake_sources = [(name, folder) for name, folder in intake_sources if folder]

    if not intake_sources or not originals_id or not output_id or not digital_id:
        print("[ERROR] Required intake, originals, printable, or digital Drive folder is missing.")
        return 1
    if not clean_id:
        print(f"[WARN] Clean-photo folder '{CLEAN_INPUT_FOLDER}' not found — display pass disabled.")

    for intake_name, source_id in intake_sources:
        if source_id == project_intake_id:
            print(
                f"[Watcher] Watching '{intake_name}' -> digital previews -> '{DIGITAL_FOLDER}'"
            )
        else:
            print(f"[Watcher] Watching '{intake_name}' -> drawing -> '{OUTPUT_FOLDER}'")
    print(f"[Watcher] Watching '{CLEAN_INPUT_FOLDER}' -> matching clean photos -> '{DIGITAL_FOLDER}'")

    def run_sources() -> int:
        processed = 0
        for _, source_id in intake_sources:
            if source_id == project_intake_id:
                processed += process_project_photos_once(
                    drive,
                    source_id,
                    originals_id,
                    digital_id,
                    reference_id,
                    docs,
                    output_id,
                    state,
                )
            else:
                processed += process_intake_once(
                    drive, source_id, originals_id, digital_id,
                    None, docs, output_id, state,
                )
        if clean_id:
            processed += process_display_photos_once(
                drive, clean_id, digital_id, originals_id, state
            )
        return processed

    if args.once:
        if docs:
            changes = sync_project_documents(drive, docs, reference_id)
            for document_name, addresses in changes.items():
                print(f"[Document] {document_name}: moved to Completed: {', '.join(addresses)}")
        n = run_sources()
        state.processed = n
        print(f"\n[Watcher] Single pass complete ({n} processed).")
        return 1 if state.errors else 0

    print(f"[Watcher] Polling every {args.interval}s. Ctrl+C to stop.")
    while True:
        try:
            if docs:
                changes = sync_project_documents(drive, docs, reference_id)
                for document_name, addresses in changes.items():
                    print(f"[Document] {document_name}: moved to Completed: {', '.join(addresses)}")
            run_sources()
        except Exception as e:
            print(f"[Watcher] Pass error (will retry): {e}")

        # Retry any uploads the API server queued while the host was offline.
        # Kept outside the block above so a failed intake pass never prevents
        # the backlog from draining (and vice versa).
        try:
            import outbox
            result = outbox.drain(drive)
            if result["sent"] or result["failed"]:
                print(f"[Watcher] Outbox: {result['sent']} synced, "
                      f"{result['failed']} still pending")
        except Exception as e:                                # noqa: BLE001
            print(f"[Watcher] Outbox drain error (will retry): {e}")

        time.sleep(args.interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Watch the Drive field-intake folder and draw cards")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    parser.add_argument(
        "--read-only-check", action="store_true",
        help="Verify Drive/Docs access and folder wiring without changing data",
    )
    args = parser.parse_args(argv)
    state = WatcherState()
    mode = "read_only" if args.read_only_check else ("once" if args.once else "service")
    try:
        with single_instance():
            state.begin_run(mode)
            try:
                result = _run(args, state)
            except Exception as exc:
                state.finish_run("failed", error_type=type(exc).__name__)
                print(f"[ERROR] Watcher run failed ({type(exc).__name__}): {exc}")
                return 1
            status = "partial_failure" if state.errors else ("success" if result == 0 else "failed")
            state.finish_run(
                status,
                processed=state.processed,
                error_type="ItemFailure" if state.errors else None,
            )
            return result
    except AlreadyRunning:
        emit_event("run_skipped", reason="already_running")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
