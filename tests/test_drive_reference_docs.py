import unittest

from drive_reference_docs import (
    ReferenceIndex,
    merge_reference,
    normalize_address,
    parse_reference_document,
)


NORTH_DOC = """North St / 96 Example St – Tiecard Field Capture

Street Main
8” Ductile Iron

96 Example St – Registries 1688 and 1688A – COMPLETE
Completion Date: 07/22/2026
Service: PS 1” Copper | HS Blue Plastic
Double Curbed: 5’ 3” from old curb
LS: 10’ 3” to old curb | 14’ 10” to new curb
RS: 23’ 3” to old curb | 25’ 3” to new curb
CH: Old 8’ 7” | New 13’ 8”
MC: 7’ 6”

1 Example St – Registry 1619
Service: PS 1” Copper | HS Black Plastic
HS:  | MC:  | LS:  | RS:
"""


class ReferenceDocumentTests(unittest.TestCase):
    def test_parses_registries_service_main_and_measurements(self):
        references = parse_reference_document(NORTH_DOC, "North St")

        school = references[0]
        self.assertEqual("1688 / 1688A", school["reg_no"])
        self.assertEqual("8” Ductile Iron", school["main_label"])
        self.assertEqual("Copper", school["service_main_to_curb"])
        self.assertEqual("1”", school["diameter_service"])
        self.assertEqual("Blue Plastic", school["service_curb_to_house"])
        self.assertEqual("Demo Contractor", school["contractor"])
        self.assertEqual("Morgan", school["inspected_by"])
        self.assertEqual("07/22/2026", school["date"])
        self.assertEqual("7’ 6”", school["vertical"])
        self.assertTrue(school["double_curbed"])
        self.assertEqual("5’ 3”", school["curb_offset"])
        self.assertEqual("10’ 3” to old curb | 14’ 10” to new curb", school["left"])
        self.assertEqual("Old 8’ 7” | New 13’ 8”", school["curb_to_house"])

    def test_matches_common_street_suffix_variants(self):
        references = parse_reference_document(NORTH_DOC, "North St")
        index = ReferenceIndex.from_references(references)

        match = index.lookup({"address": "1 EXAMPLE STREET"})

        self.assertEqual("1619", match["reg_no"])
        self.assertEqual("1 EXAMPLE ST", normalize_address("1 Example Street"))

    def test_photo_values_win_over_document_values(self):
        card = {"address": "96 Example St", "vertical": "FIELD MC"}
        reference = parse_reference_document(NORTH_DOC, "North St")[0]

        merge_reference(card, reference)

        self.assertEqual("FIELD MC", card["vertical"])
        self.assertEqual("1688 / 1688A", card["reg_no"])
        self.assertEqual("Blue Plastic", card["service_curb_to_house"])
        self.assertEqual("Copper", card["service_main_to_curb"])
        self.assertEqual("1”", card["diameter_service"])
        self.assertEqual("Demo Contractor", card["contractor"])
        self.assertEqual("Morgan", card["inspected_by"])


if __name__ == "__main__":
    unittest.main()
