"""Recording stand-ins for I/O wrappers. They do not decide expected values.

Call-argument lists exist so a test can pin the documented identity
(``user_id``, ``handle``, Hubble ``referenceId``) without reading Firestore.
"""

from __future__ import annotations

from infra.clients.users import Ambassador, GiftCard, UserProfile
from infra.hubble.types import HubbleOrder, HubbleProduct, HubbleVoucher


def success_order(
    *,
    card_number: str = "4111111111111111",
    card_pin: str = "9999",
    valid_till: str = "2027-12-31",
) -> HubbleOrder:
    return HubbleOrder(
        status="SUCCESS",
        vouchers=[
            HubbleVoucher(
                cardNumber=card_number, cardPin=card_pin, validTill=valid_till
            )
        ],
    )


def hubble_order(status: str, *, vouchers: list[HubbleVoucher] | None = None) -> HubbleOrder:
    return HubbleOrder(status=status, vouchers=vouchers or [])


class FakeGifting:
    """In-memory gift-card store keyed by the user id the caller passed."""

    def __init__(self) -> None:
        self.cards: dict[str | None, list[GiftCard]] = {}
        self.list_calls: list[object] = []
        self.fail_calls: list[tuple[object, str]] = []
        self.succeed_calls: list[tuple[object, str, object, object, object]] = []
        self.create_pending_calls: list[dict] = []
        self.next_id = "gc-mint-1"

    def seed(self, user_id: str, card: GiftCard) -> None:
        self.cards.setdefault(user_id, []).append(card)

    def _replace(self, user_id: object, card: GiftCard) -> None:
        bucket = self.cards.setdefault(user_id, [])  # type: ignore[arg-type]
        for i, existing in enumerate(bucket):
            if existing.id == card.id:
                bucket[i] = card
                return
        bucket.append(card)

    async def list(self, user_id: str) -> list[GiftCard]:
        self.list_calls.append(user_id)
        return list(self.cards.get(user_id, []))

    async def fail(self, user_id: str, gift_card: GiftCard) -> GiftCard:
        self.fail_calls.append((user_id, gift_card.id))
        updated = gift_card.model_copy(update={"status": "failed"})
        self._replace(user_id, updated)
        return updated

    async def succeed(
        self,
        user_id: str,
        gift_card: GiftCard,
        card_number: str | None,
        card_pin: str | None,
        valid_till: str | None,
    ) -> GiftCard:
        self.succeed_calls.append(
            (user_id, gift_card.id, card_number, card_pin, valid_till)
        )
        updated = gift_card.model_copy(update={"status": "succeeded"})
        self._replace(user_id, updated)
        return updated

    async def create_pending(
        self,
        user_id: str,
        product_id: str,
        brand: str,
        amount_inr: int,
        instructions: str,
        credit_inr: int,
    ) -> GiftCard:
        self.create_pending_calls.append(
            {
                "user_id": user_id,
                "product_id": product_id,
                "brand": brand,
                "amount_inr": amount_inr,
                "instructions": instructions,
            }
        )
        card = GiftCard(
            id=self.next_id,
            productId=product_id,
            brand=brand,
            amountInr=amount_inr,
            status="pending",
            createdAtMs=1_700_000_000_000,
        )
        self._replace(user_id, card)
        return card


class FakeHubble:
    """Scripted Hubble: 404 is ``None``; products default to unofferable."""

    def __init__(self) -> None:
        self.products: dict[str, HubbleProduct] = {}
        self.orders: dict[str, HubbleOrder | None] = {}
        self.get_order_calls: list[object] = []
        self.get_product_calls: list[object] = []
        self.place_order_calls: list[dict] = []
        self.place_order_result: HubbleOrder | None = None

    async def get_product(self, product_id: str) -> HubbleProduct:
        self.get_product_calls.append(product_id)
        if product_id in self.products:
            return self.products[product_id]
        return HubbleProduct(id=product_id, status="INACTIVE")

    async def get_order_by_reference(self, reference_id: str) -> HubbleOrder | None:
        self.get_order_calls.append(reference_id)
        if reference_id not in self.orders:
            return None
        return self.orders[reference_id]

    async def place_order(
        self, product_id: str, reference_id: str, amount_inr: int, customer
    ) -> HubbleOrder:
        self.place_order_calls.append(
            {
                "product_id": product_id,
                "reference_id": reference_id,
                "amount_inr": amount_inr,
            }
        )
        if self.place_order_result is None:
            raise AssertionError("FakeHubble.place_order has no scripted result")
        return self.place_order_result


class FakeUsers:
    def __init__(self) -> None:
        self.profiles_by_id: dict[str, UserProfile] = {}
        self.referred_by_handle: dict[str, list[UserProfile]] = {}
        self.counts_by_handle: dict[str, int] = {}
        self.get_many_calls: list[list[str]] = []
        self.by_persona_calls: list[object] = []
        self.by_referrer_calls: list[object] = []

    def add(self, profile: UserProfile) -> None:
        self.profiles_by_id[profile.userId] = profile

    async def get_many(self, user_ids: list[str]) -> list[UserProfile]:
        self.get_many_calls.append(list(user_ids))
        return [self.profiles_by_id[uid] for uid in user_ids if uid in self.profiles_by_id]

    async def by_referrer(self, handle: str) -> list[UserProfile]:
        self.by_referrer_calls.append(handle)
        return list(self.referred_by_handle.get(handle, []))

    async def count_by_referrer(self, handle: str) -> int:
        return self.counts_by_handle.get(handle, 0)

    async def by_persona(self, persona: str) -> list[UserProfile]:
        self.by_persona_calls.append(persona)
        return [p for p in self.profiles_by_id.values() if p.persona == persona]


class FakeReferrers:
    def __init__(
        self,
        *,
        ambassadors: list[Ambassador] | None = None,
        handles: set[str] | None = None,
    ) -> None:
        self.ambassadors = ambassadors or []
        self.handles = handles if handles is not None else {a.handle for a in self.ambassadors}

    async def list_ambassadors(self) -> list[Ambassador]:
        return list(self.ambassadors)

    async def list_handles(self) -> set[str]:
        return set(self.handles)


class FakeBlocklist:
    def __init__(self, ids: set[str] | None = None) -> None:
        self.ids = ids or set()

    async def list_ids(self) -> set[str]:
        return set(self.ids)


class FakeCampaigns:
    def __init__(self, windows_by_handle: dict[str, list] | None = None) -> None:
        self.windows_by_handle = windows_by_handle or {}
        self.list_calls: list[object] = []

    async def list(self, handle: str) -> list:
        self.list_calls.append(handle)
        return list(self.windows_by_handle.get(handle, []))


class FakeClicks:
    def __init__(
        self,
        *,
        all_by_handle: dict[str, int] | None = None,
        between: dict[tuple[str, int, int], int] | None = None,
    ) -> None:
        self.all_by_handle = all_by_handle or {}
        self.between = between or {}
        self.count_all_calls: list[object] = []
        self.count_between_calls: list[tuple[object, object, object]] = []

    async def count_all(self, handle: str) -> int:
        self.count_all_calls.append(handle)
        return self.all_by_handle.get(handle, 0)

    async def count_between(self, handle: str, start_ms: int, end_ms: int) -> int:
        self.count_between_calls.append((handle, start_ms, end_ms))
        return self.between.get((handle, start_ms, end_ms), 0)


class TextMessage:
    """Duck-typed inbound text: the documented surface is ``.text`` and ``.at_ms``."""

    def __init__(self, text: str, at_ms: int) -> None:
        self.text = text
        self.at_ms = at_ms


class BufferedOnboarding:
    def __init__(self, messages: list[TextMessage]) -> None:
        self.messages = messages


class FakeOnboarding:
    def __init__(self, items: list[BufferedOnboarding]) -> None:
        self.items = items

    async def list_all(self) -> list[BufferedOnboarding]:
        return list(self.items)
