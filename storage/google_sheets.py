"""
Google Sheets storage layer.

Required .env keys:
    GOOGLE_SERVICE_ACCOUNT_JSON  — absolute path to service account JSON file
    GOOGLE_SPREADSHEET_ID        — the spreadsheet ID from the Sheets URL
    GOOGLE_WORKSHEET_NAME        — worksheet tab name (default: "Jobs")
"""

import logging
import os
import time
from typing import TYPE_CHECKING, Optional

import gspread
import requests.exceptions
from google.oauth2.service_account import Credentials

from extractors.base import JobPost

if TYPE_CHECKING:
    from matching.local_matcher import MatchResult

logger = logging.getLogger(__name__)

HEADERS = [
    "Job Title",          # A
    "Company/Org",        # B
    "Source",             # C
    "Match Score",        # D
    "Best Profile Match", # E
    "Match Rationale",    # F
    "Link",               # G  — unique ID for dedup
    "Date Posted",        # H
    "Status",             # I
]

_LINK_COL = 7
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_MAX_RETRIES = 3
_RETRY_BACKOFF = (2, 4, 8)  # seconds between retry attempts


class GoogleSheetsClient:
    """
    Thin wrapper around gspread that handles auth, schema init,
    deduplication, and row appending for the jobs pipeline.
    All network calls are wrapped with retry logic for transient
    connection errors (RemoteDisconnected, ConnectionError, etc.).
    """

    def __init__(
        self,
        service_account_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
        worksheet_name: Optional[str] = None,
    ) -> None:
        sa_path = service_account_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        ss_id = spreadsheet_id or os.getenv("GOOGLE_SPREADSHEET_ID", "")
        ws_name = worksheet_name or os.getenv("GOOGLE_WORKSHEET_NAME", "Jobs")

        if not sa_path:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not set in .env")
        if not ss_id:
            raise ValueError("GOOGLE_SPREADSHEET_ID is not set in .env")

        creds = Credentials.from_service_account_file(sa_path, scopes=_SCOPES)
        client = gspread.authorize(creds)

        self._spreadsheet = client.open_by_key(ss_id)
        self._ws = self._get_or_create_worksheet(ws_name)
        self._ensure_headers()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_duplicate(self, job_link: str) -> bool:
        """Return True if job_link already exists in column G (Link)."""
        existing = self._request_with_retry(
            lambda: self._ws.col_values(_LINK_COL),
            label="col_values",
        )
        return job_link in (existing or [])[1:]

    def append_job(self, job: JobPost, match: "Optional[MatchResult]" = None) -> None:
        """
        Append one job as a new row.
        Pass a MatchResult to populate columns D–F; omit it to leave them blank.
        Status defaults to 'Not Applied'.
        """
        row = [
            job.title,
            job.company,
            job.source,
            match.match_score if match else "",
            match.best_profile if match else "",
            match.rationale if match else "",
            job.link,
            job.date_posted,
            "Not Applied",
        ]
        self._request_with_retry(
            lambda: self._ws.append_row(row, value_input_option="USER_ENTERED"),
            label=f"append_row({job.title!r})",
        )
        logger.info("Appended: [%s] %s — %s", job.source, job.title, job.company)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _request_with_retry(self, fn, label: str):
        """
        Call fn() with up to _MAX_RETRIES retries on transient network errors.
        Raises on the final attempt if the error persists.
        """
        for attempt, delay in enumerate(_RETRY_BACKOFF, start=1):
            try:
                return fn()
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                gspread.exceptions.APIError,
            ) as exc:
                logger.warning(
                    "Sheets network error on '%s' (attempt %d/%d): %s — retrying in %ds.",
                    label, attempt, _MAX_RETRIES, exc, delay,
                )
                time.sleep(delay)

        # Final attempt — let it propagate if it still fails
        return fn()

    def _get_or_create_worksheet(self, name: str) -> gspread.Worksheet:
        try:
            return self._spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(title=name, rows=1000, cols=len(HEADERS))
            logger.info("Created worksheet '%s'", name)
            return ws

    def _ensure_headers(self) -> None:
        first_row = self._ws.row_values(1)
        if first_row == HEADERS:
            return
        if first_row:
            logger.warning(
                "Row 1 content %s — overwriting with correct headers.", first_row,
            )
        self._ws.update("A1", [HEADERS])
        logger.info("Sheet headers initialised.")
