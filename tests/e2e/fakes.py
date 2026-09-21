"""Explicit, inspectable stand-ins for genuinely external systems.

Only Meta Graph API, OpenAI, Neo4j, Hubble and GCS are faked. Every fake keeps
an append-only call log so a test can assert both content and ordering, and can
assert that something did NOT happen (an empty list).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from infra.clients.users import GiftCardDelivery  # noqa: F401  (type reference only)
from infra.hubble.types import HubbleOrder, HubbleProduct
from infra.llm.oai.types.responses import ChatTurn, LlmResponse


# --------------------------------------------------------------------------
# Meta Graph API (outbound WhatsApp)
# --------------------------------------------------------------------------


@dataclass
class WhatsAppCall:
    """One recorded outbound WhatsApp send."""

    kind: str
    to: str
    data: dict[str, Any] = field(default_factory=dict)
    wamid: str = ""


class FakeWhatsAppClient:
    """Records every outbound Meta Graph API call in strict delivery order."""

    def __init__(self, confirmations: Optional[Any] = None) -> None:
        """Bind an optional DeliveryConfirmations registry to auto-confirm sends.

        Real WhatsApp reports 'sent' through a status webhook; the adapter's
        delivery barrier blocks on that. The fake plays Meta's part by resolving
        each waiter one loop tick after the send returns.
        """
        self.calls: list[WhatsAppCall] = []
        self.typing_calls: list[str] = []
        self.media_downloads: list[str] = []
        self._confirmations = confirmations
        self._counter = 0

    def bind_confirmations(self, confirmations: Any) -> None:
        """Bind the adapter's DeliveryConfirmations registry after construction."""
        self._confirmations = confirmations

    def reset(self) -> None:
        """Clear every recorded call."""
        self.calls.clear()
        self.typing_calls.clear()
        self.media_downloads.clear()
        self._counter = 0

    def kinds(self) -> list[str]:
        """Ordered list of call kinds, for compact ordering assertions."""
        return [call.kind for call in self.calls]

    def _record(self, kind: str, to: str, **data: Any) -> str:
        self._counter += 1
        wamid = f"wamid.out.{self._counter}"
        self.calls.append(WhatsAppCall(kind=kind, to=to, data=data, wamid=wamid))
        if self._confirmations is not None:
            loop = asyncio.get_running_loop()
            loop.call_later(0.01, self._confirmations.confirm_sent, wamid)
        return wamid

    async def send_text(self, to: str, body: str) -> str:
        """Record one plain text send."""
        return self._record("text", to, body=body)

    async def send_document(self, to: str, link: str, filename: str, caption: str) -> str:
        """Record one document send."""
        return self._record("document", to, link=link, filename=filename, caption=caption)

    async def send_image(self, to: str, link: str, caption: str) -> str:
        """Record one image send."""
        return self._record("image", to, link=link, caption=caption)

    async def send_reaction(self, to: str, message_id: str, emoji: str) -> str:
        """Record one reaction send."""
        return self._record("reaction", to, message_id=message_id, emoji=emoji)

    async def send_buttons(self, to: str, body: str, buttons: list[Any]) -> str:
        """Record one reply-buttons send."""
        return self._record(
            "buttons",
            to,
            body=body,
            buttons=[{"id": b.id, "title": b.title} for b in buttons],
        )

    async def send_list(self, to: str, body: str, button_label: str, rows: list[Any]) -> str:
        """Record one list send."""
        return self._record(
            "list",
            to,
            body=body,
            button_label=button_label,
            rows=[{"id": r.id, "title": r.title, "description": r.description} for r in rows],
        )

    async def send_cta_url(self, to: str, body: str, display_text: str, url: str) -> str:
        """Record one CTA-URL send."""
        return self._record("cta_url", to, body=body, display_text=display_text, url=url)

    async def send_location_request(self, to: str, body: str) -> str:
        """Record one location-request send."""
        return self._record("location_request", to, body=body)

    async def send_contact(self, to: str) -> str:
        """Record one contact-card send."""
        return self._record("contact", to)

    async def send_contact_request(self, to: str, body: str) -> str:
        """Record one REQUEST_CONTACT_INFO send."""
        return self._record("contact_request", to, body=body)

    async def send_flow(
        self,
        to: str,
        flow_id: str,
        flow_token: str,
        body: str,
        cta: str,
        screen: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> str:
        """Record one WhatsApp Flow launch."""
        return self._record(
            "flow",
            to,
            flow_id=flow_id,
            flow_token=flow_token,
            body=body,
            cta=cta,
            screen=screen,
            data=data,
        )

    async def show_typing(self, message_id: str) -> None:
        """Record a typing pulse; typing is UX metadata, never a delivery."""
        self.typing_calls.append(message_id)

    async def get_media_url(self, media_id: str) -> str:
        """Return a deterministic fake media URL."""
        self.media_downloads.append(media_id)
        return f"https://fake-media.invalid/{media_id}"

    async def download_media(self, url: str) -> bytes:
        """Return deterministic fake media bytes."""
        self.media_downloads.append(url)
        return b"fake-media-bytes"

    async def close(self) -> None:
        """No transport to close."""
        return None


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------


@dataclass
class RespondCall:
    """One recorded call into the faked OpenAI Responses client."""

    model: str
    previous_response_id: Optional[str]
    input_message: list[Any]


class FakeOpenAIResponsesClient:
    """Scriptable, recording stand-in for OpenAIResponsesClient."""

    def __init__(self) -> None:
        """Start with an empty script and an empty call log."""
        self.calls: list[RespondCall] = []
        self.token_count_calls: list[Optional[str]] = []
        # Each entry is either a ChatTurn to return or an Exception to raise.
        self.script: list[Any] = []
        self.default: Optional[Any] = None
        self.next_tokens: int = 1000

    def reset(self) -> None:
        """Clear the call log and the script."""
        self.calls.clear()
        self.token_count_calls.clear()
        self.script.clear()
        self.default = None
        self.next_tokens = 1000

    def push(self, item: Any) -> None:
        """Queue one scripted outcome for the next chat() call."""
        self.script.append(item)

    async def count_input_tokens(
        self,
        model: str,
        previous_response_id: Optional[str],
        input_message: Any,
    ) -> int:
        """Return the scripted token count."""
        self.token_count_calls.append(previous_response_id)
        return self.next_tokens

    async def chat(self, **kwargs: Any) -> ChatTurn[LlmResponse]:
        """Return (or raise) the next scripted outcome, recording the call."""
        history = kwargs.get("history", kwargs.get("input_message", []))
        self.calls.append(
            RespondCall(
                model=kwargs.get("model", ""),
                previous_response_id=kwargs.get("previous_response_id"),
                input_message=list(history),
            )
        )
        outcome = self.script.pop(0) if self.script else self.default
        if outcome is None:
            raise AssertionError("FakeOpenAIResponsesClient.chat called with no script")
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(kwargs)
        return outcome


class FakeOpenAIImageClient:
    """Recording stand-in for OpenAIImageClient."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[tuple[str, str]] = []

    def reset(self) -> None:
        """Clear the call log."""
        self.calls.clear()

    async def generate(self, prompt: str) -> bytes:
        """Record one image generation."""
        self.calls.append(("generate", prompt))
        return b"fake-png-bytes"

    async def edit(self, prompt: str, source_images: list[Any]) -> bytes:
        """Record one image edit."""
        self.calls.append(("edit", prompt))
        return b"fake-png-bytes"


class FakeAudioTranscriber:
    """Recording stand-in for OpenAIAudioTranscriber."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[str] = []

    def reset(self) -> None:
        """Clear the call log."""
        self.calls.clear()

    async def transcribe(self, file: Any) -> str:
        """Record one transcription request."""
        self.calls.append(getattr(file, "filename", "audio"))
        return "fake transcript"


class FakeEmbeddingClient:
    """Recording stand-in for GeminiEmbeddingClient."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[str] = []

    def reset(self) -> None:
        """Clear the call log."""
        self.calls.clear()

    async def embed_documents(self, parts: list[Any]) -> list[list[float]]:
        """Return one deterministic vector per part."""
        self.calls.append("embed_documents")
        return [[0.0, 0.0, 0.0] for _ in parts]

    async def embed_queries(self, parts: list[Any]) -> list[list[float]]:
        """Return one deterministic vector per part."""
        self.calls.append("embed_queries")
        return [[0.0, 0.0, 0.0] for _ in parts]


# --------------------------------------------------------------------------
# Neo4j
# --------------------------------------------------------------------------


@dataclass
class GraphCall:
    """One recorded Cypher execution."""

    text: str
    params: dict[str, Any]


class FakeGraphClient:
    """Recording stand-in for GraphClient with a scriptable row source."""

    def __init__(self) -> None:
        """Start with no rows and an empty call log."""
        self.calls: list[GraphCall] = []
        self.closed = False
        # Callable(text, params) -> list[dict]; default returns no rows.
        self.responder: Callable[[str, dict[str, Any]], list[dict[str, Any]]] = (
            lambda text, params: []
        )

    def reset(self) -> None:
        """Clear the call log and drop any scripted responder."""
        self.calls.clear()
        self.closed = False
        self.responder = lambda text, params: []

    async def query(self, text: str, **params: Any) -> list[dict[str, Any]]:
        """Record one query and return the scripted rows."""
        self.calls.append(GraphCall(text=text, params=dict(params)))
        return self.responder(text, params)

    async def close(self) -> None:
        """Mark the driver released."""
        self.closed = True


# --------------------------------------------------------------------------
# Hubble
# --------------------------------------------------------------------------


@dataclass
class HubbleCall:
    """One recorded Hubble partners-API call."""

    method: str
    args: dict[str, Any]


class FakeHubbleClient:
    """Recording stand-in for HubbleClient with explicit per-method scripts."""

    def __init__(self) -> None:
        """Start with an empty catalogue and no orders."""
        self.calls: list[HubbleCall] = []
        self.products: dict[str, HubbleProduct] = {}
        # referenceId -> ordered list of HubbleOrder results to hand back, one
        # per get_order_by_reference call; the last entry repeats once drained.
        self.order_reads: dict[str, list[Optional[HubbleOrder]]] = {}
        self.place_order_result: Optional[HubbleOrder] = None
        self.closed = False

    def reset(self) -> None:
        """Clear catalogue, orders and call log."""
        self.calls.clear()
        self.products.clear()
        self.order_reads.clear()
        self.place_order_result = None
        self.closed = False

    def method_calls(self, method: str) -> list[HubbleCall]:
        """Every recorded call to one method."""
        return [call for call in self.calls if call.method == method]

    async def get_product(self, product_id: str) -> HubbleProduct:
        """Return the scripted product, recording the read."""
        self.calls.append(HubbleCall("get_product", {"product_id": product_id}))
        if product_id not in self.products:
            raise AssertionError(f"FakeHubbleClient has no product {product_id!r}")
        return self.products[product_id]

    async def place_order(
        self, product_id: str, reference_id: str, amount_inr: int, customer=None
    ) -> HubbleOrder:
        """Return the scripted mint result, recording the order."""
        self.calls.append(
            HubbleCall(
                "place_order",
                {
                    "product_id": product_id,
                    "reference_id": reference_id,
                    "amount_inr": amount_inr,
                },
            )
        )
        if self.place_order_result is None:
            raise AssertionError("FakeHubbleClient.place_order called with no script")
        return self.place_order_result

    async def get_order_by_reference(self, reference_id: str) -> Optional[HubbleOrder]:
        """Return the next scripted order read for this reference id."""
        self.calls.append(
            HubbleCall("get_order_by_reference", {"reference_id": reference_id})
        )
        queue = self.order_reads.get(reference_id)
        if not queue:
            return None
        if len(queue) == 1:
            return queue[0]
        return queue.pop(0)

    async def close(self) -> None:
        """Mark the transport released."""
        self.closed = True


# --------------------------------------------------------------------------
# Google Cloud Storage (public conversation media bucket)
# --------------------------------------------------------------------------


class FakeGcsBucket:
    """Recording stand-in for GcsBucket; keeps objects in memory."""

    def __init__(self, bucket_name: str = "fake-bucket") -> None:
        """Start with an empty in-memory bucket."""
        self._bucket = bucket_name
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []

    def reset(self) -> None:
        """Clear stored objects and the call log."""
        self.objects.clear()
        self.calls.clear()

    async def upload(self, object_name: str, data: bytes, content_type: str) -> None:
        """Store one object in memory."""
        self.calls.append(("upload", object_name))
        self.objects[object_name] = data

    async def download(self, object_name: str) -> bytes:
        """Read one stored object."""
        self.calls.append(("download", object_name))
        return self.objects[object_name]

    def public_url(self, object_name: str) -> str:
        """Return the deterministic public URL for one object."""
        return f"https://storage.googleapis.com/{self._bucket}/{object_name}"

    async def list_names(self, prefix: str) -> list[str]:
        """List stored object names under one prefix."""
        self.calls.append(("list_names", prefix))
        return [name for name in self.objects if name.startswith(prefix)]

    async def delete(self, object_name: str) -> None:
        """Delete one stored object."""
        self.calls.append(("delete", object_name))
        self.objects.pop(object_name, None)

    async def delete_prefix(self, prefix: str) -> None:
        """Delete every stored object under one prefix."""
        self.calls.append(("delete_prefix", prefix))
        for name in [n for n in self.objects if n.startswith(prefix)]:
            del self.objects[name]

    async def close(self) -> None:
        """No transport to close."""
        return None


class FakeDocumentWorkerClient:
    """Recording stand-in for DocumentWorkerClient; never reached by these journeys."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[str] = []

    def reset(self) -> None:
        """Clear the call log."""
        self.calls.clear()

    async def close(self) -> None:
        """No transport to close."""
        return None
