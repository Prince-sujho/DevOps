"""Knowledge-store job command and compatibility-dispatch contracts."""

from __future__ import annotations

import asyncio

import pytest

from infra.catalog import job_args, job_module
from knowledge_store import run
from knowledge_store.jobs.setup import require_entry_id, require_no_args


@pytest.mark.parametrize(
    ("verb", "module"),
    [
        ("ingest", "knowledge_store.jobs.ingest"),
        ("remove", "knowledge_store.jobs.remove"),
        ("sessions", "knowledge_store.jobs.sessions"),
        ("import-ncert", "knowledge_store.jobs.import_ncert"),
        ("import-educart", "knowledge_store.jobs.import_educart"),
    ],
)
def test_job_module_uses_a_dedicated_module(verb, module):
    assert job_module(verb) == module


def test_entry_job_args_append_only_the_entry_id():
    assert job_args("ingest", "entry-1") == [
        "-m",
        "knowledge_store.jobs.ingest",
        "entry-1",
    ]


def test_require_entry_id_requires_exactly_one_argument():
    assert require_entry_id(["entry-1"]) == "entry-1"
    with pytest.raises(ValueError, match="exactly one entry id"):
        require_entry_id([])
    with pytest.raises(ValueError, match="exactly one entry id"):
        require_entry_id(["entry-1", "extra"])


def test_no_argument_jobs_reject_arguments():
    require_no_args([])
    with pytest.raises(ValueError, match="takes no arguments"):
        require_no_args(["unexpected"])


def test_legacy_dispatcher_runs_the_dedicated_module(monkeypatch):
    called: list[str] = []

    async def fake_run() -> None:
        called.append("sessions")

    monkeypatch.setattr(run.sessions, "run", fake_run)
    asyncio.run(run._run_verb("sessions", None))

    assert called == ["sessions"]
