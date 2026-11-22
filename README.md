# AnalystIQ — Enterprise AI Business Analyst

A runnable case-study prototype that converts a business question into SQL, validates it, executes it against a local payment analytics database, and returns segmented results, a chart, query evidence, and caveats.

## What is included

- Natural-language question interface with sample prompts
- SQL generation: optional OpenAI-assisted generation, with a deterministic local SQL planner fallback (no API key needed)
- SQL safety validation: single `SELECT` only, approved tables only, forbidden mutation statements rejected
- Read-only SQLite execution with a SQLite authorizer as a second safety layer
- Transactions, merchants, and banks datasets (5,010 transaction rows; 10 deliberately duplicated extra rows)
- Segmented analysis, result table, chart, executed SQL, evidence metadata, caveats
- Data-quality checks for duplicate transaction IDs and missing critical fields
- Failed-check demo that verifies an unsafe `DELETE` statement is rejected without execution

## Requirements

- Python 3.10+
- pip

## Run on Windows

Open a terminal in this project folder and run:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000

## Run on macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000

## Optional LLM SQL generation

The app runs without an API key. To enable LLM-assisted SQL generation, set environment variables before starting the server:

Windows PowerShell:
```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_MODEL="gpt-4o-mini"
uvicorn app.main:app --reload
```

macOS/Linux:
```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-4o-mini"
uvicorn app.main:app --reload
```

If the model is unavailable or returns invalid SQL, the app falls back to the local planner. Keep API keys private; do not commit them to GitHub.

## Suggested demo flow

1. Ask: `Compare payment success rate by bank`
2. Show segmented bank results and chart.
3. Open the SQL evidence and point out it was executed against the SQLite dataset.
4. Ask: `Show monthly transaction volume trend`
5. Click **Run failed-check demo** and show unsafe SQL is rejected.
6. Explain the duplicate extra rows quality warning and how it can inflate aggregate metrics.

## API endpoints

- `GET /api/health` — app/database and quality status
- `GET /api/datasets` — dataset names and schema
- `GET /api/quality` — quality check report
- `POST /api/ask` — natural-language question; JSON body `{ "question": "..." }`
- `POST /api/demo/failure` — demonstrate unsafe SQL rejection

## Dataset and caveats

All records are synthetic and intended only for demonstration. The transaction table intentionally contains 10 duplicate extra rows. The app flags duplicates rather than silently removing them. Results are descriptive and should not be interpreted as real financial performance.

## GitHub submission checklist

- Do not commit `.env` or API keys.
- Push the project folder to a public repository.
- Include this README and the demo video link if you make one.
- Verify the public repository URL opens without login.
