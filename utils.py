"""Shared game state and helpers used by the game cogs and views."""

import asyncio
import json
import random
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from loguru import logger as log

from models.game import Game

DEFAULT_MIN = 1
DEFAULT_MAX = 100
INVALID_GUESS_EMOJI = "❌"

active_games: dict[int, Game] = {}


def generate_secret(min_val: int, max_val: int) -> int:
    """Generate a random secret number within the given inclusive range."""
    return random.randint(min_val, max_val)


def check_guess(guess: int, target: int) -> str:
    """Return whether the target is higher, lower, or equal to the guess."""
    if guess < target:
        return "higher"
    if guess > target:
        return "lower"
    return "correct"


def validate_guess_input(content: str, min_val: int, max_val: int) -> Optional[int]:
    """Return an in-range integer, -1 if out of range, or None if not an integer."""
    try:
        value = int(content.strip())
    except (ValueError, TypeError):
        return None

    if value < min_val or value > max_val:
        return -1
    return value


def get_game(channel_id: int) -> Optional[Game]:
    """Retrieve the active game for a channel."""
    return active_games.get(channel_id)


def register_game(game: Game) -> None:
    """Store a game as the active game for its channel."""
    active_games[game.channel_id] = game


def cleanup_game(channel_id: int) -> None:
    """Remove a game and cancel its timeout task, if present."""
    game = active_games.pop(channel_id, None)
    if game and game.timeout_task:
        game.timeout_task.cancel()
    if game:
        log.debug("Cleaned up game in channel {}", channel_id)


async def _game_timeout(channel_id: int, bot: commands.Bot) -> None:
    """Cancel a game after the configured period of inactivity."""
    await asyncio.sleep(bot.game_timeout)

    game = get_game(channel_id)
    if not game or not game.active:
        return

    channel = bot.get_channel(channel_id)
    if channel:
        embed = discord.Embed(
            title="⏱️ Game Timed Out",
            description=(
                "The game has been cancelled due to inactivity "
                f"({bot.game_timeout}s with no guesses)."
            ),
            color=discord.Color.orange(),
        )
        await channel.send(embed=embed)

    cleanup_game(channel_id)
    log.info("Game timed out in channel {}", channel_id)


def schedule_timeout(game: Game, bot: commands.Bot) -> None:
    """Schedule the inactivity timeout task for a game."""
    game.timeout_task = asyncio.create_task(_game_timeout(game.channel_id, bot))


def can_cancel(game: Game, user_id: int) -> bool:
    """Check whether a user is allowed to cancel a game."""
    if game.mode == "duel":
        return user_id in game.players
    return user_id == game.starter_id


async def announce_result(
    channel: discord.abc.Messageable,
    result: str,
    user: discord.Member,
    guess: int,
) -> None:
    """Send higher/lower feedback after a guess."""
    if result == "higher":
        message = f"**{user.display_name}** guessed **{guess}** — go **higher**! ⬆️"
    elif result == "lower":
        message = f"**{user.display_name}** guessed **{guess}** — go **lower**! ⬇️"
    else:
        message = f"**{user.display_name}** guessed **{guess}** — **correct!** 🎉"
    await channel.send(message)


async def announce_winner(
    channel: discord.abc.Messageable,
    winner: discord.Member,
    game: Game,
    bot: commands.Bot,
) -> None:
    """Announce a winner and route completed challenge matches to the Duel cog."""
    embed = discord.Embed(
        title="🏆 Game Over!",
        description=(
            f"**{winner.display_name}** wins!\n"
            f"The number was **{game.target}**!\n"
            f"Range: {game.min_val}–{game.max_val}"
        ),
        color=discord.Color.gold(),
    )

    if game.series:
        await channel.send(embed=embed)
        cleanup_game(game.channel_id)

        duel_cog = bot.get_cog("Duel")
        if duel_cog is None:
            log.error("Duel cog is unavailable to continue a challenge")
            await channel.send("This challenge cannot continue because duel handling is unavailable.")
            return

        await duel_cog.complete_challenge_match(
            channel,
            winner.id,
            game.series,
            game.min_val,
            game.max_val,
        )
    elif game.mode == "duel":
        from views.duel_replay_view import DuelReplayView

        await channel.send(embed=embed, view=DuelReplayView(game, bot))
        cleanup_game(game.channel_id)
    else:
        await channel.send(embed=embed)
        cleanup_game(game.channel_id)


async def send_invalid_guess_x(message: discord.Message) -> None:
    """React to an invalid or out-of-turn guess with a cross."""
    try:
        await message.add_reaction(INVALID_GUESS_EMOJI)
    except discord.HTTPException:
        log.warning("Failed to add reaction to message {}", message.id)


def _ranges_file() -> Path:
    return Path(__file__).parent / "data" / "ranges.json"


def _load_ranges() -> dict:
    try:
        with _ranges_file().open("r") as ranges_file:
            return json.load(ranges_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_range_names() -> list[str]:
    """Load configured range preset names for autocomplete."""
    return list(_load_ranges().keys())


def resolve_range(range_name: Optional[str]) -> tuple[int, int]:
    """Resolve a configured range name or return the default bounds."""
    if range_name:
        for key, bounds in _load_ranges().items():
            if key.lower() == range_name.lower():
                return bounds["min"], bounds["max"]
    return DEFAULT_MIN, DEFAULT_MAX


async def range_autocomplete(ctx: discord.AutocompleteContext) -> list[str]:
    """Return matching range preset names."""
    names = load_range_names()
    if ctx.value:
        return [name for name in names if ctx.value.lower() in name.lower()]
    return names


async def start_public_game(
    ctx: discord.ApplicationContext,
    range_name: Optional[str],
    bot: commands.Bot,
) -> None:
    """Create and start a public game."""
    existing = get_game(ctx.channel.id)
    if existing and existing.active:
        await ctx.respond("A game is already running in this channel!", ephemeral=True)
        return

    min_val, max_val = resolve_range(range_name)
    game = Game(
        mode="public",
        target=generate_secret(min_val, max_val),
        min_val=min_val,
        max_val=max_val,
        players=[],
        channel_id=ctx.channel.id,
        starter_id=ctx.author.id,
    )
    register_game(game)
    schedule_timeout(game, bot)

    embed = discord.Embed(
        title="🎮 Higher or Lower — Public",
        description=(
            f"I'm thinking of a number between **{min_val}** and **{max_val}**.\n"
            "Type a number to guess!"
        ),
        color=discord.Color.green(),
    )
    await ctx.respond(embed=embed)
    log.info("Public game started in channel {}", ctx.channel.id)
