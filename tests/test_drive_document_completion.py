import unittest

from drive_document_completion import measurements_complete, transform_document_text


DOC = """Test St – Tiecard Field Capture

Purpose
Test.

Street Main
Material / size:

Completed Addresses
None completed yet.

Test St Parcels Ready for New Measurements

1 Test St – Registry 100
Status: NOT COMPLETED
Service: PS  | HS
HS: 8’ 0” | MC: 10’ 0” | LS: 12’ 0” | RS: 14’ 0”
Reference points / notes:
Pictures:

2 Test St – Registry 200
Status: NOT COMPLETED
Service: PS  | HS
HS:  | MC: 10’ 0” | LS: 12’ 0” | RS: 14’ 0”
Reference points / notes:
Pictures:

Field Picture Checklist
1. Front.

Registry Source
Water Registry.
"""


class CompletionTests(unittest.TestCase):
    def test_requires_house_main_left_and_right_measurements(self):
        self.assertTrue(measurements_complete([
            "1 Test St – Registry 100",
            "HS: 1 | MC: 2 | LS: 3 | RS: 4",
        ]))
        self.assertFalse(measurements_complete([
            "2 Test St – Registry 200",
            "HS:  | MC: 2 | LS: 3 | RS: 4",
        ]))
        self.assertTrue(measurements_complete([
            "3 Test St – Registry 300",
            "HS: 1 | MC: 2 | LS: 3 | RS: 4",
            "Reference points / notes: revisit later",
            "Pictures: No",
        ]))

    def test_promotes_complete_address_and_defaults_picture_to_no(self):
        updated, promoted = transform_document_text(DOC, completion_date="07/22/2026")

        self.assertEqual(["1 Test St"], promoted)
        self.assertIn("1 Test St – Registry 100 – COMPLETE", updated)
        self.assertIn("Completion Date: 07/22/2026", updated)
        self.assertNotIn("1 Test St – Registry 100 – COMPLETE\nStatus: NOT COMPLETED", updated)
        self.assertLess(
            updated.index("1 Test St – Registry 100 – COMPLETE"),
            updated.index("Test St Parcels Ready for New Measurements"),
        )
        self.assertIn("2 Test St – Registry 200\nStatus: NOT COMPLETED", updated)
        self.assertIn("Status: NOT COMPLETED\nCompletion Date:\nContractor: Demo Contractor\nInspected By: Morgan\nService:", updated)
        self.assertIn("1 Test St – Registry 100 – COMPLETE\nCompletion Date: 07/22/2026\nContractor: Demo Contractor\nInspected By: Morgan", updated)
        self.assertEqual(2, updated.count("Pictures: No"))

    def test_picture_update_is_yes_but_does_not_gate_completion(self):
        updated, promoted = transform_document_text(
            DOC, {"2 Test Street": "Yes"}, completion_date="07/22/2026"
        )

        second = updated[updated.index("2 Test St – Registry 200"):]
        self.assertIn("Pictures: Yes", second)
        self.assertNotIn("2 Test St", promoted)

    def test_hc_and_loose_field_notes_count_as_house_measurements(self):
        self.assertTrue(measurements_complete([
            "5 North St – Registry 1493",
            "LS51’ 5\"  RS31’ 3\"  MC21’ 6\"  HC38’ 5”",
        ]))
        updated, promoted = transform_document_text(
            DOC.replace(
                "HS:  | MC: 10’ 0” | LS: 12’ 0” | RS: 14’ 0”",
                "LS 12’ 0” RS 14’ 0” MC 10’ 0” HC 8’ 0”",
            ),
            completion_date="07/22/2026",
        )
        self.assertEqual(["1 Test St", "2 Test St"], promoted)
        self.assertIn("Contractor: Demo Contractor", updated)
        self.assertIn("Inspected By: Morgan", updated)
        self.assertIn("HS: 8’ 0”", updated)


if __name__ == "__main__":
    unittest.main()
