"""Embed-batch packing: a PDF record bills alone; text records pack to the
provider's cap.

Oracle: knowledge_store/embedder.py ``_batches`` docstring — "PDF records
alone (payload size); text records packed to EMBEDDING_BATCH." The cap is
imported from the real Gemini constant, never retyped, so a provider-limit
change needs no edit here.
"""

from __future__ import annotations

import pytest

from infra.llm.gemini.constants import EMBEDDING_BATCH
from knowledge_store.embedder import _batches


def _pdf(record_id: str) -> dict:
    """A record whose embed source is a PDF (payload size, so its own batch).

    Args:
        record_id: the record's id.
    Returns:
        The record dict.
    Raises:
        None.
    """
    return {
        "id": record_id,
        "text": None,
        "source_object": f"gs://{record_id}.pdf",
    }


def _text(record_id: str) -> dict:
    """A record whose embed source is plain text (packs to the batch cap).

    Args:
        record_id: the record's id.
    Returns:
        The record dict.
    Raises:
        None.
    """
    return {"id": record_id, "text": "some content", "source_object": None}


@pytest.mark.boundary
def test_every_pdf_record_gets_its_own_batch() -> None:
    """Each PDF record gets its own batch, even when several are queued
    together.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    records = [_pdf("p1"), _pdf("p2")]
    assert _batches(records) == [[records[0]], [records[1]]]


@pytest.mark.boundary
def test_text_records_pack_up_to_the_provider_batch_cap() -> None:
    """Text records pack together up to EMBEDDING_BATCH per batch, no more.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    records = [_text(f"t{i}") for i in range(EMBEDDING_BATCH + 1)]
    batches = _batches(records)
    assert [len(batch) for batch in batches] == [EMBEDDING_BATCH, 1]
    assert [record["id"] for batch in batches for record in batch] == [
        r["id"] for r in records
    ]


@pytest.mark.boundary
def test_a_pdf_record_never_shares_a_batch_with_text_records() -> None:
    """A PDF record and text records never end up in the same batch.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    records = [_text("t1"), _pdf("p1"), _text("t2")]
    for batch in _batches(records):
        assert len({record["source_object"] is None for record in batch}) == 1
