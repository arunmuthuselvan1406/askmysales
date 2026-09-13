# AskMySales — Conversational Analytics on Exasol

Built for the **Exasol AI + Data Challenge 2026** — Track: *Build Intelligent Data Experiences*

Ask questions about retail sales data in plain English. AskMySales converts your
question into SQL, runs it live against **Exasol Personal**, shows you a chart,
and proactively flags anomalies it notices in the results — no dashboards to
build, no SQL to write.

## Why Exasol

- **Speed**: every question re-queries the raw data live — no pre-aggregated
  cubes or cached dashboards — because Exasol's in-memory columnar engine
  makes that fast enough to feel instant.
- **Schema introspection**: the app reads `EXA_ALL_COLUMNS` directly so the
  LLM always has an accurate, current view of the table it's querying.
- **Zero data movement**: results are pulled with `export_to_pandas`, so the
  heavy lifting (filtering, aggregation) happens inside Exasol, not in Python.

## Architecture

```
User question
     │
     ▼
Gemini (Google AI API) ── reads schema from EXA_ALL_COLUMNS
     │  generates SQL (SELECT-only, guarded)
     ▼
Exasol Personal ── executes query, returns rows
     │
     ▼
Streamlit UI ── table + auto-chart + anomaly flags
```

## Setup

### 1. Get Exasol Personal running

Pick one:

- **Local (macOS, Windows, WSL/Linux) — starter kit:**
  https://www.exasol.com/developers/
- **Local (macOS, database only):** https://www.exasol.com/personal/
- **AWS / Azure:** https://github.com/exasol/exasol-personal

Once running, find your password with:

```bash
exakit info
```

### 2. Clone this repo and install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# edit .env: fill in EXASOL_PASSWORD and GEMINI_API_KEY
# get a free Gemini key at https://aistudio.google.com/apikey
```

### 4. Load sample data

```bash
python load_data.py
```

This creates a `RETAIL.SALES` table with ~3,000 rows of synthetic sales data
across 5 regions and 4 categories, including a few deliberately injected
anomalies (a refund spike and an outlier order) so the anomaly-detection
feature has something real to catch.

### 5. Run the app

```bash
streamlit run app.py
```

Open the local URL Streamlit prints (usually http://localhost:8501).

## Example questions to try

- "Which region had the highest sales last month?"
- "Show me daily revenue for the East region over the last 30 days"
- "Which product category has the most refunds?"
- "Are there any unusual orders recently?"

## Safety guardrails

- The generated SQL is checked to ensure it's a single `SELECT` statement
  before execution — no `INSERT`/`UPDATE`/`DELETE`/`DROP`/etc. are ever run.
- All queries are capped with a row limit to keep responses fast and the UI
  responsive.

## Project structure

```
app.py            Streamlit app (chat UI, NL->SQL, chart, anomaly detection)
load_data.py      Generates synthetic sales data and loads it into Exasol
requirements.txt  Python dependencies
.env.example      Template for connection/API secrets
```

## Roadmap (if extended beyond the hackathon)

- Swap the direct schema query for Exasol's MCP server so the agent can
  explore multiple tables and join across them.
- Let users save a generated query as a "verified query" others can reuse.
- Row-level access control so the agent only sees what the requesting user
  is permitted to query.
