"""Header/footer stamping and controlled PDF export for Build A.

Sends chat instructions to stamp revision identity on every page,
then exports the controlled PDF and saves it to disk.
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


class HeaderFooterStamper:
    """Stamps revision identity on headers/footers via chat instructions.

    Headers and footers are first-class document parts on SuperDocs —
    edited by chat instruction, the same flow as body edits.
    """

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client

    def build_header_instruction(self, revision_number: str, date: str) -> str:
        """Build the chat instruction to set the header."""
        return (
            f"Set the header on every page to: "
            f"'Revision {revision_number} — {date}'"
        )

    def build_footer_instruction(self) -> str:
        """Build the chat instruction to set page-numbered footer."""
        return "Set the footer on every page to include page numbers."

    def build_combined_instruction(
        self, revision_number: str, date: str
    ) -> str:
        """Combine header + footer instructions into a single chat turn."""
        header = self.build_header_instruction(revision_number, date)
        footer = self.build_footer_instruction()
        return f"{header}. {footer}."

    async def stamp(
        self,
        session_id: str,
        revision_number: str,
        date: str,
    ) -> StampResult:
        """Send the combined header/footer instruction (1 op).

        This stamps revision identity on every page via a single chat turn.
        """
        instruction = self.build_combined_instruction(revision_number, date)
        await self.client.edit(message=instruction, session_id=session_id)
        return StampResult(
            session_id=session_id,
            header_text=f"Revision {revision_number} — {date}",
            footer_text="Page numbers",
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
