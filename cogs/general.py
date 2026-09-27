"""
General cog — Higher or Lower game logic and commands.

Provides the guessthenum slash command group with public, duel,
and chosen subcommands.  Handles all game state, message listening,
result feedback, and game timeouts.
"""

import asyncio
import random
from typing import Optional

import discord
from discord.ext import commands
from loguru import logger as log

from views.number_guess import NumberPickerView

# --------------------------------------------------------------------------- #
#  Constants
# --------------------------------------------------------------------------- #

# Default range when no range key is specified
DEFAULT_MIN = 1
DEFAULT_MAX = 100

# Discord ❌ emoji used for invalid guesses in duel mode
INVALID_GUESS_EMOJI = "❌"


# --------------------------------------------------------------------------- #
#  Game dataclass
# --------------------------------------------------------------------------- #

class Game:
    """
    Represents an active Higher or Lower game in a single channel.

    Attributes:
        mode:           Game mode — "public", "duel", or "chosen".
        target:         The hidden number players are trying to guess.
        min_val:        Lower bound of the guessable range.
        max_val:        Upper bound of the guessable range.
        players:        List of user IDs allowed to guess (empty = anyone).
        current_turn_idx: Index into players for whose turn it is (duel).
        channel_id:     Discord channel ID where the game is running.
        active:         Whether the game is still in progress.
        chooser:        User ID of the number picker (chosen mode only).
        starter_id:     User ID of the person who started the game.
        timeout_task:   Asyncio task handling the inactivity timeout.
    """

    __slots__ = (
        "mode", "target", "min_val", "max_val", "players",
        "current_turn_idx", "channel_id", "active", "chooser",
        "starter_id", "timeout_task",
    )

    def __init__(
        self,
        mode: str,
        target: int,
        min_val: int,
        max_val: int,
        players: list[int],
        channel_id: int,
        starter_id: int,
        chooser: Optional[int] = None,
    ) -> None:
        """Initialise a new Game instance."""
        self.mode = mode
        self.target = target
        self.min_val = min_val
        self.max_val = max_val
        self.players = players
        self.current_turn_idx = 0
        self.channel_id = channel_id
        self.active = True
        self.chooser = chooser
        self.starter_id = starter_id
        self.timeout_task: Optional[asyncio.Task] = None


# --------------------------------------------------------------------------- #
#  In-memory game store — one game per channel
# --------------------------------------------------------------------------- #

# Maps channel_id -> Game
active_games: dict[int, Game] = {}


# --------------------------------------------------------------------------- #
#  Business logic helpers (each < 40 lines)
# --------------------------------------------------------------------------- #

def generate_secret(min_val: int, max_val: int) -> int:
    """
    Generate a random secret number within the given range.

    Args:
        min_val: Minimum possible value (inclusive).
        max_val: Maximum possible value (inclusive).

    Returns:
        A random integer between min_val and max_val.
    """
    return random.randint(min_val, max_val)


def check_guess(guess: int, target: int) -> str:
    """
    Compare a guess against the target number.

    Args:
        guess:  The player's guessed number.
        target: The hidden target number.

    Returns:
        "higher"  — the target is larger than the guess.
        "lower"   — the target is smaller than the guess.
        "correct" — the guess matches the target.
    """
    if guess < target:
        return "higher"
    elif guess > target:
        return "lower"
    return "correct"


def validate_guess_input(content: str, min_val: int, max_val: int) -> Optional[int]:
    """
    Validate that a message contains a valid integer within range.

    Args:
        content: Raw message content to validate.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        The parsed integer if valid, otherwise None.
    """
    try:
        value = int(content.strip())
    except (ValueError, TypeError):
        return None

    if value < min_val or value > max_val:
        return None

    return value


def get_game(channel_id: int) -> Optional[Game]:
    """
    Retrieve the active game for a given channel.

    Args:
        channel_id: The Discord channel ID to look up.

    Returns:
        The active Game, or None if no game exists.
    """
    return active_games.get(channel_id)


def cleanup_game(channel_id: int) -> None:
    """
    Remove a game from the active games store and cancel its timeout.

    Args:
        channel_id: The Discord channel ID whose game should be removed.
    """
    game = active_games.pop(channel_id, None)
    if game and game.timeout_task:
        game.timeout_task.cancel()
    if game:
        log.debug("Cleaned up game in channel {}", channel_id)


# --------------------------------------------------------------------------- #
#  Timeout handling
# --------------------------------------------------------------------------- #

async def _game_timeout(channel_id: int, bot: commands.Bot) -> None:
    """
    Wait for the configured timeout, then cancel the game if still active.

    Args:
        channel_id: The Discord channel ID of the game.
        bot:        The bot instance (for timeout duration and channel lookup).
    """
    await asyncio.sleep(bot.game_timeout)

    game = get_game(channel_id)
    if not game or not game.active:
        return

    channel = bot.get_channel(channel_id)
    if channel:
        embed = discord.Embed(
            title="⏱️ Game Timed Out",
            description=(
                f"The game has been cancelled due to inactivity "
                f"({bot.game_timeout}s with no guesses)."
            ),
            color=discord.Color.orange(),
        )
        await channel.send(embed=embed)

    cleanup_game(channel_id)
    log.info("Game timed out in channel {}", channel_id)


def schedule_timeout(game: Game, bot: commands.Bot) -> None:
    """
    Schedule an inactivity timeout task for a game.

    Args:
        game: The Game instance to monitor.
        bot:  The bot instance (for timeout duration).
    """
    game.timeout_task = asyncio.create_task(_game_timeout(game.channel_id, bot))


# --------------------------------------------------------------------------- #
#  Permission helpers
# --------------------------------------------------------------------------- #

def can_cancel(game: Game, user_id: int) -> bool:
    """
    Check whether a user is allowed to cancel a game.

    Public: only the starter may cancel.
    Duel:   the starter or either participant may cancel.
    Chosen: only the picker/starter may cancel.

    Args:
        game:    The Game instance.
        user_id: The Discord user ID attempting to cancel.

    Returns:
        True if the user may cancel the game.
    """
    if game.mode == "duel":
        return user_id in game.players
    return user_id == game.starter_id


# --------------------------------------------------------------------------- #
#  Message helpers
# --------------------------------------------------------------------------- #

async def announce_result(
    channel: discord.abc.Messageable,
    result: str,
    user: discord.Member,
    guess: int,
) -> None:
    """
    Send a feedback message after a guess.

    Args:
        channel: The channel to send the message in.
        result:  One of "higher", "lower", or "correct".
        user:    The member who made the guess.
        guess:   The number that was guessed.
    """
    if result == "higher":
        msg = f"**{user.display_name}** guessed **{guess}** — go **higher**! ⬆️"
    elif result == "lower":
        msg = f"**{user.display_name}** guessed **{guess}** — go **lower**! ⬇️"
    else:
        msg = f"**{user.display_name}** guessed **{guess}** — **correct!** 🎉"

    await channel.send(msg)


async def announce_winner(
    channel: discord.abc.Messageable,
    winner: discord.Member,
    game: Game,
) -> None:
    """
    Announce the winner and clean up the game.

    Args:
        channel: The channel to send the message in.
        winner:  The member who guessed correctly.
        game:    The Game instance (for context).
    """
    embed = discord.Embed(
        title="🏆 Game Over!",
        description=(
            f"**{winner.display_name}** wins!\n"
            f"The number was **{game.target}**!\n"
            f"Range: {game.min_val}–{game.max_val}"
        ),
        color=discord.Color.gold(),
    )
    await channel.send(embed=embed)
    cleanup_game(game.channel_id)


async def send_invalid_guess_x(message: discord.Message) -> None:
    """
    React with a ❌ emoji to indicate an invalid or out-of-turn guess.

    Used in duel mode to give silent feedback without cluttering chat.

    Args:
        message: The message to react to.
    """
    try:
        await message.add_reaction(INVALID_GUESS_EMOJI)
    except discord.HTTPException:
        log.warning("Failed to add reaction to message {}", message.id)


# --------------------------------------------------------------------------- #
#  Chosen-mode callback — invoked by the NumberPickerModal
# --------------------------------------------------------------------------- #

async def _chosen_game_callback(
    channel: discord.abc.Messageable,
    min_val: int,
    max_val: int,
    target: int,
    picker_id: int,
    bot: commands.Bot,
) -> None:
    """
    Callback triggered by NumberPickerModal after the picker selects a number.

    Creates the game, schedules its timeout, and sends the start message.

    Args:
        channel:   The channel where the game is hosted.
        min_val:   Minimum of the range.
        max_val:   Maximum of the range.
        target:    The secret number chosen by the picker.
        picker_id: User ID of the picker.
        bot:       The bot instance (for timeout scheduling).
    """
    existing = get_game(channel.id)  # type: ignore
    if existing and existing.active:
        await channel.send("A game is already running in this channel!")
        return

    game = Game(
        mode="chosen",
        target=target,
        min_val=min_val,
        max_val=max_val,
        players=[],
        channel_id=channel.id,  # type: ignore
        starter_id=picker_id,
        chooser=picker_id,
    )
    active_games[channel.id] = game  # type: ignore
    schedule_timeout(game, bot)

    embed = discord.Embed(
        title="🎮 Higher or Lower — Chosen Mode",
        description=(
            f"A secret number between **{min_val}** and **{max_val}** has been chosen!\n"
            f"Type a number to guess. The picker cannot participate!"
        ),
        color=discord.Color.purple(),
    )
    await channel.send(embed=embed)
    log.info("Chosen game started in channel {}", channel.id)


# --------------------------------------------------------------------------- #
#  Range resolution helpers
# --------------------------------------------------------------------------- #

def _load_range_names() -> list[str]:
    """
    Load range key names from the JSON file for autocomplete.

    Returns:
        A list of range key name strings.
    """
    import json
    from pathlib import Path

    ranges_file = Path(__file__).parent.parent / "data" / "ranges.json"

    try:
        with open(ranges_file, "r") as f:
            data = json.load(f)
        return list(data.keys())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _resolve_range(range_name: Optional[str]) -> tuple[int, int]:
    """
    Resolve a range key name to its (min, max) tuple.

    Args:
        range_name: The key name (e.g. "Fun"), or None for default.

    Returns:
        A tuple of (min_val, max_val).
    """
    import json
    from pathlib import Path

    if not range_name:
        return (DEFAULT_MIN, DEFAULT_MAX)

    ranges_file = Path(__file__).parent.parent / "data" / "ranges.json"

    try:
        with open(ranges_file, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return (DEFAULT_MIN, DEFAULT_MAX)

    for key, bounds in data.items():
        if key.lower() == range_name.lower():
            return (bounds["min"], bounds["max"])

    return (DEFAULT_MIN, DEFAULT_MAX)


# --------------------------------------------------------------------------- #
#  Autocomplete callback for range names
# --------------------------------------------------------------------------- #

async def range_autocomplete(ctx: discord.AutocompleteContext) -> list[str]:
    """
    Provide autocomplete suggestions for range preset names.

    Args:
        ctx: The autocomplete context.

    Returns:
        A list of matching range names.
    """
    names = _load_range_names()
    if ctx.value:
        return [n for n in names if ctx.value.lower() in n.lower()]
    return names


# --------------------------------------------------------------------------- #
#  Shared game-start helper
# --------------------------------------------------------------------------- #

async def _start_public_game(
    ctx: discord.ApplicationContext,
    range_name: Optional[str],
    bot: commands.Bot,
) -> None:
    """
    Create and start a public game.

    Args:
        ctx:        The application context.
        range_name: Optional range key. Defaults to 1–100.
        bot:        The bot instance (for timeout scheduling).
    """
    existing = get_game(ctx.channel.id)
    if existing and existing.active:
        await ctx.respond("A game is already running in this channel!", ephemeral=True)
        return

    min_val, max_val = _resolve_range(range_name)
    target = generate_secret(min_val, max_val)

    game = Game(
        mode="public",
        target=target,
        min_val=min_val,
        max_val=max_val,
        players=[],
        channel_id=ctx.channel.id,
        starter_id=ctx.author.id,
    )
    active_games[ctx.channel.id] = game
    schedule_timeout(game, bot)

    embed = discord.Embed(
        title="🎮 Higher or Lower — Public",
        description=(
            f"I'm thinking of a number between **{min_val}** and **{max_val}**.\n"
            f"Type a number to guess!"
        ),
        color=discord.Color.green(),
    )
    await ctx.respond(embed=embed)
    log.info("Public game started in channel {}", ctx.channel.id)


# --------------------------------------------------------------------------- #
#  General Cog
# --------------------------------------------------------------------------- #

class General(commands.Cog):
    """
    General cog — Higher or Lower game commands and message listener.

    Uses standard slash commands via discord.SlashCommandGroup.
    """

    # Slash command group — class attribute so decorators can attach subcommands
    guessthenum: discord.SlashCommandGroup = discord.SlashCommandGroup(
        "guessthenum",
        "Higher or Lower number guessing game",
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store bot reference and register the chosen-mode callback."""
        self.bot = bot
        # Wrap so the callback receives the bot instance for timeout scheduling
        async def _callback(channel, min_val, max_val, target, picker_id):
            await _chosen_game_callback(
                channel, min_val, max_val, target, picker_id, bot,
            )
        bot._chosen_game_callback = _callback
        log.info("General cog loaded")

    # ================================================================== #
    #  Subcommand: public
    # ================================================================== #

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
        """
        Start a public game — anyone can guess.

        Args:
            ctx:        The application context.
            range_name: Optional range key. Defaults to 1–100.
        """
        await _start_public_game(ctx, range_name, self.bot)

    # ------------------------------------------------------------------ #
    #  Subcommand: duel
    # ------------------------------------------------------------------ #

    @guessthenum.command(name="duel", description="Challenge another player to a 1v1 duel")
    async def cmd_duel(
        self,
        ctx: discord.ApplicationContext,
        opponent: discord.Option(discord.Member, "The player you want to duel"),
        range_name: discord.Option(
            str,
            "Range preset name (e.g. Fun, High Test)",
            required=False,
            default=None,
            autocomplete=range_autocomplete,
        ),
    ) -> None:
        """
        Start a duel — the command invoker vs the chosen opponent.

        Players alternate guessing until one finds the number.

        Args:
            ctx:      The application context.
            opponent: The player to duel against.
            range_name: Optional range key. Defaults to 1–100.
        """
        if opponent.id == ctx.author.id:
            await ctx.respond("You can't duel yourself!", ephemeral=True)
            return

        existing = get_game(ctx.channel.id)
        if existing and existing.active:
            await ctx.respond("A game is already running in this channel!", ephemeral=True)
            return

        min_val, max_val = _resolve_range(range_name)
        target = generate_secret(min_val, max_val)

        # Command invoker always goes first
        game = Game(
            mode="duel",
            target=target,
            min_val=min_val,
            max_val=max_val,
            players=[ctx.author.id, opponent.id],
            channel_id=ctx.channel.id,
            starter_id=ctx.author.id,
        )
        active_games[ctx.channel.id] = game
        schedule_timeout(game, self.bot)

        embed = discord.Embed(
            title="⚔️ Higher or Lower — Duel",
            description=(
                f"{ctx.author.mention} vs {opponent.mention}\n"
                f"Range: **{min_val}**–**{max_val}**\n\n"
                f"{ctx.author.mention} goes first! Type a number to guess."
            ),
            color=discord.Color.red(),
        )
        await ctx.respond(embed=embed)
        log.info(
            "Duel started in channel {}: {} vs {}",
            ctx.channel.id, ctx.author.id, opponent.id,
        )

    # ------------------------------------------------------------------ #
    #  Subcommand: chosen
    # ------------------------------------------------------------------ #

    @guessthenum.command(name="chosen", description="Someone picks the number, everyone else guesses")
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
        """
        Start a chosen game — picker uses a modal to secretly set the number.

        Args:
            ctx:        The application context.
            range_name: Optional range key. Defaults to 1–100.
        """
        existing = get_game(ctx.channel.id)
        if existing and existing.active:
            await ctx.respond("A game is already running in this channel!", ephemeral=True)
            return

        min_val, max_val = _resolve_range(range_name)

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

    # ------------------------------------------------------------------ #
    #  Subcommand: cancelgame
    # ------------------------------------------------------------------ #

    @guessthenum.command(name="cancelgame", description="Cancel the active game in this channel")
    async def cmd_cancelgame(self, ctx: discord.ApplicationContext) -> None:
        """
        Cancel the active Higher or Lower game in this channel.

        Public: only the starter may cancel.
        Duel:   either participant may cancel.
        Chosen: only the picker may cancel.

        Args:
            ctx: The application context.
        """
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

    # ================================================================== #
    #  on_message listener — process guesses from typed messages
    # ================================================================== #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Listen for messages and process guesses.

        Ignores bots and messages that aren't valid integers.
        In duel mode, only accepts guesses from the current player.
        In chosen mode, ignores guesses from the picker.
        """
        if message.author.bot:
            return

        game = get_game(message.channel.id)
        if not game or not game.active:
            return

        guess = validate_guess_input(message.content, game.min_val, game.max_val)
        if guess is None:
            if game.mode == "public":
                return
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
            await announce_winner(message.channel, message.author, game)
            return

        if game.mode == "duel":
            game.current_turn_idx = (game.current_turn_idx + 1) % len(game.players)

        await announce_result(message.channel, result, message.author, guess)


# --------------------------------------------------------------------------- #
#  Cog setup (sync in py-cord)
# --------------------------------------------------------------------------- #

def setup(bot: commands.Bot) -> None:
    """Register the General cog with the bot."""
    bot.add_cog(General(bot))
