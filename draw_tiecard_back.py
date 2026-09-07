"""
UtiliVault — draw_tiecard_back.py
Manual-entry back-page tiecard drafter.

When a technician reads the measurements directly off a physical card (the
most reliable source for faded/century-old cards), this tool draws a clean,
accurate back-page tie sketch from those supplied numbers — no OCR, no
guessing. It reuses the exact rendering engine from build_comparisons.py so
the output matches the rest of the system.

Three ways to supply measurements:

  1. Command-line flags (single card):
     py draw_tiecard_back.py --reg 7424 --address "100 UtiliVault Demo Way" \
        --vertical "11'-6\"" --left "70'-3\"" --right "71'-5\"" \
        --ref-label "Old Conn Path" --main-label "6\" CI" --upload

  2. Interactive prompt (single card, guided):
     py draw_tiecard_back.py --interactive

  3. Batch from a JSON file (many cards at once):
     py draw_tiecard_back.py --json cards.json --upload
     where cards.json is a list of objects with the same field names.

Output: a rendered back-page PNG + a TIF sized to the blank template, and
(optionally) uploaded to a chosen Drive folder. Front page can be attached
into a combined 2-page TIF if a front image is supplied.
"""

import argparse
import json
import sys
import textwrap
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from build_comparisons import draw_sketch_diagram, _double_curb_pair, _font

from config import MANUAL_DIR as OUT_DIR, DIGITAL_DIR
OUT_DIR.mkdir(parents=True, exist_ok=True)
# Digital-only cards (front + back + real house photo page). Kept in a separate
# folder so the printable pipeline never picks up the screen-only photo pages.
DIGITAL_DIR.mkdir(parents=True, exist_ok=True)

# Blank Water Service Tie Card back dimensions (matches the templates in Drive)
BACK_W, BACK_H = 1715, 1153

APPLICATION_TEXT = (
    "The undersigned requests that a service pipe be laid to the property "
    "designated, and hereby agrees to take and use water, subject at all "
    "times to the current rules and regulations established by the "
    "Commissioners of Public Works."
)


def render_front_page(card: dict) -> Image.Image:
    """
    Render the FRONT of the Water Service Tie Card, filled with the same
    supplied information: address/street, reg no, main size + material, and
    the tie measurements summarized in the comments. Pairs with the back
    page to form a complete two-page card.
    """
    img = Image.new("RGB", (BACK_W, BACK_H), "#FFFF99")   # yellow card
    draw = ImageDraw.Draw(img)

    f_title = _font(34, bold=True)
    f_lbl = _font(20, bold=True)
    f_val = _font(22)

    m = 40
    W = BACK_W
    x0, x1 = m, W - m
    y = 30

    # Title
    title = "WATER SERVICE TIE CARD"
    tb = draw.textbbox((0, 0), title, font=f_title)
    draw.text(((W - (tb[2]-tb[0])) // 2, y), title, font=f_title, fill="#000")
    y += 52
    draw.line([(x0, y), (x1, y)], fill="#999900", width=3)

    row_h = 74
    midx = (x0 + x1) // 2

    def cell(cx, cy, label, value):
        draw.text((cx + 12, cy + 8), label, font=f_lbl, fill="#000")
        if value:
            draw.text((cx + 12, cy + 38), str(value), font=f_val, fill="#00008B")

    def row(cy, left_pair, right_pair=None):
        draw.line([(x0, cy + row_h), (x1, cy + row_h)], fill="#999900", width=2)
        if right_pair is not None:
            draw.line([(midx, cy), (midx, cy + row_h)], fill="#999900", width=2)
            cell(x0, cy, left_pair[0], left_pair[1])
            cell(midx, cy, right_pair[0], right_pair[1])
        else:
            cell(x0, cy, left_pair[0], left_pair[1])

    main_size = card.get("main_size") or ""
    main_material = card.get("main_material") or ""
    # If only a composed main_label exists, split sensibly for the fields
    if not (main_size or main_material) and card.get("main_label"):
        parts = str(card["main_label"]).split()
        if parts:
            main_size = parts[0]
            main_material = " ".join(parts[1:])

    addr = card.get("address") or card.get("property_label") or ""

    row(y, ("Address:", addr), ("Reg. No:", card.get("reg_no") or ""))
    y += row_h
    row(y, ("Contractor:", card.get("contractor") or ""), ("Date:", card.get("date") or ""))
    y += row_h
    row(y, ("Inspected By:", card.get("inspected_by") or ""))
    y += row_h
    row(y, ("Material Main:", main_material), ("Diameter Main:", main_size))
    y += row_h
    row(y, ("Material Service (Main to Curb):", card.get("service_main_to_curb") or ""),
           ("Diameter Service:", card.get("diameter_service") or ""))
    y += row_h
    row(y, ("Material Service (Curb to House):", card.get("service_curb_to_house") or ""))
    y += row_h

    # Comments block with tie summary
    draw.text((x0 + 12, y + 8), "Comments:", font=f_lbl, fill="#000")
    tie_bits = []
    if card.get("double_curbed") or "old curb" in str(card.get("left", "")).casefold():
        left = _double_curb_pair(card.get("left"))
        right = _double_curb_pair(card.get("right"))
        ch = _double_curb_pair(card.get("curb_to_house"))
        old = ", ".join(filter(None, [
            f"LS {left.get('old')}" if left.get("old") else "",
            f"RS {right.get('old')}" if right.get("old") else "",
            f"CH {ch.get('old')}" if ch.get("old") else "",
        ]))
        new = ", ".join(filter(None, [
            f"LS {left.get('new')}" if left.get("new") else "",
            f"RS {right.get('new')}" if right.get("new") else "",
            f"CH {ch.get('new')}" if ch.get("new") else "",
        ]))
        if old:
            tie_bits.append(f"OLD: {old}")
        if new:
            tie_bits.append(f"NEW: {new}")
        if card.get("vertical"):
            tie_bits.append(f"MC {card['vertical']}")
        summary = " | ".join(tie_bits)
    else:
        if card.get("left"):  tie_bits.append(f"LS {card['left']}")
        if card.get("right"): tie_bits.append(f"RS {card['right']}")
        if card.get("vertical"): tie_bits.append(f"MC {card['vertical']}")
        if card.get("curb_to_house"): tie_bits.append(f"CH {card['curb_to_house']}")
        summary = "Ties — " + ", ".join(tie_bits) if tie_bits else ""
    extra = str(card.get("comments") or "").strip()
    if extra:
        summary = f"{summary}   {extra}" if summary else extra
    if summary:
        comment_font = _font(18)
        for line_no, line in enumerate(textwrap.wrap(summary, width=108)[:2]):
            draw.text((x0 + 150, y + 7 + line_no * 22), line,
                      font=comment_font, fill="#00008B")
    if card.get("main_label") or main_size:
        draw.text((x0 + 12, y + 44), f"Main: {card.get('main_label') or (main_size + ' ' + main_material).strip()}",
                  font=f_val, fill="#00008B")

    # Outer border
    draw.rectangle([x0, 82, x1, y + row_h], outline="#999900", width=3)
    return img


def paste_field_photo(base: Image.Image, draw: ImageDraw.ImageDraw,
                      photo_path: Path, x: int, y: int, w: int, h: int,
                      caption: str = "") -> None:
    """
    Paste the actual curb photo of the house into the box (x, y, w, h) on the
    back page, preserving aspect ratio and centered, with a thin border and a
    caption underneath. This puts a *picture of the real house* on the card,
    alongside the traced tie geometry.
    """
    cap_h = 30 if caption else 0
    box_w, box_h = w, h - cap_h - 8

    photo = Image.open(photo_path).convert("RGB")
    scale = min(box_w / photo.width, box_h / photo.height)
    new_w = max(1, int(photo.width * scale))
    new_h = max(1, int(photo.height * scale))
    photo = photo.resize((new_w, new_h), Image.LANCZOS)

    px = x + (box_w - new_w) // 2
    py = y + (box_h - new_h) // 2
    base.paste(photo, (px, py))
    draw.rectangle([px, py, px + new_w, py + new_h], outline="#000", width=2)

    if caption:
        f_cap = _font(18)
        cb = draw.textbbox((0, 0), caption, font=f_cap)
        draw.text((x + (w - (cb[2] - cb[0])) // 2, y + box_h + 10),
                  caption, font=f_cap, fill="#333")


def render_back_page(card: dict) -> Image.Image:
    """
    Render a full back-page tie card: APPLICATION header + application text +
    Signed/Date/Street lines + the traced tie sketch built from the supplied
    measurements. Matches the blank Water Service Tie Card back layout.
    """
    img = Image.new("RGB", (BACK_W, BACK_H), "#FFFDE0")
    draw = ImageDraw.Draw(img)

    f_title = _font(30, bold=True)
    f_body = _font(20)
    f_lbl = _font(20, bold=True)

    m = 60  # margin
    y = 40

    # Header: APPLICATION ......... Reg. No
    draw.text((m, y), "APPLICATION", font=f_title, fill="#000")
    reg = card.get("reg_no") or ""
    if reg:
        draw.text((BACK_W - m - 260, y + 4), f"Reg. No: {reg}", font=f_lbl, fill="#000")
    y += 46
    draw.line([(m, y), (BACK_W - m, y)], fill="#333", width=2)
    y += 24

    # Application paragraph (wrapped)
    import textwrap
    for line in textwrap.wrap(APPLICATION_TEXT, width=95):
        draw.text((m, y), line, font=f_body, fill="#222")
        y += 28
    y += 30

    # Signed / Date / Street lines
    draw.text((m, y), "Signed:", font=f_lbl, fill="#000")
    draw.line([(m + 90, y + 22), (BACK_W // 2 - 40, y + 22)], fill="#555", width=1)
    draw.text((BACK_W // 2, y), "Date:", font=f_lbl, fill="#000")
    draw.line([(BACK_W // 2 + 70, y + 22), (BACK_W - m, y + 22)], fill="#555", width=1)
    y += 50
    draw.text((m, y), "Street:", font=f_lbl, fill="#000")
    draw.line([(m + 90, y + 22), (BACK_W - m, y + 22)], fill="#555", width=1)
    street = card.get("address") or card.get("property_label") or ""
    if street:
        draw.text((m + 100, y - 2), str(street), font=f_body, fill="#00008B")
    y += 60

    # Sketch region occupies the remaining lower portion of the page. The real
    # house photo is intentionally NOT drawn here — the printable back page
    # stays photo-free; the photo lives on a separate digital-only page.
    sketch_x = m
    sketch_y = y
    sketch_w = BACK_W - 2 * m
    sketch_h = BACK_H - y - 50

    back_data = {
        "has_sketch": True,
        "property_label": card.get("property_label") or card.get("address") or "",
        "vertical_measurement": card.get("vertical") or card.get("vertical_measurement") or "",
        "left_diagonal_measurement": card.get("left") or card.get("left_diagonal_measurement") or "",
        "right_diagonal_measurement": card.get("right") or card.get("right_diagonal_measurement") or "",
        "main_label": card.get("main_label") or "",
        "curb_to_house": card.get("curb_to_house") or card.get("ch") or "",
        "service_line_straight": card.get("service_line_straight", True),
        "double_curbed": card.get("double_curbed") or False,
        "curb_offset": card.get("curb_offset") or "",
        "reference_structure_label": card.get("ref_label") or card.get("reference_structure_label") or "",
        "reference_structure_number": card.get("ref_number") or card.get("reference_structure_number") or "",
        "left_tie_object": card.get("left_tie_object") or {},
        "right_tie_object": card.get("right_tie_object") or {},
    }

    draw_sketch_diagram(draw, back_data, sketch_x, sketch_y, sketch_w, sketch_h,
                        house=card.get("_house"))
    return img


def render_photo_page(card: dict) -> Image.Image | None:
    """
    Render the digital-only 3rd page: a large picture of the actual house.
    Uses the clean display photo when one was supplied (address text kept out
    of the way), otherwise falls back to the annotated field photo. Returns
    None when no photo is available (so print output is unaffected).
    """
    photo_path = card.get("_display_photo_path") or card.get("_photo_path")
    if not photo_path or not Path(photo_path).exists():
        return None

    img = Image.new("RGB", (BACK_W, BACK_H), "#FFFDE0")
    draw = ImageDraw.Draw(img)
    f_title = _font(30, bold=True)
    f_lbl = _font(20, bold=True)

    m = 60
    y = 40
    draw.text((m, y), "PROPERTY PHOTO", font=f_title, fill="#000")
    reg = card.get("reg_no") or ""
    if reg:
        draw.text((BACK_W - m - 260, y + 4), f"Reg. No: {reg}", font=f_lbl, fill="#000")
    y += 46
    draw.line([(m, y), (BACK_W - m, y)], fill="#333", width=2)
    y += 24

    addr = card.get("address") or card.get("property_label") or ""
    caption = f"Field photo (digital record only) — {addr}".strip(" —")
    paste_field_photo(img, draw, Path(photo_path),
                      m, y, BACK_W - 2 * m, BACK_H - y - 40, caption=caption)
    return img


def card_filename_base(card: dict) -> str:
    """
    Filename base for a card's output files: ADDRESS + REGISTRY NUMBER, e.g.
    "6 Demo Rd 8443". Falls back to whichever is present. Illegal filename
    characters are stripped; spaces are kept (valid in Drive/Windows names).
    """
    import re
    addr = (card.get("address") or card.get("property_label") or "").strip()
    reg = str(card.get("reg_no") or "").strip()
    base = " ".join(p for p in (addr, reg) if p) or "card"
    safe = re.sub(r'[<>:"/\\|?*]', "", base).strip()
    return safe or "card"


def save_outputs(back_img: Image.Image, card: dict, front_img: Image.Image | None) -> dict:
    """
    Save PNGs + a single 2-page TIF (front page 1, back page 2). If no front
    image is supplied, the TIF is back-only. Files are named by ADDRESS.
    """
    reg = card_filename_base(card)

    back_png = OUT_DIR / f"{reg}_back.png"
    back_img.save(back_png)
    result = {"back_png": back_png}

    tif_path = OUT_DIR / f"{reg}.tif"
    if front_img is not None:
        front_png = OUT_DIR / f"{reg}_front.png"
        front_img.save(front_png)
        result["front_png"] = front_png
        front_img.convert("RGB").save(
            tif_path, format="TIFF", save_all=True,
            append_images=[back_img.convert("RGB")],
            dpi=(300, 300), compression="tiff_lzw")
    else:
        back_img.convert("RGB").save(tif_path, format="TIFF", dpi=(300, 300), compression="tiff_lzw")

    result["tif"] = tif_path
    return result


def save_digital_outputs(card: dict, front_img: Image.Image, back_img: Image.Image,
                         photo_img: Image.Image) -> dict:
    """
    Save the digital-only 3-page card (front, back, real house photo) to
    DIGITAL_DIR. This is for on-screen viewing; it is never fed to the print
    pipeline, so the printed card stays photo-free.
    """
    base = card_filename_base(card)
    photo_png = DIGITAL_DIR / f"{base}_photo.png"
    photo_img.save(photo_png)

    digital_tif = DIGITAL_DIR / f"{base}_DIGITAL.tif"
    front_img.convert("RGB").save(
        digital_tif, format="TIFF", save_all=True,
        append_images=[back_img.convert("RGB"), photo_img.convert("RGB")],
        dpi=(300, 300), compression="tiff_lzw")
    return {"photo_png": photo_png, "digital_tif": digital_tif}


def upload(tif_path: Path, folder_name: str, reg: str):
    """Upload the drawn TIF to a Drive folder using the shared helper."""
    try:
        from build_comparisons import __name__ as _  # noqa
        from tiecard_ocr_v2 import _get_drive_folder
        from googleapiclient.http import MediaFileUpload
        drive, folder_id = _get_drive_folder(folder_name)
        if not drive or not folder_id:
            print(f"  [WARN] Could not reach Drive folder '{folder_name}'")
            return
        media = MediaFileUpload(str(tif_path), mimetype="image/tiff")
        meta = {"name": f"{reg}.tif", "parents": [folder_id]}
        up = drive.files().create(body=meta, media_body=media, fields="id,name").execute()
        print(f"  [Drive] Uploaded to '{folder_name}': {up['name']}")
    except Exception as e:
        print(f"  [WARN] Upload failed: {e}")


_STREET_SUFFIXES = {"ST", "RD", "AVE", "DR", "LN", "CT", "PL", "BLVD",
                    "TER", "CIR", "WAY", "HWY", "SQ", "PKWY"}


def _normalize_address(addr: str) -> str:
    """Fix shouty street suffixes read off handwriting: 'Fenwick ST' -> 'Fenwick St'."""
    words = [w.capitalize() if w.upper() in _STREET_SUFFIXES and w.isupper() else w
             for w in str(addr).split()]
    return " ".join(words)


def _normalize_reg(reg: str) -> str:
    """Strip the 'REG' label off a photo-read registry number: 'REG 7424' -> '7424'."""
    import re
    return re.sub(r"(?i)^\s*reg\.?\s*(no\.?|#)?\s*[:\-]?\s*", "", str(reg)).strip()


def apply_photo(card: dict, photo_path: Path) -> dict:
    """
    Read a curb photo: pull the house appearance (for drawing) and any
    handwritten measurements. CLI/JSON-supplied measurements take precedence
    over photo-read ones; photo fills only the blanks.
    """
    from house_from_photo import analyze_curb_photo
    print(f"  Reading curb photo: {photo_path.name} ...")
    result = analyze_curb_photo(photo_path)
    meas = result.get("measurements") or {}
    house = result.get("house") or {}

    if meas.get("reg_no"):
        meas["reg_no"] = _normalize_reg(meas["reg_no"])
    for key in ("address", "street_name"):
        if meas.get(key):
            meas[key] = _normalize_address(meas[key])

    field_map = {
        "reg_no": "reg_no", "address": "address", "vertical": "vertical",
        "left": "left", "right": "right", "curb_to_house": "curb_to_house",
        "date": "date",                                    # date -> Date field
        "service_curb_to_house": "house_side_material",   # HS = House Side material
        "service_main_to_curb": "street_side_material",   # PS = Main-to-Curb material
        "diameter_service": "service_diameter",           # DS = Diameter of Service
        "contractor": "contractor",                        # CON = Contractor, or "Demo Contractor"
        "inspected_by": "inspected_by",                    # INSP, or Morgan/Jimmy P/Enzo/Andy
    }
    for card_key, meas_key in field_map.items():
        if not card.get(card_key) and meas.get(meas_key):
            card[card_key] = meas[meas_key]

    for obj_key in ("left_tie_object", "right_tie_object"):
        if not card.get(obj_key) and meas.get(obj_key):
            card[obj_key] = meas[obj_key]

    # Street name (fills the address / Street line if address not already set)
    if not card.get("address") and meas.get("street_name"):
        card["address"] = meas["street_name"]

    # Compose the main label from size + material (e.g. 8" DI) when present,
    # falling back to whatever main_label was written directly.
    if not card.get("main_label"):
        size = (meas.get("main_size") or "").strip()
        material = (meas.get("main_material") or "").strip()
        composed = " ".join(x for x in (size, material) if x).strip()
        card["main_label"] = composed or meas.get("main_label") or ""

    if house:
        card["_house"] = house
        print(f"  House read: {house.get('stories')}-story {house.get('roof_type')} "
              f"(garage={house.get('garage')}, porch={house.get('porch')})")
    # Echo-back so a misread measurement is easy to catch
    print(f"  Measurements in use: reg={card.get('reg_no')} vert={card.get('vertical')} "
          f"left={card.get('left')} right={card.get('right')} main={card.get('main_label')}")
    return card


def process_card(card: dict, front_path: Path | None, folder_name: str | None,
                 photo_path: Path | None = None,
                 display_photo_path: Path | None = None) -> dict:
    # The card is completed when this final rendering step runs. Preserve an
    # explicit document/field date, otherwise stamp today's local date.
    card.setdefault("date", date.today().strftime("%m/%d/%Y"))
    if photo_path and Path(photo_path).exists():
        card = apply_photo(card, Path(photo_path))
        # Keep the annotated field photo (source of record). The digital-only
        # photo page prefers a clean display photo when one is supplied.
        card["_photo_path"] = str(Path(photo_path))
    if display_photo_path and Path(display_photo_path).exists():
        card["_display_photo_path"] = str(Path(display_photo_path))
    # Only if no reg was written on the photo, fall back to the caller's
    # traceability id (the intake photo's filename stem).
    if not card.get("reg_no") and card.get("_reg_fallback"):
        card["reg_no"] = card["_reg_fallback"]
        print(f"  [WARN] No REG found on photo; falling back to '{card['reg_no']}'")
    reg = card.get("reg_no") or "card"
    print(f"\n[Draw] Rendering front + back for reg {reg}...")
    front_img = render_front_page(card)
    back_img = render_back_page(card)
    paths = save_outputs(back_img, card, front_img)
    print(f"  Saved 2-page printable TIF: {paths['tif'].name}")

    # Digital-only version with the real house photo as a 3rd page.
    photo_img = render_photo_page(card)
    if photo_img is not None:
        paths.update(save_digital_outputs(card, front_img, back_img, photo_img))
        print(f"  Saved 3-page digital TIF: {paths['digital_tif'].name}")

    if folder_name:
        upload(paths["tif"], folder_name, card_filename_base(card))
    return paths


DEFAULT_FOLDER = "10 - Manually Drawn (From Field Measurements)"


def main():
    p = argparse.ArgumentParser(description="Draw a tiecard back page from supplied measurements")
    p.add_argument("--reg")
    p.add_argument("--address")
    p.add_argument("--property-label")
    p.add_argument("--vertical")
    p.add_argument("--left")
    p.add_argument("--right")
    p.add_argument("--main-label")
    p.add_argument("--ref-label")
    p.add_argument("--ref-number")
    p.add_argument("--front", help="Optional front-page image to combine into a 2-page TIF")
    p.add_argument("--photo", help="Curb photo of the house — reads house appearance (and any handwritten measurements on it)")
    p.add_argument("--display-photo", help="Clean house photo (address kept out of the way) for the digital-only photo page")
    p.add_argument("--json", help="Batch: JSON file with a list of card objects")
    p.add_argument("--interactive", action="store_true", help="Guided prompt for one card")
    p.add_argument("--upload", action="store_true", help="Upload result to Drive")
    p.add_argument("--folder", default=DEFAULT_FOLDER, help="Drive folder to upload to")
    args = p.parse_args()

    folder_name = args.folder if args.upload else None
    front_path = Path(args.front) if args.front else None

    if args.json:
        cards = json.loads(Path(args.json).read_text(encoding="utf-8"))
        print(f"[Batch] {len(cards)} card(s) from {args.json}")
        for c in cards:
            fp = Path(c["front"]) if c.get("front") else front_path
            process_card(c, fp, folder_name)
        print(f"\n[Done] {len(cards)} card(s) drawn -> {OUT_DIR}")
        return

    if args.interactive:
        def ask(label):
            return input(f"  {label}: ").strip()
        print("Enter measurements (leave blank to skip):")
        card = {
            "reg_no": ask("Reg No"),
            "address": ask("Address / property label"),
            "vertical": ask("Vertical (curb-stop to main)"),
            "left": ask("Left diagonal tie"),
            "right": ask("Right diagonal tie"),
            "main_label": ask("Main label (e.g. 6\" CI)"),
            "ref_label": ask("Reference structure label (optional)"),
            "ref_number": ask("Reference structure number (optional)"),
        }
        process_card(card, front_path, folder_name)
        return

    # Single card from flags
    card = {
        "reg_no": args.reg,
        "address": args.address,
        "property_label": args.property_label,
        "vertical": args.vertical,
        "left": args.left,
        "right": args.right,
        "main_label": args.main_label,
        "ref_label": args.ref_label,
        "ref_number": args.ref_number,
    }
    photo_path = Path(args.photo) if args.photo else None
    display_photo_path = Path(args.display_photo) if args.display_photo else None
    # Measurements may instead be written on the photo, so only require them
    # when no photo is supplied.
    if not photo_path and not any([args.vertical, args.left, args.right]):
        p.print_help()
        print("\n[ERROR] Supply at least the tie measurements (--vertical/--left/--right), "
              "a --photo with them written on it, or use --interactive / --json.")
        sys.exit(1)
    process_card(card, front_path, folder_name, photo_path, display_photo_path)


if __name__ == "__main__":
    main()
