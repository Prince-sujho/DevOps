"""Job-arg boundary: entry verbs require an id, the rest forbid one.

Oracle: infra.catalog.types.parse_job_args docstring. Verbs are read from the
real Verb/EntryVerb literals via get_args, so a verb added tomorrow is
covered tomorrow, with no change to this file.
"""

from __future__ import annotations

from typing import get_args

import pytest

from infra.catalog import EntryVerb, Verb, job_args, parse_job_args

ALL_VERBS = get_args(Verb)
ENTRY_VERBS = set(get_args(EntryVerb))


@pytest.mark.boundary
@pytest.mark.parametrize("verb", ALL_VERBS)
def test_entry_verbs_require_an_id_and_other_verbs_forbid_one(verb: str) -> None:
    """Round-trips job_args (the container args) back through parse_job_args."""
    with_id = job_args(verb, "entry-123")[2:]
    without_id = job_args(verb)[2:]
    if verb in ENTRY_VERBS:
        assert parse_job_args(with_id) == (verb, "entry-123")
        with pytest.raises(ValueError):
            parse_job_args(without_id)
    else:
        assert parse_job_args(without_id) == (verb, None)
        with pytest.raises(ValueError):
            parse_job_args(with_id)
