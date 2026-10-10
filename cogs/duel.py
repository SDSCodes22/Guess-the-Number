"""Duel game setup and duel-specific behavior."""

from typing import Optional

import discord
from discord.ext import commands
from loguru import logger as log

from models.duel_series import DuelSeries
from models.game import Game
from utils import (
    generate_secret,
    get_game,
    range_autocomplete,
    register_game,
    resolve_range,
    schedule_timeout,
)


class Duel(commands.Cog):
    """Dedicated duel cog for single duels and scored challenge series."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        log.info("Duel cog loaded")

    def _create_duel_game(
        self,
        channel_id: int,
        players: list[int],
        min_val: int,
        max_val: int,
        series: Optional[DuelSeries] = None,
    ) -> Game:
        """Create and register a duel game, optionally attached to a series."""
        game = Game(
            mode="duel",
            target=generate_secret(min_val, max_val),
            min_val=min_val,
            max_val=max_val,
            players=players,
            channel_id=channel_id,
            starter_id=players[0],
            series=series,
        )
        register_game(game)
        schedule_timeout(game, self.bot)
        return game

    @staticmethod
    def _duel_embed(players: list[int], min_val: int, max_val: int) -> discord.Embed:
        """Build the common start embed for duel games."""
        return discord.Embed(
            title="⚔️ Higher or Lower — Duel",
            description=(
                f"<@{players[0]}> vs <@{players[1]}>\n"
                f"Range: **{min_val}**–**{max_val}**\n\n"
                f"<@{players[0]}> goes first! Type a number to guess."
            ),
            color=discord.Color.red(),
        )

    async def start_rematch(
        self,
        interaction: discord.Interaction,
        previous_players: tuple[int, ...],
        min_val: int,
        max_val: int,
        channel_id: int,
    ) -> None:
        """Start a rematch with the previous second player taking the first turn."""
        current_game = get_game(channel_id)
        if current_game and current_game.active:
            await interaction.response.send_message(
                "A game is already running in this channel!",
                ephemeral=True,
            )
            return

        players = list(reversed(previous_players))
        self._create_duel_game(
            channel_id, players, min_val, max_val,
        )
        embed = self._duel_embed(players, min_val, max_val)
        await interaction.response.send_message(embed=embed)
        log.info(
            "Duel rematch started in channel {}: {} vs {}",
            channel_id, players[0], players[1],
        )

    async def start_duel(
        self,
        ctx: discord.ApplicationContext,
        opponent: discord.Member,
        range_name: Optional[str],
    ) -> None:
        """Create a duel initiated through the /hol duel subcommand."""
        if opponent.id == ctx.author.id:
            await ctx.respond("You can't duel yourself!", ephemeral=True)
            return

        existing = get_game(ctx.channel.id)
        if existing and existing.active:
            await ctx.respond("A game is already running in this channel!", ephemeral=True)
            return

        min_val, max_val = resolve_range(range_name)
        players = [ctx.author.id, opponent.id]
        self._create_duel_game(
            ctx.channel.id, players, min_val, max_val,
        )
        embed = self._duel_embed(players, min_val, max_val)
        await ctx.respond(embed=embed)
        log.info(
            "Duel started in channel {}: {} vs {}",
            ctx.channel.id, ctx.author.id, opponent.id,
        )

    async def start_challenge(
        self,
        ctx: discord.ApplicationContext,
        opponent: discord.Member,
        range_name: Optional[str],
        ft: int,
    ) -> None:
        """Start a first-to series using the standard duel game setup."""
        if opponent.id == ctx.author.id:
            await ctx.respond("You can't challenge yourself!", ephemeral=True)
            return

        existing = get_game(ctx.channel.id)
        if existing and existing.active:
            await ctx.respond("A game is already running in this channel!", ephemeral=True)
            return

        min_val, max_val = resolve_range(range_name)
        players = (ctx.author.id, opponent.id)
        series = DuelSeries(players, ft)
        self._create_duel_game(
            ctx.channel.id, list(players), min_val, max_val, series,
        )
        await ctx.respond(embed=self._duel_embed(list(players), min_val, max_val))
        log.info(
            "First-to-{} challenge started in channel {}: {} vs {}",
            ft, ctx.channel.id, players[0], players[1],
        )

    async def complete_challenge_match(
        self,
        channel: discord.abc.Messageable,
        winner_id: int,
        series: DuelSeries,
        min_val: int,
        max_val: int,
    ) -> None:
        """Update the series score and start the next match or announce the series winner."""
        series.scores[winner_id] += 1
        player_one, player_two = series.players
        score_line = (
            f"<@{player_one}> {series.scores[player_one]}-"
            f"{series.scores[player_two]} <@{player_two}>"
        )
        await channel.send(score_line)

        if series.scores[winner_id] >= series.target_score:
            await channel.send(
                f"<@{winner_id}> wins the first-to-{series.target_score} challenge!"
            )
            return

        series.first_player_idx = 1 - series.first_player_idx
        players = list(series.players)
        if series.first_player_idx:
            players.reverse()

        self._create_duel_game(
            channel.id, players, min_val, max_val, series,
        )
        await channel.send(embed=self._duel_embed(players, min_val, max_val))
        log.info(
            "Challenge match started in channel {}: {} vs {} (score {})",
            channel.id, players[0], players[1], score_line,
        )


def setup(bot: commands.Bot) -> None:
    """Register the duel cog."""
    bot.add_cog(Duel(bot))
