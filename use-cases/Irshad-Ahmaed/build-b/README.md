# Build B — Build vs Buy ROI Calculator

Self-serve TCO calculator comparing in-house AI document pipeline costs against SuperDocs.

- Inputs: document volume, engineering hours, loaded hourly cost
- Live recompute on any input change (pure client-side math)
- Downloads a real branded PDF of the user's specific result via the SuperDocs export API

## Architecture

Build B piggybacks on Build A's FastAPI sidecar. The `/api/export-report` endpoint in Build A's `server.py` lazily imports `build_b.calculator` to run the ROI calculation and export.

```
React Frontend (Vite + TypeScript, port 5174)
    ↕ REST API (proxied to localhost:8000)
Python FastAPI Sidecar (Build A's server.py)
    ↕ lazy import
build_b.calculator → SuperDocs REST API
```

## Calculator model

- Build cost = engineering-hours × hourly cost (one-time) + maintenance (20%/yr) + infrastructure ($50-200/mo)
- Buy cost = SuperDocs tier (Free/Plus/Pro) × document volume
- Horizon: 3 years default

## Setup

```bash
cd sidecar
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"

cd ../frontend
npm install
npm run dev
```

## Operation budget

1 op per report generation (PDF export is free). Free tier allows 500 reports.
