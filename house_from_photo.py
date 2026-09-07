"""
UtiliVault — house_from_photo.py
Reads a curb-level photo of a house (always taken standing on the curb,
facing the house) and:
  1. Extracts any handwritten measurements written on the photo
  2. Produces a structured description of the house's front appearance
Then renders a recognizable front-elevation drawing of that house, to be
used as the "building" in the tie sketch instead of a generic box.

The goal is "sketch what you see" — a recognizable representation of the
actual house (stories, roof shape, garage, porch, proportions), not an
architectural or overhead-accurate drawing.
"""

import base64
import json
import os
from pathlib import Path

from PIL import ImageDraw

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent / ".env"))

CLAUDE_MODEL = "claude-sonnet-4-6"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# The API rejects images over 10 MB *after* base64 encoding (+33%), so raw
# bytes must stay under ~7.5 MB. Phone photos regularly exceed that.
_MAX_RAW_BYTES = 7_000_000


def _photo_payload(photo_path: Path) -> tuple[str, str]:
    """
    Return (mime, base64) for the photo, recompressing when the raw file is
    too large for the API. Downscales to at most 2800px on the long side and
    steps JPEG quality down until it fits — plenty of resolution to read
    handwriting while staying under the 10 MB base64 cap.
    """
    data = photo_path.read_bytes()
    mime = "image/png" if photo_path.suffix.lower() == ".png" else "image/jpeg"
    if len(data) > _MAX_RAW_BYTES:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        if max(img.size) > 2800:
            scale = 2800 / max(img.size)
            img = img.resize((int(img.width * scale), int(img.height * scale)),
                             Image.LANCZOS)
        for quality in (90, 85, 78, 70, 60):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            data = buf.getvalue()
            if len(data) <= _MAX_RAW_BYTES:
                break
        mime = "image/jpeg"
        print(f"  (photo recompressed {photo_path.stat().st_size/1e6:.1f} MB "
              f"-> {len(data)/1e6:.1f} MB for API)")
    return mime, base64.standard_b64encode(data).decode()


def analyze_curb_photo(photo_path: Path) -> dict:
    """
    Send the curb photo to Claude Vision. Returns a dict with:
      {
        "measurements": {
           "reg_no": "", "address": "",
           "vertical": "", "left": "", "right": "",
           "left_tie_object": {"type": "this_house", "label": "", "side": "left"},
           "right_tie_object": {"type": "this_house", "label": "", "side": "right"},
           "main_label": "", "reference_notes": ""
        },
        "house": {
           "stories": 1|2|3,
           "roof_type": "gable"|"hip"|"flat"|"mansard"|"gambrel",
           "width_units": 1..5,        # relative front width (wide house = higher)
           "body_color_hint": "",
           "garage": "none"|"left"|"right"|"center",
           "porch": true|false,
           "front_door": "left"|"center"|"right",
           "window_columns": int,      # rough count of window bays across the front
           "service_entry_x": 0.0..1.0,
           "service_entry_confidence": "high"|"medium"|"low",
           "notes": ""
        }
      }
    Any field not readable is left blank / sensible default.
    """
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    mime, b64 = _photo_payload(photo_path)

    prompt = """This is a photo taken by a water utility technician standing on the
curb, facing a house, to document a service tie card. Two jobs:

1) MEASUREMENTS: The technician may have written measurements directly on the
photo (reg number, address, tie distances, main size). Read any handwriting
you can find. Tie measurements are in feet/inches like 76'-4".

   The technician uses these standard abbreviations — map them exactly:
     LS = Left Side   -> the LEFT diagonal tie   -> "left"
     RS = Right Side  -> the RIGHT diagonal tie  -> "right"
     MC = Main to Curb -> the vertical curb-stop-to-main run -> "vertical"
     CH = Curb to House -> the service-run length -> "curb_to_house"
     HS = House Side -> the house-side service pipe MATERIAL (curb-to-house),
          e.g. "HS copper" -> "house_side_material"
     PS = the Main-to-Curb service pipe MATERIAL (street side),
          e.g. "PS copper" -> "street_side_material"
     REG = Registry number -> "reg_no"   (e.g. "REG 7424")
     CON = Contractor -> "contractor"     (e.g. "CON ABC Plumbing")
     INSP = Inspector -> "inspected_by"   (e.g. "INSP Nichols")
     DS = Diameter of Service -> "service_diameter"  (e.g. "DS 1\"")
   So "LS 76'-4\"" means left tie = 76'-4"; "MC 11'-9\"" means vertical = 11'-9";

   TIE OBJECTS (LS/RS targets): The subject house in the photo is the PROPERTY
   and stays centered on the sketch. LS and RS are often measured TO a neighbor
   house, utility pole, hydrant, or (if unspecified) this house's corner.
   Extract left_tie_object and right_tie_object from handwriting AND from
   clearly visible labeled objects. Examples:
     "LS 32'9\" from house 23" -> left_tie_object type=house, label="23", side=left
     "RS 64' pole 185-5" -> right_tie_object type=pole, label="185-5", side=right
     hydrant / HYD / FH with a number -> type=hydrant
     "to this house", "house corner", or no object named -> type=this_house
   Types: "house" | "pole" | "hydrant" | "this_house" | "other".
   Do NOT invent unlabeled objects. If you cannot name/identify an object,
   use this_house (do not guess a neighbor number or pole id).
   "HS copper" = house-side material copper; "PS copper" = main-to-curb
   material copper; "DS 1\"" = service diameter 1 inch.

   The photo may ALSO have written on it:
     - The water MAIN SIZE (e.g. 8", 6") -> "main_size"
     - The MAIN MATERIAL (e.g. DI = ductile iron, CI = cast iron, CL = cement
       lined, PVC, copper) -> "main_material"
     - The STREET NAME / address -> "street_name" and "address"
     - A DATE (any format) -> "date"
   Read all of these if present.

   KNOWN-VALUE RULES for this District (apply these exactly):
     - "DI" or "Ductile Iron" ALWAYS refers to the WATER MAIN: set
       main_material = "DI". The size written near it (e.g. 8") is the
       main_size. DI is never a service material.
     - "Demo Contractor" is ALWAYS the CONTRACTOR -> contractor = "Demo Contractor".
     - The names "Morgan", "Jimmy P", "Enzo", and "Andy" are ALWAYS
       INSPECTORS -> put the name found in "inspected_by".
     - Any date written on the photo -> "date".
     - A bare number that looks like a registry/record number -> "reg_no".

   There may also be a BLUE FLAG, blue paint, stake, or other technician mark
   at the curb showing the curb-stop location (blue = water in the utility
   color code). Note which side of the house the mark is on and roughly where,
   in "flag_notes".

2) HOUSE APPEARANCE: Describe the FRONT of the house as you see it, well enough
to draw a simple recognizable representation of it.

   SERVICE ENTRY POSITION: Find the technician's curb mark/flag. Project a
   straight line from that mark away from the camera toward the house. Estimate
   where that line meets the visible front foundation/facade. Return that
   horizontal location as "service_entry_x", normalized across the COMPLETE
   visible house frontage including an attached garage/addition:
     0.0 = far-left edge, 0.5 = center, 1.0 = far-right edge.
   This is the likely point where the water service enters the house. Base it on
   the curb mark alignment, not on the front door and not on address writing.
   Set "service_entry_confidence" to high when the mark and projected facade
   intersection are clear, medium when partly obstructed, and low when the mark
   is absent or ambiguous. When confidence is low, use 0.5 as the safe default.

Return ONLY JSON, no prose:
{
  "measurements": {
    "reg_no": "", "address": "", "street_name": "", "date": "",
    "vertical": "", "left": "", "right": "",
    "curb_to_house": "",
    "house_side_material": "", "street_side_material": "",
    "service_diameter": "",
    "contractor": "", "inspected_by": "",
    "main_size": "", "main_material": "",
    "main_label": "", "reference_notes": "", "flag_notes": "",
    "left_tie_object": {"type": "this_house", "label": "", "side": "left"},
    "right_tie_object": {"type": "this_house", "label": "", "side": "right"}
  },
  "house": {
    "stories": 1,
    "roof_type": "gable",
    "width_units": 3,
    "garage": "none",
    "porch": false,
    "front_door": "center",
    "window_columns": 2,
    "service_entry_x": 0.5,
    "service_entry_confidence": "low",
    "notes": ""
  }
}
Use "" or sensible defaults for anything you cannot determine. width_units is a
1-5 sense of how wide the front is (narrow=1, very wide=5). roof_type one of:
gable, hip, flat, mansard, gambrel."""

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1200,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
            {"type": "text", "text": prompt},
        ]}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"measurements": {}, "house": {}, "_parse_error": raw[:400]}


def draw_house_elevation(draw: ImageDraw.ImageDraw, house: dict,
                         cx: int, base_y: int, max_w: int, max_h: int) -> tuple[int, int]:
    """
    Draw a recognizable front-elevation of the house centered horizontally on
    cx, sitting with its base line at base_y. Returns (left_x, right_x) of the
    building's footprint base so ties can be anchored to the front corners.
    """
    stories = int(house.get("stories") or 1)
    roof_type = (house.get("roof_type") or "gable").lower()
    width_units = int(house.get("width_units") or 3)
    garage = (house.get("garage") or "none").lower()
    porch = bool(house.get("porch"))
    door = (house.get("front_door") or "center").lower()
    win_cols = int(house.get("window_columns") or 2)

    # Body size from width_units (1..5) and stories, clamped to the box
    body_w = int(min(max_w * 0.5, max_w * (0.22 + 0.06 * max(1, min(5, width_units)))))
    story_h = 34
    body_h = min(max_h - 40, story_h * max(1, min(3, stories)) + 6)

    bx0 = cx - body_w // 2
    bx1 = cx + body_w // 2
    by1 = base_y
    by0 = by1 - body_h

    # Garage widens the footprint on one side
    garage_w = 0
    gx0 = gx1 = None
    if garage in ("left", "right"):
        garage_w = int(body_w * 0.5)
        if garage == "left":
            gx1 = bx0
            gx0 = bx0 - garage_w
        else:
            gx0 = bx1
            gx1 = bx1 + garage_w

    # Body walls
    draw.rectangle([bx0, by0, bx1, by1], outline="#000", width=2)

    # Roof
    roof_h = 26
    if roof_type == "flat":
        draw.rectangle([bx0 - 3, by0 - 6, bx1 + 3, by0], outline="#000", width=2)
        peak_y = by0 - 6
    elif roof_type == "hip":
        inset = int(body_w * 0.2)
        draw.line([(bx0, by0), (bx0 + inset, by0 - roof_h)], fill="#000", width=2)
        draw.line([(bx1, by0), (bx1 - inset, by0 - roof_h)], fill="#000", width=2)
        draw.line([(bx0 + inset, by0 - roof_h), (bx1 - inset, by0 - roof_h)], fill="#000", width=2)
        draw.line([(bx0, by0), (bx1, by0)], fill="#000", width=1)
        peak_y = by0 - roof_h
    elif roof_type == "gambrel":
        draw.line([(bx0, by0), (bx0 + body_w // 6, by0 - roof_h // 2)], fill="#000", width=2)
        draw.line([(bx0 + body_w // 6, by0 - roof_h // 2), (cx, by0 - roof_h)], fill="#000", width=2)
        draw.line([(bx1, by0), (bx1 - body_w // 6, by0 - roof_h // 2)], fill="#000", width=2)
        draw.line([(bx1 - body_w // 6, by0 - roof_h // 2), (cx, by0 - roof_h)], fill="#000", width=2)
        peak_y = by0 - roof_h
    else:  # gable (default)
        draw.line([(bx0, by0), (cx, by0 - roof_h)], fill="#000", width=2)
        draw.line([(bx1, by0), (cx, by0 - roof_h)], fill="#000", width=2)
        draw.line([(bx0, by0), (bx1, by0)], fill="#000", width=1)
        peak_y = by0 - roof_h

    # Garage box
    if gx0 is not None:
        g_top = by1 - int(body_h * 0.7)
        draw.rectangle([gx0, g_top, gx1, by1], outline="#000", width=2)
        # garage door
        draw.rectangle([gx0 + 5, g_top + 8, gx1 - 5, by1 - 4], outline="#000", width=1)

    # Windows (simple squares per story per column)
    win = 10
    cols = max(1, min(4, win_cols))
    for s in range(max(1, min(3, stories))):
        wy = by1 - story_h * (s + 1) + 8
        for c in range(cols):
            wx = bx0 + int((c + 1) * body_w / (cols + 1)) - win // 2
            draw.rectangle([wx, wy, wx + win, wy + win], outline="#000", width=1)

    # Front door
    door_w, door_h = 12, 22
    if door == "left":
        dx = bx0 + int(body_w * 0.22)
    elif door == "right":
        dx = bx1 - int(body_w * 0.22) - door_w
    else:
        dx = cx - door_w // 2
    draw.rectangle([dx, by1 - door_h, dx + door_w, by1], outline="#000", width=1)

    # Porch (a shallow roof line + posts across the front)
    if porch:
        py = by1 - int(body_h * 0.35)
        draw.line([(bx0 - 6, py), (bx1 + 6, py)], fill="#000", width=1)
        draw.line([(bx0 - 6, py), (bx0 - 6, by1)], fill="#000", width=1)
        draw.line([(bx1 + 6, py), (bx1 + 6, by1)], fill="#000", width=1)

    # Footprint base corners for tie anchoring = outer extent (incl. garage)
    foot_left = gx0 if (gx0 is not None and gx0 < bx0) else bx0
    foot_right = gx1 if (gx1 is not None and gx1 > bx1) else bx1
    return foot_left, foot_right
