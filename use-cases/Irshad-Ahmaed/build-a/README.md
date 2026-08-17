# Build A — Revision Bars & Controlled Document Generator

Aviation-grade revision apparatus for controlled documents. After an editing session, the app automatically produces:

1. Change bars in the margin next to every altered paragraph
2. A revision-record table (revision number, date, summary of change)
3. A highlights-of-change summary for crew
4. Headers/footers stamped with revision number + date on every page
5. Exports a verified, controlled PDF

## Architecture

```
React Frontend (Vite + TypeScript)
    ↕ REST API
Python FastAPI Sidecar
    ↕ HTTP
SuperDocs REST API
```

## Setup

```bash
cd sidecar
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest

cd ../frontend
npm install
npm run dev
```

## Operation budget

3–4 ops per revision cycle (load + edit + inject apparatus + header/footer + export is free).

## Branches

- `build-a/skeleton` — project setup, API client, doc-diff engine
- `build-a/revision-apparatus` — change bars, record table, highlights
- `build-a/header-footer-stamps` — revision identity on every page
- `build-a/export-verify` — PDF export + verification harness
