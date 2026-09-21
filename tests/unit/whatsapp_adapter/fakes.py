"""In-memory stand-ins for the adapter's collaborators.

Each fake records what it was asked to do and returns only what the real
collaborator would return. None of them invent success: a write the real client
would perform is recorded so a test can assert it happened, and a read returns
exactly what the test scripted, never a plausible default.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from infra.clients.text_agent import GenerateResponse, Message
from infra.clients.users import (
    AppendTranscriptResult,
    CreateUserRequest,
    GiftCardDelivery,
    Persona,
    ProfileUpdate,
    ResolveAccessResult,
    SessionTranscript,
    TranscriptMessage,
    UserLocation,
    UserProfile,
)
from infra.conversation import Button, OutboundMessage
from infra.llm import AudioUsage
from infra.llm.content import TextContent
from infra.usage import UsageRecord

from whatsapp_adapter.app.src.input import PendingAction
from whatsapp_adapter.app.src.types import PendingTurn, TurnInput

SESSION_MS = 1_750_000_000_000


@dataclass
class Append:
    """One recorded call on the transcript append path."""

    user_id: str
    thread_key: str
    rows: list[TranscriptMessage]
    read_ids: list[str]
    started_at_ms: int | None

    @property
    def roles(self) -> list[str]:
        return [row.role for row in self.rows]

    @property
    def turn_ids(self) -> list[str]:
        return [row.turnId for row in self.rows]

    @property
    def response_ids(self) -> list[str | None]:
        return [row.responseId for row in self.rows]


def tagged(kind: str) -> Message:
    """A model message tagged with the builder path that produced it."""
    return Message(parts=[TextContent(text=f"<{kind}>")])


def tag_of(message: Message) -> str:
    """The builder path a tagged message came from."""
    return message.parts[0].text


class FakeUsers:
    """UsersClient stand-in: scripted access, recorded writes."""

    def __init__(
        self,
        access: ResolveAccessResult | None = None,
        refreshed: UserProfile | None = None,
        created: UserProfile | None = None,
        create_error: Exception | None = None,
        replay: SessionTranscript | None = None,
        opened_session_number: int | None = 1,
        gift_card: GiftCardDelivery | None = None,
    ) -> None:
        """Script the access decision and the profiles that writes echo back."""
        self._access = access
        self._refreshed = refreshed
        self._created = created
        self._create_error = create_error
        self._replay = replay
        self._opened = opened_session_number
        self._gift_card = gift_card
        self.resolved: list[str] = []
        self.locations: list[tuple[str, UserLocation]] = []
        self.profile_updates: list[tuple[str, ProfileUpdate]] = []
        self.created: list[CreateUserRequest] = []
        self.appends: list[Append] = []
        self.replays_read: list[tuple[str, str, int]] = []
        self.gift_cards_read: list[tuple[str, str]] = []

    async def get_gift_card(self, user_id: str, gift_card_id: str) -> GiftCardDelivery:
        self.gift_cards_read.append((user_id, gift_card_id))
        assert self._gift_card is not None, "test did not script a gift card"
        return self._gift_card

    async def append_transcript(
        self,
        user_id: str,
        thread_key: str,
        rows: list[TranscriptMessage],
        *,
        read_ids: list[str],
        started_at_ms: int | None,
    ) -> AppendTranscriptResult:
        self.appends.append(Append(user_id, thread_key, rows, read_ids, started_at_ms))
        if started_at_ms is None:
            # Only an unpinned append resolves -- or opens -- a session.
            return AppendTranscriptResult(
                startedAtMs=SESSION_MS, openedSessionNumber=self._opened
            )
        return AppendTranscriptResult(startedAtMs=started_at_ms, openedSessionNumber=None)

    async def get_session_replay(
        self, user_id: str, thread_key: str, started_at_ms: int
    ) -> SessionTranscript:
        self.replays_read.append((user_id, thread_key, started_at_ms))
        assert self._replay is not None, "test did not script a session replay"
        return self._replay

    async def create_user(self, request: CreateUserRequest) -> UserProfile:
        self.created.append(request)
        if self._create_error is not None:
            raise self._create_error
        assert self._created is not None, "test did not script a created profile"
        return self._created

    async def resolve_phone(self, phone: str) -> ResolveAccessResult:
        self.resolved.append(phone)
        assert self._access is not None, "test did not script an access decision"
        return self._access

    async def set_location(self, user_id: str, location: UserLocation) -> UserProfile:
        self.locations.append((user_id, location))
        return self._write_result()

    async def update_profile(self, user_id: str, update: ProfileUpdate) -> UserProfile:
        self.profile_updates.append((user_id, update))
        return self._write_result()

    def _write_result(self) -> UserProfile:
        """What the user service echoes back after a profile write."""
        if self._refreshed is not None:
            return self._refreshed
        assert self._access is not None and self._access.user is not None
        return self._access.user


class FakeWhatsApp:
    """WhatsAppClient stand-in: records the bubbles that went out, in order.

    Every send returns a distinct wamid, because the delivery path feeds that
    id straight to the confirmation barrier -- a test can only prove which
    bubbles were waited on if each one is individually named. `timeline` is
    shared with FakeConfirmations so send-vs-wait order is assertable, not
    two independent facts.
    """

    def __init__(self, timeline: list[str] | None = None, media: bytes = b"") -> None:
        self.timeline: list[str] = [] if timeline is None else timeline
        self.texts: list[tuple[str | None, str]] = []
        self.contact_requests: list[tuple[str, str]] = []
        self.buttons: list[tuple[str, str, list[Button]]] = []
        self.typing: list[str] = []
        self.reactions: list[tuple[str, str, str]] = []
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._wamids = 0
        self._media = media
        self.media_ids: list[str] = []
        self.downloads: list[str] = []

    def _record(self, kind: str, **fields: Any) -> str:
        """Log one outbound send and mint the wamid WhatsApp would return."""
        self._wamids += 1
        wamid = f"wamid.out{self._wamids}"
        self.sent.append((kind, fields))
        self.timeline.append(f"sent:{wamid}")
        return wamid

    @property
    def kinds(self) -> list[str]:
        """Which send was called, in call order."""
        return [kind for kind, _ in self.sent]

    async def send_text(self, to: str | None, body: str) -> str:
        self.texts.append((to, body))
        return self._record("text", to=to, body=body)

    async def show_typing(self, message_id: str) -> None:
        self.typing.append(message_id)

    async def send_contact_request(self, to: str, body: str) -> str:
        self.contact_requests.append((to, body))
        return self._record("contact_request", to=to, body=body)

    async def send_buttons(self, to: str, body: str, buttons: list[Button]) -> str:
        self.buttons.append((to, body, buttons))
        return self._record("buttons", to=to, body=body, buttons=buttons)

    async def send_reaction(self, to: str, message_id: str, emoji: str) -> str:
        self.reactions.append((to, message_id, emoji))
        return self._record("reaction", to=to, message_id=message_id, emoji=emoji)

    async def send_image(self, to: str, link: str, caption: str) -> str:
        return self._record("image", to=to, link=link, caption=caption)

    async def send_document(self, to: str, link: str, filename: str, caption: str) -> str:
        return self._record("document", to=to, link=link, filename=filename, caption=caption)

    async def send_list(
        self, to: str, body: str, button_label: str, rows: list[Any]
    ) -> str:
        return self._record("list", to=to, body=body, button_label=button_label, rows=rows)

    async def send_url(self, to: str, body: str, display_text: str, url: str) -> str:
        return self._record("url", to=to, body=body, display_text=display_text, url=url)

    async def send_location_request(self, to: str, body: str) -> str:
        return self._record("location_request", to=to, body=body)

    async def send_contact(self, to: str) -> str:
        return self._record("contact", to=to)

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
        return self._record(
            "flow",
            to=to,
            flow_id=flow_id,
            flow_token=flow_token,
            body=body,
            cta=cta,
            screen=screen,
            data=data,
        )

    async def get_media_url(self, media_id: str) -> str:
        self.media_ids.append(media_id)
        return f"https://lookaside.test/{media_id}"

    async def download_media(self, url: str) -> bytes:
        self.downloads.append(url)
        return self._media


class FakeConfirmations:
    """DeliveryConfirmations stand-in: records which wamids were waited on.

    Shares `timeline` with FakeWhatsApp so a test can assert that each bubble
    was confirmed *before* the next one was sent, rather than only that both
    happened.
    """

    def __init__(self, timeline: list[str] | None = None) -> None:
        self.timeline: list[str] = [] if timeline is None else timeline
        self.waited: list[str] = []

    async def wait(self, wamid: str) -> None:
        self.waited.append(wamid)
        self.timeline.append(f"confirmed:{wamid}")


class FakeFlows:
    """FlowLauncher stand-in: records each launch and echoes the launch bubble body."""

    def __init__(self, body: str = "Let's set up your profile.") -> None:
        self._body = body
        self.launched: list[tuple[Persona, str, str]] = []
        self.forms: list[tuple[str, Any]] = []
        self._wamids = 0

    async def onboarding(self, persona: Persona, sender_phone: str, name: str) -> str:
        self.launched.append((persona, sender_phone, name))
        return self._body

    async def launch(self, user: UserProfile, form: Any) -> str:
        self.forms.append((user.userId, form))
        self._wamids += 1
        return f"wamid.flow{self._wamids}"


class FakeInputs:
    """AgentInputBuilder stand-in: records which render path was taken."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.replayed: list[Any] = []

    async def content(self, inbound: Any, user: UserProfile, usage: list[Any]) -> Message:
        self.calls.append("content")
        # A voice note bills transcription onto the caller's own list, exactly
        # as the real MediaFetcher does; a copied or discarded list must show it.
        usage.append(AudioUsage(model="gpt-transcribe", seconds=4.2))
        return tagged("content")

    def tapped(self, inbound: Any) -> Message:
        self.calls.append("tapped")
        return tagged("tapped")

    def contact(self) -> Message:
        self.calls.append("contact")
        return tagged("contact")

    def location(self, inbound: Any) -> Message:
        self.calls.append("location")
        return tagged("location")

    def profile_updated(self) -> Message:
        self.calls.append("profile_updated")
        return tagged("profile_updated")

    async def replay(self, messages: list[Any], user: UserProfile, usage: list[Any]) -> Message:
        self.calls.append("replay")
        self.replayed = messages
        return tagged("replay")

    async def from_flow_completion(self, inbound: Any, user: UserProfile, route: str) -> Message:
        self.calls.append(f"flow:{route}")
        return tagged(f"flow:{route}")


class FakeOnboarding:
    """OnboardingCoordinator stand-in: records delegation, returns a scripted turn."""

    def __init__(self, handled: TurnInput | None = None) -> None:
        self._handled = handled
        self.phone_requests: list[Any] = []
        self.handled_with: list[tuple[Any, PendingAction | None]] = []

    async def request_phone(self, inbound: Any) -> None:
        self.phone_requests.append(inbound)

    async def handle(self, inbound: Any, pending: PendingAction | None) -> TurnInput | None:
        self.handled_with.append((inbound, pending))
        return self._handled


class FakePending:
    """OnboardingRepository stand-in: one scripted pending action per sender.

    `saved` keeps every write in order, since the state machine's whole output
    is the action it leaves behind: which step is required, what is buffered on
    it, and which bubbles are on record.
    """

    def __init__(self, pending: PendingAction | None = None) -> None:
        self._pending = pending
        self.cleared: list[str] = []
        self.saved: list[tuple[str, PendingAction]] = []

    async def get(self, sender_id: str) -> PendingAction | None:
        return self._pending

    async def set(self, sender_id: str, pending: PendingAction) -> None:
        self.saved.append((sender_id, pending))
        self._pending = pending

    async def clear(self, sender_id: str) -> None:
        self.cleared.append(sender_id)

    @property
    def latest(self) -> PendingAction:
        """The action left behind by the last write."""
        assert self.saved, "nothing was persisted"
        return self.saved[-1][1]

    @property
    def last_said(self) -> OutboundMessage:
        """The most recent bubble put on record by the last write."""
        said = self.latest.said
        assert said, "the action was persisted with no bubble on record"
        return said[-1]


class FakeBucket:
    """GcsBucket stand-in. Records uploads so a test can see the stored name
    and bytes without talking to GCS.
    """

    name = "media-bucket"

    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []

    def public_url(self, object_name: str) -> str:
        return f"https://media.test/{self.name}/{object_name}"

    async def upload(self, object_name: str, data: bytes, content_type: str) -> None:
        self.uploads.append((object_name, data, content_type))


class FakeFetcher:
    """MediaFetcher stand-in: records the media store and usage list it was handed."""

    def __init__(self, parts: list[Any] | None = None) -> None:
        self._parts = parts if parts is not None else [TextContent(text="<fetched>")]
        self.fetched: list[Any] = []
        self.scopes: list[Any] = []
        self.usage_lists: list[list[Any]] = []

    async def fetch(self, message: Any, media: Any, usage: list[Any]) -> list[Any]:
        self.fetched.append(message)
        self.scopes.append(media.scope)
        self.usage_lists.append(usage)
        return self._parts


class FakeUploads:
    """FlowUploadFetcher stand-in: records what it was asked to persist."""

    def __init__(self, parts: list[Any] | None = None) -> None:
        self._parts = parts if parts is not None else []
        self.submissions: list[tuple[Any, Any, str]] = []

    async def fetch_grade_submission(
        self, payload: Any, media: Any, message_id: str
    ) -> list[Any]:
        self.submissions.append((payload, media.scope, message_id))
        return self._parts


class FakeTextAgent:
    """TextAgentClient stand-in: echoes a scripted response, records the replay it saw."""

    def __init__(self, response: GenerateResponse) -> None:
        self._response = response
        self.asked_with: list[list[TranscriptMessage]] = []

    async def respond(
        self, user: UserProfile, thread_key: str, messages: list[TranscriptMessage]
    ) -> GenerateResponse:
        self.asked_with.append(messages)
        # The real call is a network round trip. Yielding here lets the typing
        # pulse actually run, so a test can observe it instead of racing it.
        await asyncio.sleep(0)
        return self._response


class FakeDelivery:
    """ReplyDelivery stand-in: records what was sent, to whom, against which inbound."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.sent: list[tuple[str, str, GenerateResponse]] = []

    async def send(
        self, user: UserProfile, inbound_message_id: str, reply: GenerateResponse
    ) -> None:
        if self._error is not None:
            raise self._error
        self.sent.append((user.userId, inbound_message_id, reply))


@dataclass
class FakeUsage:
    """UsageRepository stand-in: the billing ledger, in booking order."""

    records: list[UsageRecord] = field(default_factory=list)

    async def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    def of_kind(self, kind: str) -> list[UsageRecord]:
        """Every booking of one kind, oldest first."""
        return [record for record in self.records if record.kind == kind]


@dataclass
class FakeConversions:
    """ConversionsReporter stand-in. Sync on purpose: reporting never awaits the turn."""

    reported: list[tuple[str, AppendTranscriptResult]] = field(default_factory=list)

    def report(self, user: UserProfile, result: AppendTranscriptResult) -> None:
        self.reported.append((user.userId, result))


class FakeRunner:
    """ReplyRunner stand-in: records the ledger calls in the order they happened.

    `on_generate` lets a test simulate a message landing mid-generation, which
    is the one condition deciding whether the loop speaks or keeps batching.
    """

    def __init__(
        self,
        on_generate: Callable[[], None] | None = None,
        fail_generate: bool = False,
    ) -> None:
        self._on_generate = on_generate
        self._fail_generate = fail_generate
        self.calls: list[str] = []
        self.recorded: list[TurnInput] = []
        self.delivered: list[tuple[PendingTurn, Any]] = []
        self.failed: list[PendingTurn] = []

    async def record(self, turn: PendingTurn | None, contribution: TurnInput) -> PendingTurn:
        self.calls.append("record")
        self.recorded.append(contribution)
        if turn is None:
            return PendingTurn(
                user=contribution.user,
                inbound_ids=[contribution.inbound_id],
                started_at_ms=1,
            )
        turn.inbound_ids.append(contribution.inbound_id)
        return turn

    async def generate(self, turn: PendingTurn) -> str:
        self.calls.append("generate")
        if self._on_generate is not None:
            self._on_generate()
        if self._fail_generate:
            raise RuntimeError("generation failed")
        return "response"

    async def deliver(self, turn: PendingTurn, response: Any) -> None:
        self.calls.append("deliver")
        self.delivered.append((turn, response))

    async def fail(self, turn: PendingTurn) -> None:
        self.calls.append("fail")
        self.failed.append(turn)
