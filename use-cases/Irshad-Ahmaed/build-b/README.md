# Build B — Build vs Buy ROI Calculator

Self-serve TCO calculator comparing in-house AI document pipeline costs against SuperDocs.

- Inputs: document volume, engineering hours, loaded hourly cost
- Live recompute on any input change (pure client-side math)
- Downloads a real branded PDF of the user's specific result via the SuperDocs export API

## Architecture

```
React Frontend (Vite + TypeScript)
    ↕ REST API
Python FastAPI Sidecar
    ↕ HTTP
SuperDocs REST API
```

## Calculator model

- Build cost = engineering-hours × hourly cost (one-time) + maintenance (20%/yr) + infrastructure ($50-200/mo)
- Buy cost = SuperDocs tier (Free/Plus/Pro) × document volume
- Horizon: 3 years default

## Setup

```bash
cd sidecar
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

cd ../frontend
npm install
npm run dev
```

## Operation budget

1 op per PDF download. Free tier allows 500 downloads.
