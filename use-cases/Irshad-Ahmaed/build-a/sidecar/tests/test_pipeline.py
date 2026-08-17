"""Integration tests for RevisionPipeline (mocked API)."""

import httpx
import pytest
import respx

from build_a.apparatus import RevisionMetadata
from build_a.client import SuperDocsClient
from build_a.pipeline import RevisionPipeline

SAMPLE_HTML = """<html><body>
<p id="p1">First paragraph.</p>
<p id="p2">Second paragraph.</p>
<p id="p3">Third paragraph.</p>
</body></html>"""

EDITED_HTML = """<html><body>
<p id="p1">First paragraph.</p>
<p id="p2">Second paragraph has been updated.</p>
<p id="p3">Third paragraph.</p>
<p id="p4">Brand new paragraph added.</p>
</body></html>"""


def _setup_mocks() -> None:
    """Configure respx mocks for the full flow."""
    base = "https://api.superdocs.app"

    # Step 1: start session
    respx.post(f"{base}/v1/chat").mock(
        return_value=httpx.Response(200, json={
            "message": "Document loaded",
            "document_changes": None,
        })
    )


@pytest.mark.asyncio
@respx.mock
async def test_sync_flow_end_to_end() -> None:
    """Full sync flow: load → edit → diff → inject apparatus."""
    _setup_mocks()
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=["Updated section 4.2", "Added new paragraph"],
            highlights_summary="Safety threshold increased",
        )

        # Mock the edit response to return edited HTML
        respx.post("https://api.superdocs.app/v1/chat").mock(
            return_value=httpx.Response(200, json={
                "message": "Edit applied",
                "document_changes": {
                    "chunk_id": "c1",
                    "updated_html": EDITED_HTML,
                },
            })
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-revision",
            edit_instructions="Update section 4.2 with new safety threshold",
            metadata=metadata,
        )

        assert result.success
        assert result.diff.has_changes
        assert len(result.diff.changed) > 0
        assert len(result.apparatus_instructions) > 0
        assert result.ops_used > 0


@pytest.mark.asyncio
@respx.mock
async def test_no_changes_skips_apparatus() -> None:
    """When edit produces no changes, apparatus injection is skipped."""
    _setup_mocks()
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=["No changes"],
        )

        # Mock edit that returns same HTML (no changes)
        respx.post("https://api.superdocs.app/v1/chat").mock(
            return_value=httpx.Response(200, json={
                "message": "No changes needed",
                "document_changes": {
                    "updated_html": SAMPLE_HTML,
                },
            })
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-no-changes",
            edit_instructions="Make no changes",
            metadata=metadata,
        )

        assert result.success
        assert not result.diff.has_changes
        assert len(result.apparatus_instructions) == 0


@pytest.mark.asyncio
@respx.mock
async def test_session_load_failure_returns_error() -> None:
    """When session load fails, pipeline returns error without proceeding."""
    respx.post("https://api.superdocs.app/v1/chat").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=[],
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-fail",
            edit_instructions="Edit",
            metadata=metadata,
        )

        assert not result.success
        assert len(result.errors) > 0
        assert "Step 1" in result.errors[0]


@pytest.mark.asyncio
@respx.mock
async def test_metadata_in_instruction_content() -> None:
    """Verify revision number and date appear in generated instructions."""
    _setup_mocks()
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0099",
            date="2025-06-01",
            changes=["Critical fix"],
            highlights_summary="Emergency patch",
        )

        respx.post("https://api.superdocs.app/v1/chat").mock(
            return_value=httpx.Response(200, json={
                "message": "Edit applied",
                "document_changes": {"updated_html": EDITED_HTML},
            })
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-metadata",
            edit_instructions="Apply critical fix",
            metadata=metadata,
        )

        all_text = " ".join(result.apparatus_instructions)
        assert "0099" in all_text
        assert "2025-06-01" in all_text
        assert "Critical fix" in all_text
        assert "Emergency patch" in all_text


@pytest.mark.asyncio
@respx.mock
async def test_tracker_counts_ops() -> None:
    """Pipeline run increments the client's operation tracker."""
    _setup_mocks()
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=["Change 1"],
        )

        respx.post("https://api.superdocs.app/v1/chat").mock(
            return_value=httpx.Response(200, json={
                "message": "Done",
                "document_changes": {"updated_html": EDITED_HTML},
            })
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-ops",
            edit_instructions="Edit",
            metadata=metadata,
        )

        # At least: 1 (load) + 1 (edit) + N (apparatus injections)
        assert result.ops_used >= 2
        assert client.tracker.total_ops >= 2
