"""
Static HTML status page generator with persistent job history.

On each run:
  - Prepends newly scored jobs to jobs_history.json (deduplicated by link)
  - Writes stats_latest.json with the current run summary
  - Regenerates index.html (a static JS shell that fetches the JSON files)

The HTML auto-polls the JSON files every 5 minutes so the browser shows
fresh data without a manual reload. Job history accumulates across runs —
it is never cleared.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_EAT = timezone(timedelta(hours=3))

logger = logging.getLogger(__name__)

_PROFILE_COLOURS = {
    "Data_Analyst":      "bg-cyan-500/20 text-cyan-300 ring-cyan-500/40",
    "Software_Engineer": "bg-violet-500/20 text-violet-300 ring-violet-500/40",
    "Credit_Analyst":    "bg-emerald-500/20 text-emerald-300 ring-emerald-500/40",
    "IT_Support":        "bg-amber-500/20 text-amber-300 ring-amber-500/40",
    "None":              "bg-zinc-700/40 text-zinc-400 ring-zinc-600/40",
}


def generate_status_page(
    stats: dict,
    scored_jobs: list,
    output_path: Optional[str] = None,
) -> None:
    """
    Update persistent data files and regenerate the HTML shell.

    stats keys expected:
        total_fetched, skipped_old, skipped_dup, new_scored, high_matches

    scored_jobs dicts expected:
        title, company, score, profile, source, link
    """
    if output_path is None:
        output_path = os.getenv("STATUS_PAGE_PATH", "/tmp/crawler_status.html")

    now_iso = datetime.now(_EAT).strftime("%Y-%m-%dT%H:%M:%S EAT")
    out_dir = Path(output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Update persistent job history ───────────────────────────────────
    history_path = out_dir / "jobs_history.json"
    history: list = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            history = []

    existing_links = {job.get("link") for job in history if job.get("link")}

    new_entries = [
        {
            "title":   job.get("title", ""),
            "company": job.get("company", ""),
            "score":   job.get("score", 0),
            "profile": job.get("profile", "None"),
            "source":  job.get("source", ""),
            "link":    job.get("link", ""),
            "run_at":  now_iso,
        }
        for job in scored_jobs
        if job.get("link") and job.get("link") not in existing_links
    ]

    # Prepend so newest jobs appear first
    history = new_entries + history
    _write_json(history_path, history)

    # ── 2. Write latest run stats ───────────────────────────────────────────
    stats_path = out_dir / "stats_latest.json"
    _write_json(stats_path, {**stats, "run_at": now_iso})

    # ── 3. Write / refresh HTML shell ──────────────────────────────────────
    html_path = Path(output_path)
    try:
        html_path.write_text(_build_html_shell(), encoding="utf-8")
        for p in (html_path, history_path, stats_path):
            os.chmod(str(p), 0o644)
        logger.info("Status page written to %s (permissions: 644)", output_path)
    except OSError as exc:
        logger.error("Failed to write status page to %s: %s", output_path, exc)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_json(path: Path, data: object) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write %s: %s", path, exc)


def _build_html_shell() -> str:
    profile_colours_js = json.dumps(_PROFILE_COLOURS)
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Crawler Status — sowerved.tech</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>tailwind.config = {{ darkMode: 'class' }}</script>
  <script>
    const PAGE_SIZE = 10;
    const POLL_MS   = 5 * 60 * 1000;
    const PROFILE_COLOURS = {profile_colours_js};

    let allJobs    = [];
    let currentPage = 1;

    // ── Data loading ────────────────────────────────────────────────────────

    async function loadData() {{
      try {{
        const ts = Date.now();
        const [statsRes, jobsRes] = await Promise.all([
          fetch('./stats_latest.json?_=' + ts),
          fetch('./jobs_history.json?_=' + ts),
        ]);
        if (statsRes.ok) renderStats(await statsRes.json());
        if (jobsRes.ok) {{
          allJobs = await jobsRes.json();
          currentPage = 1;
          renderTable();
        }}
      }} catch (e) {{
        console.warn('Data refresh failed:', e);
      }}
    }}

    // ── Renderers ────────────────────────────────────────────────────────────

    function renderStats(s) {{
      set('stat-fetched', s.total_fetched ?? '—');
      set('stat-skipped', (s.skipped_old ?? 0) + (s.skipped_dup ?? 0));
      set('stat-scored',  s.new_scored   ?? '—');
      set('stat-high',    s.high_matches ?? '—');
      set('stat-run-at',  s.run_at ? 'Last run: ' + s.run_at : '');
    }}

    function renderTable() {{
      const tbody      = document.getElementById('jobs-tbody');
      const totalPages = Math.max(1, Math.ceil(allJobs.length / PAGE_SIZE));
      currentPage      = Math.min(currentPage, totalPages);

      const slice = allJobs.slice(
        (currentPage - 1) * PAGE_SIZE,
        currentPage * PAGE_SIZE,
      );

      tbody.innerHTML = allJobs.length === 0
        ? `<tr><td colspan="5" class="px-6 py-10 text-center text-zinc-500 italic">No jobs scored yet.</td></tr>`
        : slice.map(job => `
          <tr class="border-t border-zinc-800 hover:bg-zinc-800/50 transition-colors">
            <td class="px-6 py-4 text-sm font-medium text-white">${{esc(job.title)}}</td>
            <td class="px-6 py-4 text-sm text-zinc-300">${{esc(job.company)}}</td>
            <td class="px-6 py-4 text-sm font-bold ${{scoreColour(job.score)}}">${{job.score}}</td>
            <td class="px-6 py-4 text-sm">${{profileBadge(job.profile)}}</td>
            <td class="px-6 py-4 text-xs text-zinc-500 whitespace-nowrap">${{esc(job.run_at ?? '')}}</td>
          </tr>`).join('');

      set('page-info',
        'Page ' + currentPage + ' of ' + totalPages + ' · ' + allJobs.length + ' jobs total');
      document.getElementById('btn-prev').disabled = currentPage <= 1;
      document.getElementById('btn-next').disabled = currentPage >= totalPages;
    }}

    // ── Pagination ───────────────────────────────────────────────────────────

    function prevPage() {{
      if (currentPage > 1) {{ currentPage--; renderTable(); }}
    }}
    function nextPage() {{
      if (currentPage < Math.ceil(allJobs.length / PAGE_SIZE)) {{
        currentPage++; renderTable();
      }}
    }}

    // ── Utilities ────────────────────────────────────────────────────────────

    function profileBadge(profile) {{
      const cls   = PROFILE_COLOURS[profile] ?? PROFILE_COLOURS['None'];
      const label = (profile ?? 'None').replace(/_/g, ' ');
      return `<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs
        font-medium ring-1 ring-inset ${{cls}}">${{label}}</span>`;
    }}

    function scoreColour(score) {{
      return score >= 75 ? 'text-emerald-400' : score >= 40 ? 'text-amber-400' : 'text-red-400';
    }}

    function esc(str) {{
      return String(str ?? '')
        .replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }}

    function set(id, val) {{
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    }}

    // ── Boot ─────────────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {{
      loadData();
      setInterval(loadData, POLL_MS);
    }});
  </script>
</head>
<body class="min-h-screen bg-zinc-950 text-zinc-200 font-mono antialiased">

  <header class="border-b border-zinc-800 bg-zinc-900/80 px-8 py-5">
    <div class="mx-auto max-w-6xl flex items-center justify-between">
      <div>
        <h1 class="text-lg font-bold tracking-tight text-white">
          &#9881; Job Crawler &mdash; Status Dashboard
        </h1>
        <p class="text-xs text-zinc-500 mt-0.5">sowerved.tech &middot; automated pipeline</p>
      </div>
      <p class="text-xs text-zinc-500" id="stat-run-at"></p>
    </div>
  </header>

  <main class="mx-auto max-w-6xl px-8 py-10 space-y-10">

    <section>
      <h2 class="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">System Status</h2>
      <div class="flex flex-wrap gap-3">
        <span class="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-4 py-1.5
                     text-sm font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/30">
          <span class="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>Ollama: Online
        </span>
        <span class="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-4 py-1.5
                     text-sm font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/30">
          <span class="h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>Scrapers: Online
        </span>
        <span class="inline-flex items-center gap-2 rounded-full bg-cyan-500/10 px-4 py-1.5
                     text-sm font-medium text-cyan-400 ring-1 ring-inset ring-cyan-500/30">
          <span class="h-2 w-2 rounded-full bg-cyan-400"></span>Model: llama3.2
        </span>
      </div>
    </section>

    <section>
      <h2 class="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">
        Latest Run Statistics
      </h2>
      <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div class="rounded-xl border border-zinc-700/60 bg-zinc-800/60 px-6 py-5">
          <p class="text-xs font-medium uppercase tracking-widest text-zinc-500">Total Fetched</p>
          <p class="mt-2 text-3xl font-bold text-white" id="stat-fetched">—</p>
        </div>
        <div class="rounded-xl border border-zinc-700/60 bg-zinc-800/60 px-6 py-5">
          <p class="text-xs font-medium uppercase tracking-widest text-zinc-500">Skipped</p>
          <p class="mt-2 text-3xl font-bold text-zinc-400" id="stat-skipped">—</p>
        </div>
        <div class="rounded-xl border border-zinc-700/60 bg-zinc-800/60 px-6 py-5">
          <p class="text-xs font-medium uppercase tracking-widest text-zinc-500">Newly Scored</p>
          <p class="mt-2 text-3xl font-bold text-cyan-400" id="stat-scored">—</p>
        </div>
        <div class="rounded-xl border border-zinc-700/60 bg-zinc-800/60 px-6 py-5">
          <p class="text-xs font-medium uppercase tracking-widest text-zinc-500">High Matches</p>
          <p class="mt-2 text-3xl font-bold text-emerald-400" id="stat-high">—</p>
        </div>
      </div>
    </section>

    <section>
      <h2 class="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">
        All Scored Jobs
      </h2>
      <div class="overflow-hidden rounded-xl border border-zinc-700/60 bg-zinc-900">
        <table class="w-full text-left text-sm">
          <thead class="bg-zinc-800/80">
            <tr>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Title</th>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Company</th>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Score</th>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Profile</th>
              <th class="px-6 py-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">Crawled At</th>
            </tr>
          </thead>
          <tbody id="jobs-tbody">
            <tr>
              <td colspan="5" class="px-6 py-10 text-center text-zinc-500 italic">Loading&hellip;</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mt-4 flex items-center justify-between text-xs text-zinc-400">
        <button id="btn-prev" onclick="prevPage()"
          class="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 hover:bg-zinc-700
                 disabled:cursor-not-allowed disabled:opacity-30 transition-colors">
          &larr; Prev
        </button>
        <span id="page-info">Loading&hellip;</span>
        <button id="btn-next" onclick="nextPage()"
          class="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 hover:bg-zinc-700
                 disabled:cursor-not-allowed disabled:opacity-30 transition-colors">
          Next &rarr;
        </button>
      </div>
    </section>

  </main>

  <footer class="border-t border-zinc-800 px-8 py-4 text-center text-xs text-zinc-600">
    swe-python-crawler &middot; auto-refreshes every 5 minutes
  </footer>

</body>
</html>"""
