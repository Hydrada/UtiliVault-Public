"""
UtiliVault — tiecard_review.py
Side-by-side scan vs output review page.
Generates a single HTML review page showing every rendered card next to
its source scan so you can spot any misreads before mass commit.

Usage:
  py tiecard_review.py
  py tiecard_review.py --scans "C:/path/to/scans" --cards "C:/Users/Hydra/Desktop/Demo Tiecards"
  py tiecard_review.py --open   # open the review page in browser when done
"""

import argparse
import base64
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DESKTOP as DEFAULT_SCANS, DEMO_DIR as DEFAULT_CARDS, REVIEW_HTML as DEFAULT_OUT

SCAN_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}


def tif_page_to_b64_png(tif_path: Path, page: int = 0) -> str | None:
    """Convert one page of a TIF to a base64 PNG data URI."""
    try:
        from PIL import Image
        import io
        img = Image.open(tif_path)
        img.seek(page)
        buf = io.BytesIO()
        img.copy().convert("RGB").save(buf, format="PNG")
        return "data:image/png;base64," + base64.standard_b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def find_scan_for_card(card_html: Path, scan_dir: Path) -> Path | None:
    """Try to find the source TIF for a rendered card by reg number in filename."""
    stem = card_html.stem   # e.g. "7424_954_Concord_St"
    reg  = stem.split("_")[0]
    for ext in SCAN_EXTENSIONS:
        # Try exact reg number match
        for candidate in scan_dir.iterdir():
            if candidate.suffix.lower() in SCAN_EXTENSIONS:
                if candidate.stem == reg or candidate.stem.startswith(reg):
                    return candidate
    return None


def build_review_page(scan_dir: Path, cards_dir: Path, out_path: Path):
    card_files = sorted(cards_dir.glob("*.html"))
    card_files = [f for f in card_files if not f.name.startswith("_")]

    if not card_files:
        print(f"[WARN] No rendered card HTML files found in {cards_dir}")
        return

    print(f"\n[Review] Building review page for {len(card_files)} card(s)...")

    entries = []
    for card in card_files:
        scan = find_scan_for_card(card, scan_dir)
        scan_front_uri = None
        scan_back_uri  = None

        if scan:
            scan_front_uri = tif_page_to_b64_png(scan, page=0)
            scan_back_uri  = tif_page_to_b64_png(scan, page=1)
            print(f"  {card.name}  ←  {scan.name}")
        else:
            print(f"  {card.name}  ←  (source scan not found in {scan_dir})")

        card_html_content = card.read_text(encoding="utf-8")
        # Extract just the inner .yc block for embedding
        start = card_html_content.find('<div class="yc">')
        end   = card_html_content.find('</div>\n\n  <div class="flags">')
        if start != -1 and end != -1:
            embedded = card_html_content[start:end + 6]
        else:
            embedded = f'<p>Could not embed card content from {card.name}</p>'

        entries.append({
            "card_name":       card.name,
            "card_path":       str(card.resolve()),
            "scan_name":       scan.name if scan else "not found",
            "scan_front_uri":  scan_front_uri,
            "scan_back_uri":   scan_back_uri,
            "embedded":        embedded,
        })

    html = _build_html(entries)
    out_path.write_text(html, encoding="utf-8")
    print(f"\n[Done] Review page saved: {out_path}")
    return out_path


def _build_html(entries: list) -> str:
    cards_html = ""
    for i, e in enumerate(entries):
        scan_img_front = (
            f'<img src="{e["scan_front_uri"]}" style="width:100%;border:1px solid #ccc;border-radius:3px;margin-bottom:6px">'
            if e["scan_front_uri"] else
            '<div style="background:#eee;padding:20px;text-align:center;color:#999;font-size:12px;border-radius:3px">Scan not found</div>'
        )
        scan_img_back = (
            f'<img src="{e["scan_back_uri"]}" style="width:100%;border:1px solid #ccc;border-radius:3px;margin-top:6px">'
            if e["scan_back_uri"] else ""
        )

        cards_html += f"""
<div class="entry" id="entry-{i}">
  <div class="entry-header">
    <span class="entry-title">{e['card_name'].replace('.html','')}</span>
    <span class="entry-scan">Source: {e['scan_name']}</span>
    <a href="{e['card_path']}" target="_blank" class="open-btn">Open card ↗</a>
  </div>
  <div class="cols">
    <div class="col-scan">
      <div class="col-lbl">Original scan</div>
      {scan_img_front}
      {scan_img_back}
    </div>
    <div class="col-card">
      <div class="col-lbl">Digitized output</div>
      <div class="card-embed">
        {e['embedded']}
      </div>
    </div>
  </div>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>UtiliVault — Tie-Card Review — Example Utility</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; background: #e8e8e8; padding: 20px; }}
  h1 {{ font-size: 18px; font-weight: bold; color: #222; margin-bottom: 4px; }}
  .subtitle {{ font-size: 12px; color: #666; margin-bottom: 20px; }}
  .summary {{ background: #dceeff; border: 1px solid #99c2ff; border-radius: 5px;
    padding: 10px 14px; margin-bottom: 20px; font-size: 12px; color: #003399; }}
  .entry {{ background: #fff; border: 1px solid #ccc; border-radius: 6px;
    margin-bottom: 28px; overflow: hidden; }}
  .entry-header {{ background: #333; color: #fff; padding: 10px 16px;
    display: flex; align-items: center; gap: 16px; }}
  .entry-title {{ font-size: 14px; font-weight: bold; flex: 1; }}
  .entry-scan {{ font-size: 11px; color: #bbb; }}
  .open-btn {{ background: #555; color: #fff; border: none; padding: 4px 12px;
    border-radius: 3px; font-size: 11px; cursor: pointer; text-decoration: none;
    white-space: nowrap; }}
  .open-btn:hover {{ background: #777; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; }}
  .col-scan {{ padding: 12px; border-right: 1px solid #ddd; background: #f9f9f9; }}
  .col-card {{ padding: 12px; background: #f0f0f0; overflow: auto; }}
  .col-lbl {{ font-size: 10px; font-weight: bold; color: #888; text-transform: uppercase;
    letter-spacing: .05em; margin-bottom: 8px; }}
  /* Embed the yellow card styles inline */
  .card-embed .yc {{ background: #FFFF99; border: 2px solid #999900; border-radius: 4px; overflow: hidden; font-family: Arial,sans-serif; font-size: 90%; }}
  .card-embed .yc-title {{ text-align: center; font-size: 13px; font-weight: bold; color: #000;
    text-decoration: underline; padding: 6px 10px 4px; border-bottom: 1.5px solid #999900; }}
  .card-embed .yc-row {{ display: grid; border-bottom: 1.5px solid #999900; min-height: 26px; }}
  .card-embed .yc-row.r2 {{ grid-template-columns: 1fr 1fr; }}
  .card-embed .yc-cell {{ padding: 4px 8px; border-right: 1.5px solid #999900;
    display: flex; align-items: baseline; gap: 3px; min-height: 26px; flex-wrap: wrap; }}
  .card-embed .yc-cell:last-child {{ border-right: none; }}
  .card-embed .lbl {{ font-size: 10px; color: #000; font-weight: bold; white-space: nowrap; flex-shrink: 0; }}
  .card-embed .val {{ font-size: 11px; color: #00008B; font-family: 'Segoe Script','Comic Sans MS',cursive; flex: 1; }}
  .card-embed .yc-comments {{ padding: 5px 8px; min-height: 50px; }}
  .card-embed .yc-comments .lbl {{ display: block; margin-bottom: 3px; }}
  .card-embed .yc-comments .val {{ display: block; font-size: 11px; line-height: 1.6; }}
  .card-embed .yc-sketch {{ border-top: 1.5px solid #999900; padding: 10px; background: #FFFDE0; }}
  .card-embed .sketch-lbl {{ font-size: 9px; color: #666600; font-style: italic; margin-bottom: 6px; }}
  .card-embed .cost-wrap {{ border-top: 1.5px solid #999900; display: grid; grid-template-columns: 1fr 1fr; }}
  .card-embed .cost-col {{ border-right: 1.5px solid #999900; }}
  .card-embed .cost-col:last-child {{ border-right: none; }}
  .card-embed .cost-hdr {{ background: #fff3a0; padding: 5px 8px; font-size: 9px; font-weight: bold;
    color: #5a4600; border-bottom: 1.5px solid #999900; text-transform: uppercase; }}
  .card-embed .cost-row {{ display: grid; grid-template-columns: 1fr auto; padding: 3px 8px;
    border-bottom: 1px solid #e8d840; font-size: 10px; gap: 4px; }}
  .card-embed .cost-total {{ display: grid; grid-template-columns: 1fr auto; padding: 5px 8px;
    background: #fff3a0; border-top: 1.5px solid #999900; font-weight: bold; font-size: 11px; }}
  @media print {{ body {{ background: #fff; }} }}
</style>
</head>
<body>
  <h1>UtiliVault — Example Utility Tie-Card Digitization Review</h1>
  <p class="subtitle">Compare each original scan (left) against the digitized output (right). Open any card to print or save as PDF.</p>
  <div class="summary">
    {len(entries)} card(s) in this review batch.
    Approve each card visually before committing to Google Drive mass production.
    Flag any misread fields by noting the reg number and re-scanning at higher resolution.
  </div>
  {cards_html}
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate side-by-side scan vs card review page"
    )
    parser.add_argument("--scans",   default=str(DEFAULT_SCANS),
                        help=f"Folder containing original TIF scans (default: {DEFAULT_SCANS})")
    parser.add_argument("--cards",   default=str(DEFAULT_CARDS),
                        help=f"Folder containing rendered HTML cards (default: {DEFAULT_CARDS})")
    parser.add_argument("--out",     default=str(DEFAULT_OUT),
                        help=f"Output review HTML path (default: {DEFAULT_OUT})")
    parser.add_argument("--open",    action="store_true",
                        help="Open the review page in your default browser when done")
    args = parser.parse_args()

    out_path = build_review_page(
        scan_dir  = Path(args.scans),
        cards_dir = Path(args.cards),
        out_path  = Path(args.out),
    )

    if out_path and args.open:
        webbrowser.open(str(out_path))


if __name__ == "__main__":
    main()
