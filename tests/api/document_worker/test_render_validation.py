"""Request-shape validation for POST /render.

Field names/types/enum values are read ONLY from
infra/clients/document_worker/types.py (DocumentSource, DocumentRenderRequest,
DocumentFormat, ConversationMediaScope) and infra/utils/types.py (Slug) --
never from behavior. FastAPI's default for a Pydantic validation failure on
a route body parameter is 422 Unprocessable Entity.
"""

from __future__ import annotations

import pytest

from .conftest import auth_headers, render_body


@pytest.mark.asyncio
async def test_render_missing_markdown_is_422(client):
    body = render_body()
    del body["document"]["markdown"]
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_missing_document_is_422(client):
    body = render_body()
    del body["document"]
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_format_outside_documented_enum_is_422(client):
    # DocumentFormat = Literal["docx", "pptx"]; "pdf" is not a documented value.
    body = render_body(format="pdf")
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_missing_scope_is_422(client):
    body = render_body()
    del body["scope"]
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_missing_scope_user_id_is_422(client):
    # ConversationMediaScope requires user_id and thread_key, both plain str.
    body = render_body()
    del body["scope"]["user_id"]
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_missing_title_is_422(client):
    body = render_body()
    del body["document"]["title"]
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_missing_filename_is_422(client):
    body = render_body()
    del body["document"]["filename"]
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_filename_not_matching_slug_pattern_is_422(client):
    # filename: Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    # A directory-traversal-shaped filename does not match the slug pattern,
    # so Pydantic rejects the request before any storage object name is ever
    # composed -- the traversal shape is neutralized by validation, not by
    # storage-layer sanitization.
    body = render_body(filename="../../etc/passwd")
    response = await client.post("/render", json=body, headers=auth_headers())
    assert response.status_code == 422
