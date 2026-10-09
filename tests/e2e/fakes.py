"""Explicit, inspectable stand-ins for genuinely external systems.

Only Meta Graph API, OpenAI, Neo4j, Hubble and GCS are faked. Every fake keeps
an append-only call log so a test can assert both content and ordering, and can
assert that something did NOT happen (an empty list).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

from infra.clients.users import (
    GiftCardDelivery,  # noqa: F401  (type reference only)
)
from infra.hubble.types import HubbleOrder, HubbleProduct
from infra.llm.oai.types.responses import Speech


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

    def __init__(self, confirmations: Any | None = None) -> None:
        """Bind an optional DeliveryConfirmations registry to auto-confirm
        sends.

        Real WhatsApp reports 'sent' through a status webhook; the adapter's
        delivery barrier blocks on that. The fake plays Meta's part by resolving
        each waiter one loop tick after the send returns.

        Args:
            confirmations: the DeliveryConfirmations registry to auto-confirm
                through, or None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[WhatsAppCall] = []
        self.typing_calls: list[str] = []
        self.media_downloads: list[str] = []
        self._confirmations = confirmations
        self._counter = 0

    def bind_confirmations(self, confirmations: Any) -> None:
        """Bind the adapter's DeliveryConfirmations registry after construction.

        Args:
            confirmations: the DeliveryConfirmations registry to auto-confirm
                through.
        Returns:
            None.
        Raises:
            None.
        """
        self._confirmations = confirmations

    def reset(self) -> None:
        """Clear every recorded call.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()
        self.typing_calls.clear()
        self.media_downloads.clear()
        self._counter = 0

    def kinds(self) -> list[str]:
        """Ordered list of call kinds, for compact ordering assertions.

        Args:
            None.
        Returns:
            The kind of each recorded call, in order.
        Raises:
            None.
        """
        return [call.kind for call in self.calls]

    def _record(self, kind: str, to: str, **data: Any) -> str:
        """Append one call to the log, mint its wamid, and auto-confirm
        delivery.

        Args:
            kind: the send kind being recorded.
            to: the recipient phone.
            data: the send's other recorded field values.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        self._counter += 1
        wamid = f"wamid.out.{self._counter}"
        self.calls.append(
            WhatsAppCall(kind=kind, to=to, data=data, wamid=wamid)
        )
        if self._confirmations is not None:
            loop = asyncio.get_running_loop()
            loop.call_later(0.01, self._confirmations.confirm_sent, wamid)
        return wamid

    async def send_text(self, to: str, body: str) -> str:
        """Record one plain text send.

        Args:
            to: the recipient phone.
            body: the text body.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("text", to, body=body)

    async def send_document(
        self, to: str, link: str, filename: str, caption: str
    ) -> str:
        """Record one document send.

        Args:
            to: the recipient phone.
            link: the document URL.
            filename: the document's filename.
            caption: the document caption.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record(
            "document", to, link=link, filename=filename, caption=caption
        )

    async def send_image(self, to: str, link: str, caption: str) -> str:
        """Record one image send.

        Args:
            to: the recipient phone.
            link: the image URL.
            caption: the image caption.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("image", to, link=link, caption=caption)

    async def send_reaction(self, to: str, message_id: str, emoji: str) -> str:
        """Record one reaction send.

        Args:
            to: the recipient phone.
            message_id: the message being reacted to.
            emoji: the reaction emoji.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("reaction", to, message_id=message_id, emoji=emoji)

    async def send_buttons(self, to: str, body: str, buttons: list[Any]) -> str:
        """Record one reply-buttons send.

        Args:
            to: the recipient phone.
            body: the message body text.
            buttons: the buttons offered.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record(
            "buttons",
            to,
            body=body,
            buttons=[{"id": b.id, "title": b.title} for b in buttons],
        )

    async def send_list(
        self, to: str, body: str, button_label: str, rows: list[Any]
    ) -> str:
        """Record one list send.

        Args:
            to: the recipient phone.
            body: the message body text.
            button_label: the list-open button's label.
            rows: the list's selectable rows.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record(
            "list",
            to,
            body=body,
            button_label=button_label,
            rows=[
                {"id": r.id, "title": r.title, "description": r.description}
                for r in rows
            ],
        )

    async def send_cta_url(
        self, to: str, body: str, display_text: str, url: str
    ) -> str:
        """Record one CTA-URL send.

        Args:
            to: the recipient phone.
            body: the message body text.
            display_text: the link's display text.
            url: the link target.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record(
            "cta_url", to, body=body, display_text=display_text, url=url
        )

    async def send_location_request(self, to: str, body: str) -> str:
        """Record one location-request send.

        Args:
            to: the recipient phone.
            body: the request body text.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("location_request", to, body=body)

    async def send_contact(self, to: str) -> str:
        """Record one contact-card send.

        Args:
            to: the recipient phone.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("contact", to)

    async def send_contact_request(self, to: str, body: str) -> str:
        """Record one REQUEST_CONTACT_INFO send.

        Args:
            to: the recipient phone.
            body: the request body text.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("contact_request", to, body=body)

    async def send_flow(
        self,
        to: str,
        flow_id: str,
        flow_token: str,
        body: str,
        cta: str,
        screen: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Record one WhatsApp Flow launch.

        Args:
            to: the recipient phone.
            flow_id: the WhatsApp flow id to launch.
            flow_token: the flow session token.
            body: the message body text.
            cta: the launch button's call-to-action text.
            screen: the flow screen to open on, or None for the default.
            data: initial flow screen data, or None.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
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
        """Record a typing pulse; typing is UX metadata, never a delivery.

        Args:
            message_id: the inbound message the typing pulse responds to.
        Returns:
            None.
        Raises:
            None.
        """
        self.typing_calls.append(message_id)

    async def get_media_url(self, media_id: str) -> str:
        """Return a deterministic fake media URL.

        Args:
            media_id: the media id being looked up.
        Returns:
            A deterministic fake media URL.
        Raises:
            None.
        """
        self.media_downloads.append(media_id)
        return f"https://fake-media.invalid/{media_id}"

    async def download_media(self, url: str) -> bytes:
        """Return deterministic fake media bytes.

        Args:
            url: the media URL being downloaded.
        Returns:
            Fixed fake media bytes.
        Raises:
            None.
        """
        self.media_downloads.append(url)
        return b"fake-media-bytes"

    async def close(self) -> None:
        """No transport to close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        return None


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------


@dataclass
class RespondCall:
    """One recorded call into the faked OpenAI Responses client."""

    model: str
    input_message: list[Any]


class FakeTurn:
    """Stand-in for infra.llm.oai.responses.Turn.

    No tool rounds; finishes with a scripted Speech.
    """

    def __init__(self, speech: Speech) -> None:
        """Bind the Speech this turn resolves to once finished.

        Args:
            speech: the scripted Speech finish() returns.
        Returns:
            None.
        Raises:
            None.
        """
        self._speech = speech

    async def rounds(self):
        """These scripted journeys make no tool calls, so this yields nothing.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        return
        yield  # pragma: no cover -- unreachable; makes this an async generator

    async def finish(self) -> Speech:
        """Return the scripted Speech.

        Args:
            None.
        Returns:
            The scripted Speech.
        Raises:
            None.
        """
        return self._speech


class FakeOpenAIResponsesClient:
    """Scriptable, recording stand-in for OpenAIResponsesClient."""

    def __init__(self) -> None:
        """Start with an empty script and an empty call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[RespondCall] = []
        # Each entry is either a Speech to return or an Exception to raise.
        self.script: list[Any] = []
        self.default: Any | None = None

    def reset(self) -> None:
        """Clear the call log and the script.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()
        self.script.clear()
        self.default = None

    def push(self, item: Any) -> None:
        """Queue one scripted outcome for the next turn() call.

        Args:
            item: a Speech to return, or an Exception to raise, or a
                callable(kwargs) producing one.
        Returns:
            None.
        Raises:
            None.
        """
        self.script.append(item)

    def turn(self, **kwargs: Any) -> FakeTurn:
        """Return (or raise) the next scripted outcome, recording the call.

        Args:
            kwargs: the turn's call kwargs (model/history/etc), recorded as a
                RespondCall.
        Returns:
            A FakeTurn resolving to the scripted Speech.
        Raises:
            AssertionError: no outcome was scripted.
            Exception: the scripted outcome, if it's an exception.
        """
        self.calls.append(
            RespondCall(
                model=kwargs.get("model", ""),
                input_message=list(kwargs.get("history", [])),
            )
        )
        outcome = self.script.pop(0) if self.script else self.default
        if outcome is None:
            raise AssertionError(
                "FakeOpenAIResponsesClient.turn called with no script"
            )
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            outcome = outcome(kwargs)
        return FakeTurn(outcome)


class FakeOpenAIImageClient:
    """Recording stand-in for OpenAIImageClient."""

    def __init__(self) -> None:
        """Start with an empty call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[tuple[str, str]] = []

    def reset(self) -> None:
        """Clear the call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()

    async def generate(self, prompt: str) -> bytes:
        """Record one image generation.

        Args:
            prompt: the image prompt.
        Returns:
            Fixed fake PNG bytes.
        Raises:
            None.
        """
        self.calls.append(("generate", prompt))
        return b"fake-png-bytes"

    async def edit(self, prompt: str, source_images: list[Any]) -> bytes:
        """Record one image edit.

        Args:
            prompt: the edit prompt.
            source_images: the images being edited.
        Returns:
            Fixed fake PNG bytes.
        Raises:
            None.
        """
        self.calls.append(("edit", prompt))
        return b"fake-png-bytes"


class FakeAudioTranscriber:
    """Recording stand-in for OpenAIAudioTranscriber."""

    def __init__(self) -> None:
        """Start with an empty call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[str] = []

    def reset(self) -> None:
        """Clear the call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()

    async def transcribe(self, file: Any) -> str:
        """Record one transcription request.

        Args:
            file: the audio file being transcribed.
        Returns:
            A fixed fake transcript string.
        Raises:
            None.
        """
        self.calls.append(getattr(file, "filename", "audio"))
        return "fake transcript"


class FakeEmbeddingClient:
    """Recording stand-in for GeminiEmbeddingClient."""

    def __init__(self) -> None:
        """Start with an empty call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[str] = []

    def reset(self) -> None:
        """Clear the call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()

    async def embed_documents(self, parts: list[Any]) -> list[list[float]]:
        """Return one deterministic vector per part.

        Args:
            parts: the document parts to embed.
        Returns:
            One zero vector per part.
        Raises:
            None.
        """
        self.calls.append("embed_documents")
        return [[0.0, 0.0, 0.0] for _ in parts]

    async def embed_queries(self, parts: list[Any]) -> list[list[float]]:
        """Return one deterministic vector per part.

        Args:
            parts: the query parts to embed.
        Returns:
            One zero vector per part.
        Raises:
            None.
        """
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
        """Start with no rows and an empty call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[GraphCall] = []
        self.closed = False
        # Callable(text, params) -> list[dict]; default returns no rows.
        self.responder: Callable[
            [str, dict[str, Any]], list[dict[str, Any]]
        ] = lambda text, params: []

    def reset(self) -> None:
        """Clear the call log and drop any scripted responder.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()
        self.closed = False
        self.responder = lambda text, params: []

    async def query(self, text: str, **params: Any) -> list[dict[str, Any]]:
        """Record one query and return the scripted rows.

        Args:
            text: the Cypher query text.
            params: query parameters.
        Returns:
            Whatever the scripted responder returns for (text, params).
        Raises:
            None.
        """
        self.calls.append(GraphCall(text=text, params=dict(params)))
        return self.responder(text, params)

    async def close(self) -> None:
        """Mark the driver released.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
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
        """Start with an empty catalogue and no orders.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[HubbleCall] = []
        self.products: dict[str, HubbleProduct] = {}
        # referenceId -> ordered list of HubbleOrder results to hand back, one
        # per get_order_by_reference call; the last entry repeats once drained.
        self.order_reads: dict[str, list[HubbleOrder | None]] = {}
        self.place_order_result: HubbleOrder | None = None
        self.closed = False

    def reset(self) -> None:
        """Clear catalogue, orders and call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()
        self.products.clear()
        self.order_reads.clear()
        self.place_order_result = None
        self.closed = False

    def method_calls(self, method: str) -> list[HubbleCall]:
        """Every recorded call to one method.

        Args:
            method: the Hubble method name to filter by.
        Returns:
            Matching calls, in call order.
        Raises:
            None.
        """
        return [call for call in self.calls if call.method == method]

    async def get_product(self, product_id: str) -> HubbleProduct:
        """Return the scripted product, recording the read.

        Args:
            product_id: the product being looked up.
        Returns:
            The scripted product.
        Raises:
            AssertionError: no product was scripted for product_id.
        """
        self.calls.append(HubbleCall("get_product", {"product_id": product_id}))
        if product_id not in self.products:
            raise AssertionError(
                f"FakeHubbleClient has no product {product_id!r}"
            )
        return self.products[product_id]

    async def place_order(
        self, product_id: str, reference_id: str, amount_inr: int, customer=None
    ) -> HubbleOrder:
        """Return the scripted mint result, recording the order.

        Args:
            product_id: the product being ordered.
            reference_id: the order's reference id.
            amount_inr: the order amount, in INR.
            customer: unused; kept to match the real signature.
        Returns:
            The scripted order.
        Raises:
            AssertionError: no order result was scripted.
        """
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
            raise AssertionError(
                "FakeHubbleClient.place_order called with no script"
            )
        return self.place_order_result

    async def get_order_by_reference(
        self, reference_id: str
    ) -> HubbleOrder | None:
        """Return the next scripted order read for this reference id.

        Args:
            reference_id: the order reference id being looked up.
        Returns:
            The next queued order (or the last one, repeated), or None if none
            was scripted.
        Raises:
            None.
        """
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
        """Mark the transport released.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.closed = True


# --------------------------------------------------------------------------
# Google Cloud Storage (public conversation media bucket)
# --------------------------------------------------------------------------


class FakeGcsBucket:
    """Recording stand-in for GcsBucket; keeps objects in memory."""

    def __init__(self, bucket_name: str = "fake-bucket") -> None:
        """Start with an empty in-memory bucket.

        Args:
            bucket_name: the fake bucket name used in public_url.
        Returns:
            None.
        Raises:
            None.
        """
        self._bucket = bucket_name
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []

    def reset(self) -> None:
        """Clear stored objects and the call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.objects.clear()
        self.calls.clear()

    async def upload(
        self, object_name: str, data: bytes, content_type: str
    ) -> None:
        """Store one object in memory.

        Args:
            object_name: the object's storage path.
            data: the bytes being stored.
            content_type: unused; kept to match the real signature.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.append(("upload", object_name))
        self.objects[object_name] = data

    async def download(self, object_name: str) -> bytes:
        """Read one stored object.

        Args:
            object_name: the object's storage path.
        Returns:
            Its stored bytes.
        Raises:
            KeyError: object_name was never uploaded.
        """
        self.calls.append(("download", object_name))
        return self.objects[object_name]

    def public_url(self, object_name: str) -> str:
        """Return the deterministic public URL for one object.

        Args:
            object_name: the object's storage path.
        Returns:
            A fake public URL for object_name.
        Raises:
            None.
        """
        return f"https://storage.googleapis.com/{self._bucket}/{object_name}"

    async def list_names(self, prefix: str) -> list[str]:
        """List stored object names under one prefix.

        Args:
            prefix: the path prefix to filter by.
        Returns:
            Matching object names.
        Raises:
            None.
        """
        self.calls.append(("list_names", prefix))
        return [name for name in self.objects if name.startswith(prefix)]

    async def delete(self, object_name: str) -> None:
        """Delete one stored object.

        Args:
            object_name: the object's storage path.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.append(("delete", object_name))
        self.objects.pop(object_name, None)

    async def delete_prefix(self, prefix: str) -> None:
        """Delete every stored object under one prefix.

        Args:
            prefix: the path prefix to delete.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.append(("delete_prefix", prefix))
        for name in [n for n in self.objects if n.startswith(prefix)]:
            del self.objects[name]

    async def close(self) -> None:
        """No transport to close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        return None


class FakeDocumentWorkerClient:
    """Recording stand-in for DocumentWorkerClient; never reached by these
    journeys.
    """

    def __init__(self) -> None:
        """Start with an empty call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[str] = []

    def reset(self) -> None:
        """Clear the call log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()

    async def close(self) -> None:
        """No transport to close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        return None
