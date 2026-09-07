import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import tiecard_ocr_v2 as ocr


class CrossValidationTests(unittest.TestCase):
    def test_all_engines_failed(self):
        result = ocr.cross_validate(None, None, None)

        self.assertEqual("LOW", result["confidence"])
        self.assertEqual({}, result["data"])
        self.assertEqual([], result["engines_used"])

    def test_claude_only_is_medium_confidence(self):
        data = {"reg_no": "1234", "address": "10 Example Way"}

        result = ocr.cross_validate(data, None, None)

        self.assertEqual("MEDIUM", result["confidence"])
        self.assertIs(data, result["data"])
        self.assertEqual(["Claude Vision"], result["engines_used"])

    def test_raw_text_without_claude_is_low_confidence(self):
        result = ocr.cross_validate(
            None,
            "A sufficiently long Google Vision response",
            "A sufficiently long Tesseract response",
        )

        self.assertEqual("LOW", result["confidence"])
        self.assertIn("Claude unavailable", result["notes"])

    def test_key_field_corroboration_produces_high_confidence(self):
        data = {
            "reg_no": "1234",
            "address": "10 Example Way",
            "contractor": "Acme Water",
        }
        gcv = "Record 1234 at 10 example way installed by acme water."
        tess = "Tie card scan with enough text to count as a valid result."

        result = ocr.cross_validate(data, gcv, tess)

        self.assertEqual("HIGH", result["confidence"])
        self.assertEqual("3/3", result["corroboration"])
        self.assertIn("Triple-engine validation", result["notes"])

    def test_low_corroboration_stays_medium_and_requests_spot_check(self):
        data = {"reg_no": "1234", "address": "10 Example Way"}
        unrelated = "This response is deliberately long but confirms no key fields."

        result = ocr.cross_validate(data, unrelated, unrelated)

        self.assertEqual("MEDIUM", result["confidence"])
        self.assertEqual("0/2", result["corroboration"])
        self.assertIn("flag for spot-check", result["notes"])


class MeasurementTests(unittest.TestCase):
    def test_measurement_normalization_ignores_common_punctuation(self):
        variants = ["11'-6\"", "11 - 6", " 11' / 6 ` ", "11\\6"]

        normalized = {ocr._normalize_measurement_str(value) for value in variants}

        self.assertEqual({"116"}, normalized)

    def test_cross_reference_prefers_printed_front_measurement(self):
        back = {"vertical_measurement": "unclear", "has_sketch": True}

        updated, used = ocr.cross_reference_vertical_measurement(
            {"dist_main_to_curb_stop": "14'-2\""}, back
        )

        self.assertTrue(used)
        self.assertEqual("14'-2\"", updated["vertical_measurement"])
        self.assertEqual(
            "cross_referenced_from_front_card",
            updated["vertical_measurement_source"],
        )
        self.assertEqual("unclear", back["vertical_measurement"])

    def test_cross_reference_leaves_back_unchanged_without_front_distance(self):
        back = {"vertical_measurement": "9'"}

        updated, used = ocr.cross_reference_vertical_measurement({}, back)

        self.assertFalse(used)
        self.assertIs(back, updated)

    def test_sketch_ensemble_votes_equivalent_formats_together(self):
        image = np.zeros((100, 100), dtype=np.uint8)
        readings = [
            {"vertical_measurement": "11'-6\""},
            {"vertical_measurement": "11 - 6"},
            {"vertical_measurement": "11'6"},
            {"vertical_measurement": "12'-0\""},
        ]

        with (
            patch.object(ocr.cv2, "imread", return_value=image),
            patch.object(ocr, "_make_crop_variants", return_value=[image] * 4),
            patch.object(ocr.cv2, "resize", side_effect=lambda value, *_a, **_k: value),
            patch.object(ocr, "_read_sketch_variant", side_effect=readings),
        ):
            updated, report = ocr.ensemble_verify_sketch(
                Path("unused.png"), {"vertical_measurement": "old"}
            )

        self.assertEqual("HIGH", report["vertical_measurement"]["confidence"])
        self.assertEqual("11'-6\"", updated["vertical_measurement"])
        self.assertEqual("HIGH", updated["vertical_measurement_ensemble_confidence"])


if __name__ == "__main__":
    unittest.main()
