# swe-python-crawler

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![Ollama](https://img.shields.io/badge/AI-Ollama%20%2F%20llama3.2-black?logo=ollama)
![Google Sheets](https://img.shields.io/badge/Storage-Google%20Sheets-34a853?logo=google-sheets&logoColor=white)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=github-actions&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

An autonomous, AI-driven job aggregation pipeline. It scrapes multiple job sources, filters and deduplicates listings, scores each one against a structured candidate profile using a **local** Llama 3.2 model, writes high-value targets to Google Sheets, and publishes a live HTML health dashboard — all at zero LLM cost.

---

## Overview

Most job boards are noise. This pipeline cuts through it automatically:

- **Fetches** jobs from MyJobMag (web scraping) and ReliefWeb (REST API)
- **Filters** by posting date — only recent listings pass
- **Deduplicates** using the job URL as a unique key against the existing Sheet
- **Scores** each job 0–100 against four candidate profiles via local Llama 3.2
- **Appends** results with match scores, profile labels, and rationale to Google Sheets
- **Publishes** a static HTML dashboard showing run stats and all scored jobs

---

## System Architecture

```mermaid
graph LR
    subgraph Launcher["🚀 run_crawler.sh"]
        SH["Checks Ollama health\nActivates venv\nInvokes main.py"]
    end

    subgraph Sources["📡 Job Sources"]
        RW["ReliefWeb\nREST API v2\nup to 20 jobs"]
        MJM["MyJobMag\nBeautifulSoup4 scrape\nup to 20 jobs/category"]
    end

    subgraph LLM["🤖 Local LLM  ·  Ollama"]
        OL["llama3.2\nReturns: score 0–100\nbest_profile + rationale"]
    end

    subgraph Pipeline["⚙️  main.py — Pipeline Orchestrator"]
        FETCH["1 · FETCH\nMerges all sources"]
        FILTER["2 · DATE FILTER\nDrop listings older than cutoff"]
        DEDUP["3 · DEDUPLICATE\nCheck URL vs Sheet col G"]
        SCORE["4 · SCORE"]
        SAVE["5 · SAVE TO SHEETS\nStatus → Not Applied"]
        DASH["6 · GENERATE DASHBOARD"]
    end

    subgraph Storage["🗄️  Storage"]
        GS[("Google Sheets\nJobs worksheet\n9-column schema")]
    end

    subgraph Output["🌐 Output"]
        HTML["index.html\nTailwind dark-mode dashboard\nServed by Nginx"]
    end

    SH -->|"python main.py"| FETCH
    RW -->|"JSON"| FETCH
    MJM -->|"Parsed HTML"| FETCH
    FETCH --> FILTER
    FILTER -->|"Recent listings only"| DEDUP
    DEDUP -->|"New URLs only"| SCORE
    SCORE <-->|"job description"| OL
    SCORE -->|"score · profile · rationale"| SAVE
    SAVE --> GS
    SAVE --> DASH
    DASH --> HTML
```

---

## Project Structure

```
swe-python-crawler/
├── extractors/
│   ├── base.py              # JobPost dataclass + JobExtractor ABC
│   ├── myjobmag.py          # HTML scraper (requests + BeautifulSoup4)
│   └── reliefweb.py         # ReliefWeb v2 REST API client
├── matching/
│   └── local_matcher.py     # Ollama/llama3.2 scoring engine (Pydantic output)
├── storage/
│   └── google_sheets.py     # gspread client — schema init, dedup, append
├── reporting/
│   └── dashboard.py         # Static HTML dashboard generator (Tailwind CSS)
├── .github/
│   └── workflows/
│       └── deploy.yml       # GitHub Actions CI/CD → VPS deploy
├── main.py                  # Pipeline orchestrator
├── utils.py                 # Multi-format date parser
├── run_crawler.sh           # Production launcher script
├── requirements.txt
└── .env.example
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.9+ | Tested on 3.9 and 3.12 |
| [Ollama](https://ollama.com/download) | Local LLM runtime |
| `llama3.2` model | ~2 GB, pulled via Ollama |
| Google Cloud Service Account | Needs Sheets API enabled |
| Google Sheet | Share it with the service account as **Editor** |
| ReliefWeb appname | Free registration at [apidoc.reliefweb.int](https://apidoc.reliefweb.int/parameters#appname) |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

```env
# ── ReliefWeb API ─────────────────────────────────────────────
# Register free at: https://apidoc.reliefweb.int/parameters#appname
RELIEFWEB_APPNAME=your-approved-appname

# ── Google Sheets ─────────────────────────────────────────────
# Absolute path to your downloaded service account JSON key file
GOOGLE_SERVICE_ACCOUNT_JSON=/absolute/path/to/gcp-credentials.json

# The ID from the Sheets URL: /spreadsheets/d/<SPREADSHEET_ID>/edit
GOOGLE_SPREADSHEET_ID=your-spreadsheet-id

# Worksheet tab name (auto-created if it does not exist)
GOOGLE_WORKSHEET_NAME=Jobs

# ── Status Dashboard ──────────────────────────────────────────
# Absolute path where the HTML dashboard is written after each run
STATUS_PAGE_PATH=/home/craigouma/status.sowerved.tech/index.html
```

> **Security note:** `.env` and `gcp-credentials.json` are both listed in `.gitignore` and must never be committed.

---

## Google Sheets Schema

The pipeline writes to the following fixed column layout:

| Col | Header | Description |
|-----|--------|-------------|
| A | Job Title | |
| B | Company/Org | |
| C | Source | `MyJobMag` or `ReliefWeb` |
| D | Match Score | 0–100 integer set by Llama 3.2 |
| E | Best Profile Match | `IT_Support` · `Credit_Analyst` · `Data_Analyst` · `Software_Engineer` · `None` |
| F | Match Rationale | 2-sentence LLM explanation |
| G | Link | Unique key used for deduplication |
| H | Date Posted | |
| I | Status | Defaults to `Not Applied` |

---

## Local Setup & Execution

### 1. Clone and install

```bash
git clone https://github.com/<your-username>/swe-python-crawler.git
cd swe-python-crawler
pip install -r requirements.txt
```

### 2. Pull the model

```bash
ollama pull llama3.2
```

### 3. Configure credentials

```bash
cp .env.example .env
# Edit .env with your values
```

### 4. Run

```bash
# Start Ollama (keep running in background or as a service)
ollama serve

# In a separate terminal
python main.py
```

Or use the launcher script which handles all of the above automatically:

```bash
bash run_crawler.sh
```

### Sample output

```
00:37:28  INFO  pipeline  Fetched 20 job(s) total.
00:37:28  INFO  pipeline  SKIP (too old: 2026-04-08)  [MyJobMag]  DevOps Engineer
00:39:47  INFO  matching.local_matcher  Local [llama3.2] scored 'Financial & Data Analyst': 92/100 → Data_Analyst
00:39:47  INFO  storage.google_sheets   Appended: [MyJobMag] Financial & Data Analyst — Solar Panda
00:40:03  INFO  pipeline  Summary: 20 fetched | 8 new appended | 2 High Match(es) found (score >= 75).
00:40:03  INFO  reporting.dashboard     Status page written to /home/craigouma/status.sowerved.tech/index.html (permissions: 644)
```

---

## VPS Deployment & Security

### Isolated service user

The pipeline runs under a dedicated, least-privilege Linux user `crawler_svc` with no login shell and no sudo rights. This contains the blast radius if the process is ever compromised.

```bash
# On the VPS — create the service user (run once as root)
useradd --system --no-create-home --shell /usr/sbin/nologin crawler_svc
```

Sensitive files on the VPS are owned by `crawler_svc` and set to `600`:

```bash
chmod 600 /home/crawler_svc/swe-python-crawler/.env
chmod 600 /home/crawler_svc/swe-python-crawler/gcp-credentials.json
```

### CI/CD via GitHub Actions

Every push to `main` triggers `.github/workflows/deploy.yml`, which:

1. Checks out the repository
2. Uses `appleboy/scp-action` to copy all files to the VPS (excludes `.git` and `.github`)
3. Uses `appleboy/ssh-action` to create/update the virtual environment and install dependencies

Configure the following **GitHub Secrets** in your repository settings:

| Secret | Value |
|--------|-------|
| `SERVER_HOST` | VPS IP or hostname |
| `SERVER_USER` | `crawler_svc` |
| `SSH_PRIVATE_KEY` | Private key for `crawler_svc` |

### Cron schedule

After deployment, schedule the crawler to run every 6 hours under the `crawler_svc` user:

```bash
crontab -e -u crawler_svc
```

```cron
0 */6 * * * /home/crawler_svc/swe-python-crawler/run_crawler.sh >> /home/crawler_svc/crawler.log 2>&1
```

---

## The Dashboard

After every run, the pipeline generates a self-contained `index.html` using Tailwind CSS (CDN) and writes it to `STATUS_PAGE_PATH` with `644` permissions so the web server can read it.

The page displays:

- **System status badges** — Ollama and Scrapers online indicators
- **Run statistics** — Total fetched, skipped, newly scored, and high-match count
- **Recently Scored Jobs table** — all jobs processed in the current run with score, profile label, and pagination (10 rows per page)

Serve the output directory from Apache or Nginx as a standard static site. No backend required.

```nginx
server {
    listen 80;
    server_name status.sowerved.tech;
    root /home/craigouma/status.sowerved.tech;
    index index.html;
}
```

---

## Extending the Pipeline

To add a new job source:

1. Create `extractors/your_source.py` — subclass `JobExtractor`, implement `fetch(limit) -> list[JobPost]`
2. Export it from `extractors/__init__.py`
3. Add it to `fetch_all()` in `main.py`

The date filter, deduplication, scoring, and storage steps apply automatically — no other changes needed.

---

## License

MIT
