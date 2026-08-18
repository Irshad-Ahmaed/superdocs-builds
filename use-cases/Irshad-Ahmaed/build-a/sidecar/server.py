"""FastAPI backend — bridges the React frontend to the Python sidecar.

Run:
    cd sidecar
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import base64
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from build_a.apparatus import RevisionApparatus, RevisionMetadata
from build_a.client import AuthError, SuperDocsClient, SuperDocsError
from build_a.differ import DocDiffer
from build_a.headers import ControlledExporter, HeaderFooterStamper
from build_a.pipeline import RevisionPipeline

load_dotenv()

app = FastAPI(title="SuperDocs Build A", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
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


class DiffEntry(BaseModel):
    position: int
    change_type: str
    old_text: str
    new_text: str


class PipelineResponse(BaseModel):
    success: bool
    ops_used: int
    changes_count: int
    apparatus_instructions: list[str]
    errors: list[str]
    diff_entries: list[DiffEntry] = []
    total_paragraphs_old: int = 0
    total_paragraphs_new: int = 0
    pre_edit_html: str = ""
    post_edit_html: str = ""


class StampRequest(BaseModel):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    revision_number: str
    date: str


class StampResponse(BaseModel):
    header_text: str
    footer_text: str
    ops_used: int


class ExportRequest(BaseModel):
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    output_path: str = Field(default="output.pdf", pattern=r"^[a-zA-Z0-9_\-./]+$")


class ExportResponse(BaseModel):
    pdf_path: str
    download_url: str | None = None


class AccountInfo(BaseModel):
    info: dict
    sessions: list[dict]


# ── Step-by-step endpoints ────────────────────────────────────────────────


class LoadEditRequest(BaseModel):
    session_id: str
    document_html: str
    edit_instructions: str


class LoadEditResponse(BaseModel):
    success: bool
    ops_used: int
    post_edit_html: str
    response_text: str
    errors: list[str] = []


@app.post("/api/step/load-edit", response_model=LoadEditResponse)
async def step_load_edit(req: LoadEditRequest) -> LoadEditResponse:
    """Step 1: Load document + apply edit instructions (1 API call, 1 op)."""
    try:
        async with SuperDocsClient() as client:
            resp = await client.start_session(
                req.document_html, req.session_id, message=req.edit_instructions,
            )
            post_html = ""
            doc_changes = resp.document_changes
            if doc_changes and doc_changes.updated_html:
                post_html = doc_changes.updated_html
            elif resp.response:
                # Try to extract from response if no document_changes
                history = await client.get_session_history(req.session_id)
                if history.document_html:
                    post_html = history.document_html
            return LoadEditResponse(
                success=True,
                ops_used=client.tracker.total_ops,
                post_edit_html=post_html,
                response_text=resp.response or "",
            )
    except SuperDocsError as e:
        return LoadEditResponse(
            success=False, ops_used=0, post_edit_html="", response_text="", errors=[str(e)],
        )


class ApparatusRequest(BaseModel):
    session_id: str
    pre_edit_html: str
    post_edit_html: str
    revision_number: str
    date: str
    changes: list[str] = []
    highlights_summary: str = ""


class ApparatusResponse(BaseModel):
    success: bool
    ops_used: int
    changes_count: int
    apparatus_instructions: list[str]
    diff_entries: list[DiffEntry] = []
    total_paragraphs_old: int = 0
    total_paragraphs_new: int = 0
    errors: list[str] = []


@app.post("/api/step/apparatus", response_model=ApparatusResponse)
async def step_apparatus(req: ApparatusRequest) -> ApparatusResponse:
    """Step 2-3: Diff + generate and send apparatus instructions."""
    try:
        differ = DocDiffer()
        diff = differ.diff(req.pre_edit_html, req.post_edit_html)

        if not diff.has_changes:
            return ApparatusResponse(
                success=True, ops_used=0, changes_count=0,
                apparatus_instructions=[], total_paragraphs_old=diff.total_paragraphs_old,
                total_paragraphs_new=diff.total_paragraphs_new,
            )

        metadata = RevisionMetadata(
            revision_number=req.revision_number,
            date=req.date,
            changes=req.changes,
            highlights_summary=req.highlights_summary,
        )
        apparatus = RevisionApparatus()
        instructions = apparatus.generate_combined(diff, metadata)

        async with SuperDocsClient() as client:
            apparatus_ops = 0
            for instruction in instructions:
                try:
                    await client.edit(instruction, req.session_id)
                    apparatus_ops += 1
                except SuperDocsError as e:
                    return ApparatusResponse(
                        success=False, ops_used=apparatus_ops, changes_count=len(diff.changed),
                        apparatus_instructions=instructions, errors=[str(e)],
                    )

            diff_entries = [
                DiffEntry(
                    position=d.position, change_type=d.change_type.value,
                    old_text=d.old_text, new_text=d.new_text,
                )
                for d in diff.changed
            ]
            return ApparatusResponse(
                success=True, ops_used=apparatus_ops, changes_count=len(diff.changed),
                apparatus_instructions=instructions, diff_entries=diff_entries,
                total_paragraphs_old=diff.total_paragraphs_old,
                total_paragraphs_new=diff.total_paragraphs_new,
            )
    except Exception as e:
        return ApparatusResponse(
            success=False, ops_used=0, changes_count=0,
            apparatus_instructions=[], errors=[str(e)],
        )


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
        raise HTTPException(status_code=401, detail=str(e)) from e
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


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
            diff_entries = [
                DiffEntry(
                    position=d.position,
                    change_type=d.change_type.value,
                    old_text=d.old_text,
                    new_text=d.new_text,
                )
                for d in result.diff.changed
            ]
            return PipelineResponse(
                success=result.success,
                ops_used=result.ops_used,
                changes_count=len(result.diff.changed),
                apparatus_instructions=result.apparatus_instructions,
                errors=result.errors,
                diff_entries=diff_entries,
                total_paragraphs_old=result.diff.total_paragraphs_old,
                total_paragraphs_new=result.diff.total_paragraphs_new,
                pre_edit_html=req.document_html,
                post_edit_html=result.post_edit_html,
            )
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


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
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/export", response_model=ExportResponse)
async def export_pdf(req: ExportRequest) -> ExportResponse:
    """Export a controlled PDF."""
    try:
        safe_path = Path(req.output_path).resolve()
        if not safe_path.is_relative_to(Path.cwd()):
            raise HTTPException(status_code=400, detail="Path outside working directory")
        async with SuperDocsClient() as client:
            exporter = ControlledExporter(client)
            result = await exporter.export_pdf(req.session_id, safe_path)
            return ExportResponse(
                pdf_path=str(result.pdf_path),
                download_url=result.download_url,
            )
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


class DiffRequest(BaseModel):
    old_html: str = ""
    new_html: str = ""


@app.post("/api/diff")
async def diff_documents(body: DiffRequest) -> dict:
    """Diff two HTML documents (no API cost — local only)."""
    differ = DocDiffer()
    diff = differ.diff(body.old_html, body.new_html)
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
    session_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    volume: int = Field(ge=1, le=1_000_000)
    hours: float = Field(ge=0, le=100_000)
    hourly_cost: float = Field(ge=0, le=10_000)
    infrastructure_monthly: float = Field(default=100.0, ge=0, le=50_000)
    horizon_years: int = Field(default=3, ge=1, le=10)


class ExportReportResponse(BaseModel):
    pdf_path: str
    html_length: int
    html: str
    pdf_data_url: str


@app.post("/api/export-report", response_model=ExportReportResponse)
async def export_report(req: ExportReportRequest) -> ExportReportResponse:
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
            reports_dir = Path("reports").resolve()
            reports_dir.mkdir(exist_ok=True)
            pdf_path = reports_dir / f"{req.session_id}.pdf"
            path = await gen.export_report(req.session_id, pdf_path)
            pdf_bytes = path.read_bytes()
            pdf_b64 = base64.b64encode(pdf_bytes).decode()
            return ExportReportResponse(
                pdf_path=str(path),
                html_length=len(html),
                html=html,
                pdf_data_url=f"data:application/pdf;base64,{pdf_b64}",
            )
    except SuperDocsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
