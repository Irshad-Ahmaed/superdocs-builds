"""SuperDocs REST API client with operation tracking and error handling."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SUPERDOCS_BASE_URL = "https://api.superdocs.app"


class SuperDocsError(Exception):
    """Base error for SuperDocs API calls."""


class AuthError(SuperDocsError):
    """Invalid or missing API key."""


class RateLimitError(SuperDocsError):
    """Rate limit hit — caller should retry after backoff."""


class SuperDocsTimeoutError(SuperDocsError):
    """Request timed out."""


class ModelFailureError(SuperDocsError):
    """AI model failed — partial results may be available."""


# --- Response models ---


class DocumentChange(BaseModel):
    chunk_id: str | None = None
    updated_html: str | None = None
    proposed_change: Any = None


class ChatResponse(BaseModel):
    message: str | None = None
    document_changes: DocumentChange | None = None
    usage: dict[str, Any] | None = None


class ExportResponse(BaseModel):
    download_url: str | None = None
    format: str | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str  # "running", "awaiting_approval", "completed", "failed"
    document_changes: DocumentChange | None = None
    pending_approvals: list[dict[str, Any]] | None = None
    error: str | None = None


class SessionInfo(BaseModel):
    session_id: str
    created_at: str | None = None
    last_active: str | None = None


class SessionHistory(BaseModel):
    session_id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    document_html: str | None = None


class UploadResponse(BaseModel):
    upload_id: str
    upload_url: str
    expires_at: str | None = None


class DownloadResponse(BaseModel):
    download_url: str
    expires_at: str | None = None


class AttachmentStatus(BaseModel):
    status: str  # "processing", "ready", "failed"
    error: str | None = None


# --- Operation cost tracking ---


@dataclass
class OperationTracker:
    """Tracks API operation costs."""

    total_ops: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def record(self, operation: str, cost: int, details: str = "") -> None:
        self.total_ops += cost
        self.history.append(
            {"operation": operation, "cost": cost, "total": self.total_ops, "details": details}
        )
        logger.info("Op: %s (cost=%d, total=%d) %s", operation, cost, self.total_ops, details)


# --- Client ---


class SuperDocsClient:
    """SuperDocs REST API client.

    Handles auth, session management, the 4-call contract,
    operation cost tracking, retry/backoff, and graceful degradation.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = SUPERDOCS_BASE_URL,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        if not self.api_key:
            raise AuthError("SUPERDOCS_API_KEY not set")
        self.base_url = base_url.rstrip("/")
        self.tracker = OperationTracker()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SuperDocsClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # --- Core 4-call contract ---

    async def start_session(
        self,
        document_html: str,
        session_id: str,
        message: str | None = None,
    ) -> ChatResponse:
        """Start a session and load a document (1 op).

        The first request with a new session_id starts the session and loads
        the document. Pass message=None to load without triggering an instruction.
        """
        payload: dict[str, Any] = {"session_id": session_id, "document_html": document_html}
        if message:
            payload["message"] = message
        resp = await self._post("/v1/chat", payload)
        self.tracker.record("start_session", 1, f"session={session_id}")
        return ChatResponse.model_validate(resp)

    async def edit(self, message: str, session_id: str) -> ChatResponse:
        """Edit via natural language (1 op).

        Reuses the same session_id — server persists the document across turns.
        Returns document_changes.updated_html.
        """
        payload = {"session_id": session_id, "message": message}
        resp = await self._post("/v1/chat", payload)
        self.tracker.record("edit", 1, f"session={session_id}")
        return ChatResponse.model_validate(resp)

    async def approve(
        self,
        session_id: str,
        chunk_id: str,
        approved: bool,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """Approve or deny a proposed change (0 ops)."""
        payload = {"chunk_id": chunk_id, "approved": approved}
        if feedback:
            payload["feedback"] = feedback
        resp = await self._post(f"/v1/chat/{session_id}/approve", payload)
        self.tracker.record("approve", 0, f"chunk={chunk_id} approved={approved}")
        return resp

    async def export(
        self, session_id: str | None = None, format: str = "pdf", html: str | None = None
    ) -> ExportResponse:
        """Export a finished file (0 ops)."""
        if not session_id and not html:
            raise SuperDocsError("export() requires either session_id or html")
        payload: dict[str, Any] = {"format": format}
        if session_id:
            payload["session_id"] = session_id
        if html:
            payload["html"] = html
        resp = await self._post("/v1/documents/export", payload)
        self.tracker.record("export", 0, f"format={format}")
        return ExportResponse.model_validate(resp)

    # --- Additional operations ---

    async def async_edit(
        self,
        message: str,
        session_id: str,
        approval_mode: str = "auto_accept",
    ) -> dict[str, Any]:
        """Start a long-running edit (1 op)."""
        payload = {
            "session_id": session_id,
            "message": message,
            "approval_mode": approval_mode,
        }
        resp = await self._post("/v1/chat/async", payload)
        self.tracker.record("async_edit", 1, f"session={session_id}")
        return resp

    async def poll_job(self, job_id: str) -> JobStatus:
        """Poll an async job (0 ops)."""
        resp = await self._get(f"/v1/jobs/{job_id}")
        self.tracker.record("poll_job", 0, f"job={job_id}")
        return JobStatus.model_validate(resp)

    async def stream(self, session_id: str) -> httpx.Response:
        """SSE stream for real-time progress (0 ops)."""
        resp = await self._client.get(f"/v1/chat/{session_id}/stream")
        resp.raise_for_status()
        self.tracker.record("stream", 0, f"session={session_id}")
        return resp

    async def continue_prompt(self, session_id: str, should_continue: bool) -> dict[str, Any]:
        """Resume or stop a large edit (0 ops)."""
        payload = {"should_continue": should_continue}
        resp = await self._post(f"/v1/chat/{session_id}/continue", payload)
        self.tracker.record("continue_prompt", 0, f"continue={should_continue}")
        return resp

    async def rename_document(self, document_id: str, title: str) -> dict[str, Any]:
        """Rename a document (0 ops). Note: for renaming ONLY — headers/footers via chat."""
        payload = {"title": title}
        resp = await self._patch(f"/v1/documents/{document_id}", payload)
        self.tracker.record("rename_document", 0, f"doc={document_id}")
        return resp

    async def save_document(self, session_id: str, document_id: str) -> dict[str, Any]:
        """Persist a human-edited document (0 ops)."""
        resp = await self._post(
            f"/v1/sessions/{session_id}/documents/{document_id}/save", {}
        )
        self.tracker.record("save_document", 0, f"session={session_id} doc={document_id}")
        return resp

    async def signup(self) -> dict[str, Any]:
        """Agent self-signup — returns a working API key with 500-op free tier (0 ops)."""
        resp = await self._post("/v1/agents/signup", {})
        self.tracker.record("signup", 0)
        return resp

    async def whoami(self) -> dict[str, Any]:
        """Check account status (0 ops)."""
        resp = await self._get("/v1/agents/whoami")
        self.tracker.record("whoami", 0)
        return resp

    async def list_sessions(self) -> list[SessionInfo]:
        """List active sessions (0 ops)."""
        resp = await self._get("/v1/sessions")
        self.tracker.record("list_sessions", 0)
        sessions = resp if isinstance(resp, list) else resp.get("sessions", [])
        return [SessionInfo.model_validate(s) for s in sessions]

    async def get_session_history(
        self, session_id: str, include_document_html: bool = True
    ) -> SessionHistory:
        """Restore session history, optionally with full document HTML (0 ops)."""
        params = {}
        if include_document_html:
            params["include_document_html"] = "true"
        resp = await self._get(f"/v1/sessions/{session_id}/history", params=params)
        self.tracker.record("get_session_history", 0, f"session={session_id}")
        return SessionHistory.model_validate(resp)

    async def request_upload(self) -> UploadResponse:
        """Get a pre-signed upload URL (0 ops)."""
        resp = await self._post("/v1/uploads", {})
        self.tracker.record("request_upload", 0)
        return UploadResponse.model_validate(resp)

    async def process_upload(self, upload_id: str) -> dict[str, Any]:
        """Parse an uploaded file into structured HTML (0 ops)."""
        resp = await self._post(f"/v1/uploads/{upload_id}/process", {})
        self.tracker.record("process_upload", 0, f"upload={upload_id}")
        return resp

    async def request_download(
        self, session_id: str, format: str = "pdf"
    ) -> DownloadResponse:
        """Get a pre-signed download URL (0 ops)."""
        payload = {"session_id": session_id, "format": format}
        resp = await self._post("/v1/downloads", payload)
        self.tracker.record("request_download", 0, f"format={format}")
        return DownloadResponse.model_validate(resp)

    async def export_email(
        self, session_id: str, format: str = "pdf"
    ) -> dict[str, Any]:
        """Request async large export via email (0 ops, 24h SLA)."""
        payload = {"session_id": session_id, "format": format}
        resp = await self._post("/v1/documents/export/email-request", payload)
        self.tracker.record("export_email", 0, f"format={format}")
        return resp

    async def upload_attachment_base64(
        self, session_id: str, file_base64: str, filename: str
    ) -> dict[str, Any]:
        """Upload a reference file as base64 (0 ops)."""
        payload = {
            "session_id": session_id,
            "file_base64": file_base64,
            "filename": filename,
        }
        resp = await self._post("/v1/attachments/upload_base64", payload)
        self.tracker.record("upload_attachment", 0, f"file={filename}")
        return resp

    async def attachment_status(self, session_id: str) -> AttachmentStatus:
        """Poll attachment processing status (0 ops)."""
        resp = await self._get(f"/v1/attachments/status/{session_id}")
        self.tracker.record("attachment_status", 0, f"session={session_id}")
        return AttachmentStatus.model_validate(resp)

    # --- Internal HTTP helpers with retry/backoff ---

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request_with_retry("POST", path, json=payload)

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request_with_retry("GET", path, params=params)

    async def _patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request_with_retry("PATCH", path, json=payload)

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.request(method, path, **kwargs)
                if resp.status_code == 401:
                    raise AuthError("Invalid API key — check SUPERDOCS_API_KEY")
                if resp.status_code == 429:
                    wait = min(2**attempt * 1.0, 30.0)
                    logger.warning(
                        "Rate limited, retrying in %.1fs (attempt %d)", wait, attempt + 1
                    )
                    await asyncio.sleep(wait)
                    last_exc = RateLimitError(f"Rate limited after {max_retries} retries")
                    continue
                resp.raise_for_status()
                return resp.json()
            except AuthError:
                raise
            except httpx.TimeoutException as exc:
                last_exc = SuperDocsTimeoutError(f"Request timed out: {exc}")
                logger.warning("Timeout on %s %s (attempt %d)", method, path, attempt + 1)
                continue
            except httpx.HTTPStatusError as exc:
                last_exc = SuperDocsError(f"HTTP {exc.response.status_code}: {exc.response.text}")
                break
        raise last_exc or SuperDocsError("Request failed")
