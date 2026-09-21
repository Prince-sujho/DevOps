"""Success-path coverage for POST /render.

Everything here runs for real except the GCS upload boundary: real Pydantic
validation, real auth dependency, real Pandoc subprocess rendering (docx and
pptx), and the real LibreOffice-based page-preview pipeline
(infra/documents/previews.py). Only infra.platform.storage.GcsBucket is
faked (see conftest.FakeGcsBucket) -- the README's own stated external
dependency ("Secrets: CONVERSATION_MEDIA_BUCKET").

Expected values are committed from document_worker/README.md's Request/
Response example and infra/clients/document_worker/types.py's field names,
BEFORE running:
  - status: 200 (FastAPI's default success status for a POST route with no
    explicit status_code override -- infra/api's internal.py declares none).
  - response body: {"url": <str>, "previews": [<base64 str>, ...]}.
  - "The download filename is the URL's final segment" (README) ->
    url ends with "/{filename}.{format}".
  - "previews" is one base64 PNG string per page (README: "base64-png-page").

KNOWN ENVIRONMENT LIMITATION: infra/documents/previews.py shells out to a
local `soffice` (LibreOffice) binary to convert the rendered artifact to PDF
before rasterizing pages. This sandbox does not have `soffice` on PATH
(confirmed via `which soffice` / `which libreoffice` -> not found), even
though infra/documents/constants.py's own comment says it is "Installed on
PATH in the document-worker image" in the real deployment. That means the
render pipeline will fail at the previews step (FileNotFoundError from
asyncio.create_subprocess_exec) for EVERY real render in this sandbox,
regardless of markdown/format validity, and the route has no
try/except around that call (document_worker/src/service.py), so it
propagates to Starlette's default 500. These tests assert the real,
spec-derived 200/shape contract as committed above; if they fail here it is
this documented environment gap, not a code-behavior finding -- see the
UNCERTAINTY section of the final report.
"""

from __future__ import annotations

import base64

import pytest

from .conftest import auth_headers, render_body


@pytest.mark.xfail(
    reason=(
        "Environment gap, not a spec-vs-code mismatch: no `soffice` (LibreOffice) "
        "binary on PATH in this sandbox, so infra/documents/previews.py fails "
        "for every real render regardless of markdown/format validity -- see "
        "tests/outcomes/UNCERTAINTY.md document_worker 'Environment limitation' "
        "and tests/outcomes/FINDINGS.md document_worker."
    ),
    strict=False,
)
@pytest.mark.asyncio
async def test_render_docx_success_shape(client, fake_bucket):
    filename = "linear-equations-revision-sheet"
    body = render_body(filename=filename, format="docx")

    response = await client.post("/render", json=body, headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"url", "previews"}
    assert isinstance(payload["url"], str)
    assert payload["url"].endswith(f"/{filename}.docx")
    assert isinstance(payload["previews"], list)
    assert len(payload["previews"]) > 0
    for preview in payload["previews"]:
        assert isinstance(preview, str)
        # "base64-png-page" per README -- must decode cleanly as base64 and
        # start with the PNG magic header.
        decoded = base64.b64decode(preview, validate=True)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.xfail(
    reason=(
        "Environment gap, not a spec-vs-code mismatch: no `soffice` (LibreOffice) "
        "binary on PATH in this sandbox, so infra/documents/previews.py fails "
        "for every real render regardless of markdown/format validity -- see "
        "tests/outcomes/UNCERTAINTY.md document_worker 'Environment limitation' "
        "and tests/outcomes/FINDINGS.md document_worker."
    ),
    strict=False,
)
@pytest.mark.asyncio
async def test_render_pptx_success_shape(client, fake_bucket):
    filename = "branded-slide-deck"
    body = render_body(filename=filename, format="pptx")

    response = await client.post("/render", json=body, headers=auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"url", "previews"}
    assert payload["url"].endswith(f"/{filename}.pptx")
    assert isinstance(payload["previews"], list)
    assert len(payload["previews"]) > 0
    for preview in payload["previews"]:
        decoded = base64.b64decode(preview, validate=True)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"
