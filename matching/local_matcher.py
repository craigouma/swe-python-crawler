"""
Local LLM matching engine — Phase 3 (Ollama).

Runs entirely on-device via Ollama — no API keys, no rate limits, no cost.
Requires Ollama to be running:  ollama serve
Requires the model to be pulled: ollama pull llama3.2

No .env keys needed.
"""

import json
import logging
from typing import Literal

import ollama
from ollama import ResponseError
from pydantic import BaseModel, Field, ValidationError

from extractors.base import JobPost

logger = logging.getLogger(__name__)

_MODEL = "llama3.2"

# ── Pydantic schema ────────────────────────────────────────────────────────────

class MatchResult(BaseModel):
    match_score: int = Field(ge=0, le=100)
    best_profile: Literal[
        "IT_Support",
        "Credit_Analyst",
        "Data_Analyst",
        "Software_Engineer",
        "None",
    ]
    rationale: str  # max 2 sentences, enforced in the prompt

_FALLBACK = MatchResult(
    match_score=0,
    best_profile="None",
    rationale="Local matcher error — result unavailable.",
)

# ── Prompts ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are a ruthless, highly-calibrated technical recruiter evaluating job postings
for a single candidate. You MUST use the full 0–100 scoring scale. Do NOT hedge.
Do NOT cluster scores around 50–65. Commit to a number.

CANDIDATE: Craig Carlos Ouma

Profile 1 — IT_Support:
  5+ yrs. Linux systems (advanced), VPS migration, disaster recovery, TCP/IP,
  Apache/PHP-FPM, Bash/Python automation, Help Desk.

Profile 2 — Credit_Analyst:
  5+ yrs. Credit risk assessment, financial statement analysis, KYC, portfolio
  monitoring (PAR), advanced Excel, SQL, Python, BigQuery.

Profile 3 — Data_Analyst:
  5+ yrs. Statistical analysis, hypothesis testing, BigQuery, Power BI,
  Looker Studio, Plotly Dash, ETL pipelines, Python/SQL/R.

Profile 4 — Software_Engineer:
  5+ yrs. Full-stack & ML. Python, ReactJS, Node.js, FastAPI, Docker, GCP,
  Git, ETL, Plotly Dash.

CALIBRATION RULES — follow these exactly:
  - Score 90–100: job explicitly requires Python/SQL/Linux/BigQuery/ETL and
    matches at least one profile almost perfectly. No stretch required.
  - Score 75–89: strong match to one profile; one or two minor gaps.
  - Score 40–74: reserve ONLY for genuine split decisions — the role shares
    some overlap but also demands skills Craig clearly lacks. Do not use this
    range as a safe default.
  - Score 15–39: job requires stacks Craig does not know (Java/.NET/SAP only,
    no Python), or is semi-technical/managerial with thin technical content.
  - Score 0–14: zero overlap — teaching, pure sales, HR, legal, unrelated field.

PROFILE ASSIGNMENT RULES — mandatory:
  - NEVER set best_profile to "None" if match_score is 20 or higher.
    At that score there is enough overlap to name the closest profile.
  - Pick the profile whose skill set overlaps the most with the job, even if
    the match is imperfect. Choosing the wrong named profile is better than
    choosing "None" for a scored role.
  - Only use "None" when match_score is 0–19 AND the job has zero overlap with
    any of the four profiles.

ANTI-HEDGING DIRECTIVES:
  - Never give a score of 50, 55, 60, or 65 unless you can articulate exactly
    why the role is genuinely in-between. If you cannot, push the score up or down.
  - A DevOps/Platform Engineer role using Python, Docker, GCP scores ≥ 80.
  - A Data Analyst role with BigQuery and ETL scores ≥ 85.
  - A Software Engineer role with Python and FastAPI scores ≥ 80.
  - A Credit/Financial Analyst role with SQL and risk modelling scores ≥ 80.
  - A role that only mentions Java, C#, .NET, or SAP with no Python scores ≤ 25.
  - A teaching, HR, or purely administrative role scores ≤ 10.

YOUR TASK:
  Return ONLY a valid JSON object — no markdown, no extra text, nothing else.
  The JSON must have exactly these three keys:
    "match_score"  : integer 0–100
    "best_profile" : one of "IT_Support", "Credit_Analyst", "Data_Analyst",
                     "Software_Engineer", or "None"
    "rationale"    : string, maximum 2 sentences, blunt and specific
""".strip()


# ── Matcher class ──────────────────────────────────────────────────────────────

class LocalMatcher:
    """Scores a JobPost against Craig's profile using a local Ollama model."""

    def __init__(self, model: str = _MODEL) -> None:
        self._model = model

    def score(self, job: JobPost) -> MatchResult:
        """
        Send the job to the local Ollama model and return a MatchResult.
        Returns _FALLBACK on any error so the pipeline never crashes.
        """
        user_prompt = (
            f"Job Title: {job.title}\n"
            f"Company: {job.company}\n\n"
            f"Description:\n{job.description[:1500]}"
        )

        try:
            response = ollama.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                format="json",
            )
            raw = response.message.content
            result = MatchResult.model_validate(json.loads(raw))
            logger.info(
                "Local [%s] scored '%s': %d/100 → %s",
                self._model, job.title, result.match_score, result.best_profile,
            )
            return result

        except ConnectionError:
            logger.error(
                "Ollama not running — start it with 'ollama serve'"
            )
            return _FALLBACK

        except ResponseError as exc:
            logger.error("Ollama model error for '%s': %s", job.title, exc)
            return _FALLBACK

        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error(
                "Failed to parse Ollama response for '%s': %s", job.title, exc
            )
            return _FALLBACK

        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error scoring '%s': %s", job.title, exc)
            return _FALLBACK
