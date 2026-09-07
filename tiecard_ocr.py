"""
UtiliVault — tiecard_ocr.py
Example Utility Tie-Card OCR via Claude Vision API
Reads every page of a TIF scan, sends to Claude, extracts all fields
and sketch measurements as structured JSON.

Usage:
  py tiecard_ocr.py 7424.tif
  py tiecard_ocr.py --folder "C:/path/to/scans"
  py tiecard_ocr.py --folder "C:/path/to/scans" --out-dir "C:/output/json"
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-6"

SCAN_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}

# ── EXTRACTION PROMPT ────────────────────────────────────────────────────────

FRONT_PROMPT = """You are extracting data from a scanned water service record.
This is the FRONT of the card. It may be an old "Return of Service Pipe" form
(pre-1970s, white/black) or a modern "Water Service Tie Card" (yellow).

Extract every field you can read. Return ONLY valid JSON — no explanation.

For old-style "Return of Service Pipe" cards, extract:
{
  "card_type": "return_of_service_pipe",
  "reg_no": "",
  "date_laid": "",
  "owner": "",
  "street": "",
  "main_pipe_diameter": "",
  "main_pipe_material": "",
  "dist_main_to_curb_stop": "",
  "foreman": "",
  "status_stamp": "",
  "cost_to_town": [
    {"description": "", "quantity": "", "unit": "", "amount": ""}
  ],
  "cost_to_town_total": "",
  "cost_to_owner": [
    {"description": "", "quantity": "", "unit": "", "amount": ""}
  ],
  "cost_to_owner_total": "",
  "flags": [],
  "notes": ""
}

For modern "Water Service Tie Card" (yellow) cards, extract:
{
  "card_type": "water_service_tie_card",
  "reg_no": "",
  "address": "",
  "contractor": "",
  "date": "",
  "inspected_by": "",
  "material_main": "",
  "diameter_main": "",
  "material_service_main_to_curb": "",
  "diameter_service": "",
  "material_service_curb_to_house": "",
  "comments": "",
  "flags": [],
  "notes": ""
}

For flags, include any of: "lead_fittings", "relaid", "dual_address",
"reg_number_conflict", "low_pressure", "needs_review", "illegible_field".

If a field is unreadable, use null. If a field is blank on the card, use "".
"""

BACK_PROMPT = """You are reading the BACK of a water service tie card.
This page contains an application form at the top and a hand-drawn
triangulation tie sketch showing the buried service location.

Extract the sketch data and return ONLY valid JSON — no explanation.

The sketch is a triangulation diagram. It typically shows:
- A property/building box at the top (with address or reg number)
- A vertical line going down (the service pipe run)
- A measurement along the vertical line (distance from property to curb stop or main)
- An apex point (where the curb stop or corp stop is located)
- Two diagonal lines spreading from the apex to two corners of a reference structure
- A measurement along each diagonal line (the tie distances)
- A horizontal line representing the water main
- A reference structure box at the bottom (a building used as permanent reference)
- A label and/or address for the reference structure

Extract:
{
  "has_sketch": true,
  "property_label": "",
  "vertical_measurement": "",
  "left_diagonal_measurement": "",
  "right_diagonal_measurement": "",
  "main_label": "",
  "reference_structure_label": "",
  "reference_structure_number": "",
  "additional_dimensions": [],
  "sketch_notes": "",
  "application_text": "",
  "signed": "",
  "date_signed": ""
}

Read every number carefully. These are field measurements in feet and inches
(e.g. "11'-6\"", "7'-3\"", "23'"). Pay close attention to apostrophes and
quote marks distinguishing feet from inches. If a measurement is unclear,
include your best read and add "illegible_field" to sketch_notes.
"""

# ── IMAGE HELPERS ─────────────────────────────────────────────────────────────

def tif_pages_to_b64(tif_path: Path) -> list[tuple[str, str]]:
    """
    Extract all pages from a TIF file.
    Returns list of (base64_string, mime_type) tuples.
    """
    try:
        from PIL import Image
        import io
    except ImportError:
        print("[ERROR] Pillow not installed: py -m pip install pillow")
        sys.exit(1)

    pages = []
    img = Image.open(tif_path)
    i = 0
    while True:
        try:
            img.seek(i)
            buf = io.BytesIO()
            frame = img.copy().convert("RGB")
            frame.save(buf, format="PNG")
            b64 = base64.standard_b64encode(buf.getvalue()).decode()
            pages.append((b64, "image/png"))
            i += 1
        except EOFError:
            break
    return pages


def image_file_to_b64(path: Path) -> tuple[str, str]:
    """Convert a non-TIF image to base64."""
    import mimetypes
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    b64 = base64.standard_b64encode(path.read_bytes()).decode()
    return b64, mime


# ── CLAUDE API CALL ───────────────────────────────────────────────────────────

def ask_claude(prompt: str, image_b64: str, mime: str) -> dict:
    """Send one image + prompt to Claude, return parsed JSON."""
    try:
        from anthropic import Anthropic
    except ImportError:
        print("[ERROR] anthropic not installed: py -m pip install anthropic")
        sys.exit(1)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    )
    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [WARN] JSON parse error: {e}")
        return {"raw_response": raw, "parse_error": str(e)}


# ── PROCESS ONE FILE ──────────────────────────────────────────────────────────

def process_tif(tif_path: Path, out_dir: Path) -> Path:
    """
    Process a single TIF (or image) file.
    Extracts front + back data, saves to <out_dir>/<stem>.json.
    Returns path to the JSON file.
    """
    print(f"\n[OCR] {tif_path.name}")
    result = {
        "source_file": str(tif_path),
        "front": None,
        "back": None,
    }

    ext = tif_path.suffix.lower()

    if ext in {".tif", ".tiff"}:
        pages = tif_pages_to_b64(tif_path)
        print(f"  Pages found: {len(pages)}")

        if len(pages) >= 1:
            print("  Sending page 1 (front) to Claude...", end=" ", flush=True)
            result["front"] = ask_claude(FRONT_PROMPT, pages[0][0], pages[0][1])
            print("done")

        if len(pages) >= 2:
            print("  Sending page 2 (back/sketch) to Claude...", end=" ", flush=True)
            result["back"] = ask_claude(BACK_PROMPT, pages[1][0], pages[1][1])
            print("done")

        if len(pages) > 2:
            result["extra_pages"] = len(pages) - 2
            print(f"  [NOTE] {len(pages) - 2} additional page(s) not extracted")

    else:
        b64, mime = image_file_to_b64(tif_path)
        print("  Single image — sending as front...", end=" ", flush=True)
        result["front"] = ask_claude(FRONT_PROMPT, b64, mime)
        print("done")

    # Derive reg number for filename
    reg = None
    if result["front"]:
        reg = (result["front"].get("reg_no") or
               result["front"].get("reg_number") or "").strip()
    stem = f"{reg}_{tif_path.stem}" if reg else tif_path.stem

    out_path = out_dir / f"{stem}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  [Saved] {out_path}")

    # Print summary
    if result["front"]:
        f = result["front"]
        addr = f.get("street") or f.get("address") or "?"
        date = f.get("date_laid") or f.get("date") or "?"
        flags = f.get("flags") or []
        print(f"  Address: {addr}  |  Date: {date}  |  Flags: {flags or 'none'}")
    if result["back"] and result["back"].get("has_sketch"):
        b = result["back"]
        print(f"  Sketch: vertical={b.get('vertical_measurement')}  "
              f"left={b.get('left_diagonal_measurement')}  "
              f"right={b.get('right_diagonal_measurement')}  "
              f"ref={b.get('reference_structure_label')}")

    return out_path


# ── BATCH ─────────────────────────────────────────────────────────────────────

def process_folder(folder: Path, out_dir: Path) -> list[Path]:
    """Process all scan files in a folder."""
    files = [f for f in folder.iterdir()
             if f.is_file() and f.suffix.lower() in SCAN_EXTENSIONS]
    files.sort()

    if not files:
        print(f"[WARN] No scan files found in {folder}")
        return []

    print(f"\n[Batch] {len(files)} scan file(s) in {folder}")
    results = []
    for f in files:
        try:
            out = process_tif(f, out_dir)
            results.append(out)
        except Exception as e:
            print(f"  [ERROR] {f.name}: {e}")

    print(f"\n[Done] {len(results)}/{len(files)} files processed → {out_dir}")
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Example Utility Tie-Card OCR — extract fields via Claude Vision"
    )
    parser.add_argument("file", nargs="?", help="Single TIF/image file to process")
    parser.add_argument("--folder", help="Folder of scan files to batch process")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory for JSON files (default: same as input)")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("[ERROR] ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    if args.folder:
        folder = Path(args.folder)
        if not folder.exists():
            print(f"[ERROR] Folder not found: {folder}")
            sys.exit(1)
        out_dir = Path(args.out_dir) if args.out_dir else folder / "ocr_json"
        out_dir.mkdir(parents=True, exist_ok=True)
        process_folder(folder, out_dir)

    elif args.file:
        tif_path = Path(args.file)
        if not tif_path.exists():
            print(f"[ERROR] File not found: {tif_path}")
            sys.exit(1)
        out_dir = Path(args.out_dir) if args.out_dir else tif_path.parent / "ocr_json"
        out_dir.mkdir(parents=True, exist_ok=True)
        process_tif(tif_path, out_dir)

    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
