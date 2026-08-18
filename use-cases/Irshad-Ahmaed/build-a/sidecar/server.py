"""FastAPI backend — bridges the React frontend to the Python sidecar.

Run:
    cd sidecar
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from build_a.apparatus import RevisionApparatus, RevisionMetadata  # noqa: E402
from build_a.client import AuthError, SuperDocsClient, SuperDocsError  # noqa: E402
from build_a.differ import DocDiffer  # noqa: E402
from build_a.headers import ControlledExporter, HeaderFooterStamper  # noqa: E402
from build_a.pipeline import RevisionPipeline  # noqa: E402

load_dotenv()

app = FastAPI(title="SuperDocs Build A", version="0.1.0")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    from starlette.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": str(exc), "type": type(exc).__name__})


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
    session_id: str = ""
    header_text: str
    footer_text: str
    ops_used: int
    verified_header: bool = False
    verified_footer: bool = False


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
    pre_edit_html: str
    post_edit_html: str
    response_text: str
    errors: list[str] = []


@app.post("/api/step/load-edit", response_model=LoadEditResponse)
async def step_load_edit(req: LoadEditRequest) -> LoadEditResponse:
    """Step 1: Load document + apply edit instructions.

    For new sessions: start_session loads doc + applies edit (1 op).
    For existing sessions: edit only (1 op) — server persists doc across turns.
    """
    try:
        async with SuperDocsClient() as client:
            # Check if session already has a document
            pre_html = ""
            session_exists = False
            try:
                history = await client.get_session_history(req.session_id)
                if history.document_html:
                    pre_html = history.document_html
                    session_exists = True
            except SuperDocsError:
                pass

            if session_exists:
                # Existing session — send edit only, omit document_html
                # Server persists the document across turns per API contract
                resp = await client.edit(req.edit_instructions, req.session_id)
            else:
                # New session — load document + apply edit in one call
                resp = await client.start_session(
                    req.document_html, req.session_id, message=req.edit_instructions,
                )

            post_html = ""
            doc_changes = resp.document_changes
            if doc_changes and doc_changes.updated_html:
                post_html = doc_changes.updated_html
            elif resp.response:
                history = await client.get_session_history(req.session_id)
                if history.document_html:
                    post_html = history.document_html

            if not pre_html:
                pre_html = req.document_html

            return LoadEditResponse(
                success=True,
                ops_used=client.tracker.total_ops,
                pre_edit_html=pre_html,
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
    include_stamp: bool = False


class ApparatusResponse(BaseModel):
    success: bool
    ops_used: int
    changes_count: int
    apparatus_instructions: list[str]
    stamp_result: StampResponse | None = None
    diff_entries: list[DiffEntry] = []
    total_paragraphs_old: int = 0
    total_paragraphs_new: int = 0
    errors: list[str] = []


@app.post("/api/step/apparatus", response_model=ApparatusResponse)
async def step_apparatus(req: ApparatusRequest) -> ApparatusResponse:
    """Step 2-3: Diff + generate apparatus + optional stamp in ONE edit call."""
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

        combined_instruction = " ".join(instructions)
        stamp_via_parts = False
        document_id = None

        async with SuperDocsClient() as client:
            # Check if stamp is requested and if parts API is available
            if req.include_stamp:
                try:
                    docs = await client.list_session_documents(req.session_id)
                    if docs and isinstance(docs, list) and len(docs) > 0:
                        doc = docs[0]
                        document_id = (
                            doc.get("document_id")
                            or doc.get("durable_document_id")
                        )
                except SuperDocsError:
                    pass

                if document_id:
                    stamp_via_parts = True
                else:
                    stamper = HeaderFooterStamper.__new__(HeaderFooterStamper)
                    stamp_instruction = stamper.build_combined_instruction(
                        req.revision_number, req.date,
                    )
                    combined_instruction += f" {stamp_instruction}"

            # Send apparatus (and stamp via chat fallback) in one edit call
            try:
                await client.edit(combined_instruction, req.session_id)
                ops = 1
            except SuperDocsError as e:
                return ApparatusResponse(
                    success=False, ops_used=0, changes_count=len(diff.changed),
                    apparatus_instructions=instructions, errors=[str(e)],
                )

            # Apply stamp via parts API if available (0 ops)
            stamp_result = None
            if stamp_via_parts:
                header_html = f"Revision {req.revision_number} — {req.date}"
                footer_html = (
                    "Page <span data-field=\"PAGE\">1</span> of "
                    "<span data-field=\"NUMPAGES\">1</span>"
                )
                try:
                    parts = {
                        "headers": {"0": {"default": f"<p>{header_html}</p>"}},
                        "footers": {"0": {"default": f"<p>{footer_html}</p>"}},
                    }
                    await client.update_document_parts(document_id, parts)
                    stamp_result = StampResponse(
                        session_id=req.session_id,
                        header_text=header_html,
                        footer_text="Page X of Y",
                        ops_used=0,
                        verified_header=True,
                        verified_footer=True,
                    )
                except SuperDocsError as e:
                    logger.warning("Parts API stamp failed: %s", e)
                    stamp_result = StampResponse(
                        session_id=req.session_id,
                        header_text=f"Revision {req.revision_number} — {req.date}",
                        footer_text="Page X of Y",
                        ops_used=0,
                        verified_header=False,
                        verified_footer=False,
                    )
            elif req.include_stamp:
                verified_header = False
                verified_footer = False
                try:
                    history = await client.get_session_history(req.session_id)
                    if history.document_html:
                        import re
                        html_lower = history.document_html.lower()
                        verified_header = f"revision {req.revision_number}".lower() in html_lower
                        verified_footer = bool(re.search(r'page\s+\d+\s+of\s+\d+', html_lower))
                except SuperDocsError:
                    pass
                stamp_result = StampResponse(
                    session_id=req.session_id,
                    header_text=f"Revision {req.revision_number} — {req.date}",
                    footer_text="Page X of Y",
                    ops_used=0,
                    verified_header=verified_header,
                    verified_footer=verified_footer,
                )

            diff_entries = [
                DiffEntry(
                    position=d.position, change_type=d.change_type.value,
                    old_text=d.old_text, new_text=d.new_text,
                )
                for d in diff.changed
            ]
            return ApparatusResponse(
                success=True, ops_used=ops, changes_count=len(diff.changed),
                apparatus_instructions=instructions, stamp_result=stamp_result,
                diff_entries=diff_entries,
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
    """Stamp headers/footers with revision identity, then verify."""
    try:
        async with SuperDocsClient() as client:
            stamper = HeaderFooterStamper(client)
            result = await stamper.stamp(req.session_id, req.revision_number, req.date)

            # Verify: fetch document and check if header/footer were applied
            verified_header = False
            verified_footer = False
            try:
                history = await client.get_session_history(req.session_id)
                if history.document_html:
                    html_lower = history.document_html.lower()
                    verified_header = f"revision {req.revision_number}".lower() in html_lower
                    # Footer: check for "page" + digit pattern (e.g., "Page 1 of 5")
                    import re
                    verified_footer = bool(re.search(r'page\s+\d+\s+of\s+\d+', html_lower))
            except SuperDocsError:
                pass  # verification is best-effort

            return StampResponse(
                header_text=result.header_text,
                footer_text=result.footer_text,
                ops_used=result.ops_used,
                verified_header=verified_header,
                verified_footer=verified_footer,
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
