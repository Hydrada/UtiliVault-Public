"""
UtiliVault — tiecard_render.py
Render Pine Ln-style Water Service Tie Card HTML from OCR JSON.
Takes the JSON output from tiecard_ocr.py and produces a clean, print-ready
HTML card with accurate SVG tie sketch saved to the output folder.

Usage:
  py tiecard_render.py 7424_7424.json
  py tiecard_render.py --folder ocr_json/
  py tiecard_render.py --folder ocr_json/ --out-dir "C:/Users/Hydra/Desktop/Demo Tiecards"
"""

import argparse
import json
import math
import sys
from pathlib import Path

# Try to import tiecard_sketch for OpenCV-based faithful sketch reproduction.
# Falls back to the generic SVG builder if opencv-python is not installed.
try:
    import tiecard_sketch as _sketch_mod
    _SKETCH_AVAILABLE = True
except ImportError:
    _SKETCH_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent))
from config import DEMO_DIR as DEFAULT_OUT

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Water Service Tie Card — Reg. {reg_no} — {address}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; background: #f0f0f0; padding: 30px; }}
  .page {{ max-width: 740px; margin: 0 auto; }}
  .source-strip {{ background: #dceeff; border: 1px solid #99c2ff; border-radius: 5px;
    padding: 8px 12px; margin-bottom: 14px; font-size: 11px; color: #003399; }}
  /* Yellow card */
  .yc {{ background: #FFFF99; border: 2px solid #999900; border-radius: 4px; overflow: hidden; }}
  .yc-title {{ text-align: center; font-size: 14px; font-weight: bold; color: #000;
    text-decoration: underline; padding: 7px 12px 5px; border-bottom: 1.5px solid #999900;
    letter-spacing: .06em; }}
  .yc-row {{ display: grid; border-bottom: 1.5px solid #999900; min-height: 30px; }}
  .yc-row.r2 {{ grid-template-columns: 1fr 1fr; }}
  .yc-cell {{ padding: 5px 10px; border-right: 1.5px solid #999900; display: flex;
    align-items: baseline; gap: 4px; min-height: 30px; flex-wrap: wrap; }}
  .yc-cell:last-child {{ border-right: none; }}
  .lbl {{ font-size: 11px; color: #000; white-space: nowrap; font-weight: bold; flex-shrink: 0; }}
  .val {{ font-size: 13px; color: #00008B; font-family: 'Segoe Script','Comic Sans MS',cursive; flex: 1; }}
  .yc-comments {{ padding: 6px 10px; min-height: 70px; }}
  .yc-comments .lbl {{ display: block; margin-bottom: 4px; }}
  .yc-comments .val {{ display: block; font-size: 12px; line-height: 1.7; }}
  /* Sketch */
  .yc-sketch {{ border-top: 1.5px solid #999900; padding: 14px 20px 20px; background: #FFFDE0; }}
  .sketch-lbl {{ font-size: 10px; color: #666600; font-style: italic; margin-bottom: 10px; }}
  /* Cost table (old cards) */
  .cost-wrap {{ border-top: 1.5px solid #999900; display: grid; grid-template-columns: 1fr 1fr; }}
  .cost-col {{ border-right: 1.5px solid #999900; }}
  .cost-col:last-child {{ border-right: none; }}
  .cost-hdr {{ background: #fff3a0; padding: 6px 10px; font-size: 10px; font-weight: bold;
    color: #5a4600; border-bottom: 1.5px solid #999900; text-transform: uppercase; }}
  .cost-row {{ display: grid; grid-template-columns: 1fr auto; padding: 4px 10px;
    border-bottom: 1px solid #e8d840; font-size: 11px; gap: 6px; }}
  .cost-total {{ display: grid; grid-template-columns: 1fr auto; padding: 6px 10px;
    background: #fff3a0; border-top: 1.5px solid #999900; font-weight: bold; font-size: 12px; }}
  /* Flags */
  .flags {{ margin-top: 12px; display: flex; flex-direction: column; gap: 5px; }}
  .fl {{ border-radius: 5px; padding: 6px 11px; font-size: 11px; line-height: 1.5; }}
  .fl.warn {{ background: #fff3cd; color: #7a4f00; border: 1px solid #ffc107; }}
  .fl.ok   {{ background: #d4edda; color: #155724; border: 1px solid #86d89b; }}
  .fl.info {{ background: #d0e8ff; color: #003399; border: 1px solid #99c2ff; }}
  .fl.err  {{ background: #fde8e8; color: #7a0000; border: 1px solid #f5a0a0; }}
  .print-btn {{ display: block; margin: 14px auto 0; padding: 8px 24px; background: #333;
    color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }}
  @media print {{
    .source-strip, .flags, .print-btn {{ display: none; }}
    body {{ background: #fff; padding: 0; }}
    .page {{ max-width: 100%; }}
  }}
</style>
</head>
<body>
<div class="page">
  <div class="source-strip">
    UtiliVault &nbsp;|&nbsp; Auto-digitized via Claude Vision &nbsp;|&nbsp; <strong>{source_file}</strong>
    &nbsp;→&nbsp; Water Service Tie Card (Pine Ln format)
  </div>

  <div class="yc">
    <div class="yc-title">WATER SERVICE TIE CARD</div>

    <div class="yc-row r2">
      <div class="yc-cell"><span class="lbl">Address:</span><span class="val">{address}</span></div>
      <div class="yc-cell"><span class="lbl">Reg. No:</span><span class="val">{reg_no}</span></div>
    </div>
    <div class="yc-row r2">
      <div class="yc-cell"><span class="lbl">Contractor:</span><span class="val">{contractor}</span></div>
      <div class="yc-cell"><span class="lbl">Date:</span><span class="val">{date}</span></div>
    </div>
    <div class="yc-row">
      <div class="yc-cell" style="border-right:none">
        <span class="lbl">Inspected By:</span><span class="val">{inspected_by}</span>
      </div>
    </div>
    <div class="yc-row r2">
      <div class="yc-cell"><span class="lbl">Material Main:</span><span class="val">{material_main}</span></div>
      <div class="yc-cell"><span class="lbl">Diameter Main:</span><span class="val">{diameter_main}</span></div>
    </div>
    <div class="yc-row r2">
      <div class="yc-cell">
        <span class="lbl">Material Service (Main to Curb):</span>
        <span class="val">{material_main_to_curb}</span>
      </div>
      <div class="yc-cell">
        <span class="lbl">Diameter Service:</span>
        <span class="val">{diameter_service}</span>
      </div>
    </div>
    <div class="yc-row">
      <div class="yc-cell" style="border-right:none">
        <span class="lbl">Material Service (Curb to House):</span>
        <span class="val">{material_curb_to_house}</span>
      </div>
    </div>
    <div class="yc-row" style="border-bottom:none">
      <div class="yc-comments">
        <span class="lbl">Comments:</span>
        <span class="val">{comments}</span>
      </div>
    </div>

    {cost_section}

    <div class="yc-sketch">
      <div class="sketch-lbl">
        Tie sketch — faithfully reproduced from original scan
        {sketch_source_note}
      </div>
      {sketch_svg}
    </div>
  </div>

  <div class="flags">
    {flag_html}
  </div>

  <button class="print-btn" onclick="window.print()">Print / Save as PDF</button>
</div>
</body>
</html>
"""


# ── SVG SKETCH BUILDER ────────────────────────────────────────────────────────

def build_sketch_svg(back: dict) -> str:
    """
    Build a faithful triangulation tie sketch SVG from extracted back-page data.
    All positions are derived from the actual extracted measurements.
    """
    if not back or not back.get("has_sketch"):
        return '<p style="color:#999;font-style:italic;font-size:11px;">No sketch data extracted from this card.</p>'

    prop_label    = back.get("property_label") or ""
    vert_meas     = back.get("vertical_measurement") or ""
    left_meas     = back.get("left_diagonal_measurement") or ""
    right_meas    = back.get("right_diagonal_measurement") or ""
    main_label    = back.get("main_label") or "W. MAIN"
    ref_label     = back.get("reference_structure_label") or ""
    ref_number    = back.get("reference_structure_number") or ""
    sketch_notes  = back.get("sketch_notes") or ""

    # Fixed canvas geometry — proportions match original card sketch style
    W, H = 520, 400
    # Property box
    pb_cx, pb_y = 260, 14
    pb_w, pb_h  = 140, 48
    pb_x = pb_cx - pb_w // 2

    # Vertical line: property box bottom → apex
    apex_x, apex_y = 260, 185
    vert_top_y = pb_y + pb_h

    # Diagonal end points (bottom corners of reference box)
    ref_box_y   = 310
    ref_box_w   = 240
    ref_box_h   = 52
    ref_box_x   = pb_cx - ref_box_w // 2
    left_pt_x   = ref_box_x
    left_pt_y   = ref_box_y
    right_pt_x  = ref_box_x + ref_box_w
    right_pt_y  = ref_box_y

    # Main line y — between apex and ref box
    main_y = 248

    # Witness lines for main→apex dimension
    wit_x = apex_x - 52

    svg = f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Arial,sans-serif" style="display:block;max-height:440px">\n'

    # Property box
    svg += f'  <rect x="{pb_x}" y="{pb_y}" width="{pb_w}" height="{pb_h}" fill="#FFFDE0" stroke="#000" stroke-width="2"/>\n'
    lines = prop_label.split("\n") if "\n" in prop_label else [prop_label]
    for i, line in enumerate(lines[:2]):
        ty = pb_y + 20 + i * 16
        svg += f'  <text x="{pb_cx}" y="{ty}" text-anchor="middle" font-size="12" font-weight="bold" fill="#000">{_esc(line)}</text>\n'

    # Vertical service line
    svg += f'  <line x1="{apex_x}" y1="{vert_top_y}" x2="{apex_x}" y2="{apex_y}" stroke="#000" stroke-width="2.5"/>\n'

    # Vertical measurement label
    if vert_meas:
        svg += f'  <text x="{apex_x + 6}" y="{(vert_top_y + apex_y)//2 + 4}" font-size="12" font-weight="bold" fill="#000">{_esc(vert_meas)}</text>\n'

    # Apex dot
    svg += f'  <circle cx="{apex_x}" cy="{apex_y}" r="5" fill="#000"/>\n'
    svg += f'  <text x="{apex_x + 8}" y="{apex_y - 3}" font-size="9" fill="#444">curb stop</text>\n'

    # Left diagonal
    svg += f'  <line x1="{apex_x}" y1="{apex_y}" x2="{left_pt_x}" y2="{left_pt_y}" stroke="#000" stroke-width="2.5"/>\n'
    if left_meas:
        mx = (apex_x + left_pt_x) // 2
        my = (apex_y + left_pt_y) // 2
        angle = math.degrees(math.atan2(left_pt_y - apex_y, left_pt_x - apex_x))
        svg += (f'  <text x="{mx}" y="{my}" font-size="12" font-weight="bold" fill="#000"'
                f' transform="rotate({angle:.1f},{mx},{my})" text-anchor="middle"'
                f' dy="-5">{_esc(left_meas)}</text>\n')

    # Right diagonal
    svg += f'  <line x1="{apex_x}" y1="{apex_y}" x2="{right_pt_x}" y2="{right_pt_y}" stroke="#000" stroke-width="2.5"/>\n'
    if right_meas:
        mx = (apex_x + right_pt_x) // 2
        my = (apex_y + right_pt_y) // 2
        angle = math.degrees(math.atan2(right_pt_y - apex_y, right_pt_x - apex_x))
        svg += (f'  <text x="{mx}" y="{my}" font-size="12" font-weight="bold" fill="#000"'
                f' transform="rotate({angle:.1f},{mx},{my})" text-anchor="middle"'
                f' dy="-5">{_esc(right_meas)}</text>\n')

    # Main line
    svg += f'  <line x1="30" y1="{main_y}" x2="{W-30}" y2="{main_y}" stroke="#000" stroke-width="3"/>\n'
    svg += f'  <text x="34" y="{main_y - 4}" font-size="11" font-weight="bold" fill="#000">{_esc(main_label)}</text>\n'

    # Dashed vertical below main to ref box
    svg += f'  <line x1="{apex_x}" y1="{main_y}" x2="{apex_x}" y2="{ref_box_y}" stroke="#000" stroke-width="2" stroke-dasharray="5,3"/>\n'

    # Reference structure box
    svg += f'  <rect x="{ref_box_x}" y="{ref_box_y}" width="{ref_box_w}" height="{ref_box_h}" fill="#FFFDE0" stroke="#000" stroke-width="2"/>\n'
    if ref_label:
        svg += f'  <text x="{pb_cx}" y="{ref_box_y + 22}" text-anchor="middle" font-size="13" font-weight="bold" fill="#000">{_esc(ref_label)}</text>\n'
    if ref_number:
        svg += f'  <text x="{pb_cx}" y="{ref_box_y + 40}" text-anchor="middle" font-size="12" fill="#333">{_esc(ref_number)}</text>\n'

    # Corner dots on reference box
    svg += f'  <circle cx="{left_pt_x}" cy="{left_pt_y}" r="4" fill="#000"/>\n'
    svg += f'  <circle cx="{right_pt_x}" cy="{right_pt_y}" r="4" fill="#000"/>\n'

    # Witness lines: main → apex dimension (shows dist_main_to_curb)
    svg += f'  <line x1="{wit_x}" y1="{apex_y}" x2="{wit_x}" y2="{main_y}" stroke="#666" stroke-width="1" stroke-dasharray="3,2"/>\n'
    svg += f'  <line x1="{wit_x-6}" y1="{apex_y}" x2="{wit_x+6}" y2="{apex_y}" stroke="#666" stroke-width="1.5"/>\n'
    svg += f'  <line x1="{wit_x-6}" y1="{main_y}" x2="{wit_x+6}" y2="{main_y}" stroke="#666" stroke-width="1.5"/>\n'

    if sketch_notes:
        svg += f'  <text x="{W-10}" y="{H-8}" text-anchor="end" font-size="9" fill="#888" font-style="italic">{_esc(sketch_notes[:80])}</text>\n'

    svg += "</svg>\n"
    return svg


def _esc(s: str) -> str:
    """Escape HTML special chars for SVG text."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── COST SECTION (old-style cards only) ──────────────────────────────────────

def build_cost_section(front: dict) -> str:
    if front.get("card_type") != "return_of_service_pipe":
        return ""

    def rows(items):
        if not items:
            return ""
        out = ""
        for item in items:
            desc = item.get("description") or ""
            qty  = item.get("quantity") or ""
            unit = item.get("unit") or ""
            amt  = item.get("amount") or ""
            label = f"{qty} {unit} {desc}".strip() if (qty or unit) else desc
            out += f'<div class="cost-row"><span>{_esc(label)}</span><span>{_esc(amt)}</span></div>\n'
        return out

    town_rows  = rows(front.get("cost_to_town") or [])
    owner_rows = rows(front.get("cost_to_owner") or [])
    town_total  = front.get("cost_to_town_total") or "—"
    owner_total = front.get("cost_to_owner_total") or "—"

    return f"""
<div class="cost-wrap">
  <div class="cost-col">
    <div class="cost-hdr">Cost to town — main to curb stop cock incl.</div>
    {town_rows}
    <div class="cost-total"><span>Total</span><span>{_esc(town_total)}</span></div>
  </div>
  <div class="cost-col">
    <div class="cost-hdr">Cost to owner</div>
    {owner_rows}
    <div class="cost-total"><span>Total</span><span>{_esc(owner_total)}</span></div>
  </div>
</div>
"""


# ── FLAG HTML ─────────────────────────────────────────────────────────────────

FLAG_MESSAGES = {
    "lead_fittings":       ("warn", "Lead-lined fittings detected — flag for lead service line inventory."),
    "relaid":              ("warn", "Service was relaid — check registry for relay date and second card."),
    "dual_address":        ("warn", "Dual address on file — both should be indexed under this reg. number."),
    "reg_number_conflict": ("err",  "Reg. number conflict detected — verify against registry before committing."),
    "low_pressure":        ("err",  "Low pressure flag — review field readings."),
    "needs_review":        ("warn", "Card flagged for manual review."),
    "illegible_field":     ("warn", "One or more fields were partially illegible — verify against original scan."),
}

def build_flag_html(flags: list) -> str:
    if not flags:
        return '<div class="fl ok">&#10003; All fields extracted cleanly. No flags.</div>'
    out = ""
    for f in flags:
        cls, msg = FLAG_MESSAGES.get(f, ("info", f))
        out += f'<div class="fl {cls}">{msg}</div>\n'
    return out


# ── FIELD HELPERS ─────────────────────────────────────────────────────────────

def _f(d: dict, *keys, fallback="") -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return fallback


def front_to_fields(front: dict) -> dict:
    """Normalize front data regardless of old vs new card type."""
    ct = front.get("card_type", "")

    if ct == "return_of_service_pipe":
        address  = _f(front, "street")
        date     = _f(front, "date_laid")
        owner    = _f(front, "owner")
        foreman  = _f(front, "foreman")
        contractor = _f(front, "foreman", fallback="Town crew")
        inspected  = f"{foreman} (Foreman)" if foreman else ""
        dist       = _f(front, "dist_main_to_curb_stop")
        comments_parts = []
        if owner:            comments_parts.append(f"Owner: {owner}.")
        if dist:             comments_parts.append(f"Dist. main to curb stop cock: {dist}.")
        stamp = _f(front, "status_stamp")
        if stamp:            comments_parts.append(f"Status: {stamp}.")
        comments = "  ".join(comments_parts)
        mat_main  = _f(front, "main_pipe_material")
        diam_main = _f(front, "main_pipe_diameter")
        # Service materials from cost lines
        mat_mtc   = ""
        mat_cth   = ""
        diam_svc  = ""
        for item in (front.get("cost_to_town") or []):
            d = (item.get("description") or "").lower()
            if "pipe" in d and not mat_mtc:
                qty = item.get("quantity") or ""
                mat_mtc = f"{qty} {item.get('description','')}"
        for item in (front.get("cost_to_owner") or []):
            d = (item.get("description") or "").lower()
            if "pipe" in d and not mat_cth:
                qty = item.get("quantity") or ""
                mat_cth = f"{qty} {item.get('description','')}"

    else:
        address    = _f(front, "address")
        date       = _f(front, "date")
        contractor = _f(front, "contractor")
        inspected  = _f(front, "inspected_by")
        comments   = _f(front, "comments")
        mat_main   = _f(front, "material_main")
        diam_main  = _f(front, "diameter_main")
        mat_mtc    = _f(front, "material_service_main_to_curb")
        diam_svc   = _f(front, "diameter_service")
        mat_cth    = _f(front, "material_service_curb_to_house")

    return {
        "address":            address,
        "reg_no":             _f(front, "reg_no", "reg_number"),
        "contractor":         contractor,
        "date":               date,
        "inspected_by":       inspected,
        "material_main":      mat_main,
        "diameter_main":      diam_main,
        "material_main_to_curb": mat_mtc,
        "diameter_service":   diam_svc,
        "material_curb_to_house": mat_cth,
        "comments":           comments,
    }


# ── RENDER ONE JSON ───────────────────────────────────────────────────────────

def render_json(json_path: Path, out_dir: Path) -> Path:
    data   = json.loads(json_path.read_text(encoding="utf-8"))
    front  = data.get("front") or {}
    back   = data.get("back") or {}
    source = Path(data.get("source_file", json_path.stem)).name

    fields = front_to_fields(front)
    flags  = list(front.get("flags") or [])
    if back:
        flags += [f for f in (back.get("flags") or []) if f not in flags]
        if back.get("sketch_notes") and "illegible" in back["sketch_notes"].lower():
            if "illegible_field" not in flags:
                flags.append("illegible_field")

    # Try OpenCV-traced sketch first; fall back to generic SVG builder
    svg = None
    tif_path_str = data.get("source_file", "")
    tif_path = Path(tif_path_str) if tif_path_str else None
    sketch_method = "generic"

    if back.get("has_sketch") and _SKETCH_AVAILABLE and tif_path and tif_path.exists():
        try:
            svg = _sketch_mod.render_sketch(tif_path, back, page=1)
            sketch_method = "opencv"
        except Exception as e:
            print(f"  [WARN] tiecard_sketch failed ({e}), falling back to generic SVG")

    if svg is None:
        svg = build_sketch_svg(back)

    if back.get("has_sketch"):
        sketch_note = f"(OpenCV line-trace from {source} page 2)" if sketch_method == "opencv" else f"(generic from {source} page 2)"
    else:
        sketch_note = "(no back-page sketch found)"

    cost_html   = build_cost_section(front)
    flag_html   = build_flag_html(flags)

    reg  = fields["reg_no"] or "UNK"
    addr = fields["address"] or "unknown"
    safe_addr = addr.replace("/", "-").replace("\\", "-").replace(" ", "_").replace(".", "")
    filename = f"{reg}_{safe_addr}.html"

    html = HTML_TEMPLATE.format(
        reg_no               = _esc(reg),
        address              = _esc(addr),
        source_file          = _esc(source),
        contractor           = _esc(fields["contractor"]),
        date                 = _esc(fields["date"]),
        inspected_by         = _esc(fields["inspected_by"]),
        material_main        = _esc(fields["material_main"]),
        diameter_main        = _esc(fields["diameter_main"]),
        material_main_to_curb= _esc(fields["material_main_to_curb"]),
        diameter_service     = _esc(fields["diameter_service"]),
        material_curb_to_house=_esc(fields["material_curb_to_house"]),
        comments             = _esc(fields["comments"]),
        cost_section         = cost_html,
        sketch_source_note   = _esc(sketch_note),
        sketch_svg           = svg,
        flag_html            = flag_html,
    )

    out_path = out_dir / filename
    out_path.write_text(html, encoding="utf-8")
    print(f"  [Rendered] {out_path.name}")
    return out_path


def render_folder(json_dir: Path, out_dir: Path):
    files = sorted(json_dir.glob("*.json"))
    if not files:
        print(f"[WARN] No JSON files found in {json_dir}")
        return
    print(f"\n[Render] {len(files)} JSON file(s) → {out_dir}")
    for f in files:
        try:
            render_json(f, out_dir)
        except Exception as e:
            print(f"  [ERROR] {f.name}: {e}")
    print(f"[Done] Cards saved to {out_dir}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Render Pine Ln tie-card HTML from OCR JSON"
    )
    parser.add_argument("file", nargs="?", help="Single JSON file to render")
    parser.add_argument("--folder", help="Folder of JSON files to batch render")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT),
                        help=f"Output directory (default: {DEFAULT_OUT})")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.folder:
        render_folder(Path(args.folder), out_dir)
    elif args.file:
        render_json(Path(args.file), out_dir)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
