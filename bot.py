"""
Main bot file — Higher or Lower Discord bot.

Loads all cogs and runs the bot.  Configure via .env:
    DISCORD_TOKEN  — Your bot token.
    GAME_TIMEOUT   — Seconds before an inactive game auto-cancels (default 300).
"""

import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
from loguru import logger as log

# --------------------------------------------------------------------------- #
#  Load environment variables
# --------------------------------------------------------------------------- #

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GAME_TIMEOUT = int(os.getenv("GAME_TIMEOUT", "300"))

# --------------------------------------------------------------------------- #
#  Bot setup
# --------------------------------------------------------------------------- #

bot = discord.Bot(command_prefix="?", intents=discord.Intents.all())

# Expose the game timeout so cogs can access it via bot.game_timeout
bot.game_timeout = GAME_TIMEOUT


@bot.event
async def on_ready() -> None:
    """Log bot startup information."""
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    log.info(f"Game timeout set to {GAME_TIMEOUT}s")
    log.info("------")


@bot.slash_command(name="ping", description="Check bot latency")
async def ping(ctx: discord.ApplicationContext) -> None:
    """
    Respond with the bot's current latency in milliseconds.

    Args:
        ctx: The application context.
    """
    await ctx.respond(f"Pong! {round(bot.latency * 1000)}ms")


# --------------------------------------------------------------------------- #
#  Load cogs
# --------------------------------------------------------------------------- #

def setup_hook() -> None:
    """Load all cogs during bot startup."""
    extensions = [
        "cogs.general",
        "cogs.admin",
        # "cogs.results" Disable the results cog
    ]

    for ext in extensions:
        try:
            bot.load_extension(ext)
            log.info("Loaded {}", ext)
        except Exception as e:
            log.error("Failed to load {}: {}", ext, e)


bot.setup_hook = setup_hook
bot.setup_hook()
# --------------------------------------------------------------------------- #
#  Run the bot
# --------------------------------------------------------------------------- #

bot.run(TOKEN)
