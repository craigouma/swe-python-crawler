"""Shared utilities used across phases."""

from datetime import date
import re
from typing import Optional

# Formats tried in order when parsing date strings from job sources.
_DATE_FORMATS = [
    "%Y-%m-%d",       # ReliefWeb ISO: "2026-04-20"
    "%Y-%m-%dT%H:%M:%S",  # ISO with time
    "%d %B %Y",       # "08 April 2026"
    "%B %d, %Y",      # "April 08, 2026"
    "%d %b %Y",       # "08 Apr 2026"
    "%d %B",          # MyJobMag partial: "08 April"  — year injected below
    "%d %b",          # "08 Apr"
]

_PARTIAL_FORMATS = {"%d %B", "%d %b"}  # formats that omit the year


def parse_job_date(date_str: str) -> Optional[date]:
    """
    Parse a free-form date string from any job source into a date object.
    For partial strings that omit the year (e.g. "08 April"), the current
    calendar year is assumed — sources like MyJobMag only show live postings.
    Returns None if the string cannot be parsed.
    """
    if not date_str or date_str.strip() in ("N/A", ""):
        return None

    # Strip leading/trailing whitespace and normalise internal spaces
    clean = re.sub(r"\s+", " ", date_str.strip())

    from datetime import datetime

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(clean, fmt)
            if fmt in _PARTIAL_FORMATS:
                dt = dt.replace(year=date.today().year)
            return dt.date()
        except ValueError:
            continue

    return None
