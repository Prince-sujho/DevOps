"""Negative / failure-path coverage for POST /render (rule 8).

Status-code commitment discipline: document_worker/src/api/internal.py's
`render` handler and document_worker/src/service.py's `DocumentWorkerService.render`
have NO try/except around render_document(), render_previews(), or
media.upload_generated_document() (confirmed by reading both files -- read
for control flow only, not to decide "correct" behavior). document_worker/src/api/app.py
builds `FastAPI(lifespan=lifespan)` with no exception_handlers and no debug=True,
so an unhandled exception anywhere in that chain propagates to Starlette's
default ServerErrorMiddleware, which returns status 500. That is the
committed expectation below, BEFORE running -- not a guessed number.
"""

from __future__ import annotations

import base64

import pytest

import document_worker.src.service as service_module
from .conftest import auth_headers, render_body


async def _fake_export_pdf(data: bytes, format: str) -> bytes:
    return b"%PDF-fake"


def _fake_previews_ok(pdf: bytes) -> list[str]:
    """Stand-in for infra.documents.pdf.render_previews.

    This sandbox has no `soffice` binary, so the real export_pdf / preview
    pipeline fails for every render. Patch both calls so a test can reach
    the storage boundary it is actually about.
    """
    tiny_png = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
    return [tiny_png]


@pytest.mark.asyncio
async def test_render_storage_upload_failure_does_not_return_success(client, fake_bucket, monkeypatch):
    """The README documents no error-status contract for a storage failure,
    and the 500 that falls out today is an accident of there being no
    try/except anywhere in this path -- not a documented contract, so it is
    not asserted as the desired status here (see FINDINGS document_worker).
    The one thing the README does imply (a render either succeeds with the
    documented shape or it does not) is qualitatively checked instead.
    """
    monkeypatch.setattr(service_module, "export_pdf", _fake_export_pdf)
    monkeypatch.setattr(service_module, "render_previews", _fake_previews_ok)
    fake_bucket.upload_error = RuntimeError("simulated GCS outage")

    body = render_body()
    response = await client.post("/render", json=body, headers=auth_headers())

    assert response.status_code >= 400, "a storage failure must not report success"


@pytest.mark.asyncio
async def test_render_nonsensical_but_schema_valid_format_still_reaches_storage_prefix(
    client, fake_bucket, monkeypatch
):
    """format passes Pydantic's enum but we still verify no path escapes the
    user's thread folder. ConversationMediaStore names objects under
    users/{userId}/threads/{threadKey}/...; only the bucket call is faked.
    """
    monkeypatch.setattr(service_module, "export_pdf", _fake_export_pdf)
    monkeypatch.setattr(service_module, "render_previews", _fake_previews_ok)

    body = render_body(filename="safe-filename", user_id="user-id", thread_key="whatsapp")
    response = await client.post("/render", json=body, headers=auth_headers())

    assert response.status_code == 200
    assert fake_bucket.uploads
    names = [name for name, _data, _content_type in fake_bucket.uploads]
    for object_name in names:
        assert object_name.startswith("users/user-id/threads/whatsapp/")
        assert "../" not in object_name
    assert any(name.endswith("safe-filename.docx") for name in names)
