"""Header/footer stamping and controlled PDF export for Build A.

Uses PATCH /v1/documents/{document_id} with parts payload for headers/footers.
Dynamic page fields use <span data-field="PAGE|NUMPAGES"> for auto-numbering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from .client import SuperDocsClient, SuperDocsError

logger = logging.getLogger(__name__)


@dataclass
class StampResult:
    """Result of a header/footer stamp operation."""

    session_id: str
    header_text: str
    footer_text: str
    ops_used: int
    verified_header: bool = False
    verified_footer: bool = False


class HeaderFooterStamper:
    """Stamps revision identity on headers/footers via the document parts API.

    Uses PATCH /v1/documents/{document_id} with parts payload.
    Headers/footers are set as HTML with <span data-field="PAGE|NUMPAGES">
    for dynamic page numbering.
    """

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client

    def build_header_instruction(self, revision_number: str, date: str) -> str:
        """Build the chat instruction to set the header (fallback)."""
        return (
            f"Set the header on every page to: "
            f"'Revision {revision_number} — {date}'"
        )

    def build_footer_instruction(self) -> str:
        """Build the chat instruction to set page-numbered footer (fallback)."""
        return (
            "Set the footer on every page to show page numbers in the format 'Page X of Y'. "
            "Use a consistent font and size matching the header."
        )

    def build_combined_instruction(
        self, revision_number: str, date: str
    ) -> str:
        """Combine header + footer + page numbering into a single chat turn."""
        header = self.build_header_instruction(revision_number, date)
        footer = self.build_footer_instruction()
        return (
            f"{header}. {footer}. "
            f"Also enable decimal page numbering starting from 1 for all sections."
        )

    async def stamp(
        self,
        session_id: str,
        revision_number: str,
        date: str,
    ) -> StampResult:
        """Stamp headers/footers using the document parts API (0 ops).

        Uses PATCH /v1/documents/{document_id} with parts payload.
        Falls back to chat instruction if document_id is unavailable.
        """
        header_text = f"Revision {revision_number} — {date}"
        footer_html = (
            "Page <span data-field=\"PAGE\">1</span> of "
            "<span data-field=\"NUMPAGES\">1</span>"
        )
        header_html = header_text

        # Try to get document_id from session
        document_id = None
        try:
            docs = await self.client.list_session_documents(session_id)
            if docs and isinstance(docs, list) and len(docs) > 0:
                document_id = docs[0].get("document_id") or docs[0].get("durable_document_id")
        except SuperDocsError:
            pass

        if document_id:
            # Use the proper parts API (0 ops, direct document mutation)
            parts = {
                "headers": {
                    "0": {"default": f"<p>{header_html}</p>"},
                },
                "footers": {
                    "0": {"default": f"<p>{footer_html}</p>"},
                },
            }
            try:
                await self.client.update_document_parts(document_id, parts)
                return StampResult(
                    session_id=session_id,
                    header_text=header_text,
                    footer_text="Page X of Y",
                    ops_used=0,
                )
            except SuperDocsError as e:
                logger.warning("Parts API failed, falling back to chat: %s", e)

        # Fallback: chat instruction (1 op)
        instruction = self.build_combined_instruction(revision_number, date)
        await self.client.edit(message=instruction, session_id=session_id)
        return StampResult(
            session_id=session_id,
            header_text=header_text,
            footer_text="Page X of Y",
            ops_used=1,
        )


@dataclass
class ExportResult:
    """Result of a PDF export operation."""

    session_id: str
    pdf_path: Path
    download_url: str | None = None


class ControlledExporter:
    """Exports controlled PDFs and saves them to disk."""

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client

    async def export_pdf(
        self,
        session_id: str,
        output_path: Path,
    ) -> ExportResult:
        """Export a PDF via SuperDocs API and save to disk (0 ops).

        Tries direct export first, falls back to pre-signed URL.
        """
        try:
            result = await self.client.export(session_id=session_id, format="pdf")
            if result.download_url:
                await self._download(result.download_url, output_path)
                return ExportResult(
                    session_id=session_id,
                    pdf_path=output_path,
                    download_url=result.download_url,
                )
        except SuperDocsError as exc:
            logger.warning("Direct export failed, trying fallback: %s", exc)

        # Fallback: pre-signed download URL
        dl = await self.client.request_download(session_id, format="pdf")
        await self._download(dl.download_url, output_path)
        return ExportResult(
            session_id=session_id,
            pdf_path=output_path,
            download_url=dl.download_url,
        )

    async def _download(self, url: str, dest: Path) -> None:
        """Download a file from a URL and write to disk.

        Uses a separate httpx client without auth headers — pre-signed URLs
        must not carry Bearer tokens.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
