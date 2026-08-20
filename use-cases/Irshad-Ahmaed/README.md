# SuperDocs Builds — Build A & Build B

Built for the SuperDocs hiring round. Two production-grade builds demonstrating the full capability of the SuperDocs platform:

- **Build A — Revision Bars & Controlled Document Generator**: produces aviation-grade revision apparatus (change bars in margins next to altered paragraphs, a 4-column revision-record table, a List of Effective Pages [LEP], and a highlights-of-change summary for flight/maintenance crew) from an editing session on a controlled document. Stamps running headers/footers with revision identity and exports a verified controlled PDF.
- **Build B — Build vs Buy ROI Calculator**: self-serve TCO calculator comparing in-house AI document pipeline costs against SuperDocs. Generates an executive branded PDF report via the export API with numbers matching the on-screen calculator to the dollar (exact number invariance).

## Quick start

```bash
# Clone repository
git clone https://github.com/superdocsapp/superdocs-builds.git
cd superdocs-builds/use-cases/Irshad-Ahmaed

# Set up environment
cp .env.example .env
# Add your SUPERDOCS_API_KEY to .env

# --- Backend Sidecar Server (Serves Build A & Build B) ---
cd build-a/sidecar
python -m venv .venv
# Windows: .venv\Scripts\activate | Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
pytest  # Runs all 41 Build A tests

# Start the unified sidecar server on port 8000
uvicorn server:app --reload --port 8000

# --- Frontend for Build A (Terminal 2) ---
cd ../frontend
npm install
npm run dev  # http://localhost:5173

# --- Frontend for Build B (Terminal 3) ---
cd ../../build-b/frontend
npm install
npm run dev  # http://localhost:5174
```

## Running Tests

```bash
# Run all 61 tests across both builds
pytest build-a/sidecar/tests -q
pytest build-b/sidecar/tests -q
```

## SuperDocs features used

- **Chat Editing (`POST /v1/chat`)**: Session-based document editing with paragraph-level targeting.
- **HITL Approval (`POST /v1/chat/{session_id}/approve`)**: Human-in-the-loop review and staged change confirmation.
- **Direct & Presigned Export (`POST /v1/documents/export`)**: Vector PDF export with 0 operation cost.
- **Session History (`GET /v1/sessions/{session_id}/history`)**: Real-time document state restoration.
- **Operation Budget Optimization**: 
  - Build A uses exactly **2 ops** per revision cycle (1 for load+edit+apparatus, 1 for header/footer stamping).
  - Build B uses **1 op** per report (pre-seeded HTML template allows ~2-4s export time and 0 ops export).

## Financial Model & ROI Clarification (Build B)

- **CapEx (Initial Build)**: Calculated as `Engineering Hours × Loaded Hourly Rate` ($14,000 for 200 hrs @ $70/hr).
- **OpEx (Ongoing)**: Annual maintenance (20% of build) + hosting/infra ($120/mo = $1,440/yr).
- **SuperDocs Plus (Buy)**: $20/mo ($240/yr) with zero upfront CapEx and zero maintenance burden.
- **Payback Period**: **Immediate (Day 1)** — the organization is cash-flow positive from the first month.
- **In-House Break-Even Point**: **42.0 Months** — time required for an internal build to recoup its $14k initial engineering investment against operating savings.

## Use cases

See [use-cases.md](./use-cases.md) for 10 deeply researched real-world use cases across industries and enterprise buyers.

## License

MIT

