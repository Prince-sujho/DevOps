"""Local document render into the eval media bucket. Does not call production
GCS.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

from infra.clients.document_worker import DocumentRenderResponse, DocumentSource
from infra.conversation_media import ConversationMediaScope

from .media import EvalMediaBucket

_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.doc"
    "ument",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.prese"
    "ntation",
}

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xa5\xf6\x17\x18\x00\x00\x00\x00IEND\xaeB`\x82"
)

_PDF_HEAD = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"


def _pdf(body: str) -> bytes:
    """A minimal, valid PDF whose stream is body's raw text.

    Args:
        body: the document text to embed.
    Returns:
        Raw PDF bytes.
    Raises:
        None.
    """
    stream = body.encode("utf-8")
    objects = (
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    )
    return _PDF_HEAD + objects + b"%%EOF\n" + stream


def _zip_parts(parts: dict[str, str]) -> bytes:
    """Zip named XML parts into one office-file blob.

    Args:
        parts: archive member name to XML text.
    Returns:
        The zip bytes.
    Raises:
        None.
    """
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml)
    return buffer.getvalue()


def _docx_document_xml(body: str) -> str:
    """The word/document.xml whose one paragraph is body's raw text.

    Args:
        body: the document text to embed.
    Returns:
        The document.xml text.
    Raises:
        None.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<w:document "
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ">"
        f"<w:body><w:p><w:r><w:t>{
            escape(body)
        }</w:t></w:r></w:p></w:body></w:document>"
    )


def _docx_content_types() -> str:
    """The [Content_Types].xml for a one-document docx package.

    Args:
        None.
    Returns:
        The content-types XML text.
    Raises:
        None.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<Types "
        'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"'
        "/>"
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument'
        '.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )


def _docx(body: str) -> bytes:
    """A minimal, valid .docx whose one paragraph is body's raw text.

    Args:
        body: the document text to embed.
    Returns:
        Raw .docx (zip) bytes.
    Raises:
        None.
    """
    return _zip_parts(
        {
            "[Content_Types].xml": _docx_content_types(),
            "word/document.xml": _docx_document_xml(body),
        }
    )


def _pptx_slide_xml(body: str) -> str:
    """The slide XML whose one text box is body's raw text.

    Args:
        body: the document text to embed.
    Returns:
        The slide1.xml text.
    Raises:
        None.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<p:sld "
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>"
        f"<p:sp><p:txBody><a:p><a:r><a:t>{
            escape(body)
        }</a:t></a:r></a:p></p:txBody></p:sp>"
        "</p:spTree></p:cSld></p:sld>"
    )


def _pptx_content_types() -> str:
    """The [Content_Types].xml for a one-slide pptx package.

    Args:
        None.
    Returns:
        The content-types XML text.
    Raises:
        None.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<Types "
        'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"'
        "/>"
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentatio'
        'nml.slide+xml"/>'
        "</Types>"
    )


def _pptx(body: str) -> bytes:
    """A minimal, valid .pptx whose one slide's text box is body's raw text.

    Args:
        body: the document text to embed.
    Returns:
        Raw .pptx (zip) bytes.
    Raises:
        None.
    """
    return _zip_parts(
        {
            "[Content_Types].xml": _pptx_content_types(),
            "ppt/slides/slide1.xml": _pptx_slide_xml(body),
        }
    )


def _files_prefix(scope: ConversationMediaScope) -> str:
    """The storage prefix a scope's files are written under.

    Args:
        scope: the user/thread a rendered document belongs to.
    Returns:
        The "users/.../threads/.../files" prefix.
    Raises:
        None.
    """
    return f"users/{scope.user_id}/threads/{scope.thread_key}/files"


class EvalDocuments:
    """Local stand-in for the real document-render client: writes to
    EvalMediaBucket, not GCS.
    """

    def __init__(self, bucket: EvalMediaBucket) -> None:
        """Bind to the media bucket rendered files are written to.

        Args:
            bucket: the eval media bucket to write into.
        Returns:
            None.
        Raises:
            None.
        """
        self._bucket = bucket

    async def _store_render(
        self, document: DocumentSource, scope: ConversationMediaScope, body: str
    ) -> DocumentRenderResponse:
        """Upload the office file, PDF, and preview for one rendered body.

        Args:
            document: the source filename and format being rendered.
            scope: the user/thread the rendered files belong to.
            body: the document text already chosen for the render.
        Returns:
            The uploaded office file and PDF names, plus the preview name.
        Raises:
            None.
        """
        office_name = f"{document.filename}.{document.format}"
        pdf_name = f"{document.filename}.pdf"
        preview_name = f"{document.filename}-1.png"
        prefix = _files_prefix(scope)
        office_bytes = (
            _docx(body) if document.format == "docx" else _pptx(body)
        )
        await self._bucket.upload(
            f"{prefix}/{office_name}", office_bytes, _MIME[document.format]
        )
        await self._bucket.upload(
            f"{prefix}/{pdf_name}", _pdf(body), "application/pdf"
        )
        await self._bucket.upload(f"{prefix}/{preview_name}", _PNG, "image/png")
        return DocumentRenderResponse(
            files=[office_name, pdf_name], previews=[preview_name]
        )

    async def render(
        self, document: DocumentSource, scope: ConversationMediaScope
    ) -> DocumentRenderResponse:
        """Render document locally (docx/pptx + a PDF + a PNG preview) and
        upload it.

        Args:
            document: the source title/markdown/filename/format to render.
            scope: the user/thread the rendered files belong to.
        Returns:
            The uploaded office file and PDF names, plus the preview name.
        Raises:
            ValueError: document has no title and no markdown.
        """
        body = f"{document.title}\n\n{document.markdown}".strip()
        if not body:
            raise ValueError("document source is empty")
        return await self._store_render(document, scope, body)
