"""
UtiliVault — build_comparisons.py
Builds a side-by-side comparison image (original scan | digitized data) for
every processed card in feed_batch_output, and uploads each to the Drive
"9 - Side-by-Side Compare" folder.

Lightweight by design: uses PIL text rendering (no headless browser calls),
so it stays fast and low-resource even across hundreds of cards.

Usage:
  py build_comparisons.py                # process every JSON in feed_batch_output
  py build_comparisons.py --limit 10     # test on first 10
"""

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))

from config import FEED_OUT_DIR as OUT_DIR, COMPARE_DIR
COMPARE_DIR.mkdir(parents=True, exist_ok=True)

PANEL_W = 500
PANEL_H = 700
FONT_SIZE = 14


def _font(size=FONT_SIZE, bold=False):
    configured = os.getenv(
        "UTILIVAULT_FONT_BOLD" if bold else "UTILIVAULT_FONT_REGULAR", ""
    ).strip()
    candidates = [configured] if configured else []
    candidates.extend(
        [
            "arialbd.ttf" if bold else "arial.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
            if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        ]
    )
    for name in candidates:
        if not name:
            continue
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise RuntimeError(
        "No usable TrueType font found; set UTILIVAULT_FONT_REGULAR and "
        "UTILIVAULT_FONT_BOLD to approved font files"
    )


def _parse_feet_inches(s: str | None) -> float | None:
    """
    Best-effort parse of a feet/inches measurement string into total inches.
    Handles: 13'-6", 7'-8", 40', 14.5', 30.5, 7-0, 8'6", etc.
    Returns None if nothing numeric could be extracted.
    """
    import re
    if not s:
        return None
    s = (str(s).strip()
         .replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
         .replace("\N{LEFT SINGLE QUOTATION MARK}", "'")
         .replace("\N{RIGHT DOUBLE QUOTATION MARK}", '"')
         .replace("\N{LEFT DOUBLE QUOTATION MARK}", '"'))

    # feet' inches" or feet'-inches" or feet'inches"
    m = re.match(r"^(\d+(?:\.\d+)?)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*\"?$", s)
    if m:
        feet = float(m.group(1))
        inches = float(m.group(2)) if m.group(2) else 0.0
        return feet * 12 + inches

    # plain feet with trailing quote: 40'
    m = re.match(r"^(\d+(?:\.\d+)?)\s*'$", s)
    if m:
        return float(m.group(1)) * 12

    # bare number, e.g. "30.5" or "7" (assume feet)
    m = re.match(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1)) * 12

    return None


def _double_curb_pair(value: str | None) -> dict[str, str]:
    """Return compact ``old``/``new`` measurements from a paired field value."""
    import re

    result: dict[str, str] = {}
    for raw_part in str(value or "").split("|"):
        part = raw_part.strip()
        lower = part.casefold()
        curb = "old" if "old" in lower else "new" if "new" in lower else None
        if not curb:
            continue
        match = re.search(
            r"\d+(?:\.\d+)?\s*['\N{RIGHT SINGLE QUOTATION MARK}]"
            r"(?:\s*-?\s*\d+(?:\.\d+)?)?\s*[\"\N{RIGHT DOUBLE QUOTATION MARK}]?",
            part,
        )
        if match:
            result[curb] = re.sub(r"\s+", " ", match.group(0)).strip()
    return result


def _is_double_curb(back: dict) -> bool:
    if back.get("double_curbed") or back.get("curb_offset"):
        return True
    fields = (
        back.get("left_diagonal_measurement"),
        back.get("right_diagonal_measurement"),
        back.get("curb_to_house"),
    )
    return sum(bool(_double_curb_pair(value)) for value in fields) >= 2


def _house_service_entry_x(house: dict | None, left_x: int, right_x: int) -> int:
    """Map the photo-derived service-entry position onto the drawn frontage."""
    if not house:
        return (left_x + right_x) // 2

    confidence = str(house.get("service_entry_confidence") or "").casefold()
    if confidence == "low":
        fraction = 0.5
    else:
        try:
            fraction = float(house.get("service_entry_x"))
        except (TypeError, ValueError):
            fraction = 0.5

    fraction = max(0.0, min(1.0, fraction))
    return round(left_x + (right_x - left_x) * fraction)


def _service_line_apex_x(back: dict, service_entry_x: int, center_x: int) -> int:
    """Keep the curb-to-house run straight unless explicitly marked otherwise."""
    if back.get("service_line_straight") is False:
        return center_x
    return service_entry_x


def _draw_rotated_text(draw, center_xy, text, font, angle_deg, fill="#000"):
    """Draw `text` rotated by angle_deg (CCW), centered at center_xy."""
    import math
    base = getattr(draw, "_image", None)
    if base is None:  # fallback: unrotated
        draw.text(center_xy, text, font=font, fill=fill, anchor="mm")
        return
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 4
    tmp = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tmp)
    tdraw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=fill)
    rot = tmp.rotate(angle_deg, expand=True, resample=Image.BICUBIC)
    px = int(center_xy[0] - rot.width / 2)
    py = int(center_xy[1] - rot.height / 2)
    base.paste(rot, (px, py), rot)


def _label_off_line(draw, p1, p2, text, font, fill="#000", gap=10, side=1, pos=0.5,
                    parallel=False):
    """
    Place text at fraction `pos` along a line (0=start, 1=end), offset
    perpendicular to the line's direction so the text never sits on the
    stroke. `side` flips the perpendicular direction. If `parallel` is True,
    the text is rotated to run parallel to the line (used for swing ties).
    """
    import math
    x1, y1 = p1
    x2, y2 = p2
    mx, my = x1 + (x2 - x1) * pos, y1 + (y2 - y1) * pos
    dx, dy = x2 - x1, y2 - y1
    length = max((dx**2 + dy**2) ** 0.5, 1e-6)
    px, py = -dy / length, dx / length          # unit perpendicular

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    half_diag = ((tw / 2) ** 2 + (th / 2) ** 2) ** 0.5

    off = gap + (th / 2 if parallel else half_diag)
    tx = mx + px * off * side
    ty = my + py * off * side

    if parallel:
        angle = math.degrees(math.atan2(-(dy), dx))   # image y is down
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        _draw_rotated_text(draw, (tx, ty), text, font, angle, fill=fill)
    else:
        draw.text((tx, ty), text, font=font, fill=fill, anchor="mm")



def _normalize_tie_object(obj, side: str) -> dict:
    """Default unspecified / unlabeled targets to this house's corner."""
    side = "left" if side == "left" else "right"
    if not isinstance(obj, dict):
        obj = {}
    raw_type = str(obj.get("type") or "this_house").strip().lower()
    label = str(obj.get("label") or "").strip()
    aliases = {
        "this house": "this_house",
        "subject": "this_house",
        "corner": "this_house",
        "house corner": "this_house",
        "neighbor": "house",
        "neighbor house": "house",
        "utility pole": "pole",
        "tel pole": "pole",
        "power pole": "pole",
        "fh": "hydrant",
        "hyd": "hydrant",
        "fire hydrant": "hydrant",
    }
    obj_type = aliases.get(raw_type, raw_type)
    if obj_type not in ("house", "pole", "hydrant", "this_house", "other"):
        obj_type = "this_house"
    # Unnamed neighbor houses are not invented; a typed pole/hydrant may omit a number.
    if obj_type == "house" and not label:
        obj_type = "this_house"
    return {"type": obj_type, "label": label, "side": side}


def _draw_neighbor_house(draw, label: str, cx: int, base_y: int, k: float, font) -> tuple[int, int]:
    """Smaller numbered house; returns the street-facing base center (tie anchor)."""
    body_w = max(28, int(36 * k))
    body_h = max(24, int(32 * k))
    roof_h = max(10, int(12 * k))
    bx0 = cx - body_w // 2
    bx1 = cx + body_w // 2
    by1 = base_y
    by0 = by1 - body_h
    draw.rectangle([bx0, by0, bx1, by1], outline="#000", width=2)
    draw.line([(bx0, by0), (cx, by0 - roof_h)], fill="#000", width=2)
    draw.line([(bx1, by0), (cx, by0 - roof_h)], fill="#000", width=2)
    if label:
        draw.text((cx, by0 + body_h // 2), str(label)[:8], font=font, fill="#000", anchor="mm")
    return cx, by1


def _draw_pole(draw, label: str, x: int, base_y: int, k: float, font) -> tuple[int, int]:
    """Utility pole: post + crossarm. Anchor at the base of the post."""
    post_h = max(42, int(52 * k))
    top = base_y - post_h
    arm = max(10, int(14 * k))
    draw.line([(x, base_y), (x, top)], fill="#000", width=max(2, int(3 * k)))
    draw.line([(x - arm, top + 6), (x + arm, top + 6)], fill="#000", width=max(2, int(2 * k)))
    if label:
        draw.text((x, top - 4), str(label)[:10], font=font, fill="#000", anchor="mb")
    return x, base_y


def _draw_hydrant(draw, label: str, x: int, base_y: int, k: float, font) -> tuple[int, int]:
    bw = max(8, int(10 * k))
    bh = max(16, int(18 * k))
    draw.rectangle([x - bw // 2, base_y - bh, x + bw // 2, base_y], outline="#000", width=2)
    draw.ellipse([x - 3, base_y - bh - 6, x + 3, base_y - bh], outline="#000", width=1)
    draw.line([(x - bw, base_y - bh // 2), (x + bw, base_y - bh // 2)], fill="#000", width=2)
    if label:
        draw.text((x, base_y + 2), str(label)[:8], font=font, fill="#000", anchor="mt")
    return x, base_y


def _draw_tie_object(draw, obj: dict, x: int, base_y: int, k: float, font) -> tuple[int, int]:
    t = obj.get("type")
    label = obj.get("label") or ""
    if t == "house":
        return _draw_neighbor_house(draw, label, x, base_y, k, font)
    if t == "pole":
        return _draw_pole(draw, label, x, base_y, k, font)
    if t == "hydrant":
        return _draw_hydrant(draw, label, x, base_y, k, font)
    if t == "other" and label:
        draw.ellipse([x - 5, base_y - 10, x + 5, base_y], outline="#000", width=2)
        draw.text((x, base_y - 14), str(label)[:10], font=font, fill="#000", anchor="mb")
        return x, base_y
    return x, base_y


def draw_sketch_diagram(draw: ImageDraw.ImageDraw, back: dict, x0: int, y0: int, w: int, h: int,
                        house: dict | None = None):
    """
    Draw a traced triangulation diagram matching the ACTUAL convention seen
    on these cards (verified against multiple original scans): the building
    is drawn as its street-facing corner — a horizontal wall segment with a
    short perpendicular tick at each end marking the two corners — not a
    labeled box. LS/RS run from the named tie object (neighbor house, pole,
    hydrant) or, if unspecified, from this house's corners, down to a single
    apex (the curb/corp stop). From the apex, a
    further vertical run continues down to the water main. If the card also
    recorded a distinct reference structure (some older cards tie to a
    second building instead of the main), that's drawn below the main line.

    Every measurement label is offset perpendicular to its line so it never
    overlaps the drawn stroke, and geometry (building width, tie spread,
    vertical run length) scales to the card's actual measurements.
    """
    # Font scales with the drawing width: small on the ~500px comparison
    # panels, comfortably large on the full ~1600px back page.
    fs = max(13, int(w / 42))
    label_gap = max(8, fs)          # perpendicular clearance scales with font
    font_sm = _font(fs)
    font_sm_bold = _font(fs, bold=True)

    vert_in = _parse_feet_inches(back.get("vertical_measurement"))
    left_in = _parse_feet_inches(back.get("left_diagonal_measurement"))
    right_in = _parse_feet_inches(back.get("right_diagonal_measurement"))

    vert_in = vert_in if vert_in and vert_in > 0 else 96.0
    left_in = left_in if left_in and left_in > 0 else 240.0
    right_in = right_in if right_in and right_in > 0 else 240.0

    has_ref_structure = bool(back.get("reference_structure_label") or back.get("reference_structure_number"))

    cx = x0 + w // 2

    left_val = back.get("left_diagonal_measurement") or "?"
    right_val = back.get("right_diagonal_measurement") or "?"

    # Vertical layout budget — building elements and gaps scale with drawing
    # size (k) so the whole sketch grows together on the big back page.
    k = max(1.0, w / 480.0)
    reserved_bottom = int((34 + 14) * k) if has_ref_structure else int(34 * k)
    roof_h = int(24 * k)
    building_wall_h = int(28 * k)

    # A dedicated clear band at the very top for the property label, so it can
    # never touch the building or the ties.
    label_band = (fs + 10) if (back.get("property_label")) else 0
    prop_label_y = y0 + 8 + label_band // 2
    top_y = y0 + 10 + label_band
    wall_bottom_y = top_y + roof_h + building_wall_h
    vert_run_px = max(int(46 * k), fs * 2 + 18)   # apex -> main gap (fits vertical label)
    main_y = y0 + h - reserved_bottom
    apex_y = main_y - vert_run_px

    # Building is drawn as a neat, fixed-size generic house centered at top —
    # NOT scaled to tie length (the originals draw a tidy building and just
    # LABEL the tie distances). A mild apex offset reflects lopsidedness
    # without letting a long tie stretch the whole drawing off the page.
    base_half = int(w * 0.14)
    base_left_x = cx - base_half
    base_right_x = cx + base_half

    # Apex (curb/corp stop) sits directly below the building center, so the
    # service run from the curb stop down to the main is a clean straight
    # perpendicular drop — not angled. Differing tie lengths are conveyed by
    # their labels, matching how the hand-drawn originals are laid out.
    if house:
        # Draw a recognizable front-elevation of the actual house (from the
        # curb photo) instead of the generic box. Ties anchor to the drawn
        # house's footprint corners.
        try:
            from house_from_photo import draw_house_elevation
            elev_max_w = int(w * 0.5)
            elev_max_h = wall_bottom_y - top_y + roof_h
            foot_l, foot_r = draw_house_elevation(draw, house, cx, wall_bottom_y, elev_max_w, elev_max_h)
            base_left_x, base_right_x = foot_l, foot_r
        except Exception:
            house = None  # fall through to generic building below

    if not house:
        # --- Generic building (walls + peaked roof) -------------------------
        roof_peak = (cx, top_y)
        draw.line([(base_left_x, wall_bottom_y), (base_right_x, wall_bottom_y)], fill="#000", width=2)
        draw.line([(base_left_x, wall_bottom_y), (base_left_x, top_y + roof_h)], fill="#000", width=2)
        draw.line([(base_right_x, wall_bottom_y), (base_right_x, top_y + roof_h)], fill="#000", width=2)
        draw.line([(base_left_x, top_y + roof_h), (base_right_x, top_y + roof_h)], fill="#000", width=1)
        draw.line([(base_left_x, top_y + roof_h), roof_peak], fill="#000", width=2)
        draw.line([(base_right_x, top_y + roof_h), roof_peak], fill="#000", width=2)

    corner_l = (base_left_x, wall_bottom_y)
    corner_r = (base_right_x, wall_bottom_y)

    left_obj = _normalize_tie_object(back.get("left_tie_object"), "left")
    right_obj = _normalize_tie_object(back.get("right_tie_object"), "right")
    obj_font = _font(max(11, int(fs * 0.85)), bold=True)
    if left_obj["type"] != "this_house":
        left_x = x0 + max(18, int(w * 0.10))
        ls_pt = _draw_tie_object(draw, left_obj, left_x, wall_bottom_y, k, obj_font)
    else:
        ls_pt = corner_l
    if right_obj["type"] != "this_house":
        right_x = x0 + w - max(18, int(w * 0.10))
        rs_pt = _draw_tie_object(draw, right_obj, right_x, wall_bottom_y, k, obj_font)
    else:
        rs_pt = corner_r

    prop_label = back.get("property_label") or ""
    if prop_label:
        # Drawn in its own reserved band above the building — cannot collide
        draw.text((cx, prop_label_y), str(prop_label)[:26], font=font_sm_bold, fill="#000", anchor="mm")

    # Diagonal ties — from each building base corner down to the apex.
    # Labels run PARALLEL to each tie (rotated), offset just off the stroke.
    service_entry = (
        _house_service_entry_x(house, base_left_x, base_right_x),
        wall_bottom_y,
    )
    # Normal installations leave the house in a straight run: align the
    # facade entry, curb stop, and main connection on the same x coordinate.
    # An exceptional angled service can explicitly opt out on the card.
    apex_x = _service_line_apex_x(back, service_entry[0], cx)
    apex_pt = (apex_x, apex_y)
    is_double = _is_double_curb(back)
    r = max(4, int(4 * k))

    if is_double:
        # Two physical curb stops require two distinct sets of ties. The old
        # curb is gray and the new curb is black so a reduced card stays clear.
        old_y = wall_bottom_y + max(int(58 * k), int((apex_y - wall_bottom_y) * 0.42))
        old_y = min(old_y, apex_y - max(int(54 * k), fs * 3))
        old_pt = (apex_x, old_y)
        new_pt = apex_pt
        left_pair = _double_curb_pair(left_val)
        right_pair = _double_curb_pair(right_val)
        ch_pair = _double_curb_pair(back.get("curb_to_house"))
        double_fs = max(12, int(fs * 0.72))
        double_font = _font(double_fs, bold=True)

        curb_half = int(w * 0.22)
        draw.line([(cx - curb_half, old_y), (cx + curb_half, old_y)],
                  fill="#777", width=max(2, int(2 * k)))
        draw.line([(cx - curb_half, apex_y), (cx + curb_half, apex_y)],
                  fill="#000", width=max(2, int(2 * k)))
        draw.text((cx + curb_half + 8, old_y), "OLD CURB", font=double_font,
                  fill="#555", anchor="lm")
        draw.text((cx + curb_half + 8, apex_y), "NEW CURB", font=double_font,
                  fill="#000", anchor="lm")

        label_left_x = x0 + max(8, int(w * 0.025))
        label_right_x = x0 + w - max(8, int(w * 0.025))
        for corner, prefix, pair in (
            (ls_pt, "LS", left_pair),
            (rs_pt, "RS", right_pair),
        ):
            draw.line([corner, old_pt], fill="#777", width=2)
            draw.line([corner, new_pt], fill="#000", width=2)
            is_left = prefix == "LS"
            label_x = label_left_x if is_left else label_right_x
            anchor = "la" if is_left else "ra"
            draw.text(
                (label_x, old_y - double_fs - 5),
                f"{prefix} OLD {pair.get('old', '?')}", font=double_font,
                fill="#555", anchor=anchor,
            )
            draw.text(
                (label_x, apex_y - double_fs - 5),
                f"{prefix} NEW {pair.get('new', '?')}", font=double_font,
                fill="#000", anchor=anchor,
            )

        draw.line([service_entry, new_pt], fill="#000", width=2)
        draw.ellipse(
            [
                service_entry[0] - r,
                service_entry[1] - r,
                service_entry[0] + r,
                service_entry[1] + r,
            ],
            outline="#000",
            width=max(1, int(2 * k)),
        )
        if ch_pair.get("old"):
            draw.text(
                (cx - label_gap, (wall_bottom_y + old_y) // 2),
                f"CH OLD {ch_pair['old']}", font=double_font,
                fill="#555", anchor="rm",
            )
        if ch_pair.get("new"):
            draw.text(
                (cx - label_gap, (old_y + apex_y) // 2),
                f"CH NEW {ch_pair['new']}", font=double_font,
                fill="#000", anchor="rm",
            )

        offset = str(back.get("curb_offset") or "").strip()
        if offset:
            bracket_x = cx + int(w * 0.06)
            tick = max(5, int(5 * k))
            draw.line([(bracket_x, old_y), (bracket_x, apex_y)], fill="#555", width=1)
            draw.line([(bracket_x - tick, old_y), (bracket_x + tick, old_y)], fill="#555", width=1)
            draw.line([(bracket_x - tick, apex_y), (bracket_x + tick, apex_y)], fill="#555", width=1)
            draw.text(
                (bracket_x + label_gap, (old_y + apex_y) // 2),
                f"CURBS {offset}", font=_font(double_fs), fill="#555", anchor="lm",
            )

        draw.ellipse([apex_x-r, old_y-r, apex_x+r, old_y+r], fill="#777")
        draw.ellipse([apex_x-r, apex_y-r, apex_x+r, apex_y+r], fill="#000")
    else:
        draw.line([ls_pt, apex_pt], fill="#000", width=2)
        draw.line([rs_pt, apex_pt], fill="#000", width=2)
        tie_gap = label_gap + fs // 2
        _label_off_line(draw, ls_pt, apex_pt, str(left_val), font_sm_bold,
                        side=1, gap=tie_gap, pos=0.5, parallel=True)
        _label_off_line(draw, rs_pt, apex_pt, str(right_val), font_sm_bold,
                        side=-1, gap=tie_gap, pos=0.5, parallel=True)

        ch_val = back.get("curb_to_house") or ""
        if ch_val:
            draw.line([service_entry, apex_pt], fill="#000", width=2)
            draw.ellipse(
                [
                    service_entry[0] - r,
                    service_entry[1] - r,
                    service_entry[0] + r,
                    service_entry[1] + r,
                ],
                outline="#000",
                width=max(1, int(2 * k)),
            )
            _label_off_line(draw, service_entry, apex_pt, str(ch_val),
                            font_sm_bold, side=-1, gap=label_gap, pos=0.5, parallel=True)
        draw.ellipse([apex_x-r, apex_y-r, apex_x+r, apex_y+r], fill="#000")

    # Vertical run straight down from the apex to the main
    vline_bot = (apex_x, main_y)
    draw.line([apex_pt, vline_bot], fill="#000", width=2)
    vert = back.get("vertical_measurement") or "?"
    _label_off_line(draw, apex_pt, vline_bot, str(vert), font_sm_bold,
                    side=1, gap=label_gap, parallel=True)

    # Water main (horizontal)
    main_left = (x0 + 4, main_y)
    main_right = (x0 + w - 4, main_y)
    draw.line([main_left, main_right], fill="#000", width=max(3, int(3 * k)))
    main_label = back.get("main_label") or "MAIN"
    bbox = draw.textbbox((0, 0), str(main_label), font=font_sm_bold)
    label_h = bbox[3] - bbox[1]
    draw.text((x0 + 6, main_y - label_h - 8), str(main_label),
              font=font_sm_bold, fill="#000")

    # Some older cards tie to a second reference building instead of/below
    # the main — only draw this if that data actually exists on the card.
    if has_ref_structure:
        ref_box_h = int(30 * k)
        ref_y = main_y + int(16 * k)
        ref_box_w = int(w * 0.5)
        draw.rectangle([cx - ref_box_w//2, ref_y, cx + ref_box_w//2, ref_y + ref_box_h],
                       outline="#000", width=2)
        ref_label = back.get("reference_structure_label") or ""
        ref_number = back.get("reference_structure_number") or ""
        if ref_number:
            draw.text((cx, ref_y + ref_box_h//2 - fs//2 - 2), str(ref_label)[:24], font=font_sm_bold, fill="#000", anchor="mm")
            draw.text((cx, ref_y + ref_box_h//2 + fs//2 + 2), str(ref_number), font=font_sm, fill="#333", anchor="mm")
        else:
            draw.text((cx, ref_y + ref_box_h//2), str(ref_label)[:24], font=font_sm_bold, fill="#000", anchor="mm")

    return {
        "corner_l": corner_l,
        "corner_r": corner_r,
        "ls_pt": ls_pt,
        "rs_pt": rs_pt,
        "left_tie_object": left_obj,
        "right_tie_object": right_obj,
        "apex": apex_pt,
    }


def render_data_panel(front: dict | None, back: dict | None, front_val: dict | None,
                      back_val: dict | None) -> Image.Image:
    """Render extracted JSON fields plus an actual traced sketch diagram."""
    img = Image.new("RGB", (PANEL_W, PANEL_H), "#FFFDE0")
    draw = ImageDraw.Draw(img)
    font = _font()
    font_bold = _font(bold=True)
    font_title = _font(18, bold=True)

    y = 14
    draw.text((14, y), "DIGITIZED RECORD", font=font_title, fill="#000000")
    y += 30
    draw.line([(14, y), (PANEL_W - 14, y)], fill="#999900", width=2)
    y += 14

    def field(label, value, color="#00008B"):
        nonlocal y
        if value is None or value == "":
            return
        draw.text((14, y), f"{label}:", font=font_bold, fill="#000000")
        wrapped = textwrap.wrap(str(value), width=48)
        for line in wrapped:
            draw.text((150, y), line, font=font, fill=color)
            y += 18
        if not wrapped:
            y += 18

    if front:
        field("Card Type", front.get("card_type"))
        field("Reg No", front.get("reg_no") or front.get("reg_number"))
        field("Address", front.get("street") or front.get("address"))
        field("Date", front.get("date_laid") or front.get("date"))
        field("Owner/Contractor", front.get("owner") or front.get("contractor"))
        field("Foreman/Inspector", front.get("foreman") or front.get("inspected_by"))
        field("Main Diameter", front.get("main_pipe_diameter") or front.get("diameter_main"))
        field("Main Material", front.get("main_pipe_material") or front.get("material_main"))
        flags = front.get("flags") or []
        if flags:
            field("Flags", ", ".join(flags), color="#7a4f00")

    y += 8
    draw.line([(14, y), (PANEL_W - 14, y)], fill="#999900", width=1)
    y += 10

    front_conf = (front_val or {}).get("confidence", "?")
    back_conf = (back_val or {}).get("confidence", "?")
    conf_color = {"HIGH": "#155724", "MEDIUM": "#7a4f00", "LOW": "#7a0000"}
    draw.text((14, y), "Front confidence:", font=font_bold, fill="#000000")
    draw.text((180, y), front_conf, font=font_bold, fill=conf_color.get(front_conf, "#000"))
    y += 20
    draw.text((14, y), "Back confidence:", font=font_bold, fill="#000000")
    draw.text((180, y), back_conf, font=font_bold, fill=conf_color.get(back_conf, "#000"))
    y += 24

    draw.line([(14, y), (PANEL_W - 14, y)], fill="#999900", width=1)
    y += 8
    draw.text((14, y), "TRACED TIE SKETCH", font=font_bold, fill="#000000")
    y += 20

    if back and back.get("has_sketch"):
        sketch_h = PANEL_H - y - 10
        draw_sketch_diagram(draw, back, 10, y, PANEL_W - 20, sketch_h)
    else:
        draw.text((14, y + 10), "(no sketch data extracted)", font=font, fill="#888888")

    return img


def build_comparison(json_path: Path) -> Path | None:
    """Build one side-by-side image: [original front | original back | digitized data]."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    front_src = Path(data.get("source_front", ""))
    back_src = Path(data.get("source_back", "")) if data.get("source_back") else None

    panels = []

    for src in (front_src, back_src):
        if src and src.exists():
            im = Image.open(src).convert("RGB")
            im.thumbnail((PANEL_W, PANEL_H), Image.LANCZOS)
            canvas = Image.new("RGB", (PANEL_W, PANEL_H), "white")
            canvas.paste(im, ((PANEL_W - im.width) // 2, (PANEL_H - im.height) // 2))
            panels.append(canvas)
        else:
            panels.append(Image.new("RGB", (PANEL_W, PANEL_H), "#eeeeee"))

    data_panel = render_data_panel(
        data.get("front"), data.get("back"),
        data.get("front_validation"), data.get("back_validation"),
    )
    panels.append(data_panel)

    gap = 8
    total_w = PANEL_W * 3 + gap * 4
    combined = Image.new("RGB", (total_w, PANEL_H + 40), "#333333")
    draw = ImageDraw.Draw(combined)
    font_hdr = _font(13, bold=True)
    labels = ["ORIGINAL — FRONT", "ORIGINAL — BACK", "DIGITIZED OUTPUT"]

    x = gap
    for panel, label in zip(panels, labels):
        draw.text((x + 4, 6), label, font=font_hdr, fill="#FFFFFF")
        combined.paste(panel, (x, 30))
        x += PANEL_W + gap

    reg = (data.get("front") or {}).get("reg_no") or json_path.stem
    reg_safe = str(reg).replace("/", "-").replace("\\", "-").strip()
    out_path = COMPARE_DIR / f"{reg_safe}_{json_path.stem}_COMPARE.png"
    combined.save(out_path)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--upload", action="store_true", help="Upload each comparison to Drive")
    args = parser.parse_args()

    json_files = sorted(f for f in OUT_DIR.glob("*.json") if f.name != "batch_summary.json")
    if args.limit:
        json_files = json_files[:args.limit]

    print(f"[Compare] {len(json_files)} JSON records found")

    built = []
    for jf in json_files:
        out_path = build_comparison(jf)
        if out_path:
            built.append(out_path)
            print(f"  Built: {out_path.name}")
        else:
            print(f"  [SKIP] Could not build comparison for {jf.name}")

    print(f"\n[Done] {len(built)}/{len(json_files)} comparisons built -> {COMPARE_DIR}")

    if args.upload:
        from tiecard_ocr_v2 import _get_drive_folder
        from googleapiclient.http import MediaFileUpload

        drive, folder_id = _get_drive_folder("9 - Side-by-Side Compare (Original vs Digitized)")
        if not drive or not folder_id:
            print("[ERROR] Could not connect to Drive compare folder")
            return

        for p in built:
            try:
                media = MediaFileUpload(str(p), mimetype="image/png")
                metadata = {"name": p.name, "parents": [folder_id]}
                drive.files().create(body=metadata, media_body=media, fields="id").execute()
                print(f"  [Drive] Uploaded: {p.name}")
            except Exception as e:
                print(f"  [WARN] Upload failed for {p.name}: {e}")


if __name__ == "__main__":
    main()
