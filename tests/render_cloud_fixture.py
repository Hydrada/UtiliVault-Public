"""Render the fictional cloud-migration fixture for cross-host visual comparison."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import draw_tiecard_back as renderer


CARD = {
    "address": "10 Example Way",
    "property_label": "10 Example Way",
    "reg_no": "TEST-100",
    "contractor": "Demo Contractor",
    "date": "08/29/2026",
    "inspected_by": "Morgan",
    "main_material": "DI",
    "main_size": '8"',
    "service_main_to_curb": "Copper",
    "diameter_service": '1"',
    "service_curb_to_house": "Copper",
    "left": "18'-4\"",
    "right": "21'-8\"",
    "vertical": "12'-6\"",
    "curb_to_house": "33'-0\"",
    "ref_label": "Test Hydrant",
    "ref_number": "H-TEST",
    "comments": "Fictional migration fixture",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    printable = args.output / "printable"
    digital = args.output / "digital"
    printable.mkdir(parents=True, exist_ok=True)
    digital.mkdir(parents=True, exist_ok=True)
    photo = args.output / "fictional-house.jpg"
    Image.new("RGB", (1200, 700), "#4A78A8").save(photo, quality=90)
    with (
        patch.object(renderer, "OUT_DIR", printable),
        patch.object(renderer, "DIGITAL_DIR", digital),
    ):
        paths = renderer.process_card(
            dict(CARD), front_path=None, folder_name=None, display_photo_path=photo
        )
    print(paths["tif"])
    print(paths["digital_tif"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
