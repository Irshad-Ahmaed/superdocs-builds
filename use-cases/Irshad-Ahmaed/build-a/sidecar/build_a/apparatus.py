"""Revision apparatus injection — change bars, record table, highlights.

Generates chat instructions for SuperDocs to add revision apparatus to a document.
All apparatus is injected via natural language chat instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .differ import DiffResult


@dataclass
class RevisionMetadata:
    revision_number: str
    date: str
    changes: list[str] = field(default_factory=list)
    highlights_summary: str = ""


# Maximum paragraphs per chat instruction (SuperDocs limit: 25 sections per op)
MAX_SECTIONS_PER_TURN = 25


def _build_change_bars_instruction(positions: list[int]) -> str:
    """Build a chat instruction to add change bars next to altered paragraphs."""
    if not positions:
        return ""
    pos_list = ", ".join(str(p) for p in positions)
    return (
        f"Add vertical change bars (revision marks) in the left margin next to "
        f"every altered paragraph. The changed paragraphs are at positions "
        f"[{pos_list}] (0-indexed, counting all paragraphs including headings). "
        f"Only mark these specific paragraphs — do not add bars anywhere else."
    )


def _build_record_table_instruction(metadata: RevisionMetadata) -> str:
    """Build a chat instruction to insert a revision-record table."""
    if not metadata.changes:
        return (
            f"Insert a revision-record table at the top of the document with these columns: "
            f"Revision Number, Date, Summary of Change.\n"
            f"Row: | {metadata.revision_number} | {metadata.date} | No content changes |"
        )
    change_rows = "\n".join(
        f"| {metadata.revision_number} | {metadata.date} | {c} |"
        for c in metadata.changes
    )
    return (
        f"Insert a revision-record table at the top of the document with these columns: "
        f"Revision Number, Date, Summary of Change.\n"
        f"Use the following rows:\n{change_rows}"
    )


def _build_highlights_instruction(metadata: RevisionMetadata) -> str:
    """Build a chat instruction for highlights-of-change summary."""
    return (
        f"Add a 'Highlights of Change' summary section after the revision-record table. "
        f"Revision {metadata.revision_number} dated {metadata.date}. "
        f"Summary: {metadata.highlights_summary}"
    )


@dataclass
class InstructionBatch:
    """A batch of chat instructions to send in a single turn."""

    instructions: list[str] = field(default_factory=list)

    @property
    def combined(self) -> str:
        """Combine all instructions into a single chat message."""
        parts = [i for i in self.instructions if i]
        return "\n\n".join(parts)


class RevisionApparatus:
    """Generates and injects revision apparatus via SuperDocs chat instructions.

    Supports chunking: if >25 changed paragraphs, splits instructions across
    multiple chat turns to respect the 25-section limit.
    """

    def generate(self, diff: DiffResult, metadata: RevisionMetadata) -> list[InstructionBatch]:
        """Generate instruction batches from diff output and metadata.

        Returns a list of InstructionBatch objects — one per chat turn needed.
        """
        positions = diff.changed_positions
        batches: list[InstructionBatch] = []

        # Batch 1: revision record table + highlights (always fits in one turn)
        batch = InstructionBatch(instructions=[
            _build_record_table_instruction(metadata),
            _build_highlights_instruction(metadata),
        ])
        batches.append(batch)

        # Subsequent batches: change bars, chunked by MAX_SECTIONS_PER_TURN
        if positions:
            for i in range(0, len(positions), MAX_SECTIONS_PER_TURN):
                chunk = positions[i : i + MAX_SECTIONS_PER_TURN]
                batch = InstructionBatch(instructions=[
                    _build_change_bars_instruction(chunk),
                ])
                batches.append(batch)

        return batches

    def generate_combined(self, diff: DiffResult, metadata: RevisionMetadata) -> list[str]:
        """Generate combined instruction strings, one per chat turn.

        Each string is a complete instruction to send via client.edit().
        """
        batches = self.generate(diff, metadata)
        return [b.combined for b in batches if b.combined]
