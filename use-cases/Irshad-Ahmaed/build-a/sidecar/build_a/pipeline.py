"""Revision apparatus pipeline — end-to-end orchestration.

Connects the SuperDocs client, doc-diff engine, and revision apparatus
generator into a single callable pipeline. Handles sync and async edit
paths, HITL approval flow, and operation budget tracking.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .apparatus import RevisionApparatus, RevisionMetadata
from .client import SuperDocsClient, SuperDocsError
from .differ import DiffResult, DocDiffer

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a full revision pipeline run."""

    session_id: str
    diff: DiffResult
    apparatus_instructions: list[str] = field(default_factory=list)
    edit_response: dict[str, Any] | None = None
    apparatus_responses: list[dict[str, Any]] = field(default_factory=list)
    approval_results: list[dict[str, Any]] = field(default_factory=list)
    ops_used: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class RevisionPipeline:
    """Orchestrates the full revision apparatus flow.

    Connects: SuperDocsClient → edit → diff → apparatus injection.

    Usage:
        async with SuperDocsClient() as client:
            pipeline = RevisionPipeline(client)
            result = await pipeline.run(
                document_html=html,
                session_id="revision-0042",
                edit_instructions="Update section 4.2...",
                metadata=RevisionMetadata(...),
            )
    """

    def __init__(self, client: SuperDocsClient) -> None:
        self.client = client
        self.differ = DocDiffer()
        self.apparatus = RevisionApparatus()

    async def run(
        self,
        document_html: str,
        session_id: str,
        edit_instructions: str,
        metadata: RevisionMetadata,
        *,
        use_async: bool = False,
        approval_mode: str = "auto_accept",
        hitl_approvals: dict[str, bool] | None = None,
    ) -> PipelineResult:
        """Run the full revision flow.

        Steps:
        1. Start session + load document (1 op)
        2. Apply edit instructions (1 op, sync or async)
        3. (Optional) HITL approval for edit
        4. Diff pre-edit vs post-edit HTML
        5. Generate apparatus instructions
        6. Send apparatus instructions (1 op per batch)
        7. (Optional) HITL approval for apparatus

        Args:
            document_html: The prior revision's HTML to load.
            session_id: User-chosen session identifier.
            edit_instructions: Natural language edit instructions.
            metadata: Revision metadata (number, date, changes).
            use_async: Use async_edit + HITL instead of sync edit.
            approval_mode: "auto_accept" or "ask_every_time".
            hitl_approvals: If using HITL, dict mapping chunk_id → approved.
                If None, all proposed changes are approved.
        """
        result = PipelineResult(session_id=session_id, diff=DiffResult(
            changed=[], total_paragraphs_old=0, total_paragraphs_new=0,
        ))

        # Step 1: Start session + load document (1 op)
        try:
            await self.client.start_session(document_html, session_id)
        except SuperDocsError as e:
            result.errors.append(f"Step 1 (load): {e}")
            return result

        # Step 2: Apply edit instructions
        pre_edit_html = document_html  # save for diffing
        if use_async:
            edit_result = await self._apply_edit_async(
                session_id, edit_instructions, approval_mode, hitl_approvals, result
            )
        else:
            edit_result = await self._apply_edit_sync(
                session_id, edit_instructions, result
            )

        if edit_result is None:
            return result

        # Step 3: Get post-edit HTML
        post_edit_html = await self._get_post_edit_html(session_id, edit_result)

        # Step 4: Diff
        result.diff = self.differ.diff(pre_edit_html, post_edit_html)
        logger.info(
            "Diff: %d changed paragraphs out of %d old / %d new",
            len(result.diff.changed),
            result.diff.total_paragraphs_old,
            result.diff.total_paragraphs_new,
        )

        if not result.diff.has_changes:
            logger.info("No changes detected — skipping apparatus injection")
            result.ops_used = self.client.tracker.total_ops
            return result

        # Step 5-6: Generate and send apparatus instructions
        instructions = self.apparatus.generate_combined(result.diff, metadata)
        result.apparatus_instructions = instructions

        for instruction in instructions:
            try:
                resp = await self.client.edit(instruction, session_id)
                result.apparatus_responses.append(
                    resp.model_dump() if hasattr(resp, "model_dump") else {"message": resp.message}
                )
            except SuperDocsError as e:
                result.errors.append(f"Apparatus injection: {e}")

        result.ops_used = self.client.tracker.total_ops
        return result

    async def _apply_edit_sync(
        self,
        session_id: str,
        edit_instructions: str,
        result: PipelineResult,
    ) -> dict[str, Any] | None:
        """Apply edits synchronously (1 op)."""
        try:
            resp = await self.client.edit(edit_instructions, session_id)
            result.edit_response = (
                resp.model_dump() if hasattr(resp, "model_dump") else {"message": resp.message}
            )
            return result.edit_response
        except SuperDocsError as e:
            result.errors.append(f"Step 2 (edit): {e}")
            return None

    async def _apply_edit_async(
        self,
        session_id: str,
        edit_instructions: str,
        approval_mode: str,
        hitl_approvals: dict[str, bool] | None,
        result: PipelineResult,
    ) -> dict[str, Any] | None:
        """Apply edits asynchronously with optional HITL (1 op + approval ops)."""
        try:
            job_resp = await self.client.async_edit(
                edit_instructions, session_id, approval_mode=approval_mode,
            )
        except SuperDocsError as e:
            result.errors.append(f"Step 2 (async_edit): {e}")
            return None

        job_id = job_resp.get("job_id")
        if not job_id:
            result.errors.append("Step 2 (async_edit): no job_id returned")
            return None

        # Poll until complete or awaiting approval
        for _ in range(60):  # max 60 polls (60s)
            await asyncio.sleep(1.0)
            try:
                status = await self.client.poll_job(job_id)
            except SuperDocsError as e:
                result.errors.append(f"Step 2 (poll): {e}")
                return None

            if status.status == "completed":
                return (
                    status.document_changes.model_dump()
                    if status.document_changes
                    else {}
                )

            if status.status == "failed":
                result.errors.append(f"Step 2 (async_edit): {status.error or 'unknown failure'}")
                return None

            if status.status == "awaiting_approval" and status.pending_approvals:
                await self._handle_approvals(
                    session_id, status.pending_approvals, hitl_approvals, result,
                )

        result.errors.append("Step 2 (async_edit): timed out after 60s")
        return None

    async def _handle_approvals(
        self,
        session_id: str,
        pending: list[dict[str, Any]],
        hitl_approvals: dict[str, bool] | None,
        result: PipelineResult,
    ) -> None:
        """Approve or deny proposed changes."""
        for change in pending:
            chunk_id = change.get("chunk_id", "")
            approved = hitl_approvals.get(chunk_id, False) if hitl_approvals is not None else True
            try:
                resp = await self.client.approve(session_id, chunk_id, approved)
                result.approval_results.append(resp)
            except SuperDocsError as e:
                result.errors.append(f"Approval (chunk={chunk_id}): {e}")

    async def _get_post_edit_html(
        self, session_id: str, edit_response: dict[str, Any]
    ) -> str:
        """Get post-edit HTML from edit response or session history."""
        # Try to get from edit response first
        doc_changes = edit_response.get("document_changes") or edit_response
        if isinstance(doc_changes, dict):
            updated = doc_changes.get("updated_html")
        elif hasattr(doc_changes, "updated_html"):
            updated = doc_changes.updated_html
        else:
            updated = None
        if updated:
            return updated

        # Fallback: fetch from session history (0 ops)
        try:
            history = await self.client.get_session_history(session_id)
            if history.document_html:
                return history.document_html
        except SuperDocsError:
            pass

        return ""  # worst case: empty, diff will show everything as added
