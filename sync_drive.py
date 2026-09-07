"""
sync_drive.py — Example Utility Tie-Card Drive Sync + Full Automation Runner
Downloads scan images/PDFs from a Google Drive folder, runs OCR via
pipeline_a_ocr.py, generates modern PDFs via pipeline_c_tiecard_pdf.py,
and uploads results back to Drive.

Usage:
  python sync_drive.py --run-all              # full end-to-end pipeline
  python sync_drive.py --download-only        # just pull scans from Drive
  python sync_drive.py --ocr-only             # OCR local scans/ folder only
  python sync_drive.py --pdf-only             # render PDFs from DB only
  python sync_drive.py --status               # show what's in Drive vs local
  python sync_drive.py --folder "My Scans"   # override Drive folder name
"""

import argparse
import io
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SCANS_DIR     = Path("scans")
OUTPUT_DIR    = Path("output")
TIECARD_DIR   = OUTPUT_DIR / "tiecards"
DRIVE_SCAN_FOLDER   = os.getenv("DRIVE_SCAN_FOLDER", "Example Utility Tie-Card Scans")
DRIVE_OUTPUT_FOLDER = "Digitized Tie-Cards"

# Image/PDF extensions we'll pull from Drive
SCAN_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".pdf", ".bmp"}

PYTHON = sys.executable   # use the same interpreter that's running this script


# ─── GOOGLE DRIVE CLIENT ─────────────────────────────────────────────────────

def _drive_service():
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        print("[ERROR] google-api-python-client not installed.")
        sys.exit(1)

    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_path or not Path(sa_path).exists():
        print(f"[ERROR] Service account JSON not found: {sa_path}")
        print("        Run: python setup.py  to configure credentials")
        sys.exit(1)

    creds = Credentials.from_service_account_file(
        sa_path,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds)


def find_folder(service, name: str) -> str | None:
    """Return Drive folder ID by name, or None if not found."""
    q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    res = service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def list_scan_files(service, folder_id: str) -> list[dict]:
    """List all scan image/PDF files in the given Drive folder."""
    files = []
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime)",
            "pageSize": 200,
        }
        if page_token:
            params["pageToken"] = page_token
        res = service.files().list(**params).execute()
        for f in res.get("files", []):
            ext = Path(f["name"]).suffix.lower()
            if ext in SCAN_EXTENSIONS:
                files.append(f)
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return files


def download_file(service, file_id: str, dest: Path):
    """Download a Drive file to local dest path."""
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id)
    with open(dest, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


# ─── PDF PAGE SPLITTING ──────────────────────────────────────────────────────

def split_pdf_to_images(pdf_path: Path) -> list[Path]:
    """
    Convert each page of a scanned PDF to a JPEG for OCR.
    Requires pillow (already installed). Returns list of image paths.
    """
    try:
        from PIL import Image
        import pypdf
    except ImportError:
        print(f"  [WARN] Cannot split {pdf_path.name} — pypdf/pillow needed (already installed)")
        return [pdf_path]

    # Use pypdf to extract pages, then pillow to save as images
    # For scanned PDFs (image-only), we render via pypdf's page images
    try:
        reader = pypdf.PdfReader(str(pdf_path))
    except Exception as e:
        print(f"  [WARN] Could not read {pdf_path.name}: {e}")
        return [pdf_path]

    out_paths = []
    for i, page in enumerate(reader.pages):
        # Extract embedded images from scanned page
        images = page.images
        if images:
            for j, img_obj in enumerate(images):
                img_path = pdf_path.parent / f"{pdf_path.stem}_p{i+1}_img{j+1}.jpg"
                with open(img_path, "wb") as f:
                    f.write(img_obj.data)
                out_paths.append(img_path)
        else:
            # No embedded images — likely a native PDF, pass as-is to OCR
            out_paths.append(pdf_path)
            break

    return out_paths if out_paths else [pdf_path]


# ─── DOWNLOAD STEP ───────────────────────────────────────────────────────────

def download_scans(folder_name: str) -> list[Path]:
    """Download all new scans from Drive folder → scans/. Returns list of new files."""
    SCANS_DIR.mkdir(exist_ok=True)
    service = _drive_service()

    print(f"\n[Drive] Looking for folder: '{folder_name}'")
    folder_id = find_folder(service, folder_name)
    if not folder_id:
        print(f"[ERROR] Folder '{folder_name}' not found in your Drive.")
        print(f"        Make sure the service account has access to it, or")
        print(f"        set DRIVE_SCAN_FOLDER in .env to the correct folder name.")
        sys.exit(1)

    print(f"[Drive] Found folder (id: {folder_id})")
    files = list_scan_files(service, folder_id)
    print(f"[Drive] {len(files)} scan file(s) in folder")

    existing = {p.name for p in SCANS_DIR.iterdir() if p.is_file()}
    new_files: list[Path] = []

    for f in files:
        dest = SCANS_DIR / f["name"]
        if f["name"] in existing:
            print(f"  [skip] {f['name']} (already local)")
            continue
        print(f"  [↓]    {f['name']}  ({int(f.get('size',0))//1024} KB)", end=" ", flush=True)
        download_file(service, f["id"], dest)
        print("✓")
        new_files.append(dest)

        # If it's a multi-page scanned PDF, split into per-page images
        if dest.suffix.lower() == ".pdf":
            imgs = split_pdf_to_images(dest)
            if len(imgs) > 1:
                print(f"         → split into {len(imgs)} page image(s)")
                new_files.extend(imgs)
                new_files.remove(dest)   # replace PDF with its images

    print(f"[Done] {len(new_files)} new file(s) ready for OCR in scans/")
    return new_files


# ─── OCR STEP ────────────────────────────────────────────────────────────────

def run_ocr(files: list[Path] | None = None):
    """
    Run pipeline_a_ocr.py on scans/ folder (or specific files).
    Uses --folder mode so the pipeline handles batching.
    """
    ocr_script = Path("pipeline_a_ocr.py")
    if not ocr_script.exists():
        print("[ERROR] pipeline_a_ocr.py not found in project root.")
        sys.exit(1)

    if files:
        # Run per-file for targeted OCR
        for f in files:
            ext = f.suffix.lower()
            if ext in {".pdf"}:
                continue   # skip raw PDFs already split
            print(f"\n[OCR] Processing {f.name}...")
            result = subprocess.run(
                [PYTHON, "pipeline_a_ocr.py", "--image", str(f), "--type", "tie_card"],
                capture_output=False,
            )
            if result.returncode != 0:
                print(f"  [WARN] OCR returned non-zero for {f.name}")
    else:
        # Batch-process entire scans/ folder
        print(f"\n[OCR] Processing all images in scans/ ...")
        result = subprocess.run(
            [PYTHON, "pipeline_a_ocr.py", "--folder", "scans/", "--type", "tie_card"],
            capture_output=False,
        )
        if result.returncode != 0:
            print("[WARN] pipeline_a_ocr.py returned non-zero exit code")


# ─── PDF RENDER STEP ─────────────────────────────────────────────────────────

def run_pdf_render(upload: bool = False, review_sheet: bool = False):
    """Run pipeline_c_tiecard_pdf.py to render + optionally upload PDFs."""
    pdf_script = Path("pipeline_c_tiecard_pdf.py")
    if not pdf_script.exists():
        print("[ERROR] pipeline_c_tiecard_pdf.py not found.")
        sys.exit(1)

    cmd = [PYTHON, "pipeline_c_tiecard_pdf.py", "--merge"]
    if upload:
        cmd.append("--upload")
    if review_sheet:
        cmd.append("--review-sheet")

    print(f"\n[PDF] Rendering tie-card PDFs...")
    subprocess.run(cmd, capture_output=False)


# ─── STATUS ──────────────────────────────────────────────────────────────────

def show_drive_status(folder_name: str):
    service = _drive_service()
    folder_id = find_folder(service, folder_name)
    if not folder_id:
        print(f"[Drive] Folder '{folder_name}' not found or not shared with service account.")
        return

    files = list_scan_files(service, folder_id)
    existing = {p.name for p in SCANS_DIR.iterdir()} if SCANS_DIR.exists() else set()

    new     = [f for f in files if f["name"] not in existing]
    synced  = [f for f in files if f["name"] in existing]
    local_only = existing - {f["name"] for f in files}

    print(f"\n  Drive folder: '{folder_name}'  ({len(files)} total scans)")
    print(f"  ✓ Synced locally:   {len(synced)}")
    print(f"  ↓ New in Drive:     {len(new)}")
    if local_only:
        print(f"  ↑ Local only:      {len(local_only)} (not in Drive)")

    # Check output folder in Drive
    out_folder_id = find_folder(service, DRIVE_OUTPUT_FOLDER)
    if out_folder_id:
        out_files = list_scan_files(service, out_folder_id)
        print(f"  📁 '{DRIVE_OUTPUT_FOLDER}' in Drive: {len(out_files)} PDF(s)")
    else:
        print(f"  📁 '{DRIVE_OUTPUT_FOLDER}' not yet created in Drive")


# ─── FULL PIPELINE ───────────────────────────────────────────────────────────

def run_all(folder_name: str):
    print("=" * 60)
    print("  EXAMPLE UTILITY — FULL TIE-CARD AUTOMATION RUN")
    print("=" * 60)

    # 1. Download new scans from Drive
    new_files = download_scans(folder_name)

    # 2. OCR — targeted if we have new files, else full folder
    if new_files:
        run_ocr(files=new_files)
    else:
        # Still OCR full folder in case DB is out of sync
        run_ocr()

    # 3. Render PDFs + upload to Drive + update review sheet
    run_pdf_render(upload=True, review_sheet=True)

    # 4. Final status
    print("\n" + "=" * 60)
    print("  RUN COMPLETE — launching status dashboard...")
    print("=" * 60 + "\n")
    subprocess.run([PYTHON, "status.py"], capture_output=False)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Example Utility Tie-Card Drive Sync + Automation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-all",       action="store_true", help="Full end-to-end pipeline")
    parser.add_argument("--download-only", action="store_true", help="Download scans from Drive only")
    parser.add_argument("--ocr-only",      action="store_true", help="OCR local scans/ folder only")
    parser.add_argument("--pdf-only",      action="store_true", help="Render PDFs from DB only")
    parser.add_argument("--status",        action="store_true", help="Show Drive vs local sync status")
    parser.add_argument("--upload",        action="store_true", help="Upload PDFs to Drive (with --pdf-only)")
    parser.add_argument("--folder",        default=None,        help="Override Drive scan folder name")
    args = parser.parse_args()

    folder = args.folder or DRIVE_SCAN_FOLDER

    if not any([args.run_all, args.download_only, args.ocr_only, args.pdf_only, args.status]):
        parser.print_help()
        sys.exit(0)

    if args.status:
        show_drive_status(folder)
    elif args.download_only:
        download_scans(folder)
    elif args.ocr_only:
        run_ocr()
    elif args.pdf_only:
        run_pdf_render(upload=args.upload, review_sheet=True)
    elif args.run_all:
        run_all(folder)


if __name__ == "__main__":
    main()
