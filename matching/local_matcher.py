"""
Local LLM matching engine — Ollama / llama3.2.

Chain-of-Thought schema:  missing_critical_skills → rationale → best_profile → match_score

Field order is the reasoning chain. The model must enumerate skill gaps before it can
write a rationale, and must write the rationale before it can produce a score. This
prevents the "high score first, contradictory rationale after" hallucination pattern.

A Pydantic model_validator enforces the gap-count penalty as a hard constraint so the
model cannot talk its way around it.
"""

import json
import logging
from typing import List, Literal

import ollama
from ollama import ResponseError
from pydantic import BaseModel, Field, ValidationError, model_validator

from extractors.base import JobPost

logger = logging.getLogger(__name__)

_MODEL = "llama3.2"


# ── Pydantic schema (field order = reasoning order) ───────────────────────────

class MatchResult(BaseModel):
    # Step 1 — gaps first: forces the model to think about what's missing
    missing_critical_skills: List[str] = Field(
        description=(
            "Skills explicitly required by the job that the candidate clearly lacks. "
            "Be specific (e.g. 'SWIFT networking', 'SAP FICO'). Empty list if none."
        )
    )
    # Step 2 — rationale references the gaps already committed to above
    rationale: str = Field(
        description="2 sentences, blunt and specific. Reference the gaps or matches identified above."
    )
    # Step 3 — profile chosen after reasoning, not before
    best_profile: Literal[
        "IT_Support",
        "Credit_Analyst",
        "Data_Analyst",
        "Software_Engineer",
        "None",
    ]
    # Step 4 — score is last; the model calculates it after all reasoning is locked in
    match_score: int = Field(ge=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def _apply_gap_penalty(cls, values: dict) -> dict:
        """
        Hard-clamp match_score based on the number of critical skill gaps.
        This is a deterministic safety net — the model cannot hallucinate past it.

          3+ gaps  → score capped at 35  (role requires skills the candidate doesn't have)
          1–2 gaps → score capped at 65  (partial match at best)
          0 gaps   → full 0–100 range applies
        """
        missing = values.get("missing_critical_skills", [])
        score = values.get("match_score", 0)
        n = len(missing) if isinstance(missing, list) else 0

        if n >= 3 and score > 35:
            values["match_score"] = 35
        elif n >= 1 and score > 65:
            values["match_score"] = 65

        # Enforce profile/score consistency: "None" is only valid below 20
        if values.get("best_profile") == "None" and score >= 20:
            values["best_profile"] = "IT_Support"  # safest fallback; prompt prevents this

        return values


_FALLBACK = MatchResult(
    missing_critical_skills=[],
    rationale="Local matcher error — result unavailable.",
    best_profile="None",
    match_score=0,
)


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are a ruthless, highly-calibrated technical recruiter evaluating a job posting
for a single candidate. You think step-by-step and never skip steps.

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

─────────────────────────────────────────────────────────────────────────────
EVALUATION PROCESS — you MUST follow these four steps in strict order:

STEP 1 — missing_critical_skills (output this field first):
  Read the job description carefully. List every skill, technology, certification,
  or domain knowledge that the job explicitly requires AND that Craig clearly does
  not have. Be specific and literal (e.g. "SWIFT/KEPSS RTGS", "SAP FICO module",
  "Kubernetes CKA certification", "IFRS 9 credit modelling").
  If nothing critical is missing, output an empty list: []

STEP 2 — rationale (output this field second):
  Write exactly 2 sentences explaining your evaluation. You must reference the
  specific gaps identified in Step 1 OR the specific matches if there are no gaps.
  Do not introduce new information. Be blunt.

STEP 3 — best_profile (output this field third):
  Based on your reasoning above, name the closest matching profile.
  Rules:
    - NEVER output "None" if match_score will be 20 or higher.
    - If multiple profiles partially match, pick the one with the greatest overlap.
    - Only output "None" when there is zero meaningful overlap with any profile.

STEP 4 — match_score (output this field last):
  Calculate the final integer score (0–100) ONLY after completing Steps 1–3.

  PENALTY RULES — mandatory, not suggestions:
    - 3 or more items in missing_critical_skills → score MUST be ≤ 35.
    - 1–2 items in missing_critical_skills      → score MUST be ≤ 65.
    - Empty missing_critical_skills             → use the full scale below.

  CALIBRATION (applies after penalties):
    - 90–100: explicit match on Python/SQL/Linux/BigQuery/ETL. No stretch needed.
    - 75–89:  strong match to one profile; one or two minor gaps.
    - 40–74:  genuine split — real overlap but real gaps too. Not a safe default.
    - 15–39:  unfamiliar stack (Java/.NET/SAP only, no Python) or thin technical content.
    - 0–14:   zero overlap — teaching, pure sales, HR, legal.

  ANTI-HEDGING: never output 50, 55, 60, or 65 without a clear reason.
    DevOps+Python+Docker+GCP        → ≥ 80
    Data Analyst+BigQuery+ETL       → ≥ 85
    Software Engineer+Python+FastAPI → ≥ 80
    Credit/Financial Analyst+SQL+risk → ≥ 80
    Java/.NET/SAP only, no Python   → ≤ 25
    Teaching / HR / admin           → ≤ 10

─────────────────────────────────────────────────────────────────────────────
OUTPUT FORMAT:
  Return ONLY a valid JSON object — no markdown, no extra text, nothing else.
  Fields MUST appear in exactly this order:
    "missing_critical_skills" : array of strings (empty array if none)
    "rationale"               : string, exactly 2 sentences
    "best_profile"            : one of "IT_Support", "Credit_Analyst",
                                "Data_Analyst", "Software_Engineer", "None"
    "match_score"             : integer 0–100
""".strip()


# ── Matcher class ──────────────────────────────────────────────────────────────

class LocalMatcher:
    """Scores a JobPost against the candidate profile using a local Ollama model."""

    def __init__(self, model: str = _MODEL) -> None:
        self._model = model

    def score(self, job: JobPost) -> MatchResult:
        """
        Send the job to Ollama and return a MatchResult.
        Falls back to _FALLBACK on any error so the pipeline never crashes.
        """
        user_prompt = (
            f"Job Title: {job.title}\n"
            f"Company:   {job.company}\n\n"
            f"Description:\n{job.description[:1500]}"
        )

        try:
            response = ollama.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                format=MatchResult.model_json_schema(),
            )
            raw = response.message.content
            result = MatchResult.model_validate(json.loads(raw))
            logger.info(
                "Local [%s] scored '%s': %d/100 → %s  (gaps: %s)",
                self._model,
                job.title,
                result.match_score,
                result.best_profile,
                result.missing_critical_skills or "none",
            )
            return result

        except ConnectionError:
            logger.error("Ollama not running — start it with 'ollama serve'")
            return _FALLBACK

        except ResponseError as exc:
            logger.error("Ollama model error for '%s': %s", job.title, exc)
            return _FALLBACK

        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error("Failed to parse Ollama response for '%s': %s", job.title, exc)
            return _FALLBACK

        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error scoring '%s': %s", job.title, exc)
            return _FALLBACK
