"""Shared Google user-OAuth loader used by Drive-facing processes."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from host_config import GOOGLE_OAUTH_TOKEN_FILE, GOOGLE_SERVICE_ACCOUNT_FILE
from cloud_runtime import atomic_write_json, single_instance


DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]


def load_google_credentials():
    """Prefer a service-account key when present; otherwise the user OAuth grant."""
    if GOOGLE_SERVICE_ACCOUNT_FILE.is_file():
        return ServiceAccountCredentials.from_service_account_file(
            str(GOOGLE_SERVICE_ACCOUNT_FILE),
            scopes=DRIVE_SCOPES,
        )

    token_lock = GOOGLE_OAUTH_TOKEN_FILE.with_suffix(
        GOOGLE_OAUTH_TOKEN_FILE.suffix + ".lock"
    )
    with single_instance(token_lock):
        with GOOGLE_OAUTH_TOKEN_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)

        expiry = data.get("expiry")
        if isinstance(expiry, str):
            try:
                expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            except ValueError:
                expiry = None
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=data.get("scopes"),
            expiry=expiry,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Preserve the long-lived grant while atomically caching the short-
            # lived token. A crash can never leave truncated credential JSON.
            data["token"] = creds.token
            if creds.expiry:
                expiry = creds.expiry
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                data["expiry"] = expiry.isoformat().replace("+00:00", "Z")
            atomic_write_json(GOOGLE_OAUTH_TOKEN_FILE, data)
        return creds


def get_google_drive():
    """Build a Google Drive v3 client for the configured account."""
    return build("drive", "v3", credentials=load_google_credentials())


def get_google_docs():
    """Build a Google Docs v1 client for the configured account."""
    return build("docs", "v1", credentials=load_google_credentials())
