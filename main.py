"""
Job ingestion pipeline — Phase 4.

Flow: fetch → date-filter → deduplicate → LLM score → append to Google Sheets
      → generate HTML status page
"""

import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv

from extractors import MyJobMagExtractor, ReliefWebExtractor
from extractors.base import JobPost
from matching import LocalMatcher
from reporting import generate_status_page
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
HIGH_MATCH_THRESHOLD = 75


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


def filter_by_date(jobs: list[JobPost]) -> tuple[list[JobPost], int]:
    """Returns (kept_jobs, skipped_old_count)."""
    kept = []
    skipped_old = 0
    for job in jobs:
        parsed = parse_job_date(job.date_posted)
        if parsed is None:
            logger.warning(
                "SKIP (unparseable date '%s')  %s", job.date_posted, job.title
            )
            skipped_old += 1
        elif parsed < DATE_CUTOFF:
            logger.info(
                "SKIP (too old: %s)  [%s]  %s", parsed, job.source, job.title
            )
            skipped_old += 1
        else:
            kept.append(job)
    logger.info("%d job(s) passed date filter (cutoff: %s).", len(kept), DATE_CUTOFF)
    return kept, skipped_old


def ingest(
    jobs: list[JobPost],
    sheets: GoogleSheetsClient,
    matcher: LocalMatcher,
) -> tuple[int, int, int, list[dict]]:
    """
    Deduplicates, scores, and appends jobs.
    Returns (new_appended, skipped_dup, high_match_count, all_scored_jobs).

    all_scored_jobs contains every job processed this run (not just high matches):
        title, company, score, profile
    """
    new_appended = 0
    skipped_dup = 0
    high_match_count = 0
    all_scored_jobs: list[dict] = []

    for job in jobs:
        if sheets.is_duplicate(job.link):
            logger.info("SKIP (duplicate)  [%s]  %s", job.source, job.title)
            skipped_dup += 1
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

        all_scored_jobs.append({
            "title":   job.title,
            "company": job.company,
            "score":   match.match_score,
            "profile": match.best_profile,
        })

        if match.match_score >= HIGH_MATCH_THRESHOLD:
            high_match_count += 1

    return new_appended, skipped_dup, high_match_count, all_scored_jobs


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # 1. Fetch
    all_jobs = fetch_all()
    total_fetched = len(all_jobs)

    # 2. Date filter
    recent_jobs, skipped_old = filter_by_date(all_jobs)
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
    new_appended, skipped_dup, high_match_count, all_scored_jobs = ingest(
        recent_jobs, sheets, matcher
    )

    logger.info(
        "Summary: %d fetched | %d new appended | %d High Match(es) found (score >= %d).",
        total_fetched,
        new_appended,
        high_match_count,
        HIGH_MATCH_THRESHOLD,
    )

    # 6. Generate HTML status page
    stats = {
        "total_fetched": total_fetched,
        "skipped_old":   skipped_old,
        "skipped_dup":   skipped_dup,
        "new_scored":    new_appended,
        "high_matches":  high_match_count,
    }
    status_path = os.getenv(
        "STATUS_PAGE_PATH",
        "/home/craigouma/status.sowerved.tech/index.html",
    )
    generate_status_page(stats, all_scored_jobs, output_path=status_path)


if __name__ == "__main__":
    main()
