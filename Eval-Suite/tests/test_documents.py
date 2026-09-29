"""Local document render writes real office/PDF bytes into the eval bucket."""

from __future__ import annotations

import pytest
from infra.clients.document_worker import DocumentSource
from infra.conversation_media import ConversationMediaScope

from eval_suite.documents import EvalDocuments
from eval_suite.media import EvalMediaBucket


@pytest.mark.asyncio
async def test_render_writes_office_pdf_and_preview(tmp_path) -> None:
    """render() writes a real .docx, PDF, and PNG preview under tmp_path's
    bucket.

    Args:
        tmp_path: pytest temporary directory the rendered files are written
            under.
    Returns:
        None.
    Raises:
        None.
    """
    bucket = EvalMediaBucket(tmp_path)
    documents = EvalDocuments(bucket)
    scope = ConversationMediaScope(user_id="eval-u", thread_key="eval-t")
    rendered = await documents.render(
        DocumentSource(
            title="Notes",
            filename="class-notes",
            markdown="Hello world",
            format="docx",
        ),
        scope,
    )
    assert rendered.files == ["class-notes.docx", "class-notes.pdf"]
    assert rendered.previews == ["class-notes-1.png"]
    prefix = "users/eval-u/threads/eval-t/files"
    office = (tmp_path / prefix / "class-notes.docx").read_bytes()
    pdf = (tmp_path / prefix / "class-notes.pdf").read_bytes()
    preview = (tmp_path / prefix / "class-notes-1.png").read_bytes()
    assert office.startswith(b"PK")
    assert pdf.startswith(b"%PDF")
    assert preview.startswith(b"\x89PNG")
