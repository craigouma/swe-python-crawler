"""
ReliefWeb job extractor using the v2 public API.

API docs: https://apidoc.reliefweb.int
AppName registration: https://apidoc.reliefweb.int/parameters#appname

Set RELIEFWEB_APPNAME in .env (or the environment) to use your registered
appname.  The fallback value works for low-volume development use only.
"""

import logging
import os
from datetime import date
from typing import Any, Optional

import requests

from .base import JobExtractor, JobPost

logger = logging.getLogger(__name__)

_API_URL = "https://api.reliefweb.int/v2/jobs"

# ReliefWeb v2 theme IDs for ICT / Data work.
# Full reference: https://apidoc.reliefweb.int/fields#theme
_TARGET_THEME_IDS = [
    4590,  # Information and Communications Technology
]

_TITLE_KEYWORDS = [
    "data engineer",
    "data analyst",
    "software engineer",
    "systems administrator",
    "IT infrastructure",
    "ETL",
    "python developer",
    "database administrator",
    "devops",
    "cloud engineer",
    "GCP",
    "BigQuery",
]


class ReliefWebExtractor(JobExtractor):
    """
    Pulls jobs from the ReliefWeb v2 public API.
    Requires a registered appname (free) — set RELIEFWEB_APPNAME in .env.
    """

    def __init__(self, app_name: Optional[str] = None) -> None:
        self._app_name = app_name or os.getenv("RELIEFWEB_APPNAME", "")
        if not self._app_name:
            raise ValueError(
                "ReliefWeb requires a registered appname. "
                "Register free at https://apidoc.reliefweb.int/parameters#appname "
                "then set RELIEFWEB_APPNAME in your .env file."
            )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": f"{self._app_name}/1.0"})

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch(self, limit: int = 10, since: Optional[date] = None) -> list[JobPost]:
        raw = self._query_api(limit, since=since)
        posts = [self._parse(item) for item in raw]
        logger.info("ReliefWeb: fetched %d job(s)", len(posts))
        return posts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _query_api(self, limit: int, since: Optional[date] = None) -> list[dict[str, Any]]:
        # Per v2 docs: appname MUST be in the URL query string for both GET and POST.
        params = {
            "appname": self._app_name,
            "profile": "list",
            "preset": "latest",
            "slim": "1",
        }

        relevance_filter = {
            "operator": "OR",
            "conditions": [
                {
                    "field": "theme.id",
                    "value": _TARGET_THEME_IDS,
                    "operator": "OR",
                },
                {
                    "operator": "OR",
                    "conditions": [
                        {"field": "title", "value": kw}
                        for kw in _TITLE_KEYWORDS
                    ],
                },
            ],
        }

        if since is not None:
            api_filter = {
                "operator": "AND",
                "conditions": [
                    relevance_filter,
                    {
                        "field": "date.created",
                        "value": {"from": since.strftime("%Y-%m-%dT00:00:00+00:00")},
                    },
                ],
            }
        else:
            api_filter = relevance_filter

        payload = {
            "offset": 0,
            "limit": limit,
            "preset": "latest",
            "profile": "list",
            "sort": ["date:desc"],
            "fields": {
                "include": [
                    "title",
                    "body",
                    "date.created",
                    "source.name",
                    "url",
                    "theme.id",
                    "theme.name",
                    "country.name",
                    "city.name",
                ]
            },
            "filter": api_filter,
        }

        try:
            resp = self._session.post(_API_URL, params=params, json=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("ReliefWeb API request failed: %s", exc)
            return []

        return resp.json().get("data", [])

    @staticmethod
    def _parse(item: dict[str, Any]) -> JobPost:
        fields = item.get("fields", {})

        title = fields.get("title", "N/A")
        link = fields.get("url", item.get("href", "N/A"))
        description = fields.get("body", "")
        date_posted = fields.get("date", {}).get("created", "N/A")[:10]

        sources = fields.get("source", [])
        company = sources[0].get("name", "N/A") if sources else "N/A"

        countries = fields.get("country", [])
        cities = fields.get("city", [])
        location_parts = [c.get("name", "") for c in cities] + [c.get("name", "") for c in countries]
        location = ", ".join(filter(None, location_parts)) or None

        return JobPost(
            title=title,
            company=company,
            link=link,
            description=description,
            date_posted=date_posted,
            source="ReliefWeb",
            location=location,
        )
