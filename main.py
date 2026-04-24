"""
Job ingestion pipeline — Phase 4.

Flow: fetch → date-filter → deduplicate → LLM score → append to Google Sheets
"""

import logging
import sys
from datetime import date

from dotenv import load_dotenv

from extractors import MyJobMagExtractor, ReliefWebExtractor
from extractors.base import JobPost
from matching import LocalMatcher
from storage import GoogleSheetsClient
from utils import parse_job_date

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("pipeline")

DATE_CUTOFF = date(2026, 4, 20)


# ── Pipeline steps ────────────────────────────────────────────────────────────

def fetch_all() -> list[JobPost]:
    jobs: list[JobPost] = []

    try:
        rw = ReliefWebExtractor()
        jobs += rw.fetch(limit=20)
    except ValueError as exc:
        logger.warning("ReliefWeb skipped: %s", exc)

    mjm = MyJobMagExtractor()
    jobs += mjm.fetch(limit=20)

    logger.info("Fetched %d job(s) total.", len(jobs))
    return jobs


def filter_by_date(jobs: list[JobPost]) -> list[JobPost]:
    kept = []
    for job in jobs:
        parsed = parse_job_date(job.date_posted)
        if parsed is None:
            logger.warning(
                "SKIP (unparseable date '%s')  %s", job.date_posted, job.title
            )
        elif parsed < DATE_CUTOFF:
            logger.info(
                "SKIP (too old: %s)  [%s]  %s", parsed, job.source, job.title
            )
        else:
            kept.append(job)
    logger.info("%d job(s) passed date filter (cutoff: %s).", len(kept), DATE_CUTOFF)
    return kept


HIGH_MATCH_THRESHOLD = 75


def ingest(
    jobs: list[JobPost],
    sheets: GoogleSheetsClient,
    matcher: LocalMatcher,
) -> tuple[int, int]:
    """
    Deduplicates, scores, and appends jobs.
    Returns (new_appended, high_matches).
    """
    new_appended = 0
    high_matches = 0

    for job in jobs:
        if sheets.is_duplicate(job.link):
            logger.info("SKIP (duplicate)  [%s]  %s", job.source, job.title)
            continue

        match = matcher.score(job)
        logger.info(
            "SCORE %3d  %-20s  [%s]  %s",
            match.match_score,
            match.best_profile,
            job.source,
            job.title,
        )

        sheets.append_job(job, match)
        new_appended += 1
        if match.match_score >= HIGH_MATCH_THRESHOLD:
            high_matches += 1

    return new_appended, high_matches


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # 1. Fetch
    all_jobs = fetch_all()

    # 2. Date filter
    recent_jobs = filter_by_date(all_jobs)
    if not recent_jobs:
        logger.info("Nothing to process. Exiting.")
        return

    # 3. Storage client
    try:
        sheets = GoogleSheetsClient()
    except Exception as exc:
        logger.error("Google Sheets init failed: %s", exc)
        return

    # 4. Matching client (local Ollama — no API key needed)
    matcher = LocalMatcher()

    # 5. Deduplicate → score → append
    new_appended, high_matches = ingest(recent_jobs, sheets, matcher)

    logger.info(
        "Summary: %d fetched | %d new appended | %d High Match(es) found (score >= %d).",
        len(all_jobs),
        new_appended,
        high_matches,
        HIGH_MATCH_THRESHOLD,
    )


if __name__ == "__main__":
    main()
