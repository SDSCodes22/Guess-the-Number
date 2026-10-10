"""
Admin cog — range management and bot maintenance commands.

Provides CRUD operations for preset ranges stored in data/ranges.json,
plus reload and sync utilities for bot maintenance.
"""

import json
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from loguru import logger as log


# --------------------------------------------------------------------------- #
#  Constants
# --------------------------------------------------------------------------- #

# Path to the ranges JSON file (relative to project root)
RANGES_FILE = Path(__file__).parent.parent / "data" / "ranges.json"


# --------------------------------------------------------------------------- #
#  Range helper functions (each < 40 lines)
# --------------------------------------------------------------------------- #

def load_ranges() -> dict:
    """
    Load all preset ranges from the JSON file.

    Returns:
        A dict mapping range names to {"min": int, "max": int}.
        Returns an empty dict if the file is missing or invalid.
    """
    try:
        with open(RANGES_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning("ranges.json not found, returning empty dict")
        return {}
    except json.JSONDecodeError:
        log.error("ranges.json is corrupted, returning empty dict")
        return {}


def save_ranges(ranges: dict) -> None:
    """
    Write the ranges dict back to the JSON file.

    Args:
        ranges: A dict mapping range names to {"min": int, "max": int}.
    """
    RANGES_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(RANGES_FILE, "w") as f:
        json.dump(ranges, f, indent=4)
    log.debug("Saved ranges to {}", RANGES_FILE)


def add_range(name: str, min_val: int, max_val: int) -> bool:
    """
    Add a new preset range.

    Args:
        name:    The key name for the range (e.g. "Fun").
        min_val: Minimum value of the range.
        max_val: Maximum value of the range.

    Returns:
        True if the range was added, False if it already exists.
    """
    ranges = load_ranges()

    if name in ranges:
        return False

    ranges[name] = {"min": min_val, "max": max_val}
    save_ranges(ranges)
    log.info("Added range '{}' ({}–{})", name, min_val, max_val)
    return True


def remove_range(name: str) -> bool:
    """
    Remove a preset range by name.

    Args:
        name: The key name of the range to remove.

    Returns:
        True if the range was removed, False if it didn't exist.
    """
    ranges = load_ranges()

    if name not in ranges:
        return False

    del ranges[name]
    save_ranges(ranges)
    log.info("Removed range '{}'", name)
    return True


def edit_range(name: str, min_val: int, max_val: int) -> bool:
    """
    Update an existing preset range's bounds.

    Args:
        name:    The key name of the range to update.
        min_val: New minimum value.
        max_val: New maximum value.

    Returns:
        True if the range was updated, False if it didn't exist.
    """
    ranges = load_ranges()

    if name not in ranges:
        return False

    ranges[name] = {"min": min_val, "max": max_val}
    save_ranges(ranges)
    log.info("Edited range '{}' to ({}–{})", name, min_val, max_val)
    return True


def get_range_names() -> list[str]:
    """
    Get a list of all range key names.

    Returns:
        A list of range name strings.
    """
    return list(load_ranges().keys())


# --------------------------------------------------------------------------- #
#  Autocomplete helper for slash commands
# --------------------------------------------------------------------------- #

async def _range_autocomplete(ctx: discord.AutocompleteContext) -> list[str]:
    """
    Provide autocomplete suggestions for range names.

    Args:
        ctx: The autocomplete context.

    Returns:
        A list of matching range names.
    """
    names = get_range_names()
    if ctx.value:
        return [n for n in names if ctx.value.lower() in n.lower()]
    return names


# --------------------------------------------------------------------------- #
#  Admin Cog
# --------------------------------------------------------------------------- #

class Admin(commands.Cog):
    """
    Admin cog — range management and bot maintenance.

    Uses standard slash commands via commands.slash_command.
    """

    def __init__(self, bot: commands.Bot) -> None:
        """Store bot reference."""
        self.bot = bot
        log.info("Admin cog loaded")

    # ================================================================== #
    #  Slash commands
    # ================================================================== #

    @commands.slash_command(name="addrange", description="Add a new preset range")
    @commands.has_permissions(administrator=True)
    async def cmd_addrange(
        self,
        ctx: discord.ApplicationContext,
        name: discord.Option(str, "Key name for the range (e.g. Hard Mode)"),
        min_val: discord.Option(int, "Minimum value of the range"),
        max_val: discord.Option(int, "Maximum value of the range"),
    ) -> None:
        """
        Add a new preset range for the Higher or Lower game.

        Args:
            ctx:     The application context.
            name:    Key name for the range.
            min_val: Minimum value of the range.
            max_val: Maximum value of the range.
        """
        if min_val >= max_val:
            await ctx.respond("Minimum must be less than maximum!")
            return

        success = add_range(name, min_val, max_val)

        if success:
            await ctx.respond(f"✅ Range **{name}** added ({min_val}–{max_val}).")
        else:
            await ctx.respond(
                f"❌ Range **{name}** already exists. Use editrange to modify it."
            )

    @commands.slash_command(name="removerange", description="Remove a preset range")
    @commands.has_permissions(administrator=True)
    async def cmd_removerange(
        self,
        ctx: discord.ApplicationContext,
        name: discord.Option(str, "Key name of the range to remove"),
    ) -> None:
        """
        Remove an existing preset range.

        Args:
            ctx:  The application context.
            name: Key name of the range to remove.
        """
        success = remove_range(name)

        if success:
            await ctx.respond(f"✅ Range **{name}** removed.")
        else:
            await ctx.respond(f"❌ Range **{name}** not found.")

    @commands.slash_command(name="editrange", description="Edit an existing preset range")
    @commands.has_permissions(administrator=True)
    async def cmd_editrange(
        self,
        ctx: discord.ApplicationContext,
        name: discord.Option(str, "Key name of the range to update"),
        min_val: discord.Option(int, "New minimum value"),
        max_val: discord.Option(int, "New maximum value"),
    ) -> None:
        """
        Update an existing preset range's bounds.

        Args:
            ctx:     The application context.
            name:    Key name of the range to update.
            min_val: New minimum value.
            max_val: New maximum value.
        """
        if min_val >= max_val:
            await ctx.respond("Minimum must be less than maximum!")
            return

        success = edit_range(name, min_val, max_val)

        if success:
            await ctx.respond(f"✅ Range **{name}** updated to {min_val}–{max_val}.")
        else:
            await ctx.respond(f"❌ Range **{name}** not found.")

    @commands.slash_command(name="listranges", description="List all preset ranges")
    async def cmd_listranges(self, ctx: discord.ApplicationContext) -> None:
        """
        List all available preset ranges.

        Args:
            ctx: The application context.
        """
        ranges = load_ranges()

        if not ranges:
            await ctx.respond("No ranges configured. Use `addrange` to create one.")
            return

        lines = ["**Preset Ranges:**\n"]
        for name, bounds in ranges.items():
            lines.append(f"• **{name}** — {bounds['min']}–{bounds['max']}")

        await ctx.respond("\n".join(lines))

    @commands.slash_command(name="reload", description="Reload a cog")
    @commands.is_owner()
    async def cmd_reload(
        self,
        ctx: discord.ApplicationContext,
        cog: discord.Option(str, "Cog module name (e.g. game, duel, admin)"),
    ) -> None:
        """
        Reload a cog by name.

        Args:
            ctx:  The application context.
            cog:  The cog module name.
        """
        extension = f"cogs.{cog}"

        try:
            await self.bot.reload_extension(extension)
            await ctx.respond(f"✅ Reloaded `{extension}`.")
            log.info("Reloaded cog {}", extension)
        except Exception as e:
            await ctx.respond(f"❌ Failed to reload `{extension}`: {e}")
            log.error("Failed to reload {}: {}", extension, e)

    @commands.slash_command(name="sync", description="Sync slash commands with Discord")
    @commands.is_owner()
    async def cmd_sync(self, ctx: discord.ApplicationContext) -> None:
        """
        Sync slash commands with Discord.

        Args:
            ctx: The application context.
        """
        try:
            synced = await self.bot.tree.sync()
            await ctx.respond(f"✅ Synced {len(synced)} command(s).")
            log.info("Synced {} slash commands", len(synced))
        except Exception as e:
            await ctx.respond(f"❌ Failed to sync: {e}")
            log.error("Failed to sync commands: {}", e)


# --------------------------------------------------------------------------- #
#  Cog setup (sync in py-cord)
# --------------------------------------------------------------------------- #

def setup(bot: commands.Bot) -> None:
    """Register the Admin cog with the bot."""
    bot.add_cog(Admin(bot))
