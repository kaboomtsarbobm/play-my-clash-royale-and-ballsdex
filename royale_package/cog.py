import asyncio
import logging
import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from django.db.models import F
from django.utils import timezone

from bd_models.models import Ball, BallInstance, Player

from .battle import DECK_SIZE, TICK, Card, Game
from .models import RoyaleCard, RoyalePlayer
from .render import render

log = logging.getLogger("ballsdex.packages.royale")

CHEST_COOLDOWN = timedelta(hours=4)
WIN_REWARD = 100
WIN_PER_CROWN = 100
LOSS_PER_CROWN = 50
CHESTS = [
    ("Silver Chest", 60, 100, 300),
    ("Golden Chest", 30, 300, 800),
    ("Magical Chest", 10, 800, 2000),
]


async def get_royale(discord_id: int) -> RoyalePlayer:
    player, _ = await Player.objects.aget_or_create(discord_id=discord_id)
    royale, _ = await RoyalePlayer.objects.aget_or_create(player=player)
    return royale


async def owned_ball_ids(player_id: int) -> set[int]:
    qs = BallInstance.objects.filter(player_id=player_id, deleted=False).values_list("ball_id", flat=True).distinct()
    return {ball_id async for ball_id in qs}


def card_stats(row: RoyaleCard) -> tuple[int, int]:
    attack = row.attack if row.attack is not None else row.ball.attack
    health = row.health if row.health is not None else row.ball.health
    return attack, health


async def load_cards(ball_ids: list[int]) -> list[Card]:
    rows = RoyaleCard.objects.filter(ball_id__in=ball_ids, enabled=True).select_related("ball")
    by_ball = {row.ball_id: row async for row in rows}
    cards = []
    for ball_id in ball_ids:
        row = by_ball.get(ball_id)
        if row is None:
            continue
        attack, health = card_stats(row)
        cards.append(Card(ball_id, row.ball.country, attack, health, row.elixir_cost, row.cooldown_seconds))
    return cards


def elixir_bar(amount: float) -> str:
    full = int(amount)
    return "🟣" * full + "⚫" * (10 - full) + f" {full}/10"


class ChallengeView(discord.ui.View):
    def __init__(self, opponent: discord.User):
        super().__init__(timeout=60)
        self.opponent = opponent
        self.accepted: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("This challenge isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, _):
        self.accepted = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, _):
        self.accepted = False
        await interaction.response.defer()
        self.stop()


class CardsView(discord.ui.View):
    def __init__(self, game: Game, side: int):
        super().__init__(timeout=240)
        self.game = game
        self.side = side
        self.selected: int | None = None

        mine = game.sides[side]
        options = []
        for i, card in enumerate(mine.cards):
            wait = mine.cooldowns[i] * TICK
            status = "Ready" if wait == 0 else f"Ready in {wait}s"
            options.append(
                discord.SelectOption(
                    label=f"{card.name} ({card.cost} elixir)",
                    description=f"{status} | ATK {card.atk} | HP {card.hp}",
                    value=str(i),
                )
            )
        select = discord.ui.Select(placeholder="Pick a card", options=options)
        select.callback = self.on_select
        self.add_item(select)

    def text(self) -> str:
        return elixir_bar(self.game.sides[self.side].elixir)

    async def on_select(self, interaction: discord.Interaction):
        self.selected = int(interaction.data["values"][0])
        await interaction.response.defer()

    async def deploy(self, interaction: discord.Interaction, lane: int):
        if self.selected is None:
            return await interaction.response.send_message("Pick a card first.", ephemeral=True)
        error = self.game.play(self.side, self.selected, lane)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        fresh = CardsView(self.game, self.side)
        await interaction.response.edit_message(content=fresh.text(), view=fresh)

    @discord.ui.button(label="Left lane", style=discord.ButtonStyle.primary, row=1)
    async def left(self, interaction: discord.Interaction, _):
        await self.deploy(interaction, 0)

    @discord.ui.button(label="Right lane", style=discord.ButtonStyle.primary, row=1)
    async def right(self, interaction: discord.Interaction, _):
        await self.deploy(interaction, 1)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction: discord.Interaction, _):
        fresh = CardsView(self.game, self.side)
        await interaction.response.edit_message(content=fresh.text(), view=fresh)


class BattleView(discord.ui.View):
    def __init__(self, game: Game, users: list[discord.User]):
        super().__init__(timeout=None)
        self.game = game
        self.users = users

    @discord.ui.button(label="Open my cards", style=discord.ButtonStyle.green)
    async def open_cards(self, interaction: discord.Interaction, _):
        ids = [u.id for u in self.users]
        if interaction.user.id not in ids:
            return await interaction.response.send_message("You're not in this battle.", ephemeral=True)
        view = CardsView(self.game, ids.index(interaction.user.id))
        await interaction.response.send_message(view.text(), view=view, ephemeral=True)


class Royale(commands.GroupCog, group_name="royale"):
    def __init__(self, bot):
        self.bot = bot
        self.in_battle: set[int] = set()

    async def owned_autocomplete(self, interaction: discord.Interaction, current: str):
        player, _ = await Player.objects.aget_or_create(discord_id=interaction.user.id)
        royale = await get_royale(interaction.user.id)
        ids = await owned_ball_ids(player.pk)
        ids -= set(royale.deck)
        balls = Ball.objects.filter(
            pk__in=ids, royale_card__enabled=True, country__icontains=current
        ).order_by("country")[:25]
        return [app_commands.Choice(name=b.country, value=b.pk) async for b in balls]

    async def deck_autocomplete(self, interaction: discord.Interaction, current: str):
        royale = await get_royale(interaction.user.id)
        balls = Ball.objects.filter(pk__in=royale.deck, country__icontains=current)[:25]
        return [app_commands.Choice(name=b.country, value=b.pk) async for b in balls]

    @app_commands.command(description="See your battle record")
    async def profile(self, interaction: discord.Interaction, user: discord.User | None = None):
        user = user or interaction.user
        r = await get_royale(user.id)
        embed = discord.Embed(title=f"{user.display_name}'s Royale profile", color=discord.Color.blue())
        embed.add_field(name="W / L / D", value=f"{r.wins} / {r.losses} / {r.draws}")
        embed.add_field(name="Chests opened", value=str(r.chests_opened))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Show your battle deck")
    async def deck(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        royale = await get_royale(interaction.user.id)
        cards = await load_cards(royale.deck)
        if not cards:
            return await interaction.followup.send(
                "Your deck is empty. Use `/royale deck_add` or `/royale deck_auto`."
            )
        lines = [f"**{c.name}** | {c.cost} elixir | ATK {c.atk} | HP {c.hp}" for c in cards]
        average = sum(c.cost for c in cards) / len(cards)
        await interaction.followup.send(
            f"**Your deck ({len(cards)}/{DECK_SIZE})**\n" + "\n".join(lines) + f"\n\nAverage elixir: {average:.1f}"
        )

    @app_commands.command(description="Add a ball you own to your deck")
    @app_commands.autocomplete(ball=owned_autocomplete)
    async def deck_add(self, interaction: discord.Interaction, ball: int):
        royale = await get_royale(interaction.user.id)
        if len(royale.deck) >= DECK_SIZE:
            return await interaction.response.send_message(f"Your deck is full ({DECK_SIZE} cards).", ephemeral=True)
        if ball in royale.deck:
            return await interaction.response.send_message("That ball is already in your deck.", ephemeral=True)
        if ball not in await owned_ball_ids(royale.player_id):
            return await interaction.response.send_message("You don't own that ball.", ephemeral=True)
        if not await RoyaleCard.objects.filter(ball_id=ball, enabled=True).aexists():
            return await interaction.response.send_message("That ball isn't a Royale card.", ephemeral=True)
        royale.deck = [*royale.deck, ball]
        await royale.asave(update_fields=["deck"])
        await interaction.response.send_message(f"Added. Deck: {len(royale.deck)}/{DECK_SIZE}", ephemeral=True)

    @app_commands.command(description="Remove a ball from your deck")
    @app_commands.autocomplete(ball=deck_autocomplete)
    async def deck_remove(self, interaction: discord.Interaction, ball: int):
        royale = await get_royale(interaction.user.id)
        if ball not in royale.deck:
            return await interaction.response.send_message("That ball isn't in your deck.", ephemeral=True)
        royale.deck = [b for b in royale.deck if b != ball]
        await royale.asave(update_fields=["deck"])
        await interaction.response.send_message(f"Removed. Deck: {len(royale.deck)}/{DECK_SIZE}", ephemeral=True)

    @app_commands.command(description="Fill your deck with your 8 strongest different balls")
    async def deck_auto(self, interaction: discord.Interaction):
        royale = await get_royale(interaction.user.id)
        ids = await owned_ball_ids(royale.player_id)
        rows = [r async for r in RoyaleCard.objects.filter(ball_id__in=ids, enabled=True).select_related("ball")]
        rows.sort(key=lambda r: sum(card_stats(r)), reverse=True)
        if len(rows) < DECK_SIZE:
            return await interaction.response.send_message(
                f"You need at least {DECK_SIZE} different Royale cards (you have {len(rows)}).", ephemeral=True
            )
        royale.deck = [r.ball_id for r in rows[:DECK_SIZE]]
        await royale.asave(update_fields=["deck"])
        await interaction.response.send_message("Deck filled. Check it with `/royale deck`.", ephemeral=True)

    @app_commands.command(description="Open your free chest (every 4 hours)")
    async def chest(self, interaction: discord.Interaction):
        r = await get_royale(interaction.user.id)
        now = timezone.now()
        if r.next_chest_at and r.next_chest_at > now:
            return await interaction.response.send_message(
                f"Your next chest unlocks <t:{int(r.next_chest_at.timestamp())}:R>.", ephemeral=True
            )
        name, _, lo, hi = random.choices(CHESTS, weights=[c[1] for c in CHESTS])[0]
        amount = random.randint(lo, hi)
        await Player.objects.filter(pk=r.player_id).aupdate(money=F("money") + amount)
        r.chests_opened += 1
        r.next_chest_at = now + CHEST_COOLDOWN
        await r.asave(update_fields=["chests_opened", "next_chest_at"])
        await interaction.response.send_message(f"You opened a **{name}** and got **{amount:,}**!")

    @app_commands.command(description="Players with the most wins")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = []
        async for r in RoyalePlayer.objects.select_related("player").order_by("-wins")[:10]:
            rows.append(f"<@{r.player.discord_id}> - {r.wins} wins")
        await interaction.response.send_message("**Royale leaderboard**\n" + ("\n".join(rows) or "No one yet."))

    def battle_embed(self, game: Game, users, final_text: str | None = None) -> discord.Embed:
        a, b = game.crowns(0), game.crowns(1)
        minutes, seconds = divmod(game.seconds_left(), 60)
        phase = "Overtime" if game.overtime else ("Double elixir" if game.double_elixir else "Battle")
        embed = discord.Embed(
            title=f"{users[0].display_name} {a} - {b} {users[1].display_name}",
            description=final_text or f"{phase} | {minutes}:{seconds:02d} left",
            color=discord.Color.gold(),
        )
        embed.set_image(url="attachment://arena.jpg")
        embed.set_footer(text="Blue is the first player, red is the challenged player.")
        return embed

    async def push_frame(self, msg, game: Game, users, view=None, final_text: str | None = None):
        buffer = await asyncio.to_thread(render, game)
        await msg.edit(
            content=None,
            embed=self.battle_embed(game, users, final_text),
            attachments=[discord.File(buffer, filename="arena.jpg")],
            view=view,
        )

    @app_commands.command(description="Challenge someone to a real-time Royale battle")
    async def battle(self, interaction: discord.Interaction, opponent: discord.User):
        me = interaction.user
        if opponent.bot or opponent.id == me.id:
            return await interaction.response.send_message("Pick a real opponent.", ephemeral=True)
        if me.id in self.in_battle or opponent.id in self.in_battle:
            return await interaction.response.send_message("One of you is already in a battle.", ephemeral=True)

        ra, rb = await get_royale(me.id), await get_royale(opponent.id)
        if len(ra.deck) < DECK_SIZE or len(rb.deck) < DECK_SIZE:
            return await interaction.response.send_message(
                f"Both players need a full deck of {DECK_SIZE}. Use `/royale deck_auto` or `/royale deck_add`.",
                ephemeral=True,
            )

        self.in_battle |= {me.id, opponent.id}
        try:
            challenge = ChallengeView(opponent)
            await interaction.response.send_message(
                f"{opponent.mention}, {me.mention} challenges you to a Royale battle!", view=challenge
            )
            await challenge.wait()
            msg = await interaction.original_response()
            if not challenge.accepted:
                return await msg.edit(content="Challenge declined or expired.", view=None)

            ra, rb = await get_royale(me.id), await get_royale(opponent.id)
            cards_a, cards_b = await load_cards(ra.deck), await load_cards(rb.deck)
            if len(cards_a) < DECK_SIZE or len(cards_b) < DECK_SIZE:
                return await msg.edit(content="A deck has a card that is no longer available. Fix your decks.", view=None)
            owned_a, owned_b = await owned_ball_ids(ra.player_id), await owned_ball_ids(rb.player_id)
            if not set(ra.deck) <= owned_a or not set(rb.deck) <= owned_b:
                return await msg.edit(content="Someone's deck has balls they no longer own.", view=None)

            users = [me, opponent]
            game = Game(cards_a, cards_b)
            view = BattleView(game, users)
            await self.push_frame(msg, game, users, view)

            while not game.over:
                await asyncio.sleep(TICK)
                game.tick()
                try:
                    await self.push_frame(msg, game, users, None if game.over else view)
                except discord.HTTPException:
                    log.warning("Failed to update battle frame", exc_info=True)

            result = await self.finish(game, ra, rb)
            await self.push_frame(msg, game, users, None, result)
        except Exception:
            log.exception("Royale battle crashed")
        finally:
            self.in_battle -= {me.id, opponent.id}

    async def finish(self, game: Game, ra: RoyalePlayer, rb: RoyalePlayer) -> str:
        players = [ra, rb]
        crowns = [game.crowns(0), game.crowns(1)]

        if game.winner is None:
            for p in players:
                p.draws += 1
                await p.asave(update_fields=["draws"])
            return "It's a draw!"

        win, lose = players[game.winner], players[1 - game.winner]
        win.wins += 1
        lose.losses += 1
        await win.asave(update_fields=["wins"])
        await lose.asave(update_fields=["losses"])

        win_amount = WIN_REWARD + WIN_PER_CROWN * crowns[game.winner]
        lose_amount = LOSS_PER_CROWN * crowns[1 - game.winner]
        await Player.objects.filter(pk=win.player_id).aupdate(money=F("money") + win_amount)
        if lose_amount:
            await Player.objects.filter(pk=lose.player_id).aupdate(money=F("money") + lose_amount)

        winner_player = await Player.objects.aget(pk=win.player_id)
        return f"<@{winner_player.discord_id}> wins and earns {win_amount:,}!"


async def setup(bot):
    await bot.add_cog(Royale(bot))
