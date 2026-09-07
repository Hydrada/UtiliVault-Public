"""Host and credential locations for portable UtiliVault installations.

Existing installations keep working with secrets beside the source code. New
hosts should set ``UTILIVAULT_HOME`` and ``UTILIVAULT_SECRETS_DIR`` so data and
credentials live outside the application directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def _expand_path(value: str, *, base: Path = PROJECT_ROOT) -> Path:
    """Expand a configured path, resolving relative paths from the project."""
    expanded = os.path.expandvars(value.strip())
    path = Path(expanded).expanduser()
    return path if path.is_absolute() else base / path


def secrets_dir() -> Path:
    """Directory containing private host credentials.

    The project directory remains the compatibility default. A new host should
    explicitly set UTILIVAULT_SECRETS_DIR to a protected, backed-up directory.
    """
    configured = os.getenv("UTILIVAULT_SECRETS_DIR", "").strip()
    return _expand_path(configured) if configured else PROJECT_ROOT


def secret_path(env_name: str, default_name: str) -> Path:
    """Resolve an individual secret path with a secrets-directory fallback."""
    configured = os.getenv(env_name, "").strip()
    if configured:
        return _expand_path(configured)
    return secrets_dir() / default_name


GOOGLE_OAUTH_CLIENT_FILE = secret_path(
    "GOOGLE_OAUTH_CLIENT_JSON", "oauth_client.json"
)
GOOGLE_OAUTH_TOKEN_FILE = secret_path(
    "GOOGLE_OAUTH_TOKEN_JSON", "oauth_token.json"
)
GOOGLE_OAUTH_STATE_FILE = secret_path(
    "GOOGLE_OAUTH_STATE_JSON", "oauth_state.json"
)
GOOGLE_SERVICE_ACCOUNT_FILE = secret_path(
    "GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json"
)


def ensure_secret_parent(path: Path) -> None:
    """Create the configured credential directory before writing a secret."""
    path.parent.mkdir(parents=True, exist_ok=True)
