"""
UtiliVault — tiecard_sketch.py
Accurate tie sketch reproduction via OpenCV line tracing

Strategy for 100% geometric + measurement accuracy:
  1. Find the sketch area on the back-page scan (adaptive detection)
  2. Clean the image using scikit-image Sauvola adaptive thresholding
     (handles uneven illumination on old faded 1950s cards far better than OTSU)
  3. Detect ALL structural lines via OpenCV HoughLinesP
     - Long lines = service line, diagonals, main, box edges
     - Short strokes = handwriting (excluded by min-length filter)
  4. Detect rectangular boxes (property box, reference box)
  5. Crop label regions around each line midpoint
  6. Run EasyOCR independently on each label crop
  7. Compare EasyOCR reads against Claude's extracted measurements:
     - Both agree  → high confidence, locked in
     - EasyOCR only → use EasyOCR, mark moderate confidence
     - Claude only  → use Claude, mark moderate confidence
     - Both disagree → flag card for manual review
  8. Build clean SVG from detected geometry with verified measurement labels

Fallback chain:
  - < 3 structural lines detected → embed cleaned image directly (geometry still right)
  - EasyOCR unavailable → skip verification, use Claude measurements as-is
  - scikit-image unavailable → fall back to CLAHE+OTSU

Requirements:
  pip install opencv-python pillow numpy scikit-image easyocr
"""

import base64
import io
import math
import re
import sys
from pathlib import Path


# ── IMAGE LOADING ─────────────────────────────────────────────────────────────

def load_back_page(tif_path: Path, page: int = 1):
    """Load one page of a TIF as a numpy array (grayscale)."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("[ERROR] pillow/numpy not installed")
        sys.exit(1)

    img = Image.open(tif_path)
    try:
        img.seek(page)
    except EOFError:
        img.seek(0)

    return np.array(img.convert("L"))


def pil_to_b64(pil_img) -> str:
    """Convert a PIL image to a base64 PNG data URI."""
    buf = io.BytesIO()
    pil_img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.standard_b64encode(buf.getvalue()).decode()


# ── SKETCH AREA DETECTION ─────────────────────────────────────────────────────

def find_sketch_region(gray):
    """
    Find the bounding box of the hand-drawn sketch on the back page.
    The sketch is the densest non-uniform cluster of ink on the page.
    Returns (x, y, w, h) or None if not found.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    h, w = gray.shape

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    dilated = cv2.dilate(binary, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    candidates = []
    for c in contours:
        cx, cy, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < (w * h * 0.01):
            continue
        if cw > w * 0.85:
            continue
        center_y = cy + ch // 2
        score = area * (center_y / h)
        candidates.append((score, cx, cy, cw, ch))

    if not candidates:
        return (w // 2, h // 3, w // 2, h * 2 // 3)

    candidates.sort(reverse=True)
    _, cx, cy, cw, ch = candidates[0]

    pad = 20
    x = max(0, cx - pad)
    y = max(0, cy - pad)
    w2 = min(w - x, cw + pad * 2)
    h2 = min(h - y, ch + pad * 2)
    return (x, y, w2, h2)


# ── IMAGE CLEANING ────────────────────────────────────────────────────────────

def clean_sketch_image(gray_crop):
    """
    Clean a sketch crop for maximum legibility.

    Uses scikit-image Sauvola adaptive thresholding when available — far better
    than global OTSU on 1950s cards with faded ink and uneven paper aging.
    Falls back to CLAHE+OTSU if scikit-image is not installed.

    Returns a PIL Image (binary, white ink on white bg) ready for embedding.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
        HAS_CV2 = True
    except ImportError:
        HAS_CV2 = False

    try:
        from skimage.filters import threshold_sauvola
        from skimage.morphology import remove_small_objects
        import numpy as np
        HAS_SKIMAGE = True
    except ImportError:
        HAS_SKIMAGE = False

    if HAS_CV2:
        # Step 1: Denoise
        denoised = cv2.fastNlMeansDenoising(gray_crop, h=12, templateWindowSize=7, searchWindowSize=21)

        # Step 2: Sharpen
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(denoised, -1, kernel)
    else:
        sharpened = gray_crop

    if HAS_SKIMAGE and HAS_CV2:
        # Sauvola thresholding: computes a local threshold per pixel window.
        # Handles yellowed paper, faded ink, and shadow gradients on old scans.
        thresh = threshold_sauvola(sharpened, window_size=51, k=0.2)
        binary_bool = sharpened > thresh   # True = background (light), False = ink (dark)

        # Convert to uint8 (255 = background, 0 = ink — matches OpenCV convention)
        binary = np.where(binary_bool, 255, 0).astype(np.uint8)

        # Remove tiny noise specks (< 64px²) that would confuse HoughLinesP
        try:
            ink_mask = (binary == 0)
            cleaned_mask = remove_small_objects(ink_mask, min_size=64)
            binary = np.where(cleaned_mask, 0, 255).astype(np.uint8)
        except Exception:
            pass

        from PIL import Image
        return Image.fromarray(binary)

    elif HAS_CV2:
        # Fallback: CLAHE + OTSU
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(sharpened)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        from PIL import Image
        return Image.fromarray(binary)

    else:
        from PIL import Image, ImageEnhance, ImageFilter
        pil = Image.fromarray(gray_crop)
        pil = ImageEnhance.Contrast(pil).enhance(3.5)
        pil = ImageEnhance.Sharpness(pil).enhance(2.5)
        return pil


# ── LINE DETECTION ────────────────────────────────────────────────────────────

def detect_structural_lines(gray_crop, min_line_length_frac: float = 0.08):
    """
    Detect long structural lines (the actual drawn sketch geometry).
    Excludes short strokes that are handwriting.

    Returns list of (x1, y1, x2, y2) in crop coordinates.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    h, w = gray_crop.shape
    min_len = max(30, int(min(w, h) * min_line_length_frac))

    _, binary = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=math.pi / 180,
        threshold=40,
        minLineLength=min_len,
        maxLineGap=12,
    )

    if lines is None:
        return []

    result = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        if length >= min_len:
            result.append((x1, y1, x2, y2))

    return result


def detect_boxes(gray_crop):
    """
    Detect rectangular boxes (property box, reference box).
    Returns list of (x, y, w, h) in crop coordinates.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    _, binary = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = gray_crop.shape
    boxes = []
    for c in contours:
        approx = cv2.approxPolyDP(c, 0.04 * cv2.arcLength(c, True), True)
        if len(approx) == 4:
            bx, by, bw, bh = cv2.boundingRect(approx)
            area = bw * bh
            if area > (w * h * 0.005) and 0.2 < (bw / max(bh, 1)) < 6:
                boxes.append((bx, by, bw, bh))

    return boxes


# ── LINE CLASSIFICATION ───────────────────────────────────────────────────────

def classify_lines(lines, crop_w, crop_h):
    """
    Classify detected lines by angle and position into sketch roles:
      - 'vertical'   : service line (near-vertical, upper portion)
      - 'horizontal' : main water line (near-horizontal, middle)
      - 'diagonal_l' : left tie diagonal
      - 'diagonal_r' : right tie diagonal
      - 'box_edge'   : rectangle boundary
      - 'other'      : unclassified

    Returns list of (x1, y1, x2, y2, role) tuples.
    """
    classified = []
    for x1, y1, x2, y2 in lines:
        dx = x2 - x1
        dy = y2 - y1
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        if angle > 75:
            if crop_w * 0.3 < cx < crop_w * 0.7:
                role = "vertical"
            else:
                role = "box_edge"
        elif angle < 15:
            if crop_h * 0.3 < cy < crop_h * 0.8:
                role = "horizontal"
            else:
                role = "box_edge"
        else:
            if min(x1, x2) < crop_w * 0.45:
                role = "diagonal_l"
            else:
                role = "diagonal_r"

        classified.append((x1, y1, x2, y2, role))

    return classified


# ── EASYOCR MEASUREMENT VERIFICATION ─────────────────────────────────────────

def _normalize_measurement(s: str) -> str:
    """Normalize a measurement string for comparison (strip formatting noise)."""
    if not s:
        return ""
    # Remove spaces, curly quotes, straight quotes, apostrophes
    s = s.strip().lower()
    s = re.sub(r"[‘’“”'\"`,]", "", s)
    s = re.sub(r"\s+", "", s)
    # Normalize foot/inch separators: 11-6, 11'6, 116 all → 116
    s = re.sub(r"[-'/\\]", "", s)
    return s


def crop_label_region(gray_crop, x1, y1, x2, y2, pad_frac=0.12):
    """
    Crop the region around a line's midpoint where the measurement label sits.
    pad_frac controls how wide the crop window is relative to crop dimensions.
    """
    h, w = gray_crop.shape
    mx = (x1 + x2) // 2
    my = (y1 + y2) // 2
    pad_x = max(30, int(w * pad_frac))
    pad_y = max(20, int(h * pad_frac * 0.6))

    rx1 = max(0, mx - pad_x)
    ry1 = max(0, my - pad_y)
    rx2 = min(w, mx + pad_x)
    ry2 = min(h, my + pad_y)

    return gray_crop[ry1:ry2, rx1:rx2]


def verify_measurements_easyocr(gray_crop, classified_lines, claude_measurements: dict) -> dict:
    """
    Run EasyOCR on the label crop for each measurement line and compare to
    Claude's reading. Returns a verification dict:

    {
      "vertical_measurement":        {"claude": "11'-6\"", "easyocr": "11-6", "agreed": True,  "confidence": "high", "final": "11'-6\""},
      "left_diagonal_measurement":   {"claude": "23'",     "easyocr": "23",   "agreed": True,  "confidence": "high", "final": "23'"},
      "right_diagonal_measurement":  {"claude": "7'",      "easyocr": "17",   "agreed": False, "confidence": "low",  "final": "7'",  "flag": True},
    }

    confidence levels:
      "high"     — both Claude and EasyOCR agree (after normalization)
      "moderate" — only one source has a reading
      "low"      — both read something but they disagree → flag for review
    """
    try:
        import easyocr
        import numpy as np
    except ImportError:
        return {}

    # Only try to verify fields that have detected lines
    role_to_field = {
        "vertical":   "vertical_measurement",
        "diagonal_l": "left_diagonal_measurement",
        "diagonal_r": "right_diagonal_measurement",
    }

    # Collect one line per role (longest wins)
    best_lines = {}
    for x1, y1, x2, y2, role in classified_lines:
        if role not in role_to_field:
            continue
        length = math.sqrt((x2-x1)**2 + (y2-y1)**2)
        if role not in best_lines or length > best_lines[role][4]:
            best_lines[role] = (x1, y1, x2, y2, length)

    if not best_lines:
        return {}

    # Initialize EasyOCR (English only, no GPU needed)
    try:
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception as e:
        print(f"  [WARN] EasyOCR init failed: {e}")
        return {}

    results = {}
    for role, (x1, y1, x2, y2, _) in best_lines.items():
        field = role_to_field[role]
        claude_val = claude_measurements.get(field) or ""

        crop = crop_label_region(gray_crop, x1, y1, x2, y2)
        if crop.size == 0:
            continue

        try:
            # EasyOCR returns list of (bbox, text, confidence)
            ocr_results = reader.readtext(crop, detail=1, paragraph=False)
            # Take the highest-confidence reading
            if ocr_results:
                ocr_results.sort(key=lambda r: r[2], reverse=True)
                easyocr_val = ocr_results[0][1].strip()
                easyocr_conf = ocr_results[0][2]
            else:
                easyocr_val = ""
                easyocr_conf = 0.0
        except Exception as e:
            print(f"  [WARN] EasyOCR failed on {field}: {e}")
            easyocr_val = ""
            easyocr_conf = 0.0

        claude_norm   = _normalize_measurement(claude_val)
        easyocr_norm  = _normalize_measurement(easyocr_val)

        both_have = bool(claude_norm) and bool(easyocr_norm)
        agreed    = both_have and (claude_norm == easyocr_norm)

        if agreed:
            confidence = "high"
            final      = claude_val  # Claude has better formatting (feet/inches notation)
            flag       = False
        elif both_have and not agreed:
            confidence = "low"
            final      = claude_val  # Claude is usually better at context; flag for review
            flag       = True
        elif claude_norm and not easyocr_norm:
            confidence = "moderate"
            final      = claude_val
            flag       = False
        elif easyocr_norm and not claude_norm:
            confidence = "moderate"
            final      = easyocr_val
            flag       = False
        else:
            confidence = "low"
            final      = ""
            flag       = False

        entry = {
            "claude":     claude_val,
            "easyocr":    easyocr_val,
            "easyocr_conf": round(easyocr_conf, 3),
            "agreed":     agreed,
            "confidence": confidence,
            "final":      final,
        }
        if flag:
            entry["flag"] = True

        results[field] = entry

    return results


def apply_verified_measurements(claude_measurements: dict, verification: dict) -> tuple[dict, list]:
    """
    Merge verification results back into the measurements dict.
    Returns (updated_measurements, conflict_flags).
    """
    updated = dict(claude_measurements)
    conflicts = []

    for field, v in verification.items():
        updated[field] = v["final"]
        if v.get("flag"):
            conflicts.append(
                f"{field}: Claude='{v['claude']}' vs EasyOCR='{v['easyocr']}' — verify against scan"
            )

    return updated, conflicts


# ── SVG BUILDER FROM DETECTED GEOMETRY ───────────────────────────────────────

def build_svg_from_geometry(
    classified_lines,
    boxes,
    measurements: dict,
    crop_w: int,
    crop_h: int,
    canvas_w: int = 560,
    canvas_h: int = 420,
    conflicts: list = None,
) -> str:
    """
    Convert detected lines and boxes into a clean SVG.
    Overlays verified measurement labels.
    Adds a small conflict banner at the bottom if any measurements disagreed.
    """
    sx = canvas_w / crop_w
    sy = canvas_h / crop_h

    def tx(x): return round(x * sx, 1)
    def ty(y): return round(y * sy, 1)

    vert_meas   = measurements.get("vertical_measurement") or ""
    left_meas   = measurements.get("left_diagonal_measurement") or ""
    right_meas  = measurements.get("right_diagonal_measurement") or ""
    main_label  = measurements.get("main_label") or "W. MAIN"
    ref_label   = measurements.get("reference_structure_label") or ""
    ref_number  = measurements.get("reference_structure_number") or ""
    prop_label  = measurements.get("property_label") or ""

    svg = (f'<svg viewBox="0 0 {canvas_w} {canvas_h}" width="100%"'
           f' xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif"'
           f' style="display:block;background:#FFFDE0">\n')

    # Draw boxes first (background)
    for bx, by, bw, bh in boxes:
        svg += (f'  <rect x="{tx(bx)}" y="{ty(by)}" width="{tx(bw)}" height="{ty(bh)}"'
                f' fill="#FFFDE0" stroke="#000" stroke-width="2"/>\n')

    role_styles = {
        "vertical":   ('stroke="#000" stroke-width="2.5"', vert_meas),
        "horizontal": ('stroke="#000" stroke-width="3"',   main_label),
        "diagonal_l": ('stroke="#000" stroke-width="2.5"', left_meas),
        "diagonal_r": ('stroke="#000" stroke-width="2.5"', right_meas),
        "box_edge":   ('stroke="#000" stroke-width="2"',   ""),
        "other":      ('stroke="#888" stroke-width="1"',   ""),
    }

    # Draw lines
    for x1, y1, x2, y2, role in classified_lines:
        style, _ = role_styles.get(role, role_styles["other"])
        svg += f'  <line x1="{tx(x1)}" y1="{ty(y1)}" x2="{tx(x2)}" y2="{ty(y2)}" {style}/>\n'

    # Overlay measurement labels
    label_done = set()
    for x1, y1, x2, y2, role in classified_lines:
        _, label = role_styles.get(role, ("", ""))
        if not label or role in label_done:
            continue
        label_done.add(role)

        mx = tx((x1 + x2) / 2)
        my = ty((y1 + y2) / 2)
        dx = tx(x2) - tx(x1)
        dy = ty(y2) - ty(y1)
        angle = math.degrees(math.atan2(dy, dx))

        if role == "horizontal":
            svg += (f'  <text x="{tx(x1) + 4}" y="{ty(y1) - 5}"'
                    f' font-size="11" font-weight="bold" fill="#000">{_esc(label)}</text>\n')
        elif role == "vertical":
            svg += (f'  <text x="{mx + 6}" y="{my}"'
                    f' font-size="12" font-weight="bold" fill="#000">{_esc(label)}</text>\n')
        else:
            svg += (f'  <text x="{mx}" y="{my}" font-size="12" font-weight="bold" fill="#000"'
                    f' transform="rotate({angle:.1f},{mx},{my})" text-anchor="middle" dy="-6">'
                    f'{_esc(label)}</text>\n')

    # Property label on topmost box
    if boxes and prop_label:
        top_box = min(boxes, key=lambda b: b[1])
        bx, by, bw, bh = top_box
        cx = tx(bx + bw / 2)
        cy = ty(by + bh / 2)
        svg += (f'  <text x="{cx}" y="{cy - 4}" text-anchor="middle"'
                f' font-size="11" font-weight="bold" fill="#000">{_esc(prop_label)}</text>\n')

    # Reference label on bottommost box
    if boxes and (ref_label or ref_number):
        bot_box = max(boxes, key=lambda b: b[1] + b[3])
        bx, by, bw, bh = bot_box
        cx = tx(bx + bw / 2)
        if ref_label:
            svg += (f'  <text x="{cx}" y="{ty(by + bh/2 - 6)}" text-anchor="middle"'
                    f' font-size="12" font-weight="bold" fill="#000">{_esc(ref_label)}</text>\n')
        if ref_number:
            svg += (f'  <text x="{cx}" y="{ty(by + bh/2 + 10)}" text-anchor="middle"'
                    f' font-size="11" fill="#333">{_esc(ref_number)}</text>\n')

    # Conflict banner (measurement disagreements between Claude + EasyOCR)
    if conflicts:
        banner_y = canvas_h - 10 - 14 * len(conflicts)
        svg += (f'  <rect x="0" y="{banner_y - 14}" width="{canvas_w}" height="{14 * len(conflicts) + 10}"'
                f' fill="rgba(255,220,0,0.7)"/>\n')
        for i, msg in enumerate(conflicts):
            svg += (f'  <text x="6" y="{banner_y + i * 14}" font-size="9" fill="#7a4f00"'
                    f' font-style="italic">&#9888; {_esc(msg[:100])}</text>\n')

    svg += "</svg>\n"
    return svg


# ── FALLBACK: CLEAN IMAGE EMBED ───────────────────────────────────────────────

def build_svg_image_embed(clean_pil_img, measurements: dict, original_w: int, original_h: int) -> str:
    """
    Fallback: embed the cleaned sketch image directly in SVG.
    Pixel-perfect geometry; overlays clean measurement labels.
    """
    canvas_w = 560
    canvas_h = int(560 * original_h / original_w)
    data_uri = pil_to_b64(clean_pil_img)

    vert_meas  = measurements.get("vertical_measurement") or ""
    left_meas  = measurements.get("left_diagonal_measurement") or ""
    right_meas = measurements.get("right_diagonal_measurement") or ""
    main_label = measurements.get("main_label") or "W. MAIN"
    ref_label  = measurements.get("reference_structure_label") or ""
    ref_number = measurements.get("reference_structure_number") or ""

    svg = (f'<svg viewBox="0 0 {canvas_w} {canvas_h}" width="100%"'
           f' xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif"'
           f' style="display:block;background:#FFFDE0">\n')

    svg += (f'  <image href="{data_uri}" x="0" y="0"'
            f' width="{canvas_w}" height="{canvas_h}" opacity="0.92"/>\n')

    if ref_label or ref_number:
        svg += (f'  <rect x="0" y="{canvas_h - 40}" width="{canvas_w}" height="40"'
                f' fill="rgba(255,255,220,0.7)"/>\n')
        if ref_label:
            svg += (f'  <text x="{canvas_w//2}" y="{canvas_h - 22}" text-anchor="middle"'
                    f' font-size="13" font-weight="bold" fill="#000">{_esc(ref_label)}</text>\n')
        if ref_number:
            svg += (f'  <text x="{canvas_w//2}" y="{canvas_h - 6}" text-anchor="middle"'
                    f' font-size="11" fill="#333">{_esc(ref_number)}</text>\n')

    svg += "</svg>\n"
    return svg


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def render_sketch(tif_path: Path, measurements: dict, page: int = 1) -> str:
    """
    Full pipeline:
      load TIF back page
      → Sauvola-clean image
      → OpenCV detect lines + boxes
      → EasyOCR verify each measurement label
      → build clean SVG with verified measurements

    If vectorization yields < 3 lines, falls back to image embed.
    If EasyOCR is unavailable, skips verification silently.

    Returns SVG string ready to embed in HTML.
    """
    try:
        import cv2
        import numpy as np
        HAS_CV2 = True
    except ImportError:
        HAS_CV2 = False
        print("  [WARN] opencv-python not installed — using image-embed fallback")

    try:
        import easyocr
        HAS_EASYOCR = True
    except ImportError:
        HAS_EASYOCR = False

    try:
        from skimage.filters import threshold_sauvola
        HAS_SKIMAGE = True
    except ImportError:
        HAS_SKIMAGE = False

    # 1. Load back page
    gray = load_back_page(tif_path, page)
    orig_h, orig_w = gray.shape

    # 2. Find sketch region
    region = find_sketch_region(gray) if HAS_CV2 else None
    if region:
        rx, ry, rw, rh = region
        gray_crop = gray[ry:ry+rh, rx:rx+rw]
    else:
        gray_crop = gray[orig_h // 3:, orig_w // 3:]

    crop_h, crop_w = gray_crop.shape

    # 3. Clean the image (Sauvola if available, else CLAHE+OTSU)
    clean_pil = clean_sketch_image(gray_crop)
    method_note = "Sauvola" if HAS_SKIMAGE else "CLAHE+OTSU"

    if not HAS_CV2:
        return build_svg_image_embed(clean_pil, measurements, crop_w, crop_h)

    # 4. Detect lines and boxes
    lines = detect_structural_lines(gray_crop)
    boxes = detect_boxes(gray_crop)

    if len(lines) < 3:
        print(f"  [INFO] Only {len(lines)} structural lines detected — using image-embed mode")
        return build_svg_image_embed(clean_pil, measurements, crop_w, crop_h)

    # 5. Classify lines by role
    classified = classify_lines(lines, crop_w, crop_h)

    # 6. EasyOCR measurement verification
    verified_measurements = dict(measurements)
    conflicts = []

    if HAS_EASYOCR:
        print(f"  [OCR] Running EasyOCR measurement verification...", end=" ", flush=True)
        try:
            verification = verify_measurements_easyocr(gray_crop, classified, measurements)
            if verification:
                verified_measurements, conflicts = apply_verified_measurements(measurements, verification)
                agreed  = sum(1 for v in verification.values() if v["agreed"])
                flagged = sum(1 for v in verification.values() if v.get("flag"))
                print(f"done — {agreed}/{len(verification)} agreed, {flagged} flagged")
                for c in conflicts:
                    print(f"  [FLAG] {c}")
            else:
                print("no label regions found")
        except Exception as e:
            print(f"error ({e})")
    else:
        print(f"  [INFO] EasyOCR not available — using Claude measurements only")

    # 7. Build clean SVG
    print(f"  [Sketch] {len(lines)} lines, {len(boxes)} boxes — vectorizing ({method_note})")
    return build_svg_from_geometry(
        classified, boxes, verified_measurements, crop_w, crop_h, conflicts=conflicts
    )


def _esc(s: str) -> str:
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── CLI (test a single TIF) ───────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Test sketch extraction on a TIF file")
    parser.add_argument("tif", help="TIF file to process")
    parser.add_argument("--measurements", default="{}", help="JSON measurements from tiecard_ocr.py back field")
    parser.add_argument("--out", default="sketch_test.html")
    args = parser.parse_args()

    meas = json.loads(args.measurements)
    svg  = render_sketch(Path(args.tif), meas)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Sketch Test — {Path(args.tif).name}</title>
<style>body{{background:#f0f0f0;padding:30px;font-family:Arial}}
.wrap{{background:#FFFDE0;border:2px solid #999900;padding:14px;max-width:620px;margin:0 auto}}
p{{font-size:11px;color:#666;margin-bottom:10px}}</style>
</head><body>
<div class="wrap">
<p>Sketch test — {Path(args.tif).name} | OpenCV + Sauvola + EasyOCR pipeline</p>
{svg}
</div></body></html>"""

    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Saved: {args.out}")
