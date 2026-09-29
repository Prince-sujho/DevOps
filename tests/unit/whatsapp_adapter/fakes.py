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
        """Each row's role, in append order.

        Args:
            None.
        Returns:
            Each row's role, in append order.
        Raises:
            None.
        """
        return [row.role for row in self.rows]

    @property
    def turn_ids(self) -> list[str]:
        """Each row's turn id, in append order.

        Args:
            None.
        Returns:
            Each row's turn id, in append order.
        Raises:
            None.
        """
        return [row.turnId for row in self.rows]

    @property
    def response_ids(self) -> list[str | None]:
        """Each row's response id, in append order.

        Args:
            None.
        Returns:
            Each row's response id, in append order.
        Raises:
            None.
        """
        return [row.responseId for row in self.rows]


def tagged(kind: str) -> Message:
    """A model message tagged with the builder path that produced it.

    Args:
        kind: the builder path name to tag the message with.
    Returns:
        The tagged Message.
    Raises:
        None.
    """
    return Message(parts=[TextContent(text=f"<{kind}>")])


def tag_of(message: Message) -> str:
    """The builder path a tagged message came from.

    Args:
        message: a message built by tagged().
    Returns:
        The tag it was built with.
    Raises:
        None.
    """
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
        """Script the access decision and the profiles that writes echo back.

        Args:
            access: resolve_phone's scripted result.
            refreshed: profile returned by set_location/update_profile writes.
            created: profile returned by create_user.
            create_error: exception create_user should raise instead.
            replay: get_session_replay's scripted result.
            opened_session_number: openedSessionNumber for an unpinned append.
            gift_card: get_gift_card's scripted result.
        Returns:
            None.
        Raises:
            None.
        """
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

    async def get_gift_card(
        self, user_id: str, gift_card_id: str
    ) -> GiftCardDelivery:
        """Record the read and return the scripted gift card.

        Args:
            user_id: the user the card belongs to.
            gift_card_id: the card id requested.
        Returns:
            The scripted gift card.
        Raises:
            AssertionError: no gift card was scripted.
        """
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
        """Record the call; an unpinned append opens/resolves a session, a
        pinned one doesn't.

        Args:
            user_id: the user the transcript belongs to.
            thread_key: the thread the messages are appended to.
            rows: the transcript rows being appended.
            read_ids: node ids being marked read by this append.
            started_at_ms: pin to this session, or None to open/resolve one.
        Returns:
            The scripted or derived AppendTranscriptResult.
        Raises:
            None.
        """
        self.appends.append(
            Append(user_id, thread_key, rows, read_ids, started_at_ms)
        )
        if started_at_ms is None:
            # Only an unpinned append resolves -- or opens -- a session.
            return AppendTranscriptResult(
                startedAtMs=SESSION_MS, openedSessionNumber=self._opened
            )
        return AppendTranscriptResult(
            startedAtMs=started_at_ms, openedSessionNumber=None
        )

    async def get_session_replay(
        self, user_id: str, thread_key: str, started_at_ms: int
    ) -> SessionTranscript:
        """Record the read and return the scripted session transcript.

        Args:
            user_id: the user the session belongs to.
            thread_key: the thread the session is under.
            started_at_ms: the session's start time.
        Returns:
            The scripted session transcript.
        Raises:
            AssertionError: no session replay was scripted.
        """
        self.replays_read.append((user_id, thread_key, started_at_ms))
        assert self._replay is not None, "test did not script a session replay"
        return self._replay

    async def create_user(self, request: CreateUserRequest) -> UserProfile:
        """Record the request; return the scripted profile, or raise the
        scripted error.

        Args:
            request: the create-user request being recorded.
        Returns:
            The scripted created profile.
        Raises:
            Exception: the scripted create_error, if one was set.
            AssertionError: no created profile was scripted and no error was
                set.
        """
        self.created.append(request)
        if self._create_error is not None:
            raise self._create_error
        assert self._created is not None, (
            "test did not script a created profile"
        )
        return self._created

    async def resolve_phone(self, phone: str) -> ResolveAccessResult:
        """Record the phone and return the scripted access decision.

        Args:
            phone: the phone number being resolved.
        Returns:
            The scripted access decision.
        Raises:
            AssertionError: no access decision was scripted.
        """
        self.resolved.append(phone)
        assert self._access is not None, (
            "test did not script an access decision"
        )
        return self._access

    async def set_location(
        self, user_id: str, location: UserLocation
    ) -> UserProfile:
        """Record the write and return the write-echo profile.

        Args:
            user_id: the user being updated.
            location: the location being set.
        Returns:
            The write-echo profile (refreshed, or the scripted access user).
        Raises:
            None.
        """
        self.locations.append((user_id, location))
        return self._write_result()

    async def update_profile(
        self, user_id: str, update: ProfileUpdate
    ) -> UserProfile:
        """Record the write and return the write-echo profile.

        Args:
            user_id: the user being updated.
            update: the profile fields being set.
        Returns:
            The write-echo profile (refreshed, or the scripted access user).
        Raises:
            None.
        """
        self.profile_updates.append((user_id, update))
        return self._write_result()

    def _write_result(self) -> UserProfile:
        """What the user service echoes back after a profile write.

        Args:
            None.
        Returns:
            The refreshed profile if one was scripted, otherwise the access
            user's profile.
        Raises:
            AssertionError: no refreshed profile and no scripted access user.
        """
        if self._refreshed is not None:
            return self._refreshed
        assert self._access is not None and self._access.user is not None
        return self._access.user


class FakeWhatsApp:
    """WhatsAppClient stand-in: records the bubbles that went out, in order.

    Every send returns a distinct wamid, because the delivery path feeds that id
    straight to the confirmation barrier -- a test can only prove which bubbles
    were waited on if each one is individually named. `timeline` is shared with
    FakeConfirmations so send-vs-wait order is assertable, not two independent
    facts.
    """

    def __init__(
        self, timeline: list[str] | None = None, media: bytes = b""
    ) -> None:
        """An empty send log; media downloads return media (default empty
        bytes).

        Args:
            timeline: shared send/confirm event log; a fresh list if None.
            media: bytes download_media always returns.
        Returns:
            None.
        Raises:
            None.
        """
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
        """Log one outbound send and mint the wamid WhatsApp would return.

        Args:
            kind: the send kind (text/image/buttons/etc) being recorded.
            fields: the send's recorded field values.
        Returns:
            A fresh, distinct wamid.
        Raises:
            None.
        """
        self._wamids += 1
        wamid = f"wamid.out{self._wamids}"
        self.sent.append((kind, fields))
        self.timeline.append(f"sent:{wamid}")
        return wamid

    @property
    def kinds(self) -> list[str]:
        """Which send was called, in call order.

        Args:
            None.
        Returns:
            The kind of each send, in call order.
        Raises:
            None.
        """
        return [kind for kind, _ in self.sent]

    async def send_text(self, to: str | None, body: str) -> str:
        """Record the text and send it, returning a fresh wamid.

        Args:
            to: the recipient phone, or None.
            body: the text body.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        self.texts.append((to, body))
        return self._record("text", to=to, body=body)

    async def show_typing(self, message_id: str) -> None:
        """Record the typing pulse.

        Args:
            message_id: the inbound message the typing pulse responds to.
        Returns:
            None.
        Raises:
            None.
        """
        self.typing.append(message_id)

    async def send_contact_request(self, to: str, body: str) -> str:
        """Record the contact request and send it, returning a fresh wamid.

        Args:
            to: the recipient phone.
            body: the request body text.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        self.contact_requests.append((to, body))
        return self._record("contact_request", to=to, body=body)

    async def send_buttons(
        self, to: str, body: str, buttons: list[Button]
    ) -> str:
        """Record the buttons message and send it, returning a fresh wamid.

        Args:
            to: the recipient phone.
            body: the message body text.
            buttons: the buttons offered.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        self.buttons.append((to, body, buttons))
        return self._record("buttons", to=to, body=body, buttons=buttons)

    async def send_reaction(self, to: str, message_id: str, emoji: str) -> str:
        """Record the reaction and send it, returning a fresh wamid.

        Args:
            to: the recipient phone.
            message_id: the message being reacted to.
            emoji: the reaction emoji.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        self.reactions.append((to, message_id, emoji))
        return self._record(
            "reaction", to=to, message_id=message_id, emoji=emoji
        )

    async def send_image(self, to: str, link: str, caption: str) -> str:
        """Send an image bubble, returning a fresh wamid.

        Args:
            to: the recipient phone.
            link: the image URL.
            caption: the image caption.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("image", to=to, link=link, caption=caption)

    async def send_document(
        self, to: str, link: str, filename: str, caption: str
    ) -> str:
        """Send a document bubble, returning a fresh wamid.

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
            "document", to=to, link=link, filename=filename, caption=caption
        )

    async def send_list(
        self, to: str, body: str, button_label: str, rows: list[Any]
    ) -> str:
        """Send a list bubble, returning a fresh wamid.

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
            "list", to=to, body=body, button_label=button_label, rows=rows
        )

    async def send_url(
        self, to: str, body: str, display_text: str, url: str
    ) -> str:
        """Send a URL bubble, returning a fresh wamid.

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
            "url", to=to, body=body, display_text=display_text, url=url
        )

    async def send_location_request(self, to: str, body: str) -> str:
        """Send a location-request bubble, returning a fresh wamid.

        Args:
            to: the recipient phone.
            body: the request body text.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
        return self._record("location_request", to=to, body=body)

    async def send_contact(self, to: str) -> str:
        """Send a contact-share bubble, returning a fresh wamid.

        Args:
            to: the recipient phone.
        Returns:
            A fresh wamid.
        Raises:
            None.
        """
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
        """Send a flow bubble, returning a fresh wamid.

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
            to=to,
            flow_id=flow_id,
            flow_token=flow_token,
            body=body,
            cta=cta,
            screen=screen,
            data=data,
        )

    async def get_media_url(self, media_id: str) -> str:
        """Record the lookup and return a fake lookaside URL.

        Args:
            media_id: the media id being looked up.
        Returns:
            A fake lookaside URL for media_id.
        Raises:
            None.
        """
        self.media_ids.append(media_id)
        return f"https://lookaside.test/{media_id}"

    async def download_media(self, url: str) -> bytes:
        """Record the download and return the scripted media bytes.

        Args:
            url: the media URL being downloaded.
        Returns:
            The scripted media bytes.
        Raises:
            None.
        """
        self.downloads.append(url)
        return self._media


class FakeConfirmations:
    """DeliveryConfirmations stand-in: records which wamids were waited on.

    Shares `timeline` with FakeWhatsApp so a test can assert that each bubble
    was confirmed *before* the next one was sent, rather than only that both
    happened.
    """

    def __init__(self, timeline: list[str] | None = None) -> None:
        """An empty wait log, sharing timeline with a FakeWhatsApp.

        Args:
            timeline: shared log of waited-on ids, or None to start empty.
        Returns:
            None.
        Raises:
            None.
        """
        self.timeline: list[str] = [] if timeline is None else timeline
        self.waited: list[str] = []

    async def wait(self, wamid: str) -> None:
        """Record wamid as waited-on and append it to the shared timeline.

        Args:
            wamid: WhatsApp message id recorded as waited-on.
        Returns:
            None.
        Raises:
            None.
        """
        self.waited.append(wamid)
        self.timeline.append(f"confirmed:{wamid}")


class FakeFlows:
    """FlowLauncher stand-in: records each launch and echoes the launch bubble
    body.
    """

    def __init__(self, body: str = "Let's set up your profile.") -> None:
        """No launches recorded yet.

        Args:
            body: the scripted onboarding launch bubble body.
        Returns:
            None.
        Raises:
            None.
        """
        self._body = body
        self.launched: list[tuple[Persona, str, str]] = []
        self.forms: list[tuple[str, Any]] = []
        self._wamids = 0

    async def onboarding(
        self, persona: Persona, sender_phone: str, name: str
    ) -> str:
        """Record the onboarding launch and return the scripted bubble body.

        Args:
            persona: the persona the onboarding flow is for.
            sender_phone: the recipient's phone.
            name: the recipient's name.
        Returns:
            The scripted bubble body.
        Raises:
            None.
        """
        self.launched.append((persona, sender_phone, name))
        return self._body

    async def launch(self, user: UserProfile, form: Any) -> str:
        """Record the form launch and return a fresh flow wamid.

        Args:
            user: the profile the form is launched for.
            form: the form payload being launched.
        Returns:
            A fresh flow wamid.
        Raises:
            None.
        """
        self.forms.append((user.userId, form))
        self._wamids += 1
        return f"wamid.flow{self._wamids}"


class FakeInputs:
    """AgentInputBuilder stand-in: records which render path was taken."""

    def __init__(self) -> None:
        """No calls recorded yet.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[str] = []
        self.replayed: list[Any] = []

    async def content(
        self, inbound: Any, user: UserProfile, usage: list[Any]
    ) -> Message:
        """Record the call, bill a fake transcription, and return a tagged
        content message.

        Args:
            inbound: the inbound message being rendered.
            user: the profile the turn is for.
            usage: the usage list to bill a fake transcription onto.
        Returns:
            A message tagged "content".
        Raises:
            None.
        """
        self.calls.append("content")
        # A voice note bills transcription onto the caller's own list, exactly
        # as the real MediaFetcher does; a copied or discarded list must show
        # it.
        usage.append(AudioUsage(model="gpt-transcribe", seconds=4.2))
        return tagged("content")

    def tapped(self, inbound: Any) -> Message:
        """Record the call and return a tagged tapped message.

        Args:
            inbound: the inbound tap being rendered.
        Returns:
            A message tagged "tapped".
        Raises:
            None.
        """
        self.calls.append("tapped")
        return tagged("tapped")

    def contact(self) -> Message:
        """Record the call and return a tagged contact message.

        Args:
            None.
        Returns:
            A message tagged "contact".
        Raises:
            None.
        """
        self.calls.append("contact")
        return tagged("contact")

    def location(self, inbound: Any) -> Message:
        """Record the call and return a tagged location message.

        Args:
            inbound: the inbound location being rendered.
        Returns:
            A message tagged "location".
        Raises:
            None.
        """
        self.calls.append("location")
        return tagged("location")

    def profile_updated(self) -> Message:
        """Record the call and return a tagged profile_updated message.

        Args:
            None.
        Returns:
            A message tagged "profile_updated".
        Raises:
            None.
        """
        self.calls.append("profile_updated")
        return tagged("profile_updated")

    async def replay(
        self, messages: list[Any], user: UserProfile, usage: list[Any]
    ) -> Message:
        """Record the call and messages replayed, and return a tagged replay
        message.

        Args:
            messages: the messages being replayed.
            user: the profile the turn is for.
            usage: the usage list (unused by this fake, kept for the real
                signature).
        Returns:
            A message tagged "replay".
        Raises:
            None.
        """
        self.calls.append("replay")
        self.replayed = messages
        return tagged("replay")

    async def from_flow_completion(
        self, inbound: Any, user: UserProfile, route: str
    ) -> Message:
        """Record the call and return a message tagged with the completed flow
        route.

        Args:
            inbound: the flow-completion payload being rendered.
            user: the profile the turn is for.
            route: the completed flow's route name.
        Returns:
            A message tagged "flow:<route>".
        Raises:
            None.
        """
        self.calls.append(f"flow:{route}")
        return tagged(f"flow:{route}")


class FakeOnboarding:
    """OnboardingCoordinator stand-in: records delegation, returns a scripted
    turn.
    """

    def __init__(self, handled: TurnInput | None = None) -> None:
        """No phone requests or handled turns recorded yet.

        Args:
            handled: a turn already marked handled, or None.
        Returns:
            None.
        Raises:
            None.
        """
        self._handled = handled
        self.phone_requests: list[Any] = []
        self.handled_with: list[tuple[Any, PendingAction | None]] = []

    async def request_phone(self, inbound: Any) -> None:
        """Record the phone-request delegation.

        Args:
            inbound: the inbound message that triggered the phone request.
        Returns:
            None.
        Raises:
            None.
        """
        self.phone_requests.append(inbound)

    async def handle(
        self, inbound: Any, pending: PendingAction | None
    ) -> TurnInput | None:
        """Record the delegation and return the scripted turn input.

        Args:
            inbound: the inbound message being handled.
            pending: the sender's current pending action, or None.
        Returns:
            The scripted turn input, or None.
        Raises:
            None.
        """
        self.handled_with.append((inbound, pending))
        return self._handled


class FakePending:
    """OnboardingRepository stand-in: one scripted pending action per sender.

    `saved` keeps every write in order, since the state machine's whole output
    is the action it leaves behind: which step is required, what is buffered on
    it, and which bubbles are on record.
    """

    def __init__(self, pending: PendingAction | None = None) -> None:
        """The scripted pending action, or None.

        Args:
            pending: the pending action get() returns, or None.
        Returns:
            None.
        Raises:
            None.
        """
        self._pending = pending
        self.cleared: list[str] = []
        self.saved: list[tuple[str, PendingAction]] = []

    async def get(self, sender_id: str) -> PendingAction | None:
        """Return the currently scripted/stored pending action for sender_id.

        Args:
            sender_id: the sender whose pending action is returned.
        Returns:
            The stored pending action.
        Raises:
            None.
        """
        return self._pending

    async def set(self, sender_id: str, pending: PendingAction) -> None:
        """Record the write and store pending as the new current action.

        Args:
            sender_id: the sender the action belongs to.
            pending: the action being stored.
        Returns:
            None.
        Raises:
            None.
        """
        self.saved.append((sender_id, pending))
        self._pending = pending

    async def clear(self, sender_id: str) -> None:
        """Record sender_id as cleared.

        Args:
            sender_id: the sender recorded as cleared.
        Returns:
            None.
        Raises:
            None.
        """
        self.cleared.append(sender_id)

    @property
    def latest(self) -> PendingAction:
        """The action left behind by the last write.

        Args:
            None.
        Returns:
            The pending action stored by the most recent write.
        Raises:
            AssertionError: nothing was persisted.
        """
        assert self.saved, "nothing was persisted"
        return self.saved[-1][1]

    @property
    def last_said(self) -> OutboundMessage:
        """The most recent bubble put on record by the last write.

        Args:
            None.
        Returns:
            The last outbound message recorded by the most recent write.
        Raises:
            AssertionError: the action was persisted with no bubble on record.
        """
        said = self.latest.said
        assert said, "the action was persisted with no bubble on record"
        return said[-1]


class FakeBucket:
    """GcsBucket stand-in. Records uploads so a test can see the stored name
    and bytes without talking to GCS.
    """

    name = "media-bucket"

    def __init__(self) -> None:
        """An empty upload log.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.uploads: list[tuple[str, bytes, str]] = []

    def public_url(self, object_name: str) -> str:
        """The fake public URL for object_name under this bucket.

        Args:
            object_name: object key to build a public URL for.
        Returns:
            The fake media URL for object_name in this bucket.
        Raises:
            None.
        """
        return f"https://media.test/{self.name}/{object_name}"

    async def upload(
        self, object_name: str, data: bytes, content_type: str
    ) -> None:
        """Record the upload.

        Args:
            object_name: the object's storage path.
            data: the bytes being uploaded.
            content_type: the upload's declared content type.
        Returns:
            None.
        Raises:
            None.
        """
        self.uploads.append((object_name, data, content_type))


class FakeFetcher:
    """MediaFetcher stand-in: records the media store and usage list it was
    handed.
    """

    def __init__(self, parts: list[Any] | None = None) -> None:
        """Scripted parts to return from fetch (default one tagged text part).

        Args:
            parts: parts fetch() returns, or None for one tagged text part.
        Returns:
            None.
        Raises:
            None.
        """
        self._parts = (
            parts if parts is not None else [TextContent(text="<fetched>")]
        )
        self.fetched: list[Any] = []
        self.scopes: list[Any] = []
        self.usage_lists: list[list[Any]] = []

    async def fetch(
        self, message: Any, media: Any, usage: list[Any]
    ) -> list[Any]:
        """Record the call, scope, and usage list handed in; return the scripted
        parts.

        Args:
            message: the inbound message media is being fetched for.
            media: the media reference, whose .scope is recorded.
            usage: the usage list handed in.
        Returns:
            The scripted parts.
        Raises:
            None.
        """
        self.fetched.append(message)
        self.scopes.append(media.scope)
        self.usage_lists.append(usage)
        return self._parts


class FakeUploads:
    """FlowUploadFetcher stand-in: records what it was asked to persist."""

    def __init__(self, parts: list[Any] | None = None) -> None:
        """Scripted parts to return from fetch_grade_submission (default none).

        Args:
            parts: parts fetch_grade_submission() returns, or None for none.
        Returns:
            None.
        Raises:
            None.
        """
        self._parts = parts if parts is not None else []
        self.submissions: list[tuple[Any, Any, str]] = []

    async def fetch_grade_submission(
        self, payload: Any, media: Any, message_id: str
    ) -> list[Any]:
        """Record the submission and return the scripted parts.

        Args:
            payload: the grade-submission payload.
            media: the media reference, whose .scope is recorded.
            message_id: the inbound message id the submission came from.
        Returns:
            The scripted parts.
        Raises:
            None.
        """
        self.submissions.append((payload, media.scope, message_id))
        return self._parts


class FakeTextAgent:
    """TextAgentClient stand-in: echoes a scripted response, records the replay
    it saw.
    """

    def __init__(self, response: GenerateResponse) -> None:
        """The scripted response this client always returns.

        Args:
            response: the GenerateResponse returned from every call.
        Returns:
            None.
        Raises:
            None.
        """
        self._response = response
        self.asked_with: list[list[TranscriptMessage]] = []

    async def respond(
        self,
        user: UserProfile,
        thread_key: str,
        messages: list[TranscriptMessage],
    ) -> GenerateResponse:
        """Record the messages asked with, yield once, and return the scripted
        response.

        Args:
            user: the profile the turn is for.
            thread_key: the thread the turn belongs to.
            messages: the transcript messages sent as context.
        Returns:
            The scripted GenerateResponse.
        Raises:
            None.
        """
        self.asked_with.append(messages)
        # The real call is a network round trip. Yielding here lets the typing
        # pulse actually run, so a test can observe it instead of racing it.
        await asyncio.sleep(0)
        return self._response


class FakeDelivery:
    """ReplyDelivery stand-in: records what was sent, to whom, against which
    inbound.
    """

    def __init__(self, error: Exception | None = None) -> None:
        """No sends recorded yet; optionally scripted to raise on send.

        Args:
            error: exception send() should raise instead of recording, or None.
        Returns:
            None.
        Raises:
            None.
        """
        self._error = error
        self.sent: list[tuple[str, str, GenerateResponse]] = []

    async def send(
        self,
        user: UserProfile,
        inbound_message_id: str,
        reply: GenerateResponse,
    ) -> None:
        """Record the send, or raise the scripted error.

        Args:
            user: the recipient profile.
            inbound_message_id: the inbound message this reply answers.
            reply: the reply being sent.
        Returns:
            None.
        Raises:
            Exception: the scripted error, if one was set.
        """
        if self._error is not None:
            raise self._error
        self.sent.append((user.userId, inbound_message_id, reply))


@dataclass
class FakeUsage:
    """UsageRepository stand-in: the billing ledger, in booking order."""

    records: list[UsageRecord] = field(default_factory=list)

    async def record(self, usage: UsageRecord) -> None:
        """Book one usage record.

        Args:
            usage: the usage record to book.
        Returns:
            None.
        Raises:
            None.
        """
        self.records.append(usage)

    def of_kind(self, kind: str) -> list[UsageRecord]:
        """Every booking of one kind, oldest first.

        Args:
            kind: usage kind to filter for.
        Returns:
            Usage records of that kind, oldest first.
        Raises:
            None.
        """
        return [record for record in self.records if record.kind == kind]


@dataclass
class FakeConversions:
    """ConversionsReporter stand-in. Sync on purpose: reporting never awaits the
    turn.
    """

    reported: list[tuple[str, AppendTranscriptResult]] = field(
        default_factory=list
    )

    def report(self, user: UserProfile, result: AppendTranscriptResult) -> None:
        """Record the reported conversion.

        Args:
            user: the user the conversion is attributed to.
            result: the append result the conversion is derived from.
        Returns:
            None.
        Raises:
            None.
        """
        self.reported.append((user.userId, result))


class FakeRunner:
    """ReplyRunner stand-in: records the ledger calls in the order they
    happened.

    `on_generate` lets a test simulate a message landing mid-generation, which
    is the one condition deciding whether the loop speaks or keeps batching.
    """

    def __init__(
        self,
        on_generate: Callable[[], None] | None = None,
        fail_generate: bool = False,
    ) -> None:
        """No calls recorded yet; optionally scripted generate behavior.

        Args:
            on_generate: called during generate(), before it succeeds/fails, or
                None.
            fail_generate: whether generate() should raise instead of
                succeeding.
        Returns:
            None.
        Raises:
            None.
        """
        self._on_generate = on_generate
        self._fail_generate = fail_generate
        self.calls: list[str] = []
        self.recorded: list[TurnInput] = []
        self.delivered: list[tuple[PendingTurn, Any]] = []
        self.failed: list[PendingTurn] = []

    async def record(
        self, turn: PendingTurn | None, contribution: TurnInput
    ) -> PendingTurn:
        """Record the contribution and start or extend the pending turn.

        Args:
            turn: the pending turn to extend, or None to start one.
            contribution: the turn input being recorded.
        Returns:
            The existing turn with contribution appended, or a new PendingTurn
            when turn is None.
        Raises:
            None.
        """
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
        """Record the call, optionally invoke on_generate, then succeed or raise
        as scripted.

        Args:
            turn: the pending turn being generated for.
        Returns:
            A fixed "response" string.
        Raises:
            RuntimeError: fail_generate was set.
        """
        self.calls.append("generate")
        if self._on_generate is not None:
            self._on_generate()
        if self._fail_generate:
            raise RuntimeError("generation failed")
        return "response"

    async def deliver(self, turn: PendingTurn, response: Any) -> None:
        """Record the delivery.

        Args:
            turn: the turn the response was generated for.
            response: the response being delivered.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.append("deliver")
        self.delivered.append((turn, response))

    async def fail(self, turn: PendingTurn) -> None:
        """Record the failure.

        Args:
            turn: the turn that failed.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.append("fail")
        self.failed.append(turn)
