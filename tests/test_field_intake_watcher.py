import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import field_intake_watcher as watcher


def fake_drive_with_files(files):
    drive = Mock()
    drive.files.return_value.list.return_value.execute.return_value = {"files": files}
    return drive


class DriveHelperTests(unittest.TestCase):
    def test_folder_id_returns_first_match(self):
        drive = fake_drive_with_files([{"id": "folder-1"}, {"id": "folder-2"}])

        result = watcher.folder_id(drive, "UtiliVault", parent="root")

        self.assertEqual("folder-1", result)
        query = drive.files.return_value.list.call_args.kwargs["q"]
        self.assertIn("name='UtiliVault'", query)
        self.assertIn("'root' in parents", query)

    def test_folder_id_returns_none_when_missing(self):
        drive = fake_drive_with_files([])

        self.assertIsNone(watcher.folder_id(drive, "Missing"))

    def test_upload_tif_updates_existing_file_before_trashing_extra_duplicate(self):
        drive = Mock()
        drive.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "primary", "createdTime": "2026-01-01T00:00:00Z"},
                {"id": "duplicate", "createdTime": "2026-01-02T00:00:00Z"},
            ]
        }
        drive.files.return_value.update.return_value.execute.side_effect = [
            {"id": "primary", "name": "card.tif"},
            {"id": "duplicate"},
        ]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "card.tif"
            path.write_bytes(b"tiff")
            with patch("googleapiclient.http.MediaFileUpload", return_value=Mock()):
                result = watcher.upload_tif(drive, path, "output")

        self.assertEqual("primary", result["id"])
        calls = drive.files.return_value.update.call_args_list
        self.assertEqual("primary", calls[0].kwargs["fileId"])
        self.assertEqual("duplicate", calls[1].kwargs["fileId"])
        self.assertEqual({"trashed": True}, calls[1].kwargs["body"])
        drive.files.return_value.delete.assert_not_called()


class IntakeProcessingTests(unittest.TestCase):
    def test_no_supported_images_is_a_noop(self):
        drive = fake_drive_with_files([{"id": "1", "name": "notes.txt", "mimeType": "text/plain"}])

        result = watcher.process_intake_once(drive, "intake", "originals")

        self.assertEqual(0, result)

    def test_supported_image_is_processed_and_archived(self):
        files = [
            {"id": "image-1", "name": "REG 1234.JPG", "mimeType": "image/jpeg"},
            {"id": "text-1", "name": "ignore.txt", "mimeType": "text/plain"},
        ]
        drive = fake_drive_with_files(files)

        with tempfile.TemporaryDirectory() as root:
            work_dir = Path(root)

            def fake_download(_drive, _file_id, destination):
                destination.write_bytes(b"image")

            with (
                patch.object(watcher, "WORK_DIR", work_dir),
                patch.object(watcher, "download", side_effect=fake_download) as download,
                patch.object(watcher, "process_card", return_value={}) as process_card,
                patch.object(watcher, "move_file") as move_file,
            ):
                result = watcher.process_intake_once(drive, "intake", "originals")

        self.assertEqual(1, result)
        download.assert_called_once()
        card = process_card.call_args.args[0]
        self.assertEqual("REG 1234", card["_reg_fallback"])
        move_file.assert_called_once_with(drive, "image-1", "originals", "intake")

    def test_project_intake_enriches_from_reference_after_one_photo_read(self):
        drive = fake_drive_with_files(
            [{"id": "image-1", "name": "north.jpg", "mimeType": "image/jpeg"}]
        )
        reference_index = Mock()

        def enrich(card):
            card["reg_no"] = "1619"
            card["service_main_to_curb"] = "1\N{RIGHT DOUBLE QUOTATION MARK} Copper"
            return card

        reference_index.enrich.side_effect = enrich
        reference_index.by_address = {"1 EXAMPLE ST": {}}

        with tempfile.TemporaryDirectory() as root:
            work_dir = Path(root)

            def fake_download(_drive, _file_id, destination):
                destination.write_bytes(b"image")

            with (
                patch.object(watcher, "WORK_DIR", work_dir),
                patch.object(watcher, "download", side_effect=fake_download),
                patch.object(
                    watcher,
                    "apply_photo",
                    side_effect=lambda card, _path: {**card, "address": "1 North St"},
                ) as apply_photo,
                patch.object(watcher, "load_reference_index", return_value=reference_index),
                patch.object(watcher, "process_card", return_value={}) as process_card,
                patch.object(watcher, "move_file"),
            ):
                result = watcher.process_intake_once(
                    drive,
                    "intake",
                    "originals",
                    reference_folder_id="demo-folder",
                )

        self.assertEqual(1, result)
        apply_photo.assert_called_once()
        reference_index.enrich.assert_called_once()
        card = process_card.call_args.args[0]
        self.assertEqual("1619", card["reg_no"])
        self.assertEqual("1\N{RIGHT DOUBLE QUOTATION MARK} Copper", card["service_main_to_curb"])
        self.assertIsNone(process_card.call_args.kwargs["photo_path"])

    def test_project_photos_rebuild_digital_preview_for_existing_card(self):
        drive = fake_drive_with_files(
            [{"id": "image-1", "name": "2-north.jpg", "mimeType": "image/jpeg"}]
        )
        reference_index = Mock()
        reference_index.by_address = {"2 EXAMPLE ST": {}}

        def enrich(card):
            card["_reference_document_id"] = "north-doc"
            return card

        reference_index.enrich.side_effect = enrich

        with tempfile.TemporaryDirectory() as root:
            work_dir = Path(root)
            front = Path(root) / "2 North St 2283_front.png"
            back = Path(root) / "2 North St 2283_back.png"
            front.write_bytes(b"front")
            back.write_bytes(b"back")

            def fake_download(_drive, _file_id, destination):
                destination.write_bytes(b"image")

            with (
                patch.object(watcher, "WORK_DIR", work_dir),
                patch.object(watcher, "download", side_effect=fake_download),
                patch.object(watcher, "load_reference_index", return_value=reference_index),
                patch(
                    "match_display_photos.read_address",
                    return_value="2 North St",
                ),
                patch(
                    "match_display_photos.index_existing_cards",
                    return_value={
                        "2 north st": {
                            "base": "2 North St 2283",
                            "front_png": front,
                            "back_png": back,
                            "has_reg": True,
                        }
                    },
                ),
                patch.object(watcher, "process_card") as process_card,
                patch("PIL.Image.open", return_value=Mock()),
                patch(
                    "draw_tiecard_back.render_photo_page",
                    return_value=Mock(),
                ),
                patch(
                    "draw_tiecard_back.save_digital_outputs",
                    return_value={"digital_tif": Path(root) / "2 North St 2283_DIGITAL.tif"},
                ),
                patch.object(watcher, "upload_tif") as upload_tif,
                patch.object(watcher, "sync_document_completion", return_value=[]) as sync_doc,
                patch.object(watcher, "move_file") as move_file,
            ):
                result = watcher.process_project_photos_once(
                    drive,
                    "intake",
                    "originals",
                    digital_id="folder-14",
                    reference_folder_id="demo-folder",
                    docs=Mock(),
                )

        self.assertEqual(1, result)
        process_card.assert_not_called()
        upload_tif.assert_called_once()
        sync_doc.assert_called_once()
        self.assertEqual({"2 North St": "Yes"}, sync_doc.call_args.args[2])
        move_file.assert_called_once_with(drive, "image-1", "originals", "intake")

    def test_project_photos_draw_from_street_doc_when_no_card_exists(self):
        drive = fake_drive_with_files(
            [{"id": "image-1", "name": "5-north.jpg", "mimeType": "image/jpeg"}]
        )
        reference_index = Mock()
        reference_index.by_address = {"5 EXAMPLE ST": {}}
        reference_index.enrich.side_effect = lambda card: card

        with tempfile.TemporaryDirectory() as root:
            work_dir = Path(root)

            def fake_download(_drive, _file_id, destination):
                destination.write_bytes(b"image")

            with (
                patch.object(watcher, "WORK_DIR", work_dir),
                patch.object(watcher, "download", side_effect=fake_download),
                patch.object(watcher, "load_reference_index", return_value=reference_index),
                patch("match_display_photos.read_address", return_value="5 North St"),
                patch("match_display_photos.index_existing_cards", return_value={}),
                patch.object(
                    watcher,
                    "apply_photo",
                    side_effect=lambda card, _path: {**card, "left": "32-9", "_house": {"stories": 2}},
                ) as apply_photo,
                patch.object(
                    watcher,
                    "process_card",
                    return_value={"digital_tif": Path(root) / "card.tif"},
                ) as process_card,
                patch.object(watcher, "move_file"),
            ):
                result = watcher.process_project_photos_once(
                    drive,
                    "intake",
                    "originals",
                    reference_folder_id="demo-folder",
                )

        self.assertEqual(1, result)
        apply_photo.assert_called_once()
        self.assertEqual("5 North St", process_card.call_args.args[0]["address"])
        self.assertEqual("32-9", process_card.call_args.args[0]["left"])
        self.assertIsNone(process_card.call_args.kwargs["photo_path"])
        self.assertIsNotNone(process_card.call_args.kwargs["display_photo_path"])
        self.assertEqual(1, reference_index.enrich.call_count)

    def test_failed_image_is_not_archived(self):
        drive = fake_drive_with_files(
            [{"id": "image-1", "name": "broken.png", "mimeType": "image/png"}]
        )

        with tempfile.TemporaryDirectory() as root:
            with (
                patch.object(watcher, "WORK_DIR", Path(root)),
                patch.object(watcher, "download", side_effect=OSError("download failed")),
                patch.object(watcher, "move_file") as move_file,
            ):
                result = watcher.process_intake_once(drive, "intake", "originals")

        self.assertEqual(1, result)
        move_file.assert_not_called()

    def test_missing_required_digital_output_does_not_update_document_or_archive(self):
        drive = fake_drive_with_files(
            [{"id": "image-1", "name": "card.jpg", "mimeType": "image/jpeg"}]
        )
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            printable = root_path / "card.tif"
            printable.write_bytes(b"tiff")

            def fake_download(_drive, _file_id, destination):
                destination.write_bytes(b"image")

            with (
                patch.object(watcher, "WORK_DIR", root_path),
                patch.object(watcher, "download", side_effect=fake_download),
                patch.object(
                    watcher,
                    "process_card",
                    return_value={"tif": printable},
                ),
                patch.object(watcher, "upload_tif") as upload_tif,
                patch.object(watcher, "sync_document_completion") as sync_doc,
                patch.object(watcher, "move_file") as move_file,
            ):
                result = watcher.process_intake_once(
                    drive,
                    "intake",
                    "originals",
                    digital_id="digital",
                    docs=Mock(),
                    output_id="printable",
                )

        self.assertEqual(1, result)
        upload_tif.assert_called_once_with(drive, printable, "printable")
        sync_doc.assert_not_called()
        move_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
