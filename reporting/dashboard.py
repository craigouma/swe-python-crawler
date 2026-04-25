"""
Static HTML status page generator.

Writes a self-contained index.html after every pipeline run.
Output path is read from STATUS_PAGE_PATH in .env, with a local fallback.
"""

import logging
import os
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

_PROFILE_COLOURS = {
    "Data_Analyst":      "bg-cyan-500/20 text-cyan-300 ring-cyan-500/40",
    "Software_Engineer": "bg-violet-500/20 text-violet-300 ring-violet-500/40",
    "Credit_Analyst":    "bg-emerald-500/20 text-emerald-300 ring-emerald-500/40",
    "IT_Support":        "bg-amber-500/20 text-amber-300 ring-amber-500/40",
    "None":              "bg-zinc-700/40 text-zinc-400 ring-zinc-600/40",
}

_SCORE_COLOUR = {
    "high":    "text-emerald-400",
    "mid":     "text-amber-400",
    "low":     "text-red-400",
}


def _score_colour(score: int) -> str:
    if score >= 75:
        return _SCORE_COLOUR["high"]
    if score >= 40:
        return _SCORE_COLOUR["mid"]
    return _SCORE_COLOUR["low"]


def _profile_badge(profile: str) -> str:
    classes = _PROFILE_COLOURS.get(profile, _PROFILE_COLOURS["None"])
    label = escape(profile.replace("_", " "))
    return (
        f'<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs '
        f'font-medium ring-1 ring-inset {classes}">{label}</span>'
    )


def _scored_rows(scored_jobs: list[dict]) -> str:
    if not scored_jobs:
        return (
            '<tr><td colspan="4" class="px-6 py-10 text-center text-zinc-500 italic">'
            "No jobs scored this run.</td></tr>"
        )
    rows = []
    for job in scored_jobs:
        score = job["score"]
        colour = _score_colour(score)
        rows.append(
            f'<tr class="job-row border-t border-zinc-800 hover:bg-zinc-800/50 transition-colors">'
            f'<td class="px-6 py-4 text-sm font-medium text-white">{escape(job["title"])}</td>'
            f'<td class="px-6 py-4 text-sm text-zinc-300">{escape(job["company"])}</td>'
            f'<td class="px-6 py-4 text-sm font-bold {colour}">{score}</td>'
            f'<td class="px-6 py-4 text-sm">{_profile_badge(job["profile"])}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def _stat_card(label: str, value: Union[int, str], colour: str = "text-white") -> str:
    return (
        f'<div class="rounded-xl border border-zinc-700/60 bg-zinc-800/60 px-6 py-5">'
        f'<p class="text-xs font-medium uppercase tracking-widest text-zinc-500">{escape(label)}</p>'
        f'<p class="mt-2 text-3xl font-bold {colour}">{escape(str(value))}</p>'
        f"</div>"
    )


def generate_status_page(
    stats: dict,
    scored_jobs: list[dict],
    output_path: Optional[str] = None,
) -> None:
    """
    Generate a Tailwind-styled dark-mode HTML status page and write it to disk.

    stats keys expected:
        total_fetched   int
        skipped_old     int
        skipped_dup     int
        new_scored      int
        high_matches    int

    scored_jobs is a list of dicts for ALL jobs scored this run:
        title, company, score, profile
    """
    if output_path is None:
        output_path = os.getenv(
            "STATUS_PAGE_PATH",
            "/tmp/crawler_status.html",
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_skipped = stats.get("skipped_old", 0) + stats.get("skipped_dup", 0)

    stat_cards = "\n".join([
        _stat_card("Total Fetched",  stats.get("total_fetched", 0)),
        _stat_card("Skipped",        total_skipped,                    "text-zinc-400"),
        _stat_card("Newly Scored",   stats.get("new_scored", 0),       "text-cyan-400"),
        _stat_card("High Matches",   stats.get("high_matches", 0),     "text-emerald-400"),
    ])

    html = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Crawler Status — sowerved.tech</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>tailwind.config = {{ darkMode: 'class' }}</script>
  <script>
    const PAGE_SIZE = 10;
    let currentPage = 1;

    function paginate() {{
      const rows = Array.from(document.querySelectorAll('.job-row'));
      const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
      rows.forEach((row, i) => {{
        row.style.display = (i >= (currentPage - 1) * PAGE_SIZE && i < currentPage * PAGE_SIZE)
          ? '' : 'none';
      }});
      document.getElementById('page-info').textContent =
        'Page ' + currentPage + ' of ' + totalPages;
      document.getElementById('btn-prev').disabled = currentPage <= 1;
      document.getElementById('btn-next').disabled = currentPage >= totalPages;
    }}

    function prevPage() {{ if (currentPage > 1) {{ currentPage--; paginate(); }} }}
    function nextPage() {{
      const total = Math.ceil(document.querySelectorAll('.job-row').length / PAGE_SIZE);
      if (currentPage < total) {{ currentPage++; paginate(); }}
    }}

    document.addEventListener('DOMContentLoaded', paginate);
  </script>
</head>
<body class="min-h-screen bg-zinc-950 text-zinc-200 font-mono antialiased">

  <!-- Header -->
  <header class="border-b border-zinc-800 bg-zinc-900/80 px-8 py-5">
    <div class="mx-auto max-w-6xl flex items-center justify-between">
      <div>
        <h1 class="text-lg font-bold tracking-tight text-white">
          ⚙ Job Crawler — Status Dashboard
        </h1>
        <p class="text-xs text-zinc-500 mt-0.5">sowerved.tech · automated pipeline</p>
      </div>
      <p class="text-xs text-zinc-500">Last updated: <span class="text-zinc-300">{now}</span></p>
    </div>
  </header>

  <main class="mx-auto max-w-6xl px-8 py-10 space-y-10">

    <!-- System Status -->
    <section>
      <h2 class="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">
        System Status
      </h2>
      <div class="flex flex-wrap gap-3">
        <span class="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-4 py-1.5
                     text-sm font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/30">
          <span class="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
          Ollama: Online
        </span>
        <span class="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-4 py-1.5
                     text-sm font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/30">
          <span class="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
          Scrapers: Online
        </span>
        <span class="inline-flex items-center gap-2 rounded-full bg-cyan-500/10 px-4 py-1.5
                     text-sm font-medium text-cyan-400 ring-1 ring-inset ring-cyan-500/30">
          <span class="h-2 w-2 rounded-full bg-cyan-400"></span>
          Model: llama3.2
        </span>
      </div>
    </section>

    <!-- Run Stats -->
    <section>
      <h2 class="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">
        Run Statistics
      </h2>
      <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {stat_cards}
      </div>
    </section>

    <!-- Scored Jobs -->
    <section>
      <h2 class="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">
        Recently Scored Jobs
      </h2>
      <div class="overflow-hidden rounded-xl border border-zinc-700/60 bg-zinc-900">
        <table class="w-full text-left text-sm">
          <thead class="bg-zinc-800/80">
            <tr>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Title</th>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Company</th>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Score</th>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Profile</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-800/60">
            {_scored_rows(scored_jobs)}
          </tbody>
        </table>
      </div>
      <!-- Pagination controls -->
      <div class="mt-4 flex items-center justify-between text-xs text-zinc-400">
        <button id="btn-prev" onclick="prevPage()"
          class="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 hover:bg-zinc-700
                 disabled:cursor-not-allowed disabled:opacity-30 transition-colors">
          ← Prev
        </button>
        <span id="page-info">Page 1</span>
        <button id="btn-next" onclick="nextPage()"
          class="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 hover:bg-zinc-700
                 disabled:cursor-not-allowed disabled:opacity-30 transition-colors">
          Next →
        </button>
      </div>
    </section>

  </main>

  <footer class="border-t border-zinc-800 px-8 py-4 text-center text-xs text-zinc-600">
    Generated by swe-python-crawler · {now}
  </footer>

</body>
</html>"""

    try:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        os.chmod(output_path, 0o644)
        logger.info("Status page written to %s (permissions: 644)", output_path)
    except OSError as exc:
        logger.error("Failed to write status page to %s: %s", output_path, exc)
