import asyncio

import logging

import random

from datetime import date, datetime, timedelta, timezone as datetime_timezone



import discord

from discord import app_commands

from discord.ext import commands

from django.db.models import Q



from bd_models.models import Ball, BallInstance, Player

from ballsdex.packages.countryballs.countryball import BallSpawnView



from .models import Shop, ShopBallPrice, ShopCycleState, ShopEvent



log = logging.getLogger("ballsdex.packages.dandys_shops")

CATCH_REWARD = 20

UI_TIMEOUT = 300





DEFAULT_SHOPS = (

    {

        "key": "dandys", "name": "Dandy's Store", "regime_name": "Toon",

        "enabled": True, "welcome_message": "Welcome to Dandy's Store! Pick a Toon, Trinket, or Item below.",

        "slots": 3, "is_holiday": False, "fallback_priority": 10,

    },

    {

        "key": "dyles", "name": "Dyles Store", "regime_name": "Skins",

        "enabled": True, "welcome_message": "Welcome to Dyles Store! Pick a skin below.",

        "slots": 3, "is_holiday": False, "fallback_priority": 20,

    },

    {

        "key": "bobettes", "name": "Bobette's Store", "regime_name": "Christmas",

        "enabled": True, "welcome_message": "Welcome to Bobette's Christmas Store!",

        "slots": 3, "is_holiday": True, "start_month": 12, "start_day": 1,

        "end_month": 1, "end_day": 3, "fallback_priority": 10,

    },

    {

        "key": "bassies", "name": "Bassies Store", "regime_name": "Easter",

        "enabled": True, "welcome_message": "Welcome to Bassies' Easter Store!",

        "slots": 3, "is_holiday": True, "start_month": 4, "start_day": 1,

        "end_month": 5, "end_day": 3, "fallback_priority": 20,

    },

    {

        "key": "gourdys", "name": "Gourdys Store", "regime_name": "Halloween",

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

    await ShopCycleState.objects.aget_or_create(id=1, defaults={"next_kind": "event"})





def _emoji_for(ball: Ball):
    """Use a text fallback rather than an unverified custom emoji ID."""
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

                await interaction.response.send_message("Please run /shop again. Sorry.", ephemeral=True)

                return

            if interaction.response.is_done():

                return

            price_row = await ShopBallPrice.objects.select_related("ball__regime", "shop").filter(

                pk=self.price_row_id, available=True, shop__enabled=True, ball__enabled=True

            ).afirst()

            if price_row is None or price_row.pk in view.purchased_ids:

                await interaction.response.send_message("That item is no longer available. Please look here later!", ephemeral=True)

                return

            # Verify the ball still has the exact regime required by this shop.

            regime_name = price_row.ball.regime.name.casefold()

            eligible_regimes = {"toon", "trinket", "item"} if view.shop.key == "dandys" else {view.shop.regime_name.casefold()}

            if regime_name not in eligible_regimes:

                await interaction.response.send_message("That item is no longer eligible for this shop.", ephemeral=True)

                return

            player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)

            cost = (price_row.price * 90) // 100 if view.discount else price_row.price

            if not player.can_afford(cost):

                await interaction.response.send_message(

                    f"You need {cost:,} ichor, but you only have {player.money:,}. Please come back later when you have more!", ephemeral=True

                )

                return

            # Disable the selected item before awaiting the balance/instance updates to discourage double-clicks.

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

                await interaction.followup.send("..What do you mean error from docker?? Just hasvse your ichor back..", ephemeral=True)

                return

            view.purchased_ids.add(price_row.pk)

            await interaction.followup.send(

                f"You bought **{price_row.ball.country}** for {cost:,} ichor! Your ichor is now {player.money - cost:,}.",

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

            await interaction.response.send_message("Please run the /shop command again, sorry.", ephemeral=True)

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

            await interaction.response.send_message("Please run /shop again, sorry.", ephemeral=True)

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

                await interaction.response.send_message("That event is off the table right now.", ephemeral=True)

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

        # The first automatic entry after every bot startup is always Event.

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

            # The original spawn method posts the countryball first. Count this spawn

            # whether the ball is later caught, despawned, or spawned by an admin.

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

        """Post the next Event/Store entry for one completed BallSpawnView.spawn call."""

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

            await channel.send("Hm, no shop events")

            return

        descriptions = "\n".join(

            f"**{event.button_label or event.get_key_display()}** — {event.description}" for event in events

        )

        view = EventSelectionView(self)

        for event in events:

            view.add_item(event_button(event.key, event.button_label or event.get_key_display(), event.description))

        view.message = await channel.send(f"**3 cards appear for shop events!**\n{descriptions}", view=view)



    async def post_shop_to_channel(self, channel, shop_key: str):
        """Post a shop to a channel after an automatic countryball spawn."""
        shop = await Shop.objects.filter(key=shop_key, enabled=True).afirst()
        if shop is None:
            message = (
                "No event store is on right now, maybe later."
                if shop_key in {"bobettes", "bassies", "gourdys"}
                else "That shop is currently disabled."
            )
            await channel.send(message)
            return

        eligible = ShopBallPrice.objects.filter(
            shop=shop, available=True, ball__enabled=True
        ).select_related("ball", "ball__regime")
        if shop.key == "dandys":
            eligible = eligible.filter(
                Q(ball__regime__name__iexact="Toon")
                | Q(ball__regime__name__iexact="Trinket")
                | Q(ball__regime__name__iexact="Item")
            )
        else:
            eligible = eligible.filter(ball__regime__name__iexact=shop.regime_name)

        stock = [item async for item in eligible]
        random.shuffle(stock)
        stock = stock[:shop.slots]
        if not stock:
            await channel.send(
                f"{shop.name} has no stock rn, or the prices just suck "
                "Sorry."
            )
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

        # Manual command use does not alter the automatic spawn-based rotation.

        await ensure_defaults()

        await self.send_shop(interaction, "dandys")



    @app_commands.command(name="holidayshop", description="Open (if there is one) the holiday shop currently active.")

    async def holidayshop(self, interaction: discord.Interaction):

        await ensure_defaults()

        today = date.today()

        shops = [shop async for shop in Shop.objects.filter(is_holiday=True).order_by("fallback_priority", "name")]

        active = [shop for shop in shops if _within_date(today, shop)]

        # Prefer an enabled in-season shop, but if it is disabled or has no eligible

        # priced stock, try the other enabled holiday shops by configured priority.

        ordered = [shop for shop in active if shop.enabled] + [

            shop for shop in shops if shop.enabled and shop not in active

        ]

        for shop in ordered:

            if await self._has_eligible_stock(shop):

                await self.send_shop(interaction, shop.key)

                return

        await interaction.response.send_message("No event store is on right now, maybe later.", ephemeral=True)



    async def _has_eligible_stock(self, shop: Shop) -> bool:

        eligible = ShopBallPrice.objects.filter(shop=shop, available=True, ball__enabled=True)

        if shop.key == "dandys":

            eligible = eligible.filter(

                Q(ball__regime__name__iexact="Toon")

                | Q(ball__regime__name__iexact="Trinket")

                | Q(ball__regime__name__iexact="Item")

            )

        else:

            eligible = eligible.filter(ball__regime__name__iexact=shop.regime_name)

        return await eligible.aexists()



    async def send_event(self, interaction: discord.Interaction):

        events = [event async for event in ShopEvent.objects.filter(enabled=True)]

        if not events:

            await interaction.response.send_message("Awh, no shop events.", ephemeral=True)

            return

        descriptions = "\n".join(f"**{event.button_label or event.get_key_display()}** — {event.description}" for event in events)

        view = EventSelectionView(self)

        for event in events:

            view.add_item(event_button(event.key, event.button_label or event.get_key_display(), event.description))

        await interaction.response.send_message(f"**3 cards appear for events!**\n{descriptions}", view=view)

        view.message = await interaction.original_response()



    async def send_shop(self, interaction: discord.Interaction, shop_key: str, *, discount=False, extra_slots=False):

        shop = await Shop.objects.filter(key=shop_key, enabled=True).afirst()

        if shop is None:

            message = "No event store is on right now, maybe later." if shop_key in {"bobettes", "bassies", "gourdys"} else "That shop is currently closed."

            if interaction.response.is_done():

                await interaction.followup.send(message, ephemeral=True)

            else:

                await interaction.response.send_message(message, ephemeral=True)

            return

        eligible = ShopBallPrice.objects.filter(

            shop=shop, available=True, ball__enabled=True

        ).select_related("ball", "ball__regime")

        if shop.key == "dandys":

            eligible = eligible.filter(

                Q(ball__regime__name__iexact="Toon")

                | Q(ball__regime__name__iexact="Trinket")

                | Q(ball__regime__name__iexact="Item")

            )

        else:

            eligible = eligible.filter(ball__regime__name__iexact=shop.regime_name)

        stock = [item async for item in eligible]

        random.shuffle(stock)

        slot_count = 4 if extra_slots and shop.key == "dandys" else shop.slots

        stock = stock[:slot_count]

        if not stock:

            message = f"{shop.name} has uh, noooo stock..?"

            if interaction.response.is_done():

                await interaction.followup.send(message, ephemeral=True)

            else:

                await interaction.response.send_message(message, ephemeral=True)

            return

        details = shop.welcome_message

        details += "\n\n" + "\n".join(

            f"{_emoji_for(item.ball) or '•'} **{item.ball.country}** — {(item.price * 90) // 100 if discount else item.price:,} currency"

            for item in stock

        )

        if discount:

            details += "\n\n**Event bonus: 10% off these items only**"

        view = ShopView(shop, stock, opener_id=interaction.user.id, discount=discount)

        if interaction.response.is_done():

            view.message = await interaction.followup.send(details, view=view)

        else:

            await interaction.response.send_message(details, view=view)

            view.message = await interaction.original_response()





async def setup(bot):

    await bot.add_cog(DandysShopsCog(bot))
