"""Commands and message handling for Higher or Lower games."""

import discord
from discord.ext import commands
from loguru import logger as log

from models.game import Game as GameState
from utils import (
    announce_result,
    announce_winner,
    can_cancel,
    check_guess,
    cleanup_game,
    generate_secret,
    get_game,
    range_autocomplete,
    register_game,
    resolve_range,
    schedule_timeout,
    send_invalid_guess_x,
    start_public_game,
    validate_guess_input,
)
from views.number_guess import NumberPickerView


async def _start_chosen_game(
    channel: discord.abc.Messageable,
    min_val: int,
    max_val: int,
    target: int,
    picker_id: int,
    bot: commands.Bot,
) -> None:
    """Create a chosen-number game after the picker submits the modal."""
    channel_id = channel.id
    existing = get_game(channel_id)
    if existing and existing.active:
        await channel.send("A game is already running in this channel!")
        return

    game = GameState(
        mode="chosen",
        target=target,
        min_val=min_val,
        max_val=max_val,
        players=[],
        channel_id=channel_id,
        starter_id=picker_id,
        chooser=picker_id,
    )
    register_game(game)
    schedule_timeout(game, bot)

    embed = discord.Embed(
        title="🎮 Higher or Lower — Chosen Mode",
        description=(
            f"A secret number between **{min_val}** and **{max_val}** has been chosen!\n"
            "Type a number to guess. The picker cannot participate!"
        ),
        color=discord.Color.purple(),
    )
    await channel.send(embed=embed)
    log.info("Chosen game started in channel {}", channel_id)


class Game(commands.Cog):
    """Cog for public/chosen games, shared game controls, and guess handling."""

    guessthenum: discord.SlashCommandGroup = discord.SlashCommandGroup(
        "hol",
        "Higher or Lower number guessing game",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        async def chosen_callback(channel, min_val, max_val, target, picker_id):
            await _start_chosen_game(
                channel, min_val, max_val, target, picker_id, bot,
            )

        bot._chosen_game_callback = chosen_callback
        log.info("Game cog loaded")

    @guessthenum.command(name="public", description="Start a public guessing game")
    async def cmd_public(
        self,
        ctx: discord.ApplicationContext,
        range_name: discord.Option(
            str,
            "Range preset name (e.g. Fun, High Test)",
            required=False,
            default=None,
            autocomplete=range_autocomplete,
        ),
    ) -> None:
        """Start a public game in the current channel."""
        await start_public_game(ctx, range_name, self.bot)

    @guessthenum.command(
        name="duel",
        description="Challenge another player to a 1v1 duel",
    )
    async def cmd_duel(
        self,
        ctx: discord.ApplicationContext,
        opponent: discord.Option(discord.Member, "The player you want to duel"),
        range_name: discord.Option(
            str,
            "Range preset name (e.g. Fun, High Test)",
            required=False,
            name="range_preset",
            default=None,
            autocomplete=range_autocomplete,
        ),
    ) -> None:
        """Delegate duel creation to the dedicated duel cog."""
        duel_cog = self.bot.get_cog("Duel")
        if duel_cog is None:
            log.error("Duel cog is unavailable")
            await ctx.respond("Duel games are temporarily unavailable.", ephemeral=True)
            return
        await duel_cog.start_duel(ctx, opponent, range_name)

    @guessthenum.command(
        name="challenge",
        description="Challenge another player to a first-to duel series",
    )
    async def cmd_challenge(
        self,
        ctx: discord.ApplicationContext,
        opponent: discord.Option(discord.Member, "The player you want to challenge"),
        ft: discord.Option(
            int,
            "Number of match wins needed to win the challenge",
            min_value=1,
        ),
        range_name: discord.Option(
            str,
            "Range preset name (e.g. Fun, High Test)",
            required=False,
            name="range_preset",
            default=None,
            autocomplete=range_autocomplete,
        ),
    ) -> None:
        """Delegate a first-to challenge to the Duel cog."""
        duel_cog = self.bot.get_cog("Duel")
        if duel_cog is None:
            log.error("Duel cog is unavailable")
            await ctx.respond("Duel challenges are temporarily unavailable.", ephemeral=True)
            return
        await duel_cog.start_challenge(ctx, opponent, range_name, ft)

    @guessthenum.command(
        name="chosen",
        description="Someone picks the number, everyone else guesses",
    )
    async def cmd_chosen(
        self,
        ctx: discord.ApplicationContext,
        range_name: discord.Option(
            str,
            "Range preset name (e.g. Fun, High Test)",
            required=False,
            default=None,
            autocomplete=range_autocomplete,
        ),
    ) -> None:
        """Start a chosen-number game."""
        existing = get_game(ctx.channel.id)
        if existing and existing.active:
            await ctx.respond("A game is already running in this channel!", ephemeral=True)
            return

        min_val, max_val = resolve_range(range_name)
        view = NumberPickerView(
            min_val=min_val,
            max_val=max_val,
            game_creator_id=ctx.author.id,
        )
        embed = discord.Embed(
            title="🎯 Higher or Lower — Chosen Mode",
            description=(
                f"{ctx.author.mention}, click the button below to pick a secret number "
                f"between **{min_val}** and **{max_val}**."
            ),
            color=discord.Color.purple(),
        )
        await ctx.respond(embed=embed, view=view)

    @guessthenum.command(
        name="stop",
        description="Cancel the active game in this channel",
    )
    async def cmd_cancelgame(self, ctx: discord.ApplicationContext) -> None:
        """Cancel an active game when the caller has permission."""
        game = get_game(ctx.channel.id)
        if not game or not game.active:
            await ctx.respond("No active game in this channel to cancel.", ephemeral=True)
            return

        if not can_cancel(game, ctx.author.id):
            await ctx.respond(
                "Only the game starter (or a duel participant) can cancel this game.",
                ephemeral=True,
            )
            return

        cleanup_game(ctx.channel.id)
        await ctx.respond("🛑 Game cancelled.")
        log.info("Game cancelled in channel {}", ctx.channel.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Process numeric guesses and enforce duel/chosen-mode restrictions."""
        if message.author.bot:
            return

        game = get_game(message.channel.id)
        if not game or not game.active:
            return

        guess = validate_guess_input(message.content, game.min_val, game.max_val)
        if guess is None:
            return
        if guess == -1:
            await send_invalid_guess_x(message)
            return

        if game.mode == "duel":
            current_player_id = game.players[game.current_turn_idx]
            if message.author.id != current_player_id:
                await send_invalid_guess_x(message)
                return

        if game.mode == "chosen" and message.author.id == game.chooser:
            await send_invalid_guess_x(message)
            return

        result = check_guess(guess, game.target)
        if result == "correct":
            await announce_winner(message.channel, message.author, game, self.bot)
            return

        if game.mode == "duel":
            game.current_turn_idx = (game.current_turn_idx + 1) % len(game.players)
        await announce_result(message.channel, result, message.author, guess)


def setup(bot: commands.Bot) -> None:
    """Register the game cog."""
    bot.add_cog(Game(bot))
