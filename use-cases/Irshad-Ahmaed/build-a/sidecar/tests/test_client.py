"""Tests for the SuperDocs client (mocked)."""

import httpx
import pytest
import respx

from build_a.client import AuthError, OperationTracker, SuperDocsClient


def test_tracker_counts_ops() -> None:
    tracker = OperationTracker()
    tracker.record("start_session", 1, "test")
    tracker.record("export", 0, "test")
    assert tracker.total_ops == 1
    assert len(tracker.history) == 2


def test_missing_api_key_raises() -> None:
    import os
    old = os.environ.pop("SUPERDOCS_API_KEY", None)
    try:
        with pytest.raises(AuthError):
            SuperDocsClient(api_key="")
    finally:
        if old:
            os.environ["SUPERDOCS_API_KEY"] = old


@pytest.mark.asyncio
@respx.mock
async def test_start_session_calls_correct_endpoint() -> None:
    respx.post("https://api.superdocs.app/v1/chat").mock(
        return_value=httpx.Response(200, json={"message": "ok", "document_changes": None})
    )
    client = SuperDocsClient(api_key="sk_test_key")
    try:
        result = await client.start_session("<p>Hello</p>", "test-session")
        assert result.message == "ok"
        assert client.tracker.total_ops == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_export_returns_download_url() -> None:
    respx.post("https://api.superdocs.app/v1/documents/export").mock(
        return_value=httpx.Response(
            200, json={"download_url": "https://example.com/file.pdf", "format": "pdf"}
        )
    )
    client = SuperDocsClient(api_key="sk_test_key")
    try:
        result = await client.export(session_id="test-session", format="pdf")
        assert result.download_url == "https://example.com/file.pdf"
        assert client.tracker.total_ops == 0  # export is free
    finally:
        await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_list_sessions() -> None:
    respx.get("https://api.superdocs.app/v1/sessions").mock(
        return_value=httpx.Response(200, json=[{"session_id": "s1"}, {"session_id": "s2"}])
    )
    client = SuperDocsClient(api_key="sk_test_key")
    try:
        sessions = await client.list_sessions()
        assert len(sessions) == 2
        assert sessions[0].session_id == "s1"
    finally:
        await client.close()
