import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

import draw_tiecard_back as renderer
from build_comparisons import (
    _double_curb_pair,
    _house_service_entry_x,
    _is_double_curb,
    _normalize_tie_object,
    _service_line_apex_x,
    draw_sketch_diagram,
)

def tiff_metadata(path: Path) -> list[dict]:
    frames = []
    with Image.open(path) as image:
        index = 0
        while True:
            image.seek(index)
            frames.append(
                {
                    "size": image.size,
                    "compression": image.tag_v2.get(259),
                    "dpi": image.info.get("dpi"),
                }
            )
            index += 1
            try:
                image.seek(index)
            except EOFError:
                break
    return frames


class TieCardRendererContractTests(unittest.TestCase):
    def setUp(self):
        self.card = {
            "address": "6 Demo Rd",
            "property_label": "6 Demo Rd",
            "reg_no": "8443",
            "contractor": "Example Utility",
            "date": "07/18/2026",
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
            "ref_label": "Hydrant",
            "ref_number": "H-17",
            "comments": "Renderer contract fixture",
        }

    def test_printable_card_is_two_page_lzw_tiff_at_300_dpi(self):
        with tempfile.TemporaryDirectory() as root:
            out_dir = Path(root) / "printable"
            digital_dir = Path(root) / "digital"
            out_dir.mkdir()
            digital_dir.mkdir()

            with (
                patch.object(renderer, "OUT_DIR", out_dir),
                patch.object(renderer, "DIGITAL_DIR", digital_dir),
            ):
                paths = renderer.process_card(
                    dict(self.card), front_path=None, folder_name=None
                )
                frames = tiff_metadata(paths["tif"])

            self.assertEqual("6 Demo Rd 8443.tif", paths["tif"].name)
            self.assertEqual(2, len(frames))
            self.assertEqual(
                [(renderer.BACK_W, renderer.BACK_H)] * 2,
                [frame["size"] for frame in frames],
            )
            self.assertTrue(all(frame["compression"] == 5 for frame in frames))
            self.assertTrue(
                all(
                    frame["dpi"]
                    and round(frame["dpi"][0]) == 300
                    and round(frame["dpi"][1]) == 300
                    for frame in frames
                )
            )
            self.assertNotIn("digital_tif", paths)
            self.assertEqual([], list(digital_dir.iterdir()))

    def test_photo_creates_separate_three_page_digital_tiff(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            out_dir = root_path / "printable"
            digital_dir = root_path / "digital"
            out_dir.mkdir()
            digital_dir.mkdir()
            photo = root_path / "house.jpg"
            Image.new("RGB", (1200, 700), "#4A78A8").save(photo, quality=90)

            with (
                patch.object(renderer, "OUT_DIR", out_dir),
                patch.object(renderer, "DIGITAL_DIR", digital_dir),
            ):
                paths = renderer.process_card(
                    dict(self.card),
                    front_path=None,
                    folder_name=None,
                    display_photo_path=photo,
                )
                printable_frames = tiff_metadata(paths["tif"])
                digital_frames = tiff_metadata(paths["digital_tif"])

            self.assertEqual(2, len(printable_frames))
            self.assertEqual(3, len(digital_frames))
            self.assertEqual(
                "6 Demo Rd 8443_DIGITAL.tif", paths["digital_tif"].name
            )
            self.assertEqual("6 Demo Rd 8443_photo.png", paths["photo_png"].name)
            self.assertEqual(out_dir, paths["tif"].parent)
            self.assertEqual(digital_dir, paths["digital_tif"].parent)
            self.assertTrue(all(frame["compression"] == 5 for frame in digital_frames))
            self.assertTrue(
                all(
                    frame["dpi"]
                    and round(frame["dpi"][0]) == 300
                    and round(frame["dpi"][1]) == 300
                    for frame in digital_frames
                )
            )

    def test_filename_uses_address_and_written_registry_number(self):
        self.assertEqual(
            "150 Demo Way 10464",
            renderer.card_filename_base(
                {"address": "150 Demo Way", "reg_no": "10464"}
            ),
        )
        self.assertEqual(
            "150 Demo Way 10464",
            renderer.card_filename_base(
                {"address": "150 Demo Way:*?", "reg_no": "10464"}
            ),
        )

    def test_registry_fallback_is_used_only_when_registry_is_blank(self):
        with (
            patch.object(renderer, "render_front_page", return_value=Image.new("RGB", (10, 10))),
            patch.object(renderer, "render_back_page", return_value=Image.new("RGB", (10, 10))),
            patch.object(renderer, "render_photo_page", return_value=None),
            patch.object(renderer, "save_outputs", return_value={"tif": Path("card.tif")}),
        ):
            missing = {"address": "10 Example Way", "_reg_fallback": "photo-123"}
            renderer.process_card(missing, front_path=None, folder_name=None)
            present = {
                "address": "10 Example Way",
                "reg_no": "7424",
                "_reg_fallback": "photo-123",
            }
            renderer.process_card(present, front_path=None, folder_name=None)

        self.assertEqual("photo-123", missing["reg_no"])
        self.assertEqual("7424", present["reg_no"])

    def test_double_curb_values_are_split_into_distinct_old_and_new_ties(self):
        self.assertEqual(
            {"old": "10’ 3”", "new": "14’ 10”"},
            _double_curb_pair("10’ 3” to old curb | 14’ 10” to new curb"),
        )
        self.assertEqual(
            {"old": "8’ 7”", "new": "13’ 8”"},
            _double_curb_pair("Old 8’ 7” | New 13’ 8”"),
        )
        self.assertTrue(
            _is_double_curb(
                {
                    "left_diagonal_measurement": "10’ 3” to old curb | 14’ 10” to new curb",
                    "right_diagonal_measurement": "23’ 3” to old curb | 25’ 3” to new curb",
                }
            )
        )

    def test_double_curb_card_renders_at_full_card_size(self):
        card = dict(self.card)
        card.update(
            {
                "address": "96 Example St",
                "property_label": "96 Example St",
                "left": "10’ 3” to old curb | 14’ 10” to new curb",
                "right": "23’ 3” to old curb | 25’ 3” to new curb",
                "curb_to_house": "Old 8’ 7” | New 13’ 8”",
                "vertical": "7’ 6”",
                "double_curbed": True,
                "curb_offset": "5’ 3”",
            }
        )

        front = renderer.render_front_page(card)
        back = renderer.render_back_page(card)

        self.assertEqual((renderer.BACK_W, renderer.BACK_H), front.size)
        self.assertEqual((renderer.BACK_W, renderer.BACK_H), back.size)

    def test_house_service_entry_uses_curb_mark_projection(self):
        house = {
            "service_entry_x": 0.2,
            "service_entry_confidence": "high",
        }

        self.assertEqual(120, _house_service_entry_x(house, 100, 200))

    def test_house_service_entry_falls_back_to_center_when_uncertain(self):
        self.assertEqual(
            150,
            _house_service_entry_x(
                {
                    "service_entry_x": 0.9,
                    "service_entry_confidence": "low",
                },
                100,
                200,
            ),
        )
        self.assertEqual(150, _house_service_entry_x({}, 100, 200))

    def test_service_line_is_straight_from_house_by_default(self):
        self.assertEqual(172, _service_line_apex_x({}, 172, 150))
        self.assertEqual(
            172,
            _service_line_apex_x(
                {"service_line_straight": True},
                172,
                150,
            ),
        )


    def test_unlabeled_tie_object_defaults_to_this_house(self):
        self.assertEqual(
            {"type": "this_house", "label": "", "side": "left"},
            _normalize_tie_object(None, "left"),
        )
        self.assertEqual(
            "this_house",
            _normalize_tie_object({"type": "house", "label": ""}, "left")["type"],
        )
        self.assertEqual(
            "pole",
            _normalize_tie_object({"type": "pole", "label": "185-5"}, "right")["type"],
        )

    def test_ls_rs_to_neighbor_house_and_pole_not_subject_corners(self):
        img = Image.new("RGB", (900, 700), "#FFFDE0")
        draw = ImageDraw.Draw(img)
        house = {
            "stories": 2,
            "roof_type": "gable",
            "width_units": 3,
            "garage": "none",
            "porch": False,
            "front_door": "center",
            "window_columns": 2,
            "service_entry_x": 0.5,
            "service_entry_confidence": "low",
        }
        back = {
            "has_sketch": True,
            "property_label": "21 Purchase St",
            "vertical_measurement": "21'",
            "left_diagonal_measurement": "32'-9\"",
            "right_diagonal_measurement": "64'",
            "main_label": "8\" DI",
            "left_tie_object": {"type": "house", "label": "23", "side": "left"},
            "right_tie_object": {"type": "pole", "label": "185-5", "side": "right"},
        }
        geo = draw_sketch_diagram(draw, back, 20, 20, 860, 640, house=house)
        self.assertLess(geo["ls_pt"][0], geo["corner_l"][0])
        self.assertGreater(geo["rs_pt"][0], geo["corner_r"][0])
        self.assertEqual("house", geo["left_tie_object"]["type"])
        self.assertEqual("23", geo["left_tie_object"]["label"])
        self.assertEqual("pole", geo["right_tie_object"]["type"])
        self.assertNotEqual(geo["ls_pt"], geo["corner_l"])
        self.assertNotEqual(geo["rs_pt"], geo["corner_r"])
        # Pole-like: a tall ink column at RS, above the baseline, not a house wall.
        rx, ry = geo["rs_pt"]
        col = 0
        for y in range(ry - 40, ry - 8):
            px = img.getpixel((rx, y))
            if px[0] < 40 and px[1] < 40 and px[2] < 40:
                col += 1
        self.assertGreaterEqual(col, 8)

    def test_this_house_both_sides_still_uses_corners(self):
        img = Image.new("RGB", (900, 700), "#FFFDE0")
        draw = ImageDraw.Draw(img)
        house = {
            "stories": 1,
            "roof_type": "gable",
            "width_units": 3,
            "garage": "none",
            "service_entry_x": 0.5,
            "service_entry_confidence": "low",
        }
        back = {
            "has_sketch": True,
            "property_label": "6 Demo Rd",
            "vertical_measurement": "12'-6\"",
            "left_diagonal_measurement": "18'-4\"",
            "right_diagonal_measurement": "21'-8\"",
            "left_tie_object": {"type": "this_house", "side": "left"},
            "right_tie_object": {"type": "this_house", "side": "right"},
        }
        geo = draw_sketch_diagram(draw, back, 20, 20, 860, 640, house=house)
        self.assertEqual(geo["ls_pt"], geo["corner_l"])
        self.assertEqual(geo["rs_pt"], geo["corner_r"])

    def test_service_line_can_be_explicitly_angled(self):
        self.assertEqual(
            150,
            _service_line_apex_x(
                {"service_line_straight": False},
                172,
                150,
            ),
        )


if __name__ == "__main__":
    unittest.main()
