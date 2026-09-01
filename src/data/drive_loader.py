from __future__ import annotations

import io
from collections.abc import Mapping

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class SourceConfigurationError(RuntimeError):
    """Raised when an expected secret or source cannot be used safely."""


def drive_service(account_info: Mapping[str, object]):
    credentials = service_account.Credentials.from_service_account_info(
        dict(account_info), scopes=[DRIVE_READONLY_SCOPE]
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def export_google_sheet(service, spreadsheet_id: str) -> bytes:
    """Export a native Google Sheet through Drive API; never uses public URLs."""
    if not spreadsheet_id:
        raise SourceConfigurationError("Falta el identificador de una fuente de datos.")
    request = service.files().export_media(
        fileId=spreadsheet_id,
        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request)
    finished = False
    while not finished:
        _, finished = downloader.next_chunk()
    return output.getvalue()


def read_google_sheet(service, spreadsheet_id: str, sheet_name: str) -> pd.DataFrame:
    payload = export_google_sheet(service, spreadsheet_id)
    return pd.read_excel(io.BytesIO(payload), sheet_name=sheet_name, dtype=object)
