"""Report whether a machine is configured to host UtiliVault safely.

This command never prints secret values and performs no network calls.

Usage:
    py host_readiness.py
    py host_readiness.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from config import DEMO_DIR, WORK_ROOT
from host_config import (
    GOOGLE_OAUTH_CLIENT_FILE,
    GOOGLE_OAUTH_TOKEN_FILE,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    PROJECT_ROOT,
    secrets_dir,
)


@dataclass
class Check:
    name: str
    status: str
    detail: str


def _configured(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _json_has(path: Path, fields: set[str]) -> tuple[bool, str]:
    if not path.is_file():
        return False, "file not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "file is not readable JSON"
    missing = sorted(field for field in fields if not data.get(field))
    return (not missing, "valid" if not missing else f"missing: {', '.join(missing)}")


def _oauth_client_valid(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "file not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "file is not readable JSON"
    client = data.get("installed") or data.get("web") or {}
    missing = [field for field in ("client_id", "client_secret") if not client.get(field)]
    return (not missing, "valid" if not missing else f"missing: {', '.join(missing)}")


def _oauth_scope_valid(path: Path, required_scope: str) -> tuple[bool, str]:
    """Confirm the saved Google grant includes a required API scope."""
    if not path.is_file():
        return False, "token file not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "token file is not readable JSON"
    scopes = set(data.get("scopes") or [])
    return (
        required_scope in scopes,
        "configured" if required_scope in scopes else "rerun oauth_setup.py to grant Google Docs access",
    )


def _configured_file(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    path = Path(os.path.expandvars(value)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def collect_checks() -> list[Check]:
    checks: list[Check] = []
    checks.append(Check("Python", "PASS", platform.python_version()))

    if _configured("UTILIVAULT_HOME"):
        checks.append(Check("Data home", "PASS", str(DEMO_DIR.parent)))
    else:
        checks.append(Check(
            "Data home", "WARN",
            "UTILIVAULT_HOME is not set; this host uses the legacy PC-specific paths",
        ))

    secret_root = secrets_dir()
    if secret_root.resolve() == PROJECT_ROOT.resolve():
        checks.append(Check(
            "Secrets directory", "WARN",
            "UTILIVAULT_SECRETS_DIR is not set; credentials are beside the source code",
        ))
    else:
        checks.append(Check("Secrets directory", "PASS", str(secret_root)))

    client_ok, client_detail = _oauth_client_valid(GOOGLE_OAUTH_CLIENT_FILE)
    checks.append(Check(
        "Google OAuth client", "PASS" if client_ok else "FAIL",
        str(GOOGLE_OAUTH_CLIENT_FILE) if client_ok else client_detail,
    ))

    token_ok, token_detail = _json_has(
        GOOGLE_OAUTH_TOKEN_FILE,
        {"refresh_token", "token_uri", "client_id", "client_secret"},
    )
    checks.append(Check(
        "Google Drive grant", "PASS" if token_ok else "FAIL",
        str(GOOGLE_OAUTH_TOKEN_FILE) if token_ok else token_detail,
    ))

    docs_ok, docs_detail = _oauth_scope_valid(
        GOOGLE_OAUTH_TOKEN_FILE,
        "https://www.googleapis.com/auth/documents",
    )
    checks.append(Check(
        "Google Docs automation grant", "PASS" if docs_ok else "FAIL", docs_detail,
    ))

    for env_name, label in (
        ("DEMO_PROJECTS_FOLDER_ID", "Street-document project folder"),
        ("PROJECT_PICTURE_INTAKE_FOLDER_ID", "Project picture-intake folder"),
    ):
        checks.append(Check(
            label,
            "PASS" if _configured(env_name) else "WARN",
            "configured" if _configured(env_name) else "using the built-in Demo Contractor deployment ID; copy .env.example values to the new host",
        ))

    for name, label, required in (
        ("ANTHROPIC_API_KEY", "Claude API billing key", True),
        ("UTILIVAULT_API_KEY", "Mobile API shared key", True),
        ("EXPO_TOKEN", "Expo build account", False),
    ):
        present = _configured(name)
        status = "PASS" if present else ("FAIL" if required else "WARN")
        detail = "configured" if present else "not configured"
        checks.append(Check(label, status, detail))

    sheets_ok, sheets_detail = _json_has(
        GOOGLE_SERVICE_ACCOUNT_FILE, {"client_email", "private_key", "project_id"}
    )
    checks.append(Check(
        "Sheets service account", "PASS" if sheets_ok else "WARN",
        str(GOOGLE_SERVICE_ACCOUNT_FILE) if sheets_ok else sheets_detail,
    ))

    vision_file = _configured_file("GOOGLE_APPLICATION_CREDENTIALS")
    vision_ok, vision_detail = (
        _json_has(vision_file, {"client_email", "private_key", "project_id"})
        if vision_file else (False, "not configured")
    )
    checks.append(Check(
        "Vision service account", "PASS" if vision_ok else "WARN",
        str(vision_file) if vision_ok else vision_detail,
    ))

    defaults_file = PROJECT_ROOT / "mobile" / "src" / "defaults.js"
    baked_key = False
    if defaults_file.is_file():
        text = defaults_file.read_text(encoding="utf-8")
        match = re.search(r'DEFAULT_API_KEY\s*=\s*["\']([^"\']*)', text)
        baked_key = bool(match and match.group(1).strip())
    checks.append(Check(
        "Mobile credential packaging",
        "WARN" if baked_key else "PASS",
        "an API key is embedded in the mobile build; rebuild and rotate it during transfer"
        if baked_key else "no default API key detected",
    ))

    checks.append(Check("Card data path", "INFO", str(DEMO_DIR)))
    checks.append(Check("Work path", "INFO", str(WORK_ROOT)))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Check UtiliVault new-host readiness")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()
    checks = collect_checks()

    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        print("UtiliVault host readiness\n")
        for check in checks:
            print(f"[{check.status:4}] {check.name}: {check.detail}")
        failures = sum(check.status == "FAIL" for check in checks)
        warnings = sum(check.status == "WARN" for check in checks)
        print(f"\nResult: {failures} failure(s), {warnings} warning(s)")
        if failures:
            print("This host is not ready to take over yet.")
        elif warnings:
            print("Core credentials are present; review warnings before cutover.")
        else:
            print("This host is ready for a controlled cutover.")
    return 1 if any(check.status == "FAIL" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
