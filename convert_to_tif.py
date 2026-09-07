r"""
UtiliVault — convert_to_tif.py
Converts JPG, PNG, BMP, PDF files to TIF format.
Works on a local folder OR downloads from a Google Drive folder and converts in place.

Usage:
  py convert_to_tif.py --folder "C:\path\to\folder"         # local folder
  py convert_to_tif.py --drive-folder "5 - Blank Card Layouts"  # Drive folder
  py convert_to_tif.py --drive-folder "1 - Feed"               # Feed folder
"""
import os, sys, json, argparse, tempfile
from pathlib import Path

def get_drive_service():
    from google_drive_auth import get_google_drive

    return get_google_drive()


def find_utili_folder(drive, name):
    # Find UtiliVault parent
    r = drive.files().list(
        q="name='UtiliVault' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id)"
    ).execute()
    parent_id = r["files"][0]["id"]
    # Find subfolder by name
    r = drive.files().list(
        q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false",
        fields="files(id,name)"
    ).execute()
    if not r["files"]:
        raise ValueError(f"Folder '{name}' not found inside UtiliVault")
    return r["files"][0]["id"], parent_id


def list_drive_files(drive, folder_id):
    results = []
    page_token = None
    while True:
        r = drive.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id,name,mimeType)",
            pageToken=page_token
        ).execute()
        results.extend(r.get("files", []))
        page_token = r.get("nextPageToken")
        if not page_token:
            break
    return results


def convert_file_to_tif(src_path: Path, out_path: Path):
    """Convert a single image or PDF to TIF."""
    suffix = src_path.suffix.lower()

    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            print("  Installing PyMuPDF for PDF support...")
            os.system("py -m pip install pymupdf -q")
            import fitz

        doc = fitz.open(str(src_path))
        if len(doc) == 1:
            page = doc[0]
            mat = fitz.Matrix(300 / 72, 300 / 72)  # 300 DPI
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            pix.save(str(out_path))
        else:
            # Multi-page PDF: save each page as tif_p001.tif, etc.
            base = out_path.stem
            for i, page in enumerate(doc):
                mat = fitz.Matrix(300 / 72, 300 / 72)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                page_out = out_path.parent / f"{base}_p{i+1:03d}.tif"
                pix.save(str(page_out))
                print(f"    -> {page_out.name}")
            return  # skip the normal save below
        doc.close()

    elif suffix in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
        from PIL import Image
        img = Image.open(str(src_path))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        img.save(str(out_path), format="TIFF", compression="lzw", dpi=(300, 300))

    else:
        print(f"  Skipping unsupported format: {src_path.name}")
        return

    print(f"  Converted: {src_path.name} -> {out_path.name}")


def process_local_folder(folder_path: str):
    folder = Path(folder_path)
    if not folder.exists():
        print(f"Folder not found: {folder_path}")
        sys.exit(1)

    supported = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".pdf"}
    files = [f for f in folder.iterdir() if f.suffix.lower() in supported and not f.stem.endswith("_tif")]

    if not files:
        print("No convertible files found.")
        return

    print(f"\n[UtiliVault] Converting {len(files)} file(s) in {folder}\n")
    for f in files:
        out = folder / (f.stem + ".tif")
        if out.exists():
            print(f"  Already exists: {out.name}")
            continue
        convert_file_to_tif(f, out)

    print("\nDone.")


def process_drive_folder(folder_name: str):
    from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
    import io

    drive = get_drive_service()
    folder_id, utili_id = find_utili_folder(drive, folder_name)
    files = list_drive_files(drive, folder_id)

    supported = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".pdf"}
    convertible = [f for f in files if Path(f["name"]).suffix.lower() in supported]
    already_tif = {Path(f["name"]).stem for f in files if f["name"].lower().endswith(".tif")}

    to_convert = [f for f in convertible if Path(f["name"]).stem not in already_tif]

    if not to_convert:
        print(f"No files to convert in '{folder_name}' — all already TIF or folder is empty.")
        return

    print(f"\n[UtiliVault] Converting {len(to_convert)} file(s) in Drive folder '{folder_name}'\n")

    with tempfile.TemporaryDirectory() as tmp:
        for file in to_convert:
            name = file["name"]
            src = Path(tmp) / name
            out = Path(tmp) / (Path(name).stem + ".tif")

            # Download
            print(f"  Downloading: {name}")
            req = drive.files().get_media(fileId=file["id"])
            with open(src, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            # Convert
            convert_file_to_tif(src, out)

            # Upload TIF back to same Drive folder
            if out.exists():
                media = MediaFileUpload(str(out), mimetype="image/tiff")
                drive.files().create(
                    body={"name": out.name, "parents": [folder_id]},
                    media_body=media,
                    fields="id"
                ).execute()
                print(f"    Uploaded {out.name} to Drive")

    print(f"\nDone. TIF versions are now in '{folder_name}' alongside the originals.")


def main():
    parser = argparse.ArgumentParser(description="Convert images/PDFs to TIF for UtiliVault")
    parser.add_argument("--folder",       help="Local folder path to convert")
    parser.add_argument("--drive-folder", help="Drive subfolder name inside UtiliVault to convert")
    args = parser.parse_args()

    if args.folder:
        process_local_folder(args.folder)
    elif args.drive_folder:
        process_drive_folder(args.drive_folder)
    else:
        print("Specify --folder <path> or --drive-folder <name>")
        parser.print_help()


if __name__ == "__main__":
    main()
