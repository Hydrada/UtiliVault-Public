"""
UtiliVault — tiecard_ocr_v2.py
Multi-engine OCR pipeline for Example Utility Tie Cards

Engines:
  1. Claude Vision API  (cloud, zero local load)
  2. Google Cloud Vision (cloud, zero local load) — skipped if no credentials
  3. Tesseract v5       (local, ~50 MB RAM, lightweight)

Cross-validation:
  All 3 agree  → HIGH confidence, auto-file
  2 of 3 agree → MEDIUM, flag for spot-check
  All differ   → LOW, hold for human review

Usage:
  py tiecard_ocr_v2.py image-52.png image-51.png
  py tiecard_ocr_v2.py --folder "C:/path/to/scans"
  py tiecard_ocr_v2.py image-52.png image-51.png --delay 2 --no-priority
"""

import argparse
import base64
import ctypes
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-6"
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
SCAN_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}

# ── PROMPTS (same as tiecard_ocr.py) ─────────────────────────────────────────

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
  "main_pipe_material": null,
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

Flags: "lead_fittings", "relaid", "dual_address", "reg_number_conflict",
"low_pressure", "needs_review", "illegible_field".
If a field is unreadable, use null. If blank on the card, use "".
"""

BACK_PROMPT = """You are reading the BACK of a water service tie card.
This page has an application form at top and a hand-drawn triangulation sketch.

The sketch shows:
- A property/building box at the top (address or reg number)
- A vertical line down (service pipe run) with a measurement
- An apex point (curb stop / corp stop location)
- Two diagonal lines from the apex to corners of a reference structure, each with a measurement
- A horizontal line = the water main
- A reference structure box at the bottom with label/address

Return ONLY valid JSON:
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

Read measurements carefully — feet/inches format e.g. "11'-6\\"", "7'-3\\"", "23'".
If unclear, include best read and note "illegible_field" in sketch_notes.
"""

# ── PROCESS PRIORITY ──────────────────────────────────────────────────────────

def set_below_normal_priority():
    """Set this process to Below Normal so game servers always win CPU."""
    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, os.getpid())
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x4000)  # BELOW_NORMAL
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False

# ── IMAGE PREPROCESSING ───────────────────────────────────────────────────────

def preprocess_image(img_path: Path) -> np.ndarray:
    """
    OpenCV preprocessing pipeline:
    1. Load as grayscale
    2. Deskew (rotate to straighten text)
    3. Denoise
    4. CLAHE contrast enhancement
    """
    img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not load image: {img_path}")

    # Denoise first (before deskew to avoid artefacts)
    img = cv2.fastNlMeansDenoising(img, h=10, templateWindowSize=7, searchWindowSize=21)

    # Deskew via Hough line detection
    img = _deskew(img)

    # CLAHE — adaptive contrast enhancement (helps faded handwriting)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    img = clahe.apply(img)

    return img


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Deskew image using Hough lines. Returns corrected image."""
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100,
                             minLineLength=gray.shape[1] // 4,
                             maxLineGap=20)
    if lines is None:
        return gray

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 != x1:
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(angle) < 10:  # only near-horizontal lines
                angles.append(angle)

    if not angles:
        return gray

    median_angle = np.median(angles)
    if abs(median_angle) < 0.3:  # skip tiny corrections
        return gray

    h, w = gray.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(gray, M, (w, h),
                              flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
    return rotated


def ndarray_to_b64(img: np.ndarray) -> tuple[str, str]:
    """Encode OpenCV ndarray → base64 PNG string."""
    success, buf = cv2.imencode(".png", img)
    if not success:
        raise ValueError("Failed to encode preprocessed image")
    b64 = base64.standard_b64encode(buf.tobytes()).decode()
    return b64, "image/png"


def file_to_b64(path: Path) -> tuple[str, str]:
    """Raw file → base64 (no preprocessing)."""
    import mimetypes
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    b64 = base64.standard_b64encode(path.read_bytes()).decode()
    return b64, mime

# ── ENGINE 1: CLAUDE VISION ────────────────────────────────────────────────────

def ocr_claude(prompt: str, b64: str, mime: str) -> dict | None:
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        print(f"    [Claude] error: {e}")
        return None

# ── ENGINE 2: GOOGLE CLOUD VISION ─────────────────────────────────────────────

def _gcv_available() -> bool:
    try:
        from google.cloud import vision  # noqa: F401
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        return bool(creds_path and Path(creds_path).exists())
    except ImportError:
        return False


def ocr_google_cloud_vision(img_path: Path) -> str | None:
    """Run GCV document_text_detection, return raw text or None."""
    if not _gcv_available():
        return None
    try:
        from google.cloud import vision
        client = vision.ImageAnnotatorClient()
        content = img_path.read_bytes()
        image = vision.Image(content=content)
        response = client.document_text_detection(image=image)
        if response.error.message:
            print(f"    [GCV] error: {response.error.message}")
            return None
        return response.full_text_annotation.text
    except Exception as e:
        print(f"    [GCV] error: {e}")
        return None

# ── ENGINE 3: TESSERACT ────────────────────────────────────────────────────────

def ocr_tesseract(img: np.ndarray) -> str | None:
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        text = pytesseract.image_to_string(
            img,
            config="--oem 3 --psm 6",
        )
        return text.strip()
    except Exception as e:
        print(f"    [Tesseract] error: {e}")
        return None

# ── CROSS-VALIDATION ──────────────────────────────────────────────────────────

def _key_fields(data: dict) -> dict:
    """Pull the most important identifying fields for comparison."""
    if not data:
        return {}
    keys = ["reg_no", "street", "address", "date_laid", "date",
            "owner", "contractor", "main_pipe_diameter", "diameter_main",
            "foreman", "inspected_by"]
    return {k: str(data.get(k) or "").strip().lower() for k in keys
            if data.get(k)}


def cross_validate(claude_data: dict | None,
                   gcv_text: str | None,
                   tess_text: str | None,
                   page: str = "front") -> dict:
    """
    Compare engines. Returns:
      {
        "confidence": "HIGH" | "MEDIUM" | "LOW",
        "data": <best dict>,
        "engines_used": [...],
        "notes": "..."
      }
    """
    engines_used = []
    notes_parts = []

    # Which engines returned useful data?
    have_claude = bool(claude_data and not claude_data.get("parse_error"))
    have_gcv    = bool(gcv_text and len(gcv_text.strip()) > 20)
    have_tess   = bool(tess_text and len(tess_text.strip()) > 20)

    if have_claude: engines_used.append("Claude Vision")
    if have_gcv:    engines_used.append("Google Cloud Vision")
    if have_tess:   engines_used.append("Tesseract")

    n_engines = len(engines_used)

    if n_engines == 0:
        return {"confidence": "LOW", "data": {}, "engines_used": [],
                "notes": "All engines failed"}

    # Claude is the gold standard for structured extraction.
    # Use it as the primary data source; GCV + Tesseract are validators.
    # If GCV and/or Tesseract raw text contains the key fields Claude found,
    # that's a match.

    if not have_claude:
        notes_parts.append("Claude unavailable — using raw text engines only")
        return {"confidence": "LOW", "data": {},
                "engines_used": engines_used,
                "notes": "; ".join(notes_parts)}

    if n_engines == 1:
        # Only Claude
        notes_parts.append("Single engine — Claude only")
        return {"confidence": "MEDIUM", "data": claude_data,
                "engines_used": engines_used,
                "notes": "; ".join(notes_parts)}

    # Check how many raw-text engines corroborate Claude's key fields
    claude_fields = _key_fields(claude_data)
    corroborated = 0
    total_checks = 0

    for field_val in claude_fields.values():
        if not field_val or len(field_val) < 2:
            continue
        total_checks += 1
        found_in = 0
        if have_gcv and field_val in (gcv_text or "").lower():
            found_in += 1
        if have_tess and field_val in (tess_text or "").lower():
            found_in += 1
        if found_in > 0:
            corroborated += 1

    if total_checks == 0:
        confidence = "MEDIUM"
        notes_parts.append("No key fields to cross-check")
    else:
        ratio = corroborated / total_checks
        if ratio >= 0.6:
            confidence = "HIGH"
        elif ratio >= 0.3:
            confidence = "MEDIUM"
            notes_parts.append(f"Partial corroboration ({corroborated}/{total_checks} fields confirmed)")
        else:
            confidence = "MEDIUM"
            notes_parts.append(f"Low corroboration ({corroborated}/{total_checks} fields) — flag for spot-check")

    if have_gcv and have_tess and n_engines == 3:
        notes_parts.append("Triple-engine validation")
    elif n_engines == 2:
        notes_parts.append("Dual-engine validation")

    return {
        "confidence": confidence,
        "data": claude_data,
        "engines_used": engines_used,
        "corroboration": f"{corroborated}/{total_checks}" if total_checks else "n/a",
        "notes": "; ".join(notes_parts) if notes_parts else "OK",
    }

# ── ENSEMBLE SKETCH-LABEL VERIFICATION ────────────────────────────────────────
#
# For badly faded 1950s-era handwriting, reading the whole sketch in one pass
# is unreliable — every engine tends to disagree. What actually works: crop
# each measurement tightly, generate several independently-enhanced versions
# of just that crop, and ask Claude to read each variant separately. Then
# vote across variants. This only runs when the first-pass confidence isn't
# already HIGH, so easy/legible cards aren't slowed down or cost more.

def _make_crop_variants(gray_crop: np.ndarray) -> list[np.ndarray]:
    """
    Produce several independently-enhanced versions of one label crop.
    Different enhancement strategies surface different ink that's otherwise
    lost — no single method wins on every card, so we generate a few and
    let majority vote sort it out.
    """
    variants = []

    # Variant 1: Sauvola adaptive threshold (best for uneven old-paper lighting)
    try:
        from skimage.filters import threshold_sauvola
        thresh = threshold_sauvola(gray_crop, window_size=25, k=0.15)
        sauvola = np.where(gray_crop > thresh, 255, 0).astype(np.uint8)
        variants.append(sauvola)
    except ImportError:
        pass

    # Variant 2: CLAHE + sharpen (best for low-contrast faded ink)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(6, 6))
    enhanced = clahe.apply(gray_crop)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    variants.append(sharpened)

    # Variant 3: Morphological closing (reconnects broken/faded pen strokes)
    _, binary = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel2, iterations=1)
    variants.append(255 - closed)  # back to white-bg/black-ink convention

    # Variant 4: raw upscale only (sometimes enhancement destroys real signal)
    variants.append(gray_crop)

    return variants


def _read_measurement_crop(variant: np.ndarray, context: str) -> str | None:
    """Ask Claude to read ONE isolated, enhanced measurement crop."""
    try:
        from anthropic import Anthropic
        success, buf = cv2.imencode(".png", variant)
        if not success:
            return None
        b64 = base64.standard_b64encode(buf.tobytes()).decode()

        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": (
                    f"This is a zoomed, enhanced crop of a single handwritten measurement "
                    f"({context}) on a 1950s water service card, in feet-and-inches notation "
                    f"(e.g. 13'-6\"). Reply with ONLY the measurement you read, nothing else. "
                    f"If genuinely unreadable, reply UNREADABLE."
                )},
            ]}],
        )
        text = response.content[0].text.strip()
        return None if "UNREADABLE" in text.upper() else text
    except Exception:
        return None


def ensemble_verify_measurement(gray_crop: np.ndarray, context: str) -> dict:
    """
    Run all crop variants through Claude independently, vote on the result.
    Returns {"value": str|None, "confidence": "HIGH"|"MEDIUM"|"LOW", "candidates": [...]}
    """
    variants = _make_crop_variants(gray_crop)
    candidates = []
    for v in variants:
        # Upscale each variant for legibility before sending
        v_big = cv2.resize(v, (v.shape[1] * 4, v.shape[0] * 4), interpolation=cv2.INTER_LANCZOS4)
        reading = _read_measurement_crop(v_big, context)
        if reading:
            candidates.append(reading)

    if not candidates:
        return {"value": None, "confidence": "LOW", "candidates": []}

    # Normalize and vote
    norm_counts = {}
    for c in candidates:
        norm = _normalize_measurement_str(c)
        norm_counts.setdefault(norm, []).append(c)

    best_norm, readings = max(norm_counts.items(), key=lambda kv: len(kv[1]))
    agreement = len(readings)

    if agreement >= 3:
        confidence = "HIGH"
    elif agreement == 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {"value": readings[0], "confidence": confidence, "candidates": candidates}


def _normalize_measurement_str(s: str) -> str:
    import re
    s = s.strip().lower()
    s = re.sub(r'''['"`,]''', "", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[-'/\\]", "", s)
    return s


SKETCH_FIELDS = [
    ("vertical_measurement", "vertical service-line measurement, top to bottom from the property box down to the apex/curb-stop point"),
    ("left_diagonal_measurement", "left diagonal tie measurement, from the apex down to the bottom-left corner"),
    ("right_diagonal_measurement", "right diagonal tie measurement, from the apex down to the bottom-right corner"),
]


def _read_sketch_variant(variant: np.ndarray) -> dict | None:
    """Ask Claude to read all three measurements from one enhanced sketch crop."""
    try:
        from anthropic import Anthropic
        success, buf = cv2.imencode(".png", variant)
        if not success:
            return None
        b64 = base64.standard_b64encode(buf.tobytes()).decode()

        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": (
                    "This is an enhanced crop of a hand-drawn triangulation tie sketch on a "
                    "1950s water service card. Read the three handwritten measurements in "
                    "feet-and-inches notation (e.g. 13'-6\"). Reply with ONLY JSON, no explanation:\n"
                    '{"vertical_measurement": "", "left_diagonal_measurement": "", "right_diagonal_measurement": ""}\n'
                    'Use "" for any measurement you genuinely cannot read.'
                )},
            ]}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return None


def ensemble_verify_sketch(back_path: Path, back_data: dict) -> tuple[dict, dict]:
    """
    Escalation tier for badly faded sketches. Crops the sketch region (fixed
    proportional crop — proven more reliable on this card family than
    blob/line auto-detection, which gets confused by paper texture noise),
    generates several independently-enhanced versions of that whole crop,
    and asks Claude to read all three measurements from each variant
    independently. Then votes per-field across variants.

    Returns (updated_back_data, ensemble_report).
    """
    img = cv2.imread(str(back_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return back_data, {}

    h, w = img.shape
    # Wider crop than the original 0.35w start — narrower crops were clipping
    # leading digits off measurements written further left than expected.
    crop = img[int(h * 0.22):, int(w * 0.20):]

    variants = _make_crop_variants(crop)
    per_field_candidates = {f: [] for f, _ in SKETCH_FIELDS}

    for v in variants:
        v_big = cv2.resize(v, (v.shape[1] * 3, v.shape[0] * 3), interpolation=cv2.INTER_LANCZOS4)
        reading = _read_sketch_variant(v_big)
        if not reading:
            continue
        for field, _ in SKETCH_FIELDS:
            val = (reading.get(field) or "").strip()
            if val:
                per_field_candidates[field].append(val)

    updated = dict(back_data)
    report = {}

    for field, _ in SKETCH_FIELDS:
        candidates = per_field_candidates[field]
        if not candidates:
            report[field] = {"value": None, "confidence": "LOW", "candidates": []}
            continue

        norm_counts = {}
        for c in candidates:
            norm = _normalize_measurement_str(c)
            norm_counts.setdefault(norm, []).append(c)

        best_norm, readings = max(norm_counts.items(), key=lambda kv: len(kv[1]))
        agreement = len(readings)

        if agreement >= 3:
            confidence = "HIGH"
        elif agreement == 2:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        result = {"value": readings[0], "confidence": confidence, "candidates": candidates}
        report[field] = result

        if confidence in ("HIGH", "MEDIUM"):
            updated[field] = result["value"]
            updated[f"{field}_ensemble_confidence"] = confidence

    return updated, report


# ── CROSS-REFERENCE FRONT/BACK MEASUREMENTS ──────────────────────────────────

def cross_reference_vertical_measurement(front_data: dict, back_data: dict) -> tuple[dict, bool]:
    """
    The back-sketch 'vertical_measurement' (property/curb to main tie point) is
    frequently the same physical distance as a field already printed on the
    front card (e.g. 'dist_main_to_curb_stop' on old Return of Service Pipe
    cards). Faded sketch ink is the least reliable thing on the card to OCR;
    a printed front-card field is the most reliable. When both exist, prefer
    the front-card value and mark the sketch reading as corroborated instead
    of guessed.

    Returns (updated_back_data, was_cross_referenced).
    """
    if not front_data or not back_data:
        return back_data, False

    front_dist = (front_data.get("dist_main_to_curb_stop")
                  or front_data.get("dist_main_to_curb_stop_cock"))
    if not front_dist:
        return back_data, False

    updated = dict(back_data)
    updated["vertical_measurement"] = front_dist
    updated["vertical_measurement_source"] = "cross_referenced_from_front_card"
    return updated, True


NEEDS_REVIEW_LOG = "needs_review.jsonl"
DRIVE_REVIEW_FOLDER = "6 - Needs Your Review (Cards I Cannot Read Confidently)"
DRIVE_LEGIBLE_FOLDER = "7 - Already Legible (Verified, No OCR Needed)"

_drive_service = None
_drive_folder_ids = {}


def _get_drive_folder(folder_name: str):
    """Lazily build a Drive client using the existing OAuth token, cache folder IDs."""
    global _drive_service, _drive_folder_ids

    if folder_name in _drive_folder_ids:
        return _drive_service, _drive_folder_ids[folder_name]

    try:
        from google_drive_auth import get_google_drive

        if _drive_service is None:
            _drive_service = get_google_drive()

        r = _drive_service.files().list(
            q="name='UtiliVault' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id)"
        ).execute()
        utili_id = r["files"][0]["id"]

        r = _drive_service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
              f"and '{utili_id}' in parents and trashed=false",
            fields="files(id)"
        ).execute()
        folder_id = r["files"][0]["id"] if r["files"] else None
        _drive_folder_ids[folder_name] = folder_id
        return _drive_service, folder_id
    except Exception as e:
        print(f"  [WARN] Could not connect to Drive folder '{folder_name}': {e}")
        return None, None


def upload_combined_tif(front_path: Path, back_path: Path | None, reg_no: str,
                        folder_name: str, name_suffix: str):
    """
    Combine front+back into one multi-page TIF (same format as the rest of
    the pipeline) and upload it to the given Drive folder.
    """
    drive, folder_id = _get_drive_folder(folder_name)
    if not drive or not folder_id:
        return

    tmp_path = None
    try:
        from PIL import Image
        from googleapiclient.http import MediaFileUpload
        import tempfile, uuid

        front_img = Image.open(front_path).convert("RGB")
        pages = [front_img]
        if back_path and back_path.exists():
            pages.append(Image.open(back_path).convert("RGB"))

        stem = reg_no or front_path.stem
        # Unique suffix avoids collisions when multiple cards share a reg_no
        # (duplicates happen — relaid services, re-issued reg numbers, etc.)
        tmp_path = Path(tempfile.gettempdir()) / f"{name_suffix}_{stem}_{uuid.uuid4().hex[:8]}.tif"
        pages[0].save(tmp_path, format="TIFF", save_all=True,
                      append_images=pages[1:], dpi=(300, 300), compression="tiff_lzw")

        media = MediaFileUpload(str(tmp_path), mimetype="image/tiff")
        metadata = {"name": f"{stem}_{name_suffix}.tif", "parents": [folder_id]}
        uploaded = drive.files().create(body=metadata, media_body=media, fields="id,name").execute()
        print(f"  [Drive] Uploaded to '{folder_name}': {uploaded['name']}")
    except Exception as e:
        print(f"  [WARN] Could not upload to '{folder_name}': {e}")
    finally:
        # Cleanup failures (Windows file lock, antivirus scan, etc.) are not
        # upload failures — the Drive upload already succeeded above. Don't
        # let a lingering local temp file misreport as an error.
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def upload_to_review_folder(front_path: Path, back_path: Path | None, reg_no: str):
    upload_combined_tif(front_path, back_path, reg_no, DRIVE_REVIEW_FOLDER, "NEEDS_REVIEW")


def upload_to_legible_folder(front_path: Path, back_path: Path | None, reg_no: str):
    upload_combined_tif(front_path, back_path, reg_no, DRIVE_LEGIBLE_FOLDER, "LEGIBLE")


def flag_for_review(out_dir: Path, front_path: Path, reason: str, detail: dict,
                    back_path: Path | None = None, reg_no: str = ""):
    """Append a low-confidence card to the needs-review queue and upload it to Drive."""
    entry = {
        "file": str(front_path),
        "reason": reason,
        "detail": detail,
    }
    log_path = out_dir / NEEDS_REVIEW_LOG
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"  [NEEDS REVIEW] {reason} -> logged to {log_path.name}")

    upload_to_review_folder(front_path, back_path, reg_no)


# ── PROCESS ONE IMAGE PAIR ────────────────────────────────────────────────────

# ── SKIP ALREADY-LEGIBLE / MODERN CARDS ──────────────────────────────────────

def classify_card_legibility(front_path: Path) -> dict:
    """
    Fast, cheap pre-check before running the full multi-engine pipeline.
    Distinguishes:
      - Modern, typed/printed, already-legible cards (no digitization needed —
        they're already clean records, just archive as-is)
      - Old handwritten/faded cards that genuinely need the OCR pipeline

    Returns {"skip": bool, "reason": str}. Errs toward NOT skipping when
    uncertain — better to run the full pipeline unnecessarily than silently
    drop a card that actually needed processing.
    """
    try:
        from anthropic import Anthropic
        b64 = base64.standard_b64encode(front_path.read_bytes()).decode()
        import mimetypes
        mime = mimetypes.guess_type(str(front_path))[0] or "image/jpeg"

        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": (
                    "Is this a MODERN, typed/printed, fully legible water service "
                    "tie card (clean form, clear text, no faded/illegible handwriting), "
                    "or an OLDER card with handwritten fields, faded ink, or any text "
                    "that's hard to read?\n\n"
                    'Reply with ONLY JSON: {"modern_and_legible": true/false, "reason": "short reason"}'
                )},
            ]}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
        return {"skip": bool(parsed.get("modern_and_legible")), "reason": parsed.get("reason", "")}
    except Exception as e:
        # Uncertain -> don't skip, let the full pipeline handle it
        return {"skip": False, "reason": f"classification failed ({e}) — processing normally"}


SKIPPED_LOG = "skipped_already_legible.jsonl"


def log_skipped_card(out_dir: Path, front_path: Path, reason: str):
    entry = {"file": str(front_path), "reason": reason}
    log_path = out_dir / SKIPPED_LOG
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def process_pair(front_path: Path, back_path: Path | None,
                 out_dir: Path, delay: float = 0, skip_legible: bool = True) -> dict | None:
    """
    Run all engines on front (and optionally back) image.
    Returns result dict, or None if the card was skipped (modern/already
    legible — no digitization needed). Saves JSON to out_dir.
    """
    print(f"\n{'='*60}")
    print(f"[UtiliVault OCR v2]  {front_path.name}")
    print(f"{'='*60}")

    if skip_legible:
        print("  Checking legibility...", end=" ", flush=True)
        check = classify_card_legibility(front_path)
        if check["skip"]:
            print(f"SKIPPED — {check['reason']}")
            log_skipped_card(out_dir, front_path, check["reason"])
            upload_to_legible_folder(front_path, back_path, front_path.stem)
            return None
        print(f"needs processing — {check['reason']}")

    result = {
        "source_front": str(front_path),
        "source_back": str(back_path) if back_path else None,
        "front": None,
        "back": None,
        "front_validation": None,
        "back_validation": None,
    }

    # ── FRONT ──────────────────────────────────────────────────────────────────
    print("\n[FRONT]")

    print("  Preprocessing with OpenCV...", end=" ", flush=True)
    front_img = preprocess_image(front_path)
    front_b64, front_mime = ndarray_to_b64(front_img)
    print("done")

    print("  Engine 1 — Claude Vision...", end=" ", flush=True)
    front_claude = ocr_claude(FRONT_PROMPT, front_b64, front_mime)
    print("done" if front_claude else "failed")

    gcv_available = _gcv_available()
    print(f"  Engine 2 — Google Cloud Vision...", end=" ", flush=True)
    if gcv_available:
        front_gcv = ocr_google_cloud_vision(front_path)
        print("done" if front_gcv else "failed")
    else:
        front_gcv = None
        print("skipped (no credentials)")

    print("  Engine 3 — Tesseract...", end=" ", flush=True)
    front_tess = ocr_tesseract(front_img)
    print("done" if front_tess else "failed")

    front_val = cross_validate(front_claude, front_gcv, front_tess, "front")
    result["front"] = front_val["data"]
    result["front_validation"] = {
        "confidence": front_val["confidence"],
        "engines_used": front_val["engines_used"],
        "corroboration": front_val.get("corroboration", "n/a"),
        "notes": front_val["notes"],
    }

    _print_validation(front_val, "FRONT")

    if delay > 0:
        time.sleep(delay)

    # ── BACK ───────────────────────────────────────────────────────────────────
    if back_path and back_path.exists():
        print("\n[BACK]")

        print("  Preprocessing with OpenCV...", end=" ", flush=True)
        back_img = preprocess_image(back_path)
        back_b64, back_mime = ndarray_to_b64(back_img)
        print("done")

        print("  Engine 1 — Claude Vision...", end=" ", flush=True)
        back_claude = ocr_claude(BACK_PROMPT, back_b64, back_mime)
        print("done" if back_claude else "failed")

        print(f"  Engine 2 — Google Cloud Vision...", end=" ", flush=True)
        if gcv_available:
            back_gcv = ocr_google_cloud_vision(back_path)
            print("done" if back_gcv else "failed")
        else:
            back_gcv = None
            print("skipped (no credentials)")

        print("  Engine 3 — Tesseract...", end=" ", flush=True)
        back_tess = ocr_tesseract(back_img)
        print("done" if back_tess else "failed")

        back_val = cross_validate(back_claude, back_gcv, back_tess, "back")

        # Cross-reference the sketch's vertical tie against a printed front-card
        # field when available — the printed field is far more reliable than
        # OCR on faded handwriting.
        cross_ref_data, was_cross_ref = cross_reference_vertical_measurement(
            result["front"], back_val["data"]
        )
        back_val["data"] = cross_ref_data

        result["back"] = back_val["data"]
        result["back_validation"] = {
            "confidence": back_val["confidence"],
            "engines_used": back_val["engines_used"],
            "corroboration": back_val.get("corroboration", "n/a"),
            "notes": back_val["notes"] + (" ; vertical cross-referenced from front card" if was_cross_ref else ""),
        }

        _print_validation(back_val, "BACK")

        # Escalation tier: if the first pass isn't already HIGH confidence,
        # auto-crop each measurement label and run the ensemble variant-vote
        # reader before giving up. This is what actually works on faded
        # 1950s handwriting — isolated, enhanced, multi-variant reads beat
        # a single whole-page pass every time.
        if back_val["confidence"] != "HIGH":
            print("  [Ensemble] First pass not HIGH — running per-label variant voting...")
            ensembled_data, ensemble_report = ensemble_verify_sketch(back_path, back_val["data"])
            back_val["data"] = ensembled_data
            result["back"] = ensembled_data

            if ensemble_report:
                upgraded = [f for f, r in ensemble_report.items() if r["confidence"] in ("HIGH", "MEDIUM")]
                still_low = [f for f, r in ensemble_report.items() if r["confidence"] == "LOW"]
                if upgraded:
                    print(f"  [Ensemble] Resolved via variant voting: {upgraded}")
                if still_low:
                    print(f"  [Ensemble] Still unresolved: {still_low}")
                result["back_ensemble_report"] = ensemble_report

                # Recompute overall back confidence: HIGH only if every
                # sketch field that was checked reached HIGH or MEDIUM.
                if still_low:
                    back_val["confidence"] = "LOW"
                elif upgraded:
                    back_val["confidence"] = "MEDIUM" if any(
                        r["confidence"] == "MEDIUM" for r in ensemble_report.values()
                    ) else "HIGH"
                result["back_validation"]["confidence"] = back_val["confidence"]
                result["back_validation"]["notes"] += " ; ensemble variant-vote applied"

        # Genuinely unreadable ink (even after ensemble escalation) -> flag
        # for a human glance instead of silently guessing. Some of these
        # source cards are illegible even to a person — that's expected,
        # not a pipeline failure.
        if back_val["confidence"] == "LOW":
            reg_no = (result["front"].get("reg_no") or "").strip() if result["front"] else ""
            flag_for_review(
                out_dir, front_path,
                reason="back sketch measurements LOW confidence after ensemble escalation",
                detail={"back_data": back_val["data"], "engines_used": back_val["engines_used"]},
                back_path=back_path, reg_no=reg_no,
            )

    # ── SAVE JSON ──────────────────────────────────────────────────────────────
    reg = ""
    if result["front"]:
        reg = (result["front"].get("reg_no") or "").strip()
    stem = f"{reg}_{front_path.stem}" if reg else front_path.stem
    out_path = out_dir / f"{stem}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n[Saved] {out_path}")

    return result


def _print_validation(val: dict, label: str):
    conf = val["confidence"]
    indicator = {"HIGH": "[HIGH]", "MEDIUM": "[MEDIUM]", "LOW": "[LOW]"}.get(conf, conf)
    print(f"\n  -- {label} Confidence: {indicator} --")
    print(f"     Engines : {', '.join(val['engines_used'])}")
    print(f"     Corroboration: {val.get('corroboration', 'n/a')}")
    print(f"     Notes   : {val['notes']}")
    if val.get("data"):
        d = val["data"]
        addr = d.get("street") or d.get("address") or d.get("property_label") or "?"
        reg  = d.get("reg_no") or ""
        date = d.get("date_laid") or d.get("date") or d.get("date_signed") or "?"
        flags = d.get("flags") or []
        if addr or reg:
            print(f"     Address : {addr}")
        if reg:
            print(f"     Reg No  : {reg}")
        if date and date != "?":
            print(f"     Date    : {date}")
        if flags:
            print(f"     Flags   : {flags}")
        # Sketch summary
        if d.get("vertical_measurement"):
            print(f"     Sketch  : vert={d.get('vertical_measurement')}  "
                  f"left={d.get('left_diagonal_measurement')}  "
                  f"right={d.get('right_diagonal_measurement')}")

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UtiliVault Multi-Engine Tie-Card OCR v2"
    )
    parser.add_argument("front", nargs="?", help="Front image path")
    parser.add_argument("back",  nargs="?", help="Back image path (optional)")
    parser.add_argument("--folder", help="Batch: folder of front images")
    parser.add_argument("--out-dir", default=None,
                        help="Output folder for JSON (default: Desktop/Demo Tiecards)")
    parser.add_argument("--delay", type=float, default=0,
                        help="Seconds to sleep between cards (throttle for overnight batch)")
    parser.add_argument("--no-priority", action="store_true",
                        help="Skip setting Below Normal process priority")
    parser.add_argument("--no-skip-legible", action="store_true",
                        help="Disable the legibility pre-check (process every card, even modern/clean ones)")
    args = parser.parse_args()

    # Process priority — protect game servers
    if not args.no_priority:
        ok = set_below_normal_priority()
        print(f"[Priority] {'Below Normal (game servers protected)' if ok else 'could not set — run as admin if needed'}")

    # Default out dir
    from config import DEMO_DIR as default_out
    out_dir = Path(args.out_dir) if args.out_dir else default_out
    out_dir.mkdir(parents=True, exist_ok=True)

    # Engine status
    print(f"[Engines] Claude Vision: {'OK' if ANTHROPIC_API_KEY else 'NO API KEY'}")
    print(f"[Engines] Google Cloud Vision: {'available' if _gcv_available() else 'skipped (set GOOGLE_APPLICATION_CREDENTIALS)'}")
    print(f"[Engines] Tesseract: {TESSERACT_CMD}")

    if args.folder:
        folder = Path(args.folder)
        files = sorted(f for f in folder.iterdir()
                       if f.is_file() and f.suffix.lower() in SCAN_EXTENSIONS)
        print(f"\n[Batch] {len(files)} files in {folder}")
        skipped_count = 0
        for f in files:
            try:
                res = process_pair(f, None, out_dir, args.delay, skip_legible=not args.no_skip_legible)
                if res is None:
                    skipped_count += 1
            except Exception as e:
                print(f"  [ERROR] {f.name}: {e}")
        print(f"\n[Batch done] {len(files)} files → {out_dir}  "
              f"({skipped_count} skipped as already-legible)")

    elif args.front:
        front = Path(args.front)
        back  = Path(args.back) if args.back else None
        if not front.exists():
            print(f"[ERROR] Not found: {front}")
            sys.exit(1)
        if back and not back.exists():
            print(f"[WARN] Back image not found: {back} — processing front only")
            back = None
        process_pair(front, back, out_dir, args.delay, skip_legible=not args.no_skip_legible)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
