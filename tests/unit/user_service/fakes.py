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
    """A SUCCESS Hubble order carrying one voucher.

    Args:
        card_number: the voucher card number.
        card_pin: the voucher PIN.
        valid_till: the voucher expiry date.
    Returns:
        The HubbleOrder.
    Raises:
        None.
    """
    return HubbleOrder(
        status="SUCCESS",
        vouchers=[
            HubbleVoucher(
                cardNumber=card_number, cardPin=card_pin, validTill=valid_till
            )
        ],
    )


def hubble_order(
    status: str, *, vouchers: list[HubbleVoucher] | None = None
) -> HubbleOrder:
    """A Hubble order with the given status and vouchers.

    Args:
        status: Hubble order status string.
        vouchers: vouchers on the order, or None for none.
    Returns:
        A HubbleOrder with the given status and vouchers, or no vouchers.
    Raises:
        None.
    """
    return HubbleOrder(status=status, vouchers=vouchers or [])


class FakeGifting:
    """In-memory gift-card store keyed by the user id the caller passed."""

    def __init__(self) -> None:
        """An empty gift-card store; no calls recorded yet.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.cards: dict[str | None, list[GiftCard]] = {}
        self.list_calls: list[object] = []
        self.fail_calls: list[tuple[object, str]] = []
        self.succeed_calls: list[
            tuple[object, str, object, object, object]
        ] = []
        self.create_pending_calls: list[dict] = []
        self.next_id = "gc-mint-1"

    def seed(self, user_id: str, card: GiftCard) -> None:
        """Add a gift card for user_id.

        Args:
            user_id: the user the card is stored under.
            card: the gift card to store.
        Returns:
            None.
        Raises:
            None.
        """
        self.cards.setdefault(user_id, []).append(card)

    def _replace(self, user_id: object, card: GiftCard) -> None:
        """Replace an existing card with the same id, or append if not found.

        Args:
            user_id: the card's owner.
            card: the card to store.
        Returns:
            None.
        Raises:
            None.
        """
        bucket = self.cards.setdefault(user_id, [])  # type: ignore[arg-type]
        for i, existing in enumerate(bucket):
            if existing.id == card.id:
                bucket[i] = card
                return
        bucket.append(card)

    async def list(self, user_id: str) -> list[GiftCard]:
        """Record the call and return user_id's stored cards.

        Args:
            user_id: the user whose stored cards are returned.
        Returns:
            user_id's stored gift cards, or an empty list.
        Raises:
            None.
        """
        self.list_calls.append(user_id)
        return list(self.cards.get(user_id, []))

    async def fail(self, user_id: str, gift_card: GiftCard) -> GiftCard:
        """Record the call, mark gift_card failed, and store the update.

        Args:
            user_id: the card's owner.
            gift_card: the card to fail.
        Returns:
            The updated gift card.
        Raises:
            None.
        """
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
        """Record the call, mark gift_card succeeded, and store the update.

        Args:
            user_id: the card's owner.
            gift_card: the card to succeed.
            card_number: the voucher card number.
            card_pin: the voucher PIN.
            valid_till: the voucher expiry date.
        Returns:
            The updated gift card.
        Raises:
            None.
        """
        self.succeed_calls.append(
            (user_id, gift_card.id, card_number, card_pin, valid_till)
        )
        updated = gift_card.model_copy(update={"status": "succeeded"})
        self._replace(user_id, updated)
        return updated

    def _store_pending_card(
        self,
        user_id: str,
        product_id: str,
        brand: str,
        amount_inr: int,
        instructions: str,
    ) -> GiftCard:
        """Record one create_pending call and store the pending card.

        Args:
            user_id: the recipient user.
            product_id: the reward product being minted.
            brand: the gift-card brand.
            amount_inr: the gift-card amount, in INR.
            instructions: redemption instructions.
        Returns:
            The created (pending) gift card.
        Raises:
            None.
        """
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

    async def create_pending(
        self,
        user_id: str,
        product_id: str,
        brand: str,
        amount_inr: int,
        instructions: str,
        credit_inr: int,
    ) -> GiftCard:
        """Record the call and create a pending gift card for user_id.

        Args:
            user_id: the recipient user.
            product_id: the reward product being minted.
            brand: the gift-card brand.
            amount_inr: the gift-card amount, in INR.
            instructions: redemption instructions.
            credit_inr: unused; kept to match the real signature.
        Returns:
            The created (pending) gift card.
        Raises:
            None.
        """
        return self._store_pending_card(
            user_id, product_id, brand, amount_inr, instructions
        )


class FakeHubble:
    """Scripted Hubble: 404 is ``None``; products default to unofferable."""

    def __init__(self) -> None:
        """No products or orders scripted; get_product defaults to INACTIVE.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.products: dict[str, HubbleProduct] = {}
        self.orders: dict[str, HubbleOrder | None] = {}
        self.get_order_calls: list[object] = []
        self.get_product_calls: list[object] = []
        self.place_order_calls: list[dict] = []
        self.place_order_result: HubbleOrder | None = None

    async def get_product(self, product_id: str) -> HubbleProduct:
        """Record the call and return the scripted product, or an INACTIVE
        default.

        Args:
            product_id: the product being looked up.
        Returns:
            The scripted product, or an INACTIVE default.
        Raises:
            None.
        """
        self.get_product_calls.append(product_id)
        if product_id in self.products:
            return self.products[product_id]
        return HubbleProduct(id=product_id, status="INACTIVE")

    async def get_order_by_reference(
        self, reference_id: str
    ) -> HubbleOrder | None:
        """Record the call and return the scripted order, or None if unset.

        Args:
            reference_id: the order reference id being looked up.
        Returns:
            The scripted order, or None.
        Raises:
            None.
        """
        self.get_order_calls.append(reference_id)
        if reference_id not in self.orders:
            return None
        return self.orders[reference_id]

    async def place_order(
        self, product_id: str, reference_id: str, amount_inr: int, customer
    ) -> HubbleOrder:
        """Record the call and return the scripted result, or raise if none is
        set.

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
        self.place_order_calls.append(
            {
                "product_id": product_id,
                "reference_id": reference_id,
                "amount_inr": amount_inr,
            }
        )
        if self.place_order_result is None:
            raise AssertionError(
                "FakeHubble.place_order has no scripted result"
            )
        return self.place_order_result


class FakeUsers:
    def __init__(self) -> None:
        """No profiles seeded yet.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.profiles_by_id: dict[str, UserProfile] = {}
        self.referred_by_handle: dict[str, list[UserProfile]] = {}
        self.counts_by_handle: dict[str, int] = {}
        self.get_many_calls: list[list[str]] = []
        self.by_persona_calls: list[object] = []
        self.by_referrer_calls: list[object] = []

    def add(self, profile: UserProfile) -> None:
        """Index profile by its user id.

        Args:
            profile: the profile to index by its user id.
        Returns:
            None.
        Raises:
            None.
        """
        self.profiles_by_id[profile.userId] = profile

    async def get_many(self, user_ids: list[str]) -> list[UserProfile]:
        """Record the call and return every seeded profile matching user_ids, in
        order found.

        Args:
            user_ids: user ids to look up, in the order to return.
        Returns:
            Seeded profiles whose ids are in user_ids, in that order.
        Raises:
            None.
        """
        self.get_many_calls.append(list(user_ids))
        return [
            self.profiles_by_id[uid]
            for uid in user_ids
            if uid in self.profiles_by_id
        ]

    async def by_referrer(self, handle: str) -> list[UserProfile]:
        """Record the call and return the seeded profiles referred by handle.

        Args:
            handle: ambassador handle whose referrals are returned.
        Returns:
            Seeded profiles referred by handle.
        Raises:
            None.
        """
        self.by_referrer_calls.append(handle)
        return list(self.referred_by_handle.get(handle, []))

    async def count_by_referrer(self, handle: str) -> int:
        """The seeded referred-user count for handle.

        Args:
            handle: ambassador handle whose referred-user count is returned.
        Returns:
            The seeded referred-user count for handle, or 0.
        Raises:
            None.
        """
        return self.counts_by_handle.get(handle, 0)

    async def by_persona(self, persona: str) -> list[UserProfile]:
        """Record the call and return every seeded profile with the given
        persona.

        Args:
            persona: persona the returned profiles must have.
        Returns:
            Seeded profiles whose persona equals persona.
        Raises:
            None.
        """
        self.by_persona_calls.append(persona)
        return [p for p in self.profiles_by_id.values() if p.persona == persona]


class FakeReferrers:
    def __init__(
        self,
        *,
        ambassadors: list[Ambassador] | None = None,
        handles: set[str] | None = None,
    ) -> None:
        """Ambassadors and their handles, seeded or derived from the ambassador
        list.

        Args:
            ambassadors: seeded ambassadors, or None.
            handles: seeded handles, or None to derive them from ambassadors.
        Returns:
            None.
        Raises:
            None.
        """
        self.ambassadors = ambassadors or []
        self.handles = (
            handles
            if handles is not None
            else {a.handle for a in self.ambassadors}
        )

    async def list_ambassadors(self) -> list[Ambassador]:
        """Every seeded ambassador.

        Args:
            None.
        Returns:
            Every seeded ambassador.
        Raises:
            None.
        """
        return list(self.ambassadors)

    async def list_handles(self) -> set[str]:
        """Every seeded ambassador handle.

        Args:
            None.
        Returns:
            Every seeded ambassador handle.
        Raises:
            None.
        """
        return set(self.handles)


class FakeBlocklist:
    def __init__(self, ids: set[str] | None = None) -> None:
        """The seeded blocked user id set, or empty.

        Args:
            ids: seeded blocked user ids, or None.
        Returns:
            None.
        Raises:
            None.
        """
        self.ids = ids or set()

    async def list_ids(self) -> set[str]:
        """Every blocked user id.

        Args:
            None.
        Returns:
            Every blocked user id.
        Raises:
            None.
        """
        return set(self.ids)


class FakeCampaigns:
    def __init__(
        self, windows_by_handle: dict[str, list] | None = None
    ) -> None:
        """Campaign windows by referrer handle, seeded or empty.

        Args:
            windows_by_handle: seeded campaign windows keyed by handle, or None.
        Returns:
            None.
        Raises:
            None.
        """
        self.windows_by_handle = windows_by_handle or {}
        self.list_calls: list[object] = []

    async def list(self, handle: str) -> list:
        """Record the call and return handle's seeded campaign windows.

        Args:
            handle: ambassador handle whose campaign windows are returned.
        Returns:
            handle's seeded campaign windows.
        Raises:
            None.
        """
        self.list_calls.append(handle)
        return list(self.windows_by_handle.get(handle, []))


class FakeClicks:
    def __init__(
        self,
        *,
        all_by_handle: dict[str, int] | None = None,
        between: dict[tuple[str, int, int], int] | None = None,
    ) -> None:
        """Seeded all-time and windowed click counts by handle.

        Args:
            all_by_handle: seeded all-time click counts keyed by handle, or
                None.
            between: seeded windowed click counts keyed by (handle, start_ms,
                end_ms), or None.
        Returns:
            None.
        Raises:
            None.
        """
        self.all_by_handle = all_by_handle or {}
        self.between = between or {}
        self.count_all_calls: list[object] = []
        self.count_between_calls: list[tuple[object, object, object]] = []

    async def count_all(self, handle: str) -> int:
        """Record the call and return handle's seeded all-time click count.

        Args:
            handle: ambassador handle whose all-time click count is returned.
        Returns:
            handle's seeded all-time click count, or 0.
        Raises:
            None.
        """
        self.count_all_calls.append(handle)
        return self.all_by_handle.get(handle, 0)

    async def count_between(
        self, handle: str, start_ms: int, end_ms: int
    ) -> int:
        """Record the call and return the seeded click count for that
        handle/window.

        Args:
            handle: the referrer handle to count clicks for.
            start_ms: the window start, epoch ms.
            end_ms: the window end, epoch ms.
        Returns:
            The seeded click count for this window.
        Raises:
            None.
        """
        self.count_between_calls.append((handle, start_ms, end_ms))
        return self.between.get((handle, start_ms, end_ms), 0)


class TextMessage:
    """Duck-typed inbound text: the documented surface is ``.text`` and
    ``.at_ms``.
    """

    def __init__(self, text: str, at_ms: int) -> None:
        """A duck-typed inbound text message with the documented .text/.at_ms
        surface.

        Args:
            text: the message body.
            at_ms: when the message arrived, in epoch milliseconds.
        Returns:
            None.
        Raises:
            None.
        """
        self.text = text
        self.at_ms = at_ms


class BufferedOnboarding:
    def __init__(self, messages: list[TextMessage]) -> None:
        """One buffered onboarding record: its queued text messages.

        Args:
            messages: the queued text messages on this onboarding record.
        Returns:
            None.
        Raises:
            None.
        """
        self.messages = messages


class FakeOnboarding:
    def __init__(self, items: list[BufferedOnboarding]) -> None:
        """Seeded with the given buffered onboarding items.

        Args:
            items: buffered onboarding records to seed.
        Returns:
            None.
        Raises:
            None.
        """
        self.items = items

    async def list_all(self) -> list[BufferedOnboarding]:
        """Every seeded buffered onboarding item.

        Args:
            None.
        Returns:
            Every seeded buffered onboarding item.
        Raises:
            None.
        """
        return list(self.items)
