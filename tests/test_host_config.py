import os
import unittest
from pathlib import Path
from unittest.mock import patch

import host_config


class HostConfigTests(unittest.TestCase):
    def test_secret_path_defaults_to_configured_secret_directory(self):
        with patch.dict(
            os.environ,
            {"UTILIVAULT_SECRETS_DIR": "private", "GOOGLE_OAUTH_TOKEN_JSON": ""},
            clear=False,
        ):
            result = host_config.secret_path(
                "GOOGLE_OAUTH_TOKEN_JSON", "oauth_token.json"
            )
        self.assertEqual(
            host_config.PROJECT_ROOT / "private" / "oauth_token.json", result
        )

    def test_individual_secret_path_overrides_directory(self):
        with patch.dict(
            os.environ,
            {
                "UTILIVAULT_SECRETS_DIR": "private",
                "GOOGLE_OAUTH_TOKEN_JSON": "alternate/token.json",
            },
            clear=False,
        ):
            result = host_config.secret_path(
                "GOOGLE_OAUTH_TOKEN_JSON", "oauth_token.json"
            )
        self.assertEqual(
            host_config.PROJECT_ROOT / "alternate" / "token.json", result
        )

    def test_absolute_secret_path_is_preserved(self):
        absolute = Path(host_config.PROJECT_ROOT.anchor) / "UtiliVault" / "token.json"
        with patch.dict(
            os.environ, {"GOOGLE_OAUTH_TOKEN_JSON": str(absolute)}, clear=False
        ):
            result = host_config.secret_path(
                "GOOGLE_OAUTH_TOKEN_JSON", "oauth_token.json"
            )
        self.assertEqual(absolute, result)


if __name__ == "__main__":
    unittest.main()
