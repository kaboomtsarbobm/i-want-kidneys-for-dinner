import asyncio
import logging
import random
from datetime import date, datetime, timedelta, timezone as datetime_timezone

import discord
from discord import app_commands
from discord.ext import commands

from bd_models.models import Ball, BallInstance, Player
from ballsdex.packages.countryballs.countryball import BallSpawnView

from .models import Shop, ShopBallPrice, ShopCycleState, ShopEvent, ShopMessage


log = logging.getLogger("ballsdex.packages.dandys_shops")
CATCH_REWARD = 20
UI_TIMEOUT = 300
DEFAULT_MESSAGE_TEXT = "SAMPLETEXT"


DEFAULT_SHOPS = (
    {
        "key": "dandys", "name": "Dandy's Store",
        "enabled": True, "welcome_message": "Welcome to Dandy's Store! Pick a Toon, Trinket, or Item below.",
        "slots": 3, "is_holiday": False, "fallback_priority": 10,
    },
    {
        "key": "dyles", "name": "Dyles Store",
        "enabled": True, "welcome_message": "Welcome to Dyles Store! Pick a skin below.",
        "slots": 3, "is_holiday": False, "fallback_priority": 20,
    },
    {
        "key": "bobettes", "name": "Bobette's Store",
        "enabled": True, "welcome_message": "Welcome to Bobette's Christmas Store!",
        "slots": 3, "is_holiday": True, "start_month": 12, "start_day": 1,
        "end_month": 1, "end_day": 3, "fallback_priority": 10,
    },
    {
        "key": "bassies", "name": "Bassies Store",
        "enabled": True, "welcome_message": "Welcome to Bassies' Easter Store!",
        "slots": 3, "is_holiday": True, "start_month": 4, "start_day": 1,
        "end_month": 5, "end_day": 3, "fallback_priority": 20,
    },
    {
        "key": "gourdys", "name": "Gourdys Store",
        "enabled": True, "welcome_message": "Welcome to Gourdys' Halloween Store!",
        "slots": 3, "is_holiday": True, "start_month": 10, "start_day": 1,
        "end_month": 11, "end_day": 3, "fallback_priority": 30,
    },
)
DEFAULT_EVENTS = (
    {"key": "discount", "enabled": True, "button_label": "Discount", "description": "10% off randomized Dandy's Store stock."},
    {"key": "extra_stock", "enabled": True, "button_label": "Extra Stock", "description": "Dandy's Store has four slots instead of three slots."},
    {"key": "special_shop", "enabled": True, "button_label": "Dyles Store", "description": "Open Dyles Store."},
)
DEFAULT_MESSAGES = (
    "expired",
    "item_unavailable",
    "cannot_afford",
    "purchase_error",
    "purchase_success",
    "event_unavailable",
    "no_events",
    "events_header",
    "shop_disabled",
    "no_event_store",
    "no_stock",
)


def _within_date(today: date, shop: Shop) -> bool:
    if not all((shop.start_month, shop.start_day, shop.end_month, shop.end_day)):
        return False
    start = (shop.start_month, shop.start_day)
    end = (shop.end_month, shop.end_day)
    current = (today.month, today.day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


async def ensure_defaults():
    for data in DEFAULT_SHOPS:
        key = data["key"]
        defaults = {k: v for k, v in data.items() if k != "key"}
        await Shop.objects.aget_or_create(key=key, defaults=defaults)
    for data in DEFAULT_EVENTS:
        key = data["key"]
        defaults = {k: v for k, v in data.items() if k != "key"}
        await ShopEvent.objects.aget_or_create(key=key, defaults=defaults)
    for key in DEFAULT_MESSAGES:
        await ShopMessage.objects.aget_or_create(key=key, defaults={"text": DEFAULT_MESSAGE_TEXT})
    await ShopCycleState.objects.aget_or_create(id=1, defaults={"next_kind": "event"})


async def get_message(key: str, **values) -> str:
    message, _ = await ShopMessage.objects.aget_or_create(key=key, defaults={"text": DEFAULT_MESSAGE_TEXT})
    try:
        return message.text.format(**values)
    except (KeyError, IndexError, ValueError):
        return message.text


def _emoji_for(ball: Ball):
    return None


class ShopItemButton(discord.ui.Button):
    def __init__(self, view: "ShopView", item: ShopBallPrice, index: int):
        self.shop_view = view
        self.price_row_id = item.pk
        self.ball_id = item.ball_id
        self.base_price = item.price
        actual_price = (item.price * 90) // 100 if view.discount else item.price
        self.actual_price = actual_price
        label = f"{item.ball.country[:55]} — {actual_price:,}"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success,
            emoji=_emoji_for(item.ball),
            custom_id=f"dandys_buy_{view.shop.key}_{item.pk}_{index}",
            row=index // 5,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.shop_view
        async with view.purchase_lock:
            if view.is_expired or view.is_finished():
                await interaction.response.send_message(await get_message("expired"), ephemeral=True)
                return
            if interaction.response.is_done():
                return
            price_row = await ShopBallPrice.objects.select_related("ball", "shop").filter(
                pk=self.price_row_id, available=True, shop__enabled=True, ball__enabled=True
            ).afirst()
            if price_row is None or price_row.pk in view.purchased_ids:
                await interaction.response.send_message(await get_message("item_unavailable"), ephemeral=True)
                return
            player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
            cost = (price_row.price * 90) // 100 if view.discount else price_row.price
            if not player.can_afford(cost):
                await interaction.response.send_message(
                    await get_message("cannot_afford", cost=cost, balance=player.money, ball=price_row.ball.country),
                    ephemeral=True,
                )
                return
            self.disabled = True
            try:
                await interaction.response.edit_message(view=view)
            except discord.HTTPException:
                pass
            await player.remove_money(cost)
            try:
                await BallInstance.objects.acreate(
                    ball=price_row.ball,
                    player=player,
                    attack_bonus=random.randint(-20, 20),
                    health_bonus=random.randint(-20, 20),
                    server_id=interaction.guild_id,
                )
            except Exception:
                await player.add_money(cost)
                log.exception("Could not create purchased ball instance; refunded player %s", interaction.user.id)
                await interaction.followup.send(
                    await get_message("purchase_error", cost=cost, ball=price_row.ball.country), ephemeral=True
                )
                return
            view.purchased_ids.add(price_row.pk)
            await interaction.followup.send(
                await get_message(
                    "purchase_success",
                    ball=price_row.ball.country,
                    cost=cost,
                    balance=player.money - cost,
                ),
                ephemeral=True,
            )


class ShopView(discord.ui.View):
    def __init__(self, shop: Shop, stock: list[ShopBallPrice], *, opener_id: int | None = None, discount=False):
        super().__init__(timeout=UI_TIMEOUT)
        self.shop = shop
        self.discount = discount
        self.opener_id = opener_id
        self.created_at = datetime.now(datetime_timezone.utc)
        self.is_expired = False
        self.message = None
        self.purchase_lock = asyncio.Lock()
        self.purchased_ids: set[int] = set()
        for index, item in enumerate(stock):
            self.add_item(ShopItemButton(self, item, index))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.is_expired or self.is_finished():
            await interaction.response.send_message(await get_message("expired"), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        self.is_expired = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound):
                pass


class EventSelectionView(discord.ui.View):
    def __init__(self, cog: "DandysShopsCog"):
        super().__init__(timeout=UI_TIMEOUT)
        self.cog = cog
        self.message = None
        self.is_expired = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.is_expired or self.is_finished():
            await interaction.response.send_message(await get_message("expired"), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        self.is_expired = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.HTTPException, discord.NotFound):
                pass


def event_button(event_key: str, label: str, description: str):
    class _EventButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"dandys_event_{event_key}")
            self.event_key = event_key

        async def callback(self, interaction: discord.Interaction):
            view: EventSelectionView = self.view
            event = await ShopEvent.objects.filter(key=self.event_key, enabled=True).afirst()
            if event is None:
                await interaction.response.send_message(await get_message("event_unavailable"), ephemeral=True)
                return
            view.is_expired = True
            for child in view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            await interaction.response.edit_message(view=view)
            if self.event_key == "discount":
                await view.cog.send_shop(interaction, "dandys", discount=True)
            elif self.event_key == "extra_stock":
                await view.cog.send_shop(interaction, "dandys", extra_slots=True)
            else:
                await view.cog.send_shop(interaction, "dyles")
    return _EventButton()


class DandysShopsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._original_catch = None
        self._original_spawn = None
        self._cycle_lock = asyncio.Lock()

    async def cog_load(self):
        await ensure_defaults()
        await ShopCycleState.objects.filter(id=1).aupdate(next_kind="event")
        self._install_catch_reward_hook()
        self._install_spawn_cycle_hook()

    def cog_unload(self):
        if self._original_catch is not None and getattr(BallSpawnView.catch_ball, "_dandys_reward_hook", False):
            BallSpawnView.catch_ball = self._original_catch
            self._original_catch = None
        if self._original_spawn is not None and getattr(BallSpawnView.spawn, "_dandys_spawn_hook", False):
            BallSpawnView.spawn = self._original_spawn
            self._original_spawn = None

    def _install_catch_reward_hook(self):
        current = BallSpawnView.catch_ball
        if getattr(current, "_dandys_reward_hook", False):
            return
        self._original_catch = current

        async def wrapped(view, user, *, player=None, guild=None):
            result = await current(view, user, player=player, guild=guild)
            try:
                recipient = player or await Player.objects.aget(discord_id=user.id)
                await recipient.add_money(CATCH_REWARD)
            except Exception:
                log.exception("Failed to award catch reward to Discord user %s", user.id)
            return result

        wrapped._dandys_reward_hook = True
        BallSpawnView.catch_ball = wrapped

    def _install_spawn_cycle_hook(self):
        current = BallSpawnView.spawn
        if getattr(current, "_dandys_spawn_hook", False):
            return
        self._original_spawn = current

        async def wrapped_spawn(view, *args, **kwargs):
            result = await current(view, *args, **kwargs)
            channel = kwargs.get("channel")
            if channel is None and args:
                channel = args[0]
            if channel is not None:
                try:
                    await self.post_next_cycle(channel)
                except Exception:
                    log.exception("Could not post the Dandy's shop/event cycle after a countryball spawn")
            return result

        wrapped_spawn._dandys_spawn_hook = True
        BallSpawnView.spawn = wrapped_spawn

    async def post_next_cycle(self, channel):
        async with self._cycle_lock:
            state = await ShopCycleState.objects.filter(id=1).afirst()
            if state is None:
                state = await ShopCycleState.objects.acreate(id=1, next_kind="event")
            kind = state.next_kind
            await ShopCycleState.objects.filter(id=1).aupdate(next_kind="shop" if kind == "event" else "event")
            if kind == "event":
                await self.post_event_to_channel(channel)
            else:
                await self.post_shop_to_channel(channel, "dandys")

    async def post_event_to_channel(self, channel):
        events = [event async for event in ShopEvent.objects.filter(enabled=True)]
        if not events:
            await channel.send(await get_message("no_events"))
            return
        descriptions = "\n".join(
            f"**{event.button_label or event.get_key_display()}** — {event.description}" for event in events
        )
        view = EventSelectionView(self)
        for event in events:
            view.add_item(event_button(event.key, event.button_label or event.get_key_display(), event.description))
        header = await get_message("events_header", descriptions=descriptions)
        view.message = await channel.send(f"{header}\n{descriptions}", view=view)

    async def post_shop_to_channel(self, channel, shop_key: str):
        shop = await Shop.objects.filter(key=shop_key, enabled=True).afirst()
        if shop is None:
            key = "no_event_store" if shop_key in {"bobettes", "bassies", "gourdys"} else "shop_disabled"
            await channel.send(await get_message(key))
            return

        eligible = ShopBallPrice.objects.filter(
            shop=shop, available=True, ball__enabled=True
        ).select_related("ball")

        stock = [item async for item in eligible]
        random.shuffle(stock)
        stock = stock[:shop.slots]
        if not stock:
            await channel.send(await get_message("no_stock", shop=shop.name))
            return

        details = shop.welcome_message + "\n\n" + "\n".join(
            f"{_emoji_for(item.ball) or '•'} **{item.ball.country}** — "
            f"{item.price:,} currency"
            for item in stock
        )
        view = ShopView(shop, stock)
        view.message = await channel.send(details, view=view)

    @app_commands.command(name="shop", description="Open Dandys Store")
    async def shop(self, interaction: discord.Interaction):
        await ensure_defaults()
        await self.send_shop(interaction, "dandys")
