"""
Anti-fragility health monitor for the scraper pipeline.

Tracks consecutive zero-fetch runs per extractor in health_state.json.
When an extractor hits ALERT_THRESHOLD consecutive zero runs it fires a
CRITICAL log and returns itself as an active alert so the dashboard can
surface a red banner.

State file location defaults to health_state.json in the project root.
Override via HEALTH_STATE_PATH in .env if needed.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 2

_DEFAULT_STATE_PATH = Path(__file__).parent / "health_state.json"


def _state_path() -> Path:
    override = os.getenv("HEALTH_STATE_PATH", "")
    return Path(override) if override else _DEFAULT_STATE_PATH


def _load_state() -> Dict[str, int]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("health_state.json unreadable — starting fresh.")
        return {}


def _save_state(state: Dict[str, int]) -> None:
    p = _state_path()
    try:
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write health_state.json: %s", exc)


def update_and_get_alerts(fetch_counts: Dict[str, int]) -> List[str]:
    """
    Update consecutive-zero counters for each extractor and return the list
    of extractor names that have reached or exceeded ALERT_THRESHOLD.

    Args:
        fetch_counts: mapping of extractor name → number of jobs fetched
                      e.g. {"MyJobMag": 0, "ReliefWeb": 16}

    Returns:
        List of extractor names currently in alert state.
    """
    state = _load_state()
    alerts: List[str] = []

    for extractor, count in fetch_counts.items():
        if count == 0:
            state[extractor] = state.get(extractor, 0) + 1
        else:
            state[extractor] = 0

        consecutive = state[extractor]
        if consecutive >= ALERT_THRESHOLD:
            logger.critical(
                "HEALTH ALERT: %s has fetched 0 jobs for %d consecutive run(s). "
                "Scraper likely broken — check selectors or API endpoint.",
                extractor,
                consecutive,
            )
            alerts.append(extractor)

    _save_state(state)
    return alerts
