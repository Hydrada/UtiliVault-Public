import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import google_drive_auth


class GoogleDriveAuthTests(unittest.TestCase):
    def test_refresh_replaces_token_json_atomically_and_preserves_refresh_grant(self):
        with tempfile.TemporaryDirectory() as root:
            token_file = Path(root) / "oauth_token.json"
            token_file.write_text(
                json.dumps(
                    {
                        "token": "TEST_EXPIRED_ACCESS_TOKEN",
                        "refresh_token": "TEST_REFRESH_TOKEN",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                        "scopes": ["scope"],
                        "expiry": "2020-01-01T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            credentials = Mock()
            credentials.expired = True
            credentials.refresh_token = "TEST_REFRESH_TOKEN"

            def refresh(_request):
                credentials.token = "TEST_FRESH_ACCESS_TOKEN"
                credentials.expiry = datetime(2030, 1, 1, tzinfo=timezone.utc)

            credentials.refresh.side_effect = refresh
            missing_sa = Path(root) / "missing-service-account.json"
            with (
                patch.object(google_drive_auth, "GOOGLE_SERVICE_ACCOUNT_FILE", missing_sa),
                patch.object(google_drive_auth, "GOOGLE_OAUTH_TOKEN_FILE", token_file),
                patch.object(google_drive_auth, "Credentials", return_value=credentials),
                patch.object(google_drive_auth, "Request", return_value=Mock()),
            ):
                result = google_drive_auth.load_google_credentials()

            saved = json.loads(token_file.read_text(encoding="utf-8"))
            self.assertIs(credentials, result)
            self.assertEqual("TEST_FRESH_ACCESS_TOKEN", saved["token"])
            self.assertEqual("TEST_REFRESH_TOKEN", saved["refresh_token"])
            self.assertEqual([], list(Path(root).glob(".oauth_token.json.*")))


    def test_service_account_is_preferred_when_key_exists(self):
        with tempfile.TemporaryDirectory() as root:
            sa_file = Path(root) / "service_account.json"
            sa_file.write_text("{}", encoding="utf-8")
            expected = Mock()
            with (
                patch.object(google_drive_auth, "GOOGLE_SERVICE_ACCOUNT_FILE", sa_file),
                patch.object(
                    google_drive_auth.ServiceAccountCredentials,
                    "from_service_account_file",
                    return_value=expected,
                ) as factory,
            ):
                result = google_drive_auth.load_google_credentials()
            self.assertIs(expected, result)
            factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
