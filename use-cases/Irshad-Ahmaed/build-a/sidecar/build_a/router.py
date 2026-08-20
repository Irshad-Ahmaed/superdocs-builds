"""FastAPI APIRouter for Build A: Aviation FCOM Revision Apparatus."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .apparatus import RevisionApparatus, RevisionMetadata
from .client import AuthError, SuperDocsClient, SuperDocsError
from .differ import DocDiffer
from .headers import ControlledExporter, HeaderFooterStamper
from .pipeline import RevisionPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Build A: Aviation FCOM"])


class PipelineRequest(BaseModel):
    session_id: str
    document_html: str
    edit_instructions: str
    revision_number: str
    date: str
    author: str
    reason: str
    manual_type: str = "FCOM"
    operator_code: str = "AAL"
    affected_sections: Optional[List[str]] = None


class DiffRequest(BaseModel):
    old_html: str
    new_html: str


class ExportRequest(BaseModel):
    session_id: str
    revision_number: str
    manual_type: str = "FCOM"
    operator_code: str = "AAL"
    document_html: Optional[str] = None


class Step1Request(BaseModel):
    document_html: str
    revision_number: str
    date: str
    author: str
    reason: str
    manual_type: str = "FCOM"
    operator_code: str = "AAL"
    affected_sections: Optional[List[str]] = None


class Step2Request(BaseModel):
    session_id: str
    edit_instructions: str


class Step3Request(BaseModel):
    session_id: str
    revision_number: str
    date: str
    author: str
    reason: str
    manual_type: str = "FCOM"
    operator_code: str = "AAL"
    affected_sections: Optional[List[str]] = None


@router.post("/run")
async def run_pipeline(req: PipelineRequest) -> Dict[str, Any]:
    """Execute the complete revision pipeline in one atomic pass."""
    metadata = RevisionMetadata(
        revision_number=req.revision_number,
        date=req.date,
        author=req.author,
        reason=req.reason,
        manual_type=req.manual_type,
        operator_code=req.operator_code,
        affected_sections=req.affected_sections,
    )
    async with SuperDocsClient() as client:
        pipeline = RevisionPipeline(client)
        result = await pipeline.run(
            session_id=req.session_id,
            document_html=req.document_html,
            edit_instructions=req.edit_instructions,
            metadata=metadata,
        )
    return {
        "success": result.success,
        "session_id": result.session_id,
        "operations_used": result.operations_used,
        "diff_summary": {
            "total_changes": result.diff.total_changes,
            "modified": len(result.diff.modified),
            "added": len(result.diff.added),
            "removed": len(result.diff.removed),
        } if result.diff else None,
        "apparatus_applied": result.apparatus_applied,
        "headers_stamped": result.headers_stamped,
        "export_pdf_path": str(result.export_pdf_path) if result.export_pdf_path else None,
        "error": result.error,
    }


@router.post("/step/1-load")
async def step1_load_and_prep(req: Step1Request) -> Dict[str, Any]:
    """Step 1: Parse original document and start SuperDocs session."""
    differ = DocDiffer()
    sections = differ._extract_sections(req.document_html)
    section_names = [s.name for s in sections]

    metadata = RevisionMetadata(
        revision_number=req.revision_number,
        date=req.date,
        author=req.author,
        reason=req.reason,
        manual_type=req.manual_type,
        operator_code=req.operator_code,
        affected_sections=req.affected_sections or section_names,
    )

    async with SuperDocsClient() as client:
        session = await client.start_session(
            name=f"{metadata.manual_type}_{metadata.revision_number}",
            document=req.document_html,
        )
        session_id = session.get("id") or session.get("session_id") or "session_unknown"

    return {
        "session_id": session_id,
        "sections_detected": section_names,
        "metadata": {
            "revision_number": metadata.revision_number,
            "date": metadata.date,
            "author": metadata.author,
            "reason": metadata.reason,
            "manual_type": metadata.manual_type,
            "operator_code": metadata.operator_code,
        },
    }


@router.post("/step/2-edit")
async def step2_apply_edits(req: Step2Request) -> Dict[str, Any]:
    """Step 2: Send edit instructions to SuperDocs session."""
    async with SuperDocsClient() as client:
        result = await client.send_chat(
            session_id=req.session_id,
            content=req.edit_instructions,
        )
        updated_doc = await client.get_document(req.session_id)

    return {
        "session_id": req.session_id,
        "chat_response": result.get("content", ""),
        "document_preview": updated_doc[:1000] if updated_doc else "",
        "document_length": len(updated_doc) if updated_doc else 0,
    }


@router.post("/step/3-apparatus")
async def step3_generate_apparatus(req: Step3Request) -> Dict[str, Any]:
    """Step 3: Diff edited against original and insert revision apparatus."""
    metadata = RevisionMetadata(
        revision_number=req.revision_number,
        date=req.date,
        author=req.author,
        reason=req.reason,
        manual_type=req.manual_type,
        operator_code=req.operator_code,
        affected_sections=req.affected_sections,
    )

    async with SuperDocsClient() as client:
        current_html = await client.get_document(req.session_id)
        if not current_html:
            raise HTTPException(status_code=404, detail="Session document not found")

        differ = DocDiffer()
        diff = differ.diff(current_html, current_html)
        apparatus = RevisionApparatus(metadata)
        instructions = apparatus.build_combined_instruction(diff, current_html)

        for instruction in instructions:
            await client.send_chat(req.session_id, instruction)

    return {
        "session_id": req.session_id,
        "apparatus_applied": True,
        "changes_detected": diff.total_changes,
        "sections_changed": diff.changed_sections,
    }


@router.post("/export")
async def export_pdf(req: ExportRequest) -> Dict[str, Any]:
    """Export the current document session to PDF with verified headers/footers."""
    async with SuperDocsClient() as client:
        exporter = ControlledExporter(client)
        pdf_path = await exporter.export_controlled_pdf(
            session_id=req.session_id,
            revision_number=req.revision_number,
            manual_type=req.manual_type,
            operator_code=req.operator_code,
            document_html=req.document_html,
        )
        pdf_bytes = pdf_path.read_bytes() if pdf_path.exists() else b""
        pdf_b64 = base64.b64encode(pdf_bytes).decode() if pdf_bytes else ""
        pdf_data_url = f"data:application/pdf;base64,{pdf_b64}" if pdf_b64 else ""

    return {
        "success": True,
        "pdf_path": str(pdf_path),
        "pdf_base64": pdf_b64,
        "pdf_data_url": pdf_data_url,
    }


@router.post("/diff")
async def compute_diff(req: DiffRequest) -> Dict[str, Any]:
    """Preview diff between two HTML strings without modifying session."""
    from .differ import ChangeType
    differ = DocDiffer()
    diff = differ.diff(req.old_html, req.new_html)
    return {
        "total_changes": len(diff.changed),
        "has_changes": diff.has_changes,
        "modified_count": len([d for d in diff.changed if d.change_type == ChangeType.MODIFIED]),
        "added_count": len([d for d in diff.changed if d.change_type == ChangeType.ADDED]),
        "removed_count": len([d for d in diff.changed if d.change_type == ChangeType.REMOVED]),
        "changes": [
            {
                "position": d.position,
                "type": d.change_type.value,
                "old_text": d.old_text[:200],
                "new_text": d.new_text[:200],
            }
            for d in diff.changed
        ],
    }
