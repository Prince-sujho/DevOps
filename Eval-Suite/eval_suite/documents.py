"""Local document render into the eval media bucket. Does not call production GCS."""

from __future__ import annotations

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

from infra.clients.document_worker import DocumentRenderResponse, DocumentSource
from infra.conversation_media import ConversationMediaScope

from .media import EvalMediaBucket

_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00"
    b"\x00\x04\x00\x01\xa5\xf6\x17\x18\x00\x00\x00\x00IEND\xaeB`\x82"
)

_PDF_HEAD = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"


def _pdf(body: str) -> bytes:
    stream = body.encode("utf-8")
    objects = (
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    )
    return _PDF_HEAD + objects + b"%%EOF\n" + stream


def _docx(body: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{escape(body)}</w:t></w:r></w:p></w:body></w:document>"
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _pptx(body: str) -> bytes:
    slide = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>"
        f"<p:sp><p:txBody><a:p><a:r><a:t>{escape(body)}</a:t></a:r></a:p></p:txBody></p:sp>"
        "</p:spTree></p:cSld></p:sld>"
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        "</Types>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("ppt/slides/slide1.xml", slide)
    return buffer.getvalue()


def _files_prefix(scope: ConversationMediaScope) -> str:
    return f"users/{scope.user_id}/threads/{scope.thread_key}/files"


class EvalDocuments:
    def __init__(self, bucket: EvalMediaBucket) -> None:
        self._bucket = bucket

    async def render(
        self, document: DocumentSource, scope: ConversationMediaScope
    ) -> DocumentRenderResponse:
        body = f"{document.title}\n\n{document.markdown}".strip()
        if not body:
            raise ValueError("document source is empty")
        office_name = f"{document.filename}.{document.format}"
        pdf_name = f"{document.filename}.pdf"
        preview_name = f"{document.filename}-1.png"
        prefix = _files_prefix(scope)
        office_bytes = _docx(body) if document.format == "docx" else _pptx(body)
        await self._bucket.upload(f"{prefix}/{office_name}", office_bytes, _MIME[document.format])
        await self._bucket.upload(f"{prefix}/{pdf_name}", _pdf(body), "application/pdf")
        await self._bucket.upload(f"{prefix}/{preview_name}", _PNG, "image/png")
        return DocumentRenderResponse(files=[office_name, pdf_name], previews=[preview_name])
