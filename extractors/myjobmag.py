import logging
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from .base import JobExtractor, JobPost

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.myjobmag.co.ke"

# Category pages that map to Craig's target roles.
_CATEGORY_PATHS = [
    "/jobs-by-field/information-technology",   # ICT / Computer
    "/jobs-by-field/research-data-analysis",   # Data, Business Analysis and AI
    "/jobs-by-field/engineering",              # Engineering / Technical (catches SWE roles)
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_REQUEST_DELAY_SEC = 1.5

# Matches " at CompanyName" suffix in job titles on myjobmag.
_AT_COMPANY_RE = re.compile(r"\s+at\s+(.+)$", re.IGNORECASE)


class MyJobMagExtractor(JobExtractor):
    """
    Scrapes job listings from myjobmag.co.ke using requests + BeautifulSoup.

    Page structure (each job is a group of sibling <li> inside one <ul>):
      <li class="mag-b">   — title + link (and embedded company "Title at Company")
      <li class="job-desc"> — short description snippet
      <li class="job_detail_tag"> — salary / tags (optional)
      <li class="job-item">
        <ul><li id="job-date"> — date text + location link
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch(self, limit: int = 10) -> list[JobPost]:
        posts: list[JobPost] = []
        seen: set[str] = set()

        for path in _CATEGORY_PATHS:
            if len(posts) >= limit:
                break
            url = _BASE_URL + path
            for post in self._scrape_page(url):
                if post.link not in seen:
                    seen.add(post.link)
                    posts.append(post)
                    if len(posts) >= limit:
                        break
            time.sleep(_REQUEST_DELAY_SEC)

        logger.info("MyJobMag: fetched %d job(s)", len(posts))
        return posts[:limit]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _scrape_page(self, url: str) -> list[JobPost]:
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("MyJobMag request failed for %s: %s", url, exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse_listing(soup)

    def _parse_listing(self, soup: BeautifulSoup) -> list[JobPost]:
        posts: list[JobPost] = []
        # Every job starts with a li.mag-b inside a shared parent <ul>.
        for title_li in soup.select("li.mag-b"):
            try:
                post = self._parse_group(title_li)
                if post:
                    posts.append(post)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping card: %s", exc)
        return posts

    def _parse_group(self, title_li: Tag) -> JobPost | None:
        # --- Title + link ---
        anchor = title_li.find("a", href=True)
        if not anchor:
            return None
        raw_title = anchor.get_text(strip=True)
        href = anchor["href"]
        link = urljoin(_BASE_URL, href)

        # Extract company from "Job Title at Company Name"
        company = "N/A"
        m = _AT_COMPANY_RE.search(raw_title)
        if m:
            company = m.group(1).strip()
            title = raw_title[: m.start()].strip()
        else:
            title = raw_title

        # Walk sibling <li> elements that belong to the same job group.
        description = ""
        date_posted = "N/A"
        location = None

        sibling = title_li.find_next_sibling("li")
        while sibling:
            classes = sibling.get("class", [])

            if "job-desc" in classes:
                description = sibling.get_text(strip=True)

            elif "job-item" in classes:
                date_li = sibling.find("li", id="job-date")
                if date_li:
                    # Date text is a direct NavigableString inside li#job-date
                    # before the <span> with the location icon.
                    date_text = date_li.find(string=True, recursive=False)
                    if date_text:
                        date_posted = date_text.strip()

                    loc_anchor = date_li.find("a", href=lambda h: h and "jobs-location" in h)
                    if loc_anchor:
                        location = loc_anchor.get_text(strip=True)
                # job-item marks the end of this job's group
                break

            elif "mag-b" in classes:
                # Next job started — stop
                break

            sibling = sibling.find_next_sibling("li")

        return JobPost(
            title=title,
            company=company,
            link=link,
            description=description,
            date_posted=date_posted,
            source="MyJobMag",
            location=location,
        )
