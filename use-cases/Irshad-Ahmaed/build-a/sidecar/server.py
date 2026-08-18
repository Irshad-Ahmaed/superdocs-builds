"""FastAPI backend — bridges the React frontend to the Python sidecar.

Run:
    cd sidecar
    set SUPERDOCS_API_KEY=your_superdocs_api_key_placeholder_
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from build_a.apparatus import RevisionMetadata
from build_a.client import AuthError, SuperDocsClient, SuperDocsError
from build_a.differ import DocDiffer
from build_a.headers import ControlledExporter, HeaderFooterStamper
from build_a.pipeline import RevisionPipeline

load_dotenv()

app = FastAPI(title="SuperDocs Build A", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / Response models ─────────────────────────────────────────────


class PipelineRequest(BaseModel):
    session_id: str
    document_html: str
    edit_instructions: str
    revision_number: str
    date: str
    changes: list[str] = []
    highlights_summary: str = ""


class PipelineResponse(BaseModel):
    success: bool
    ops_used: int
    changes_count: int
    apparatus_instructions: list[str]
    errors: list[str]


class StampRequest(BaseModel):
    session_id: str
    revision_number: str
    date: str


class StampResponse(BaseModel):
    header_text: str
    footer_text: str
    ops_used: int


class ExportRequest(BaseModel):
    session_id: str
    output_path: str = "output.pdf"


class ExportResponse(BaseModel):
    pdf_path: str
    download_url: str | None = None


class AccountInfo(BaseModel):
    info: dict
    sessions: list[dict]


# ── Endpoints ─────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/account", response_model=AccountInfo)
async def get_account() -> AccountInfo:
    """Check account status and list sessions."""
    try:
        async with SuperDocsClient() as client:
            info = await client.whoami()
            sessions = await client.list_sessions()
            return AccountInfo(
                info=info if isinstance(info, dict) else {"raw": str(info)},
                sessions=[s.model_dump() for s in sessions],
            )
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/pipeline", response_model=PipelineResponse)
async def run_pipeline(req: PipelineRequest) -> PipelineResponse:
    """Run the full revision pipeline: load → edit → diff → apparatus."""
    try:
        async with SuperDocsClient() as client:
            metadata = RevisionMetadata(
                revision_number=req.revision_number,
                date=req.date,
                changes=req.changes,
                highlights_summary=req.highlights_summary,
            )
            pipeline = RevisionPipeline(client)
            result = await pipeline.run(
                document_html=req.document_html,
                session_id=req.session_id,
                edit_instructions=req.edit_instructions,
                metadata=metadata,
            )
            return PipelineResponse(
                success=result.success,
                ops_used=result.ops_used,
                changes_count=len(result.diff.changed),
                apparatus_instructions=result.apparatus_instructions,
                errors=result.errors,
            )
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/stamp", response_model=StampResponse)
async def stamp_headers(req: StampRequest) -> StampResponse:
    """Stamp headers/footers with revision identity."""
    try:
        async with SuperDocsClient() as client:
            stamper = HeaderFooterStamper(client)
            result = await stamper.stamp(req.session_id, req.revision_number, req.date)
            return StampResponse(
                header_text=result.header_text,
                footer_text=result.footer_text,
                ops_used=result.ops_used,
            )
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/export", response_model=ExportResponse)
async def export_pdf(req: ExportRequest) -> ExportResponse:
    """Export a controlled PDF."""
    try:
        async with SuperDocsClient() as client:
            exporter = ControlledExporter(client)
            result = await exporter.export_pdf(req.session_id, Path(req.output_path))
            return ExportResponse(
                pdf_path=str(result.pdf_path),
                download_url=result.download_url,
            )
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/diff")
async def diff_documents(body: dict) -> dict:
    """Diff two HTML documents (no API cost — local only)."""
    old_html = body.get("old_html", "")
    new_html = body.get("new_html", "")
    differ = DocDiffer()
    diff = differ.diff(old_html, new_html)
    return {
        "has_changes": diff.has_changes,
        "changes_count": len(diff.changed),
        "total_old": diff.total_paragraphs_old,
        "total_new": diff.total_paragraphs_new,
        "changed": [
            {
                "position": d.position,
                "type": d.change_type.value,
                "old_text": d.old_text[:200],
                "new_text": d.new_text[:200],
            }
            for d in diff.changed
        ],
    }


# ── Build B: ROI Calculator Export ────────────────────────────────────────


class ExportReportRequest(BaseModel):
    session_id: str
    volume: int
    hours: float
    hourly_cost: float
    infrastructure_monthly: float = 100.0
    horizon_years: int = 3


@app.post("/api/export-report")
async def export_report(req: ExportReportRequest) -> dict:
    """Generate ROI report via SuperDocs and export as PDF."""
    try:
        from build_b.calculator import CalculatorInputs, ReportGenerator, compute_tco

        inputs = CalculatorInputs(
            volume=req.volume,
            hours=req.hours,
            hourly_cost=req.hourly_cost,
            infrastructure_monthly=req.infrastructure_monthly,
            horizon_years=req.horizon_years,
        )
        results = compute_tco(inputs)

        async with SuperDocsClient() as client:
            gen = ReportGenerator(client)
            html = await gen.generate_report(req.session_id, results)
            path = await gen.export_report(req.session_id, Path(f"reports/{req.session_id}.pdf"))
            return {"pdf_path": str(path), "html_length": len(html)}
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
