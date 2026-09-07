"""
UtiliVault — match_display_photos.py
Pairs a folder of CLEAN display photos with the cards already built from the
annotated field photos, matching by the street address written in red on each
clean photo. For every match it rebuilds the digital-only 3-page card (front +
back + the clean house photo) and (optionally) uploads it to Drive folder 14.

Why this exists: the annotated field photo is the source of record (it carries
the measurements), but it's busy. Morgan re-shoots each house with just the
address in red, out of the way, for a cleaner page-3 photo. Those clean shots
are matched back to the existing cards here — no re-reading of measurements,
no re-drawing of the sketch. Only one cheap address-read per clean photo.

Usage:
  py match_display_photos.py                       # match ./clean_display_photos -> rebuild
  py match_display_photos.py --photos-dir "D:\\clean" --upload
  py match_display_photos.py --dry-run             # show matches, build nothing
"""

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from draw_tiecard_back import (
    OUT_DIR as MANUAL_DIR, render_photo_page, save_digital_outputs, DIGITAL_DIR,
)
from house_from_photo import _photo_payload, CLAUDE_MODEL, ANTHROPIC_API_KEY

from config import CLEAN_DIR as DEFAULT_PHOTOS_DIR
DRIVE_DIGITAL_FOLDER = "14 - Digital Cards (With Photo, Screen Only)"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

_TRAILING_REG = re.compile(r"(?:\s+\d{3,6}A?)+$")  # "150 Demo Way 10464" or "96 Example St 1688  1688A"


def _norm(s: str) -> str:
    """Loose address key: lowercase, drop punctuation, collapse spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[.,]", "", str(s).lower())).strip()


def read_address(photo_path: Path) -> str:
    """Read just the street address written in red on the clean photo."""
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    mime, b64 = _photo_payload(photo_path)
    prompt = (
        "This is a house photo with a street address written on it in red text. "
        "Return ONLY JSON: {\"address\": \"<the street address, e.g. 150 Demo Way>\"}. "
        "Give just the street number and name — no city, state, or ZIP."
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=120,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
            {"type": "text", "text": prompt},
        ]}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return (json.loads(raw.strip()).get("address") or "").strip()
    except json.JSONDecodeError:
        return ""


def index_existing_cards() -> dict:
    """Map normalized address -> {base, front_png, back_png} for built cards."""
    cards = {}
    for back in MANUAL_DIR.glob("*_back.png"):
        base = back.name[:-len("_back.png")]
        front = MANUAL_DIR / f"{base}_front.png"
        if not front.exists():
            continue
        addr_part = _TRAILING_REG.sub("", base)          # drop trailing reg number
        key = _norm(addr_part)
        has_reg = bool(_TRAILING_REG.search(base))
        # When two cards share an address, prefer the one that carries a reg
        # number (the real batch card over a reg-less test artifact).
        if key in cards and cards[key]["has_reg"] and not has_reg:
            continue
        cards[key] = {"base": base, "front_png": front, "back_png": back, "has_reg": has_reg}
    return cards


def find_card(address: str, cards: dict) -> dict | None:
    key = _norm(address)
    if key in cards:
        return cards[key]
    # Fall back to a prefix match (handles minor suffix differences)
    for k, v in cards.items():
        if k.startswith(key) or key.startswith(k):
            return v
    return None


def _card_from_base(base: str, clean_photo: Path) -> dict:
    """Reconstruct the minimal card dict (address, reg) from the file base."""
    match = re.search(r"^(.*?)((?:\s+\d{3,6}A?)+)$", base)
    if match:
        address = match.group(1).strip()
        reg = " / ".join(re.findall(r"\d{3,6}A?", match.group(2)))
    else:
        address, reg = base, ""
    return {"address": address, "reg_no": reg, "_display_photo_path": str(clean_photo)}


def main():
    p = argparse.ArgumentParser(description="Match clean display photos to built cards and rebuild digital cards")
    p.add_argument("--photos-dir", default=str(DEFAULT_PHOTOS_DIR),
                   help="Folder of clean display photos (address in red)")
    p.add_argument("--upload", action="store_true", help="Upload rebuilt digital cards to Drive folder 14")
    p.add_argument("--dry-run", action="store_true", help="Show matches only; build nothing")
    args = p.parse_args()

    photos_dir = Path(args.photos_dir)
    photos_dir.mkdir(parents=True, exist_ok=True)
    photos = sorted(f for f in photos_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS)
    if not photos:
        print(f"[Match] No clean photos in {photos_dir}. Drop them there and re-run.")
        return

    cards = index_existing_cards()
    print(f"[Match] {len(photos)} clean photo(s); {len(cards)} built card(s) to match against.\n")

    drive = digital_id = None
    if args.upload and not args.dry_run:
        from field_intake_watcher import get_drive, folder_id, upload_tif
        drive = get_drive()
        utili_id = folder_id(drive, "UtiliVault")
        digital_id = folder_id(drive, DRIVE_DIGITAL_FOLDER, utili_id)

    matched = unmatched = 0
    for photo in photos:
        address = read_address(photo)
        card_ref = find_card(address, cards) if address else None
        if not card_ref:
            unmatched += 1
            print(f"  [NO MATCH] {photo.name}  (read address: '{address or '?'}')")
            continue
        matched += 1
        print(f"  [MATCH] {photo.name}  ->  {card_ref['base']}")
        if args.dry_run:
            continue

        card = _card_from_base(card_ref["base"], photo)
        photo_img = render_photo_page(card)
        if photo_img is None:
            print(f"    [WARN] could not build photo page for {photo.name}")
            continue
        front_img = Image.open(card_ref["front_png"])
        back_img = Image.open(card_ref["back_png"])
        paths = save_digital_outputs(card, front_img, back_img, photo_img)
        print(f"    -> {paths['digital_tif'].name}")
        if drive and digital_id:
            from field_intake_watcher import upload_tif
            upload_tif(drive, paths["digital_tif"], digital_id)

    print(f"\n[Match] Done. {matched} matched, {unmatched} unmatched. "
          f"Digital cards in {DIGITAL_DIR}")


if __name__ == "__main__":
    main()
