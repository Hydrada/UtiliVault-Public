import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from werkzeug.exceptions import BadRequest

import api_server as api


@contextmanager
def isolated_card_store():
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        manual = root_path / "manual"
        digital = root_path / "digital"
        clean = root_path / "clean"
        for directory in (manual, digital, clean):
            directory.mkdir()
        with (
            patch.object(api, "MANUAL_DIR", manual),
            patch.object(api, "DIGITAL_DIR", digital),
            patch.object(api, "CLEAN_DIR", clean),
        ):
            yield manual, digital, clean


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        api.app.config.update(TESTING=True)
        self.client = api.app.test_client()

    def test_api_key_is_required_when_configured(self):
        with patch.object(api, "API_KEY", "secret"):
            missing = self.client.get("/api/health")
            wrong = self.client.get("/api/health", headers={"X-Api-Key": "wrong"})
            valid = self.client.get("/api/health", headers={"X-Api-Key": "secret"})

        self.assertEqual(401, missing.status_code)
        self.assertEqual(401, wrong.status_code)
        self.assertEqual(200, valid.status_code)

    def test_cors_preflight_bypasses_api_key(self):
        with patch.object(api, "API_KEY", "secret"):
            response = self.client.options("/api/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual("*", response.headers["Access-Control-Allow-Origin"])
        self.assertIn("X-Api-Key", response.headers["Access-Control-Allow-Headers"])

    def test_unsafe_card_ids_are_rejected(self):
        with api.app.test_request_context():
            for unsafe in ("", "../secret", "bad/name", "bad*name"):
                with self.subTest(unsafe=unsafe), self.assertRaises(BadRequest):
                    api._check_base(unsafe)


class CardStoreTests(unittest.TestCase):
    def setUp(self):
        api.app.config.update(TESTING=True)
        self.client = api.app.test_client()

    def test_card_summary_uses_metadata_and_page_state(self):
        with isolated_card_store() as (manual, digital, _clean):
            base = "10 Main 1234"
            (manual / f"{base}_card.json").write_text(
                json.dumps({"address": "10 Example Way", "reg_no": "1234", "_source": "mobile"}),
                encoding="utf-8",
            )
            (manual / f"{base}_front.png").write_bytes(b"front")
            (manual / f"{base}_back.png").write_bytes(b"back")
            (digital / f"{base}_photo.png").write_bytes(b"photo")

            summary = api._card_summary(base)

        self.assertEqual("10 Example Way", summary["address"])
        self.assertEqual("1234", summary["reg_no"])
        self.assertEqual(3, summary["pages"])
        self.assertTrue(summary["has_photo_page"])
        self.assertEqual("mobile", summary["source"])

    def test_create_requires_address_or_registration_number(self):
        with isolated_card_store(), patch.object(api, "API_KEY", ""):
            response = self.client.post("/api/cards", json={"comments": "no identity"})

        self.assertEqual(400, response.status_code)
        self.assertIn("address or a reg number", response.get_json()["error"])

    def test_create_rejects_unsupported_photo_before_rendering(self):
        with (
            isolated_card_store(),
            patch.object(api, "API_KEY", ""),
            patch.object(api, "process_card") as process_card,
        ):
            response = self.client.post(
                "/api/cards",
                data={"address": "10 Main", "photo": (io.BytesIO(b"data"), "photo.exe")},
                content_type="multipart/form-data",
            )

        self.assertEqual(400, response.status_code)
        self.assertIn("unsupported photo type", response.get_json()["error"])
        process_card.assert_not_called()

    def test_successful_json_create_persists_metadata_and_returns_pages(self):
        with isolated_card_store() as (manual, _digital, _clean):
            base = "10 Main 1234"

            def render(card, **_kwargs):
                front = manual / f"{base}_front.png"
                back = manual / f"{base}_back.png"
                tif = manual / f"{base}.tif"
                front.write_bytes(b"front")
                back.write_bytes(b"back")
                tif.write_bytes(b"tif")
                return {"front_png": front, "back_png": back, "tif": tif}

            with (
                patch.object(api, "API_KEY", ""),
                patch.object(api, "card_filename_base", return_value=base),
                patch.object(api, "process_card", side_effect=render) as process_card,
                patch.object(api, "_drive_upload", return_value="drive-off"),
            ):
                response = self.client.post(
                    "/api/cards",
                    json={"address": "10 Main", "reg_no": "1234", "comments": "  verified  "},
                )

            metadata = json.loads((manual / f"{base}_card.json").read_text(encoding="utf-8"))

        self.assertEqual(201, response.status_code)
        self.assertEqual(base, response.get_json()["base"])
        self.assertEqual(2, response.get_json()["pages"])
        self.assertEqual("verified", metadata["comments"])
        self.assertEqual("Demo Contractor", metadata["contractor"])
        self.assertEqual("Morgan", metadata["inspected_by"])
        self.assertEqual("mobile", metadata["_source"])
        process_card.assert_called_once()

    def test_explicit_contractor_and_inspector_override_defaults(self):
        with isolated_card_store() as (manual, _digital, _clean):
            base = "10 Main 1234"

            def render(_card, **_kwargs):
                front = manual / f"{base}_front.png"
                back = manual / f"{base}_back.png"
                tif = manual / f"{base}.tif"
                front.write_bytes(b"front")
                back.write_bytes(b"back")
                tif.write_bytes(b"tif")
                return {"front_png": front, "back_png": back, "tif": tif}

            with (
                patch.object(api, "API_KEY", ""),
                patch.object(api, "card_filename_base", return_value=base),
                patch.object(api, "process_card", side_effect=render),
                patch.object(api, "_drive_upload", return_value="drive-off"),
            ):
                response = self.client.post(
                    "/api/cards",
                    json={
                        "address": "10 Main",
                        "reg_no": "1234",
                        "contractor": "Other Contractor",
                        "inspected_by": "Other Inspector",
                    },
                )

            metadata = json.loads((manual / f"{base}_card.json").read_text(encoding="utf-8"))

        self.assertEqual(201, response.status_code)
        self.assertEqual("Other Contractor", metadata["contractor"])
        self.assertEqual("Other Inspector", metadata["inspected_by"])


if __name__ == "__main__":
    unittest.main()
