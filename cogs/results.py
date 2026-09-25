import discord 
from loguru import logger as log
import json

tiers = [f"{'H' if i % 2 == 0 else 'L'}T{i // 2 + 1}" for i in range(10)]  # Generates LT1, HT1, LT2, HT2, ..., LT5, HT5

def numerical_tiers_to_short_string(numerical_tier: int) -> str:
    """
    Convert a numerical tier to its string representation.

    Args:
        numerical_tier: The numerical tier (1-10).

    Returns:
        The string representation of the tier (e.g., "LT1", "HT1").
    """
    if 1 <= numerical_tier <= 10:
        return tiers[9 - (numerical_tier - 1)]
    else:
        raise ValueError("Numerical tier must be between 1 and 10.")

def short_string_to_numerical_tiers(tier_str: str) -> int:
    """
    Convert a short string representation of a tier to its numerical value.

    Args:
        tier_str: The string representation of the tier (e.g., "LT1", "HT1").

    Returns:
        The numerical value of the tier (1-10).
    """
    if tier_str in tiers:
        return 10 - tiers.index(tier_str)
    else:
        raise ValueError("Invalid tier string. Must be one of: " + ", ".join(tiers))

def get_tier_from_discord_id(discord_id: int) -> str:
    """
    Get the tier string representation for a given Discord ID.

    Args:
        discord_id: The Discord ID of the user.
    Returns:
        The string representation of the tier (e.g., "LT1", "HT1").
    """
    with open("data/tiers.json", "r") as f:
        tiers_data = json.load(f)  # {<discord_id>: <numerical tier, LT5 = 1, HT1 = 10>}
    
    numerical_tier = tiers_data.get(str(discord_id))
    if numerical_tier is not None:
        return numerical_tiers_to_short_string(numerical_tier)
    else:
        return "Unranked"  # Return "Unranked" if the user has no tier assigned
    
def save_tier_for_discord_id(discord_id: int, numerical_tier: int) -> None:
    """
    Save the numerical tier for a given Discord ID.

    Args:
        discord_id: The Discord ID of the user.
        numerical_tier: The numerical tier (1-10) to save.
    """
    if not (1 <= numerical_tier <= 10):
        raise ValueError("Numerical tier must be between 1 and 10.")
    
    with open("data/tiers.json", "r") as f:
        tiers_data = json.load(f)
    
    tiers_data[str(discord_id)] = numerical_tier
    
    with open("data/tiers.json", "w") as f:
        json.dump(tiers_data, f, indent=4)

def short_string_to_long_string(tier_str: str) -> str:
    """
    Convert a short string representation of a tier to its long string representation.

    Args:
        tier_str: The string representation of the tier (e.g., "LT1", "HT1").

    Returns:
        The long string representation of the tier (e.g., "Low Tier 1", "High Tier 1").
    """
    if tier_str.startswith("LT"):
        return f"Low Tier {tier_str[2:]}"
    elif tier_str.startswith("HT"):
        return f"High Tier {tier_str[2:]}"
    else:
        raise ValueError("Invalid tier string. Must be one of: " + ", ".join(tiers))
    
class ResultsCog(discord.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        log.info("Results cog loaded")

    
    @discord.slash_command(name="result", description="Send a result message to the results channel")
    async def result(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Member,
        tester: discord.Member,
        tier: discord.Option(str, description="Tier that the player has earned", choices=tiers),
        region: discord.Option(str, description="Region of the player", choices=["NA", "EU", "AS", "SA", "AF", "OC"]),
        score: str,
        notes: str = None
        ):
        await ctx.defer(ephemeral=True)  # Defer the response to give more time for processing
        # Open data/config.json and get the tester roles
        with open("data/config.json", "r") as f:
            config = json.load(f)
            tester_roles = config.get("tester_roles", [])
            results_channel_id = config.get("results_channel_id")
        is_tester = any(role.id in tester_roles for role in ctx.author.roles)
        if not is_tester:
            await ctx.respond(embed=discord.Embed(title=":x: No Permission", description="You have no permission to use this command", color=discord.Color.red()), ephemeral=True)
            return

        prev_tier = get_tier_from_discord_id(user.id)
        save_tier_for_discord_id(user.id, short_string_to_numerical_tiers(tier))
        results_channel = await self.bot.fetch_channel(results_channel_id)
        

        #! You can configure the results embed here
        fields=[
                discord.EmbedField(name="Tester:", value=tester.mention),
                discord.EmbedField(name="Region:", value=region),
                discord.EmbedField(name="Previous Tier:", value=(short_string_to_long_string(prev_tier) if prev_tier != "Unranked" else "Unranked")),
                discord.EmbedField(name="New Tier:", value=short_string_to_long_string(tier)),
                discord.EmbedField(name="Score:", value=score),
        ]
        if notes:
            fields.append(discord.EmbedField(name="Notes:", value=notes))

        results_embed = discord.Embed(
            author=discord.EmbedAuthor(name=f"{user.display_name}'s Test Results 🏆"),
            color = discord.Color.yellow(),
            fields=fields
        )
        results_msg = await results_channel.send(content=user.mention, embed=results_embed)
        await results_msg.add_reaction("⬆️")
        await results_msg.add_reaction("⬇️")
        await results_msg.add_reaction("📊")
        await results_msg.add_reaction("🤑")
        await ctx.respond(embed=discord.Embed(title=":white_check_mark: Result Sent", description=f"Result sent to {results_channel.mention}", color=discord.Color.green()), ephemeral=True)


    
def setup(bot: discord.Bot):
    bot.add_cog(ResultsCog(bot))