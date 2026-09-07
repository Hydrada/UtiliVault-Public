"""
UtiliVault — process_feed_batch.py
End-to-end batch processor for the "1 - Feed" Drive folder.

For each file in Feed:
  - PDF: split into pages (front/back pairs, consecutive pages per card)
  - Image: treated as a single front-only card
Each card pair runs through the full tiecard_ocr_v2 pipeline (legibility
skip check -> multi-engine OCR -> cross-validation -> ensemble escalation
-> needs-review flagging -> Drive upload to the correct destination folder).

Once every card from a source file is done, the ORIGINAL file is moved
(not copied) from "1 - Feed" into "8 - Originals (Processed, For
Cross-Reference)" so Morgan can cross-reference source vs digitized output.

Usage:
  py process_feed_batch.py                  # process everything in Feed
  py process_feed_batch.py --limit 3         # process only first 3 source files (testing)
  py process_feed_batch.py --delay 1.5       # throttle between cards
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from googleapiclient.http import MediaIoBaseDownload

load_dotenv(str(Path(__file__).parent / ".env"))

sys.path.insert(0, str(Path(__file__).parent))
from tiecard_ocr_v2 import process_pair, set_below_normal_priority, _gcv_available, ANTHROPIC_API_KEY

from config import FEED_WORK_DIR as WORK_DIR, FEED_OUT_DIR as OUT_DIR
from google_drive_auth import get_google_drive
WORK_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROGRESS_LOG = OUT_DIR / "batch_progress.log"


def log(msg: str):
    print(msg, flush=True)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def get_drive():
    return get_google_drive()


def get_folder_id(drive, name: str, parent_id: str | None = None) -> str | None:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    r = drive.files().list(q=q, fields="files(id,name)").execute()
    return r["files"][0]["id"] if r["files"] else None


def download_file(drive, file_id: str, dest: Path):
    req = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    dest.write_bytes(buf.read())


def move_file_to_folder(drive, file_id: str, new_parent_id: str, old_parent_id: str):
    drive.files().update(
        fileId=file_id,
        addParents=new_parent_id,
        removeParents=old_parent_id,
        fields="id,parents",
    ).execute()


def split_pdf_to_pages(pdf_path: Path, out_dir: Path, dpi: int = 300) -> list[Path]:
    """Render every page of a PDF to PNG. Returns list of page image paths, in order."""
    doc = fitz.open(pdf_path)
    pages = []
    for i in range(doc.page_count):
        pix = doc[i].get_pixmap(dpi=dpi)
        out_path = out_dir / f"{pdf_path.stem}_p{i:03d}.png"
        pix.save(str(out_path))
        pages.append(out_path)
    doc.close()
    return pages


def process_source_file(drive, file_info: dict, feed_id: str, originals_id: str,
                        delay: float, skip_legible: bool) -> dict:
    """Process one Feed file (PDF or image) end to end. Returns a summary dict."""
    name = file_info["name"]
    file_id = file_info["id"]
    mime = file_info["mimeType"]

    log(f"\n{'#'*70}")
    log(f"# SOURCE FILE: {name}")
    log(f"{'#'*70}")

    local_path = WORK_DIR / name
    log(f"  Downloading...")
    download_file(drive, file_id, local_path)

    summary = {"file": name, "cards_processed": 0, "cards_skipped_legible": 0,
               "cards_flagged_review": 0, "errors": []}

    try:
        if mime == "application/pdf":
            page_dir = WORK_DIR / f"{local_path.stem}_pages"
            page_dir.mkdir(exist_ok=True)
            log(f"  Splitting PDF into pages...")
            pages = split_pdf_to_pages(local_path, page_dir)
            log(f"  {len(pages)} pages -> {len(pages)//2} card(s) (front/back pairs)")

            for i in range(0, len(pages) - 1, 2):
                front_page, back_page = pages[i], pages[i+1]
                try:
                    result = process_pair(front_page, back_page, OUT_DIR, delay, skip_legible=skip_legible)
                    if result is None:
                        summary["cards_skipped_legible"] += 1
                    else:
                        summary["cards_processed"] += 1
                        back_val = result.get("back_validation") or {}
                        if back_val.get("confidence") == "LOW":
                            summary["cards_flagged_review"] += 1
                except Exception as e:
                    summary["errors"].append(f"{front_page.name}: {e}")
                    log(f"  [ERROR] {front_page.name}: {e}")

            # Odd page count -> last page unpaired, process as front-only
            if len(pages) % 2 == 1:
                try:
                    result = process_pair(pages[-1], None, OUT_DIR, delay, skip_legible=skip_legible)
                    if result is None:
                        summary["cards_skipped_legible"] += 1
                    else:
                        summary["cards_processed"] += 1
                except Exception as e:
                    summary["errors"].append(f"{pages[-1].name}: {e}")

        else:
            # Single image file -> front-only card
            try:
                result = process_pair(local_path, None, OUT_DIR, delay, skip_legible=skip_legible)
                if result is None:
                    summary["cards_skipped_legible"] += 1
                else:
                    summary["cards_processed"] += 1
            except Exception as e:
                summary["errors"].append(f"{name}: {e}")

    finally:
        # Move the original source file from Feed -> Originals, regardless of
        # per-card errors, so Feed empties out and nothing gets stuck/reprocessed.
        try:
            move_file_to_folder(drive, file_id, originals_id, feed_id)
            log(f"  [Drive] Moved original '{name}' -> Originals folder")
        except Exception as e:
            log(f"  [WARN] Could not move original '{name}': {e}")

    log(f"  Summary: {summary['cards_processed']} processed, "
        f"{summary['cards_skipped_legible']} skipped (legible), "
        f"{summary['cards_flagged_review']} flagged for review, "
        f"{len(summary['errors'])} errors")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Batch process the UtiliVault Feed folder")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N source files (testing)")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between cards (API throttle)")
    parser.add_argument("--no-skip-legible", action="store_true", help="Process every card, even modern/clean ones")
    parser.add_argument("--no-priority", action="store_true", help="Skip setting Below Normal process priority")
    args = parser.parse_args()

    if not args.no_priority:
        ok = set_below_normal_priority()
        log(f"[Priority] {'Below Normal (game servers protected)' if ok else 'could not set'}")

    log(f"[Engines] Claude Vision: {'OK' if ANTHROPIC_API_KEY else 'NO API KEY'}")
    log(f"[Engines] Google Cloud Vision: {'available' if _gcv_available() else 'unavailable'}")

    drive = get_drive()
    utili_id = get_folder_id(drive, "UtiliVault")
    feed_id = get_folder_id(drive, "1 - Feed", utili_id)
    originals_id = get_folder_id(drive, "8 - Originals (Processed, For Cross-Reference)", utili_id)

    if not feed_id or not originals_id:
        log("[ERROR] Could not find Feed or Originals folder in Drive.")
        sys.exit(1)

    r = drive.files().list(
        q=f"'{feed_id}' in parents and trashed=false",
        fields="files(id,name,mimeType,size)", pageSize=500
    ).execute()
    files = r["files"]

    if args.limit:
        files = files[:args.limit]

    log(f"\n[Batch] {len(files)} source file(s) to process from '1 - Feed'\n")

    all_summaries = []
    for idx, f in enumerate(files, 1):
        log(f"\n>>> [{idx}/{len(files)}] {f['name']}")
        try:
            summary = process_source_file(
                drive, f, feed_id, originals_id,
                delay=args.delay, skip_legible=not args.no_skip_legible,
            )
            all_summaries.append(summary)
        except Exception as e:
            log(f"[FATAL] Failed on source file '{f['name']}': {e}")
            all_summaries.append({"file": f["name"], "error": str(e)})

    total_processed = sum(s.get("cards_processed", 0) for s in all_summaries)
    total_skipped = sum(s.get("cards_skipped_legible", 0) for s in all_summaries)
    total_flagged = sum(s.get("cards_flagged_review", 0) for s in all_summaries)

    log(f"\n{'='*70}")
    log(f"[BATCH COMPLETE] {len(files)} source files")
    log(f"  Cards processed:        {total_processed}")
    log(f"  Cards skipped (legible): {total_skipped}")
    log(f"  Cards flagged (review):  {total_flagged}")
    log(f"{'='*70}")

    summary_path = OUT_DIR / "batch_summary.json"
    summary_path.write_text(json.dumps(all_summaries, indent=2), encoding="utf-8")
    log(f"\nFull summary saved -> {summary_path}")


if __name__ == "__main__":
    main()
