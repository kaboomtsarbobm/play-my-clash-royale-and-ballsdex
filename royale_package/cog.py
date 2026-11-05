import asyncio
import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from django.db.models import F
from django.utils import timezone

from bd_models.models import Ball, BallInstance, Player

from .battle import DECK_SIZE, TICK, Card, Game
from .models import RoyaleCard, RoyalePlayer
from .render import render

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


log = logging.getLogger("ballsdex.packages.royale")

CHEST_COOLDOWN = timedelta(hours=4)
WIN_REWARD = 100
WIN_PER_CROWN = 100
LOSS_PER_CROWN = 50

CHESTS = [
    ("Clash", 60, 100, 300),
    ("Royale", 30, 300, 800),
    ("Awesome Verity Chest", 10, 800, 2000),
]


async def get_royale(discord_id: int) -> RoyalePlayer:
    player, _ = await Player.objects.aget_or_create(discord_id=discord_id)
    royale, _ = await RoyalePlayer.objects.aget_or_create(player=player)
    return royale


async def owned_ball_ids(player_id: int) -> set[int]:
    queryset = (
        BallInstance.objects.filter(player_id=player_id, deleted=False)
        .values_list("ball_id", flat=True)
        .distinct()
    )
    return {ball_id async for ball_id in queryset}


def card_stats(row: RoyaleCard) -> tuple[int, int]:
    attack = row.attack if row.attack is not None else row.ball.attack
    health = row.health if row.health is not None else row.ball.health
    return attack, health


async def load_cards(ball_ids: list[int]) -> list[Card]:
    queryset = (
        RoyaleCard.objects.filter(ball_id__in=ball_ids, enabled=True)
        .select_related("ball")
    )
    cards_by_ball = {row.ball_id: row async for row in queryset}

    cards = []
    for ball_id in ball_ids:
        row = cards_by_ball.get(ball_id)
        if row is None:
            continue

        attack, health = card_stats(row)
        cards.append(
            Card(
                ball_id,
                row.ball.country,
                attack,
                health,
                row.elixir_cost,
                row.cooldown_seconds,
            )
        )

    return cards


def elixir_bar(amount: float) -> str:
    full = max(0, min(10, int(amount)))
    empty = 10 - full
    return f"{'🟣' * full}{'⚫' * empty} {full}/10"


class ChallengeView(discord.ui.View):
    def __init__(self, opponent: discord.User | discord.Member):
        super().__init__(timeout=60)
        self.opponent = opponent
        self.accepted: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "This challenge isn't for you.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.accepted = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.accepted = False
        await interaction.response.defer()
        self.stop()


class CardsView(discord.ui.View):
    def __init__(self, game: Game, side: int):
        super().__init__(timeout=240)
        self.game = game
        self.side = side
        self.selected: int | None = None

        player_side = game.sides[side]
        options = []

        for index, card in enumerate(player_side.cards):
            wait = player_side.cooldowns[index] * TICK
            status = "Ready" if wait == 0 else f"Ready in {wait}s"
            label = f"{card.name} ({card.cost} elixir)"[:100]
            description = f"{status} | ATK {card.atk} | HP {card.hp}"[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    description=description,
                    value=str(index),
                )
            )

        select = discord.ui.Select(
            placeholder="Pick a card",
            options=options,
        )
        select.callback = self.on_select
        self.add_item(select)

    def text(self) -> str:
        return elixir_bar(self.game.sides[self.side].elixir)

    async def on_select(self, interaction: discord.Interaction) -> None:
        values = interaction.data.get("values", []) if interaction.data else []
        if not values:
            return await interaction.response.send_message(
                "Select a card first.",
                ephemeral=True,
            )

        self.selected = int(values[0])
        await interaction.response.defer()

    async def deploy(self, interaction: discord.Interaction, lane: int) -> None:
        if self.selected is None:
            await interaction.response.send_message(
                "Pick a card first.",
                ephemeral=True,
            )
            return

        error = self.game.play(self.side, self.selected, lane)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        fresh_view = CardsView(self.game, self.side)
        await interaction.response.edit_message(
            content=fresh_view.text(),
            view=fresh_view,
        )

    @discord.ui.button(
        label="Left lane",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def left(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.deploy(interaction, 0)

    @discord.ui.button(
        label="Right lane",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def right(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.deploy(interaction, 1)

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        fresh_view = CardsView(self.game, self.side)
        await interaction.response.edit_message(
            content=fresh_view.text(),
            view=fresh_view,
        )


class BattleView(discord.ui.View):
    def __init__(self, game: Game, users: list[discord.User | discord.Member]):
        super().__init__(timeout=None)
        self.game = game
        self.users = users

    @discord.ui.button(
        label="Open my cards",
        style=discord.ButtonStyle.green,
    )
    async def open_cards(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        user_ids = [user.id for user in self.users]
        if interaction.user.id not in user_ids:
            await interaction.response.send_message(
                "You're not in this battle.",
                ephemeral=True,
            )
            return

        side = user_ids.index(interaction.user.id)
        view = CardsView(self.game, side)
        await interaction.response.send_message(
            view.text(),
            view=view,
            ephemeral=True,
        )


class Royale(commands.GroupCog, group_name="royale"):
    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.in_battle: set[int] = set()

    async def owned_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[int]]:
        royale = await get_royale(interaction.user.id)
        owned_ids = await owned_ball_ids(royale.player_id)
        available_ids = owned_ids - set(royale.deck)

        balls = Ball.objects.filter(
            pk__in=available_ids,
            royale_card__enabled=True,
            country__icontains=current,
        ).order_by("country")[:25]

        return [
            app_commands.Choice(name=ball.country, value=ball.pk)
            async for ball in balls
        ]

    async def deck_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[int]]:
        royale = await get_royale(interaction.user.id)
        balls = Ball.objects.filter(
            pk__in=royale.deck,
            country__icontains=current,
        ).order_by("country")[:25]

        return [
            app_commands.Choice(name=ball.country, value=ball.pk)
            async for ball in balls
        ]

    @app_commands.command(description="See your battle record")
    async def profile(
        self,
        interaction: discord.Interaction,
        user: discord.User | None = None,
    ) -> None:
        target = user or interaction.user
        royale = await get_royale(target.id)

        embed = discord.Embed(
            title=f"{target.display_name}'s Royale profile",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="W / L / D",
            value=f"{royale.wins} / {royale.losses} / {royale.draws}",
        )
        embed.add_field(
            name="Chests opened",
            value=str(royale.chests_opened),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Show your battle deck")
    async def deck(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        royale = await get_royale(interaction.user.id)
        cards = await load_cards(royale.deck)

        if not cards:
            await interaction.followup.send(
                "Your deck is empty. Use `/royale deck_add` or `/royale deck_auto`."
            )
            return

        lines = [
            f"**{card.name}** | {card.cost} elixir | ATK {card.atk} | HP {card.hp}"
            for card in cards
        ]
        average_cost = sum(card.cost for card in cards) / len(cards)
        await interaction.followup.send(
            f"**Your deck ({len(cards)}/{DECK_SIZE})**\n"
            + "\n".join(lines)
            + f"\n\nAverage elixir: {average_cost:.1f}"
        )

    @app_commands.command(description="Add a ball you own to your deck")
    @app_commands.autocomplete(ball=owned_autocomplete)
    async def deck_add(
        self,
        interaction: discord.Interaction,
        ball: int,
    ) -> None:
        royale = await get_royale(interaction.user.id)

        if len(royale.deck) >= DECK_SIZE:
            await interaction.response.send_message(
                f"Your deck is full ({DECK_SIZE} cards).",
                ephemeral=True,
            )
            return

        if ball in royale.deck:
            await interaction.response.send_message(
                "That ball is already in your deck.",
                ephemeral=True,
            )
            return

        owned_ids = await owned_ball_ids(royale.player_id)
        if ball not in owned_ids:
            await interaction.response.send_message(
                "You don't own that ball.",
                ephemeral=True,
            )
            return

        is_enabled = await RoyaleCard.objects.filter(
            ball_id=ball,
            enabled=True,
        ).aexists()
        if not is_enabled:
            await interaction.response.send_message(
                "That ball isn't a Royale card.",
                ephemeral=True,
            )
            return

        royale.deck = [*royale.deck, ball]
        await royale.asave(update_fields=["deck"])
        await interaction.response.send_message(
            f"Added. Deck: {len(royale.deck)}/{DECK_SIZE}",
            ephemeral=True,
        )

    @app_commands.command(description="Remove a ball from your deck")
    @app_commands.autocomplete(ball=deck_autocomplete)
    async def deck_remove(
        self,
        interaction: discord.Interaction,
        ball: int,
    ) -> None:
        royale = await get_royale(interaction.user.id)

        if ball not in royale.deck:
            await interaction.response.send_message(
                "That ball isn't in your deck.",
                ephemeral=True,
            )
            return

        royale.deck = [ball_id for ball_id in royale.deck if ball_id != ball]
        await royale.asave(update_fields=["deck"])
        await interaction.response.send_message(
            f"Removed. Deck: {len(royale.deck)}/{DECK_SIZE}",
            ephemeral=True,
        )

    @app_commands.command(description="Fill your deck with your 8 strongest different balls")
    async def deck_auto(self, interaction: discord.Interaction) -> None:
        royale = await get_royale(interaction.user.id)
        owned_ids = await owned_ball_ids(royale.player_id)

        queryset = (
            RoyaleCard.objects.filter(ball_id__in=owned_ids, enabled=True)
            .select_related("ball")
        )
        rows = [row async for row in queryset]
        rows.sort(
            key=lambda row: sum(card_stats(row)),
            reverse=True,
        )

        if len(rows) < DECK_SIZE:
            await interaction.response.send_message(
                f"You need at least {DECK_SIZE} different Royale cards "
                f"(you have {len(rows)}).",
                ephemeral=True,
            )
            return

        royale.deck = [row.ball_id for row in rows[:DECK_SIZE]]
        await royale.asave(update_fields=["deck"])
        await interaction.response.send_message(
            "Deck filled. Check it with `/royale deck`.",
            ephemeral=True,
        )

    @app_commands.command(description="Open your free chest (every 4 hours)")
    async def chest(self, interaction: discord.Interaction) -> None:
        royale = await get_royale(interaction.user.id)
        now = timezone.now()

        if royale.next_chest_at and royale.next_chest_at > now:
            await interaction.response.send_message(
                f"Your next chest unlocks "
                f"<t:{int(royale.next_chest_at.timestamp())}:R>.",
                ephemeral=True,
            )
            return

        name, _, minimum, maximum = random.choices(
            CHESTS,
            weights=[chest[1] for chest in CHESTS],
            k=1,
        )[0]
        amount = random.randint(minimum, maximum)

        await Player.objects.filter(pk=royale.player_id).aupdate(
            money=F("money") + amount,
        )

        royale.chests_opened += 1
        royale.next_chest_at = now + CHEST_COOLDOWN
        await royale.asave(
            update_fields=["chests_opened", "next_chest_at"],
        )

        await interaction.response.send_message(
            f"You opened a **{name}** and got **{amount:,}**!"
        )

    @app_commands.command(description="Players with the most wins")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        rows = []
        queryset = (
            RoyalePlayer.objects.select_related("player")
            .order_by("-wins")[:10]
        )

        async for royale in queryset:
            rows.append(
                f"<@{royale.player.discord_id}> - {royale.wins} wins"
            )

        await interaction.response.send_message(
            "**Royale leaderboard**\n" + ("\n".join(rows) or "No one yet.")
        )

    def battle_embed(
        self,
        game: Game,
        users: list[discord.User | discord.Member],
        final_text: str | None = None,
    ) -> discord.Embed:
        crowns_a = game.crowns(0)
        crowns_b = game.crowns(1)
        minutes, seconds = divmod(game.seconds_left(), 60)

        if game.overtime:
            phase = "Overtime"
        elif game.double_elixir:
            phase = "Double elixir"
        else:
            phase = "Battle"

        embed = discord.Embed(
            title=(
                f"{users[0].display_name} {crowns_a} - "
                f"{crowns_b} {users[1].display_name}"
            ),
            description=final_text or f"{phase} | {minutes}:{seconds:02d} left",
            color=discord.Color.gold(),
        )
        embed.set_image(url="attachment://arena.jpg")
        embed.set_footer(
            text="Blue is the first player, red is the challenged player."
        )
        return embed

    async def push_frame(
        self,
        message: discord.Message,
        game: Game,
        users: list[discord.User | discord.Member],
        view: discord.ui.View | None = None,
        final_text: str | None = None,
    ) -> None:
        buffer = await asyncio.to_thread(render, game)
        if hasattr(buffer, "seek"):
            buffer.seek(0)

        await message.edit(
            content=None,
            embed=self.battle_embed(game, users, final_text),
            attachments=[discord.File(buffer, filename="arena.jpg")],
            view=view,
        )

    @app_commands.command(description="Challenge someone to a real-time Royale battle")
    async def battle(
        self,
        interaction: discord.Interaction,
        opponent: discord.User,
    ) -> None:
        challenger = interaction.user

        if opponent.bot or opponent.id == challenger.id:
            await interaction.response.send_message(
                "Pick a real opponent.",
                ephemeral=True,
            )
            return

        if challenger.id in self.in_battle or opponent.id in self.in_battle:
            await interaction.response.send_message(
                "One of you is already in a battle.",
                ephemeral=True,
            )
            return

        self.in_battle.update({challenger.id, opponent.id})
        message = None

        try:
            await interaction.response.defer()

            royale_a = await get_royale(challenger.id)
            royale_b = await get_royale(opponent.id)

            if len(royale_a.deck) < DECK_SIZE or len(royale_b.deck) < DECK_SIZE:
                await interaction.followup.send(
                    f"Both players need a full deck of {DECK_SIZE}. "
                    "Use `/royale deck_auto` or `/royale deck_add`.",
                    ephemeral=True,
                )
                return

            challenge = ChallengeView(opponent)
            message = await interaction.followup.send(
                f"{opponent.mention}, {challenger.mention} "
                "challenges you to a Royale battle!",
                view=challenge,
                wait=True,
            )

            await challenge.wait()
            if not challenge.accepted:
                await message.edit(
                    content="Challenge declined or expired.",
                    view=None,
                )
                return

            royale_a = await get_royale(challenger.id)
            royale_b = await get_royale(opponent.id)
            cards_a = await load_cards(royale_a.deck)
            cards_b = await load_cards(royale_b.deck)

            if len(cards_a) < DECK_SIZE or len(cards_b) < DECK_SIZE:
                await message.edit(
                    content="A deck has a card that is no longer available. Fix your decks.",
                    view=None,
                )
                return

            owned_a = await owned_ball_ids(royale_a.player_id)
            owned_b = await owned_ball_ids(royale_b.player_id)
            if not set(royale_a.deck) <= owned_a or not set(royale_b.deck) <= owned_b:
                await message.edit(
                    content="Someone's deck has balls they no longer own.",
                    view=None,
                )
                return

            users = [challenger, opponent]
            game = Game(cards_a, cards_b)
            battle_view = BattleView(game, users)
            await self.push_frame(message, game, users, battle_view)

            while not game.over:
                await asyncio.sleep(TICK)
                game.tick()

                try:
                    await self.push_frame(
                        message,
                        game,
                        users,
                        None if game.over else battle_view,
                    )
                except discord.HTTPException:
                    log.warning(
                        "Failed to update Royale battle frame.",
                        exc_info=True,
                    )

            result = await self.finish(game, royale_a, royale_b)
            await self.push_frame(
                message,
                game,
                users,
                None,
                result,
            )

        except Exception:
            log.exception("Royale battle crashed.")
            if message is not None:
                try:
                    await message.edit(
                        content="The battle encountered an error and could not continue.",
                        view=None,
                    )
                except discord.HTTPException:
                    log.warning("Could not update the failed Royale battle message.")
            elif not interaction.is_expired():
                try:
                    await interaction.followup.send(
                        "The battle encountered an error and could not start.",
                        ephemeral=True,
                    )
                except discord.HTTPException:
                    log.warning("Could not send the Royale battle error message.")
        finally:
            self.in_battle.difference_update({challenger.id, opponent.id})

    async def finish(
        self,
        game: Game,
        royale_a: RoyalePlayer,
        royale_b: RoyalePlayer,
    ) -> str:
        players = [royale_a, royale_b]
        crowns = [game.crowns(0), game.crowns(1)]

        if game.winner is None:
            for player in players:
                player.draws += 1
                await player.asave(update_fields=["draws"])
            return "It's a draw!"

        winner = players[game.winner]
        loser = players[1 - game.winner]

        winner.wins += 1
        loser.losses += 1
        await winner.asave(update_fields=["wins"])
        await loser.asave(update_fields=["losses"])

        winner_amount = WIN_REWARD + WIN_PER_CROWN * crowns[game.winner]
        loser_amount = LOSS_PER_CROWN * crowns[1 - game.winner]

        await Player.objects.filter(pk=winner.player_id).aupdate(
            money=F("money") + winner_amount,
        )
        if loser_amount:
            await Player.objects.filter(pk=loser.player_id).aupdate(
                money=F("money") + loser_amount,
            )

        winner_player = await Player.objects.aget(pk=winner.player_id)
        return (
            f"<@{winner_player.discord_id}> wins "
            f"and earns {winner_amount:,}!"
        )


async def setup(bot: "BallsDexBot") -> None:
    await bot.add_cog(Royale(bot))
