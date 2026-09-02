from __future__ import annotations

import io
from collections.abc import Mapping

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class SourceConfigurationError(RuntimeError):
    """Raised when an expected secret or source cannot be used safely."""


def drive_service(account_info: Mapping[str, object]):
    credentials = service_account.Credentials.from_service_account_info(dict(account_info), scopes=[DRIVE_READONLY_SCOPE])
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def sheets_service(account_info: Mapping[str, object]):
    credentials = service_account.Credentials.from_service_account_info(
        dict(account_info), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


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


def read_google_sheet_values_paged(sheets, spreadsheet_id: str, sheet_name: str, chunk_rows: int = 100_000) -> pd.DataFrame:
    """Read a Sheet in bounded ranges when Drive cannot export large workbooks."""
    rows: list[list[object]] = []
    start = 1
    while True:
        end = start + chunk_rows - 1
        response = sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A{start}:AH{end}",
            majorDimension="ROWS",
        ).execute()
        batch = response.get("values", [])
        if start == 1:
            if not batch:
                return pd.DataFrame()
            headers, batch = batch[0], batch[1:]
        rows.extend(batch)
        if len(batch) < chunk_rows - (1 if start == 1 else 0):
            break
        start = end + 1
    return pd.DataFrame(rows, columns=headers)


def read_google_sheet(service, spreadsheet_id: str, sheet_name: str, sheets=None) -> pd.DataFrame:
    try:
        payload = export_google_sheet(service, spreadsheet_id)
        return pd.read_excel(io.BytesIO(payload), sheet_name=sheet_name, dtype=object)
    except HttpError as error:
        if "exportSizeLimitExceeded" not in str(error):
            raise
        if sheets is None:
            raise SourceConfigurationError("La fuente supera el límite de exportación y falta el cliente Sheets.") from error
        return read_google_sheet_values_paged(sheets, spreadsheet_id, sheet_name)
