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
    def _apply_penalties(cls, values: dict) -> dict:
        """
        Deterministic safety net — the model cannot hallucinate past these rules.

        Dealbreaker cap (checked first):
          Any gap string containing "years experience", "certification", or
          "outside candidate's domain" triggers the dealbreaker: score ≤ 19,
          best_profile forced to "None".

        Gap-count penalty (applied if no dealbreaker):
          3+ gaps → score ≤ 35
          1–2 gaps → score ≤ 65
          0 gaps  → full range

        Profile/score consistency:
          "None" is only valid when score < 20.
        """
        missing = values.get("missing_critical_skills", [])
        score   = values.get("match_score", 0)
        n = len(missing) if isinstance(missing, list) else 0

        _DEALBREAKER_MARKERS = ("years experience", "certification", "outside candidate")
        is_dealbreaker = any(
            any(marker in gap.lower() for marker in _DEALBREAKER_MARKERS)
            for gap in (missing if isinstance(missing, list) else [])
        )

        if is_dealbreaker:
            if score > 19:
                values["match_score"] = 19
            values["best_profile"] = "None"
        else:
            if n >= 3 and score > 35:
                values["match_score"] = 35
            elif n >= 1 and score > 65:
                values["match_score"] = 65

            # "None" profile is only valid below 20
            if values.get("best_profile") == "None" and values.get("match_score", 0) >= 20:
                values["best_profile"] = "IT_Support"

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
Assume mid-level experience: ~3–5 years across all profiles.

Profile 1 — IT_Support:
  Linux systems (advanced), VPS migration, disaster recovery, TCP/IP,
  Apache/PHP-FPM, Bash/Python automation, Help Desk.
  No certifications: no CISSP, no CISM, no CompTIA Security+, no CCNA.

Profile 2 — Credit_Analyst:
  Credit risk assessment, financial statement analysis, KYC, portfolio
  monitoring (PAR), advanced Excel, SQL, Python, BigQuery.
  No certifications: no CPA, no CFA, no ACCA.

Profile 3 — Data_Analyst:
  Statistical analysis, hypothesis testing, BigQuery, Power BI,
  Looker Studio, Plotly Dash, ETL pipelines, Python/SQL/R.
  No certifications: no AWS/Azure/GCP Professional certs, no CKA.

Profile 4 — Software_Engineer:
  Full-stack & ML. Python, ReactJS, Node.js, FastAPI, Docker, GCP,
  Git, ETL, Plotly Dash.
  No certifications: no AWS Solutions Architect, no CKA, no TOGAF.

─────────────────────────────────────────────────────────────────────────────
EVALUATION PROCESS — follow these steps in strict order, no exceptions:

STEP 0 — DEALBREAKER CHECK (run this before anything else):
  A dealbreaker immediately caps match_score at ≤ 19 and forces best_profile
  to "None". Check all three conditions:

  [DB-1] EXPERIENCE GAP:
    Does the job explicitly require more years of experience than 3–5 years?
    Examples that trigger this: "7+ years", "minimum 8 years", "10 years experience".
    If yes → add "Requires X years experience (candidate has ~3–5 years)" to
    missing_critical_skills.

  [DB-2] MANDATORY CERTIFICATION:
    Does the job require a specific advanced certification that Craig does not hold?
    Certifications that always trigger this: CISSP, CISM, CRISC, CEH, OSCP,
    CPA, CFA, ACCA, CISA, PMP, PRINCE2, AWS Professional/Specialty,
    Azure Expert, GCP Professional, CKA, CKAD, TOGAF, Six Sigma Black Belt.
    If yes → add "Requires [CERT NAME] certification (candidate does not hold this)"
    to missing_critical_skills.

  [DB-3] UNRELATED DOMAIN:
    Is the job in a specialized domain that Craig has no background in?
    Domains that always trigger this: Cybersecurity Operations / SOC management,
    Core Banking / SWIFT / RTGS clearing, Clinical / Nursing / Healthcare,
    Legal / Compliance Officer, Civil / Structural Engineering,
    Supply Chain / Procurement management.
    If yes → add "Role is in [DOMAIN] — outside candidate's domain" to
    missing_critical_skills.

  If ANY dealbreaker fires:
    - missing_critical_skills must contain the exact dealbreaker string(s) above.
    - match_score MUST be 0–19. No exceptions. Ignore all calibration rules below.
    - best_profile MUST be "None".
    - Stop. Do not apply further calibration.

STEP 1 — missing_critical_skills (output this field first):
  If no dealbreaker fired, list every other skill, technology, or domain knowledge
  the job explicitly requires that Craig clearly does not have.
  Be specific (e.g. "SWIFT/KEPSS RTGS", "SAP FICO module", "IFRS 9 modelling").
  If nothing is missing, output an empty list: []

STEP 2 — rationale (output this field second):
  Write exactly 2 sentences. Reference the specific gaps from Step 1 (or the
  dealbreaker from Step 0) OR the specific matches if there are none.
  Do not introduce new information. Be blunt.

STEP 3 — best_profile (output this field third):
  Name the closest matching profile. Rules:
    - If a dealbreaker fired → must be "None".
    - NEVER output "None" if match_score will be 20 or higher.
    - If multiple profiles partially match, pick the greatest overlap.

STEP 4 — match_score (output this field last):
  Calculate the final integer (0–100) only after Steps 0–3 are complete.

  PENALTY RULES (only if no dealbreaker fired):
    - 3+ items in missing_critical_skills → score MUST be ≤ 35.
    - 1–2 items in missing_critical_skills → score MUST be ≤ 65.
    - Empty missing_critical_skills → use the full calibration scale below.

  CALIBRATION (applies only when no dealbreaker and no gap penalty):
    - 90–100: explicit match on Python/SQL/Linux/BigQuery/ETL. No stretch needed.
    - 75–89:  strong match; one or two minor gaps.
    - 40–74:  genuine split — real overlap but real gaps. Not a safe default.
    - 15–39:  unfamiliar stack (Java/.NET/SAP only, no Python) or thin technical content.
    - 0–14:   zero overlap — teaching, pure sales, HR, legal.

  ANTI-HEDGING: never output 50, 55, 60, or 65 without a clear reason.
    DevOps+Python+Docker+GCP          → ≥ 80
    Data Analyst+BigQuery+ETL         → ≥ 85
    Software Engineer+Python+FastAPI  → ≥ 80
    Credit/Financial Analyst+SQL+risk → ≥ 80
    Java/.NET/SAP only, no Python     → ≤ 25
    Teaching / HR / admin             → ≤ 10

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
