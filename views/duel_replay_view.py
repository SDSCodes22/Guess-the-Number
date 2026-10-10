"""Replay button view for completed duels."""

import discord
from discord.ext import commands
from loguru import logger as log

from models.game import Game


class DuelReplayView(discord.ui.View):
    """Offer duel participants a rematch with the turn order reversed."""

    def __init__(self, game: Game, bot: commands.Bot) -> None:
        super().__init__()
        self.players = tuple(game.players)
        self.min_val = game.min_val
        self.max_val = game.max_val
        self.channel_id = game.channel_id
        self.bot = bot

    @discord.ui.button(label="Play Again", style=discord.ButtonStyle.primary)
    async def play_again(
        self,
        button: discord.ui.Button,
        interaction: discord.Interaction,
    ) -> None:
        """Start a new duel with the previous second player going first."""
        if interaction.user.id not in self.players:
            await interaction.response.send_message(
                "Only the duel participants can start a rematch.",
                ephemeral=True,
            )
            return

        duel_cog = self.bot.get_cog("Duel")
        if duel_cog is None:
            log.error("Duel cog is unavailable for a rematch")
            await interaction.response.send_message(
                "Duel rematches are temporarily unavailable.",
                ephemeral=True,
            )
            return

        await duel_cog.start_rematch(
            interaction,
            self.players,
            self.min_val,
            self.max_val,
            self.channel_id,
        )
