"""Entry-owned node ids: deterministic per position, never colliding across
positions.

Oracle: knowledge_store/graph/ids.py — "Entry-owned ids are deterministic."
Materialize-replace depends on this: re-ingesting the same entry must
regenerate the same ids (no duplicate nodes on re-ingest), and two different
positions must never collide (no silently merged content). Question vs.
artefact kinds come from the product's real QUESTION_KINDS, never retyped.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, strategies as st

from infra.content import QUESTION_KINDS
from knowledge_store.graph.ids import chapter_id, item_id, source_id

ENTRY_ID = st.text(min_size=1, max_size=12)
POSITION = st.integers(min_value=0, max_value=99)
ANY_KIND = st.sampled_from([*QUESTION_KINDS, "diagram", "table"])


@pytest.mark.property
@given(entry_id=ENTRY_ID, unit_index=POSITION, ordinal=POSITION)
def test_the_same_position_always_mints_the_same_id(
    entry_id: str, unit_index: int, ordinal: int
) -> None:
    """chapter_id and source_id are pure functions of their position: no hidden
    state.

    Args:
        entry_id: hypothesis-generated entry id.
        unit_index: hypothesis-generated chapter/unit position.
        ordinal: hypothesis-generated source ordinal.
    Returns:
        None.
    Raises:
        None.
    """
    assert chapter_id(entry_id, unit_index) == chapter_id(entry_id, unit_index)
    assert source_id(entry_id, unit_index, ordinal) == source_id(
        entry_id, unit_index, ordinal
    )


@pytest.mark.property
@given(
    a=st.tuples(ENTRY_ID, POSITION, POSITION),
    b=st.tuples(ENTRY_ID, POSITION, POSITION),
)
def test_distinct_source_positions_never_collide(a: tuple, b: tuple) -> None:
    """Two different (entry_id, unit_index, ordinal) triples never mint the same
    source id.

    Args:
        a: a hypothesis-generated (entry_id, unit_index, ordinal) triple.
        b: a second, assumed-distinct triple.
    Returns:
        None.
    Raises:
        None.
    """
    assume(a != b)
    assert source_id(*a) != source_id(*b)


@pytest.mark.property
@given(
    position=st.tuples(ENTRY_ID, POSITION, POSITION),
    kind=ANY_KIND,
    other_kind=ANY_KIND,
    key=st.text(min_size=1, max_size=20),
)
def test_item_id_is_scoped_by_kind_as_well_as_position(
    position: tuple, kind: str, other_kind: str, key: str
) -> None:
    """The same position and key still mint distinct ids for distinct kinds.

    Args:
        position: a hypothesis-generated (entry_id, unit_index, ordinal) triple.
        kind: hypothesis-generated item kind.
        other_kind: a second, assumed-distinct item kind.
        key: hypothesis-generated item key.
    Returns:
        None.
    Raises:
        None.
    """
    assume(kind != other_kind)
    assert item_id(*position, kind, key) != item_id(*position, other_kind, key)


@pytest.mark.boundary
@pytest.mark.parametrize("kind", QUESTION_KINDS)
def test_question_kinds_mint_a_q_prefixed_id(kind: str) -> None:
    """Every real question kind mints an id starting with the Question prefix.

    Args:
        kind: a question-item kind.
    Returns:
        None.
    Raises:
        None.
    """
    assert item_id("e1", 0, 0, kind, "stem").startswith("Q:")


def test_non_question_kinds_mint_an_a_prefixed_id() -> None:
    """A kind outside QUESTION_KINDS mints an Artefact-prefixed id instead.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    assert item_id("e1", 0, 0, "diagram", "title").startswith("A:")
