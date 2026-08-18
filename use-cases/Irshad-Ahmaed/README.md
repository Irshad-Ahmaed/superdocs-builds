# SuperDocs Builds — Build A & Build B

Built for the SuperDocs hiring round. Two builds demonstrating SuperDocs capabilities:

- **Build A — Revision Bars & Controlled Document Generator**: produces aviation-grade revision apparatus (change bars, revision-record table, highlights-of-change summary) from an editing session on a controlled document. Stamps headers/footers with revision identity, exports a verified PDF.
- **Build B — Build vs Buy ROI Calculator**: self-serve TCO calculator comparing in-house AI document pipeline costs against SuperDocs. Generates a real branded PDF report via the export API with numbers matching the on-screen calculator.

## Quick start

```bash
# Clone (after forking)
git clone git@github.com:<your-handle>/superdocs-builds.git
cd superdocs-builds/use-cases/<your-handle>

# Set up API key
cp .env.example .env
# Edit .env and add your SuperDocs API key

# Python sidecar (Build A — also serves Build B's /api/export-report)
cd build-a/sidecar
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -e ".[dev]"
pytest  # run tests

# Start the sidecar server
uvicorn server:app --reload --port 8000

# React frontend (Build A — separate terminal)
cd ../frontend
npm install
npm run dev  # http://localhost:5173

# Build B sidecar setup
cd ../../build-b/sidecar
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
pytest  # run Build B tests

# React frontend (Build B — separate terminal)
cd ../frontend
npm install
npm run dev  # http://localhost:5174
```

## SuperDocs features used

- Chat editing (`POST /v1/chat`) — session-based document editing
- HITL approval (`POST /v1/chat/{session_id}/approve`) — human-in-the-loop review
- Export (`POST /v1/documents/export`) — controlled PDF export
- Session history (`GET /v1/sessions/{session_id}/history`) — restore session state
- Operation cost tracking — stays within free tier (500 ops/month)

## Assumptions & limitations

- Calculator TCO model: maintenance = 20% of build hours/year, infrastructure = $50-200/mo, horizon = 3 years
- SuperDocs pricing: Free ($0/mo, 500 ops), Plus ($20/mo, 2000 ops), Pro ($99/mo, 10000 ops)
- Revision apparatus is generated via chat instructions — not a custom PDF editor
- Effective pages are computed from the exported PDF, not from the diff

## Use cases

See [use-cases.md](./use-cases.md) for 10 real-world use cases across industries and personas.

## License

MIT
