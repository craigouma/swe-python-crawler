# Job Ingestion & LLM Matching Pipeline

An automated pipeline that scrapes job listings, scores them against a candidate profile using a local LLM, and writes results to Google Sheets.

## How It Works

```
Extractors → Date Filter → Deduplication → Local LLM Scoring → Google Sheets
```

1. **Extract** — pulls jobs from MyJobMag (HTML scrape) and ReliefWeb (REST API)
2. **Filter** — drops any job posted before the configured cutoff date
3. **Deduplicate** — skips jobs whose URL already exists in the sheet
4. **Score** — sends each job to a local `llama3.2` model via Ollama; returns a 0–100 match score, a best-fit profile label, and a 2-sentence rationale
5. **Store** — appends scored jobs to a Google Sheet with status `Not Applied`

## Project Structure

```
.
├── extractors/
│   ├── base.py            # JobPost dataclass + JobExtractor ABC
│   ├── myjobmag.py        # HTML scraper (requests + BeautifulSoup)
│   └── reliefweb.py       # ReliefWeb v2 API client
├── matching/
│   └── local_matcher.py   # Ollama/llama3.2 scoring engine (Pydantic output)
├── storage/
│   └── google_sheets.py   # gspread client — schema init, dedup, append
├── main.py                # Pipeline orchestrator
├── utils.py               # Date parsing utility
├── run_crawler.sh         # One-command launcher (handles Ollama + conda)
├── requirements.txt
└── .env.example
```

## Prerequisites

| Tool | Purpose |
|------|---------|
| Python 3.10+ | Runtime |
| [Ollama](https://ollama.com/download) | Local LLM inference |
| `llama3.2` model | Scoring (pulled via Ollama) |
| Google Cloud service account | Sheets write access |
| ReliefWeb appname | API access (free, requires registration) |

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd swe-python-crawler
pip install -r requirements.txt
```

### 2. Pull the LLM model

```bash
ollama pull llama3.2
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
# ReliefWeb — register at https://apidoc.reliefweb.int/parameters#appname
RELIEFWEB_APPNAME=your-approved-appname

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON=/absolute/path/to/gcp-credentials.json
GOOGLE_SPREADSHEET_ID=your-spreadsheet-id
GOOGLE_WORKSHEET_NAME=Jobs
```

### 4. Set up Google Sheets access

1. Create a service account in Google Cloud Console and download the JSON key
2. Share your target spreadsheet with the service account's `client_email` as **Editor**
3. Set `GOOGLE_SERVICE_ACCOUNT_JSON` in `.env` to the absolute path of the key file

## Running

```bash
# Recommended — handles Ollama startup and conda activation automatically
bash run_crawler.sh

# With a specific conda environment
bash run_crawler.sh my_env_name

# Or directly
python main.py
```

### Output Sheet Schema

| Column | Field | Notes |
|--------|-------|-------|
| A | Job Title | |
| B | Company/Org | |
| C | Source | `MyJobMag` or `ReliefWeb` |
| D | Match Score | 0–100, set by LLM |
| E | Best Profile Match | `IT_Support`, `Credit_Analyst`, `Data_Analyst`, `Software_Engineer`, or `None` |
| F | Match Rationale | 2-sentence LLM explanation |
| G | Link | Unique key used for deduplication |
| H | Date Posted | |
| I | Status | Defaults to `Not Applied` |

## Candidate Profiles Scored Against

| Label | Summary |
|-------|---------|
| `IT_Support` | Linux, VPS, TCP/IP, Apache, Bash/Python automation |
| `Credit_Analyst` | Credit risk, KYC, PAR monitoring, SQL, BigQuery |
| `Data_Analyst` | BigQuery, ETL, Plotly Dash, Power BI, Python/SQL/R |
| `Software_Engineer` | Python, FastAPI, Docker, GCP, ReactJS, Node.js |

A score **≥ 75** is flagged as a High Match in the pipeline summary log.

## Adding a New Job Source

1. Create `extractors/your_source.py` — subclass `JobExtractor`, implement `fetch(limit) -> list[JobPost]`
2. Export it from `extractors/__init__.py`
3. Add it to `fetch_all()` in `main.py`
