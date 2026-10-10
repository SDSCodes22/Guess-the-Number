"""
Discord views and modals for the Higher or Lower game.

Provides UI components for the "chosen" game mode where a picker
secretly selects the hidden number via a modal.
"""

import discord
from discord.ext import commands
from loguru import logger as log


# --------------------------------------------------------------------------- #
#  Number Picker Modal — used in "chosen" mode to secretly input the target
# --------------------------------------------------------------------------- #

class NumberPickerModal(discord.ui.Modal):
    """
    Modal that allows the number picker to secretly enter the hidden number.

    This is only used in the "chosen" game mode where a human selects
    the number that other players must guess.
    """

    def __init__(self, min_val: int, max_val: int, game_creator_id: int):
        """
        Initialise the modal with the valid range and game creator.

        Args:
            min_val: Minimum possible number in the range.
            max_val: Maximum possible number in the range.
            game_creator_id: User ID of the person who started the game.
        """
        super().__init__(title="Pick a Secret Number")
        self.min_val = min_val
        self.max_val = max_val
        self.game_creator_id = game_creator_id

        # Add a text input field for the secret number
        self.number_input = discord.ui.TextInput(
            label=f"Enter a number between {min_val} and {max_val}",
            placeholder="Type your number here...",
            required=True,
            min_length=1,
            max_length=10,
        )
        self.add_item(self.number_input)

    # ------------------------------------------------------------------ #
    #  Modal submission handler
    # ------------------------------------------------------------------ #

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Handle the modal submission.

        Validates the input, stores the chosen number, and signals
        the game cog to start the game via a callback stored on
        the bot instance.
        """
        # Validate the entered number is an integer within range
        try:
            chosen_number = int(self.number_input.value)
        except ValueError:
            await interaction.response.send_message(
                "That's not a valid number. Game cancelled.",
                ephemeral=True,
            )
            return

        if chosen_number < self.min_val or chosen_number > self.max_val:
            await interaction.response.send_message(
                f"Number must be between {self.min_val} and {self.max_val}. Game cancelled.",
                ephemeral=True,
            )
            return

        # Acknowledge the modal submission
        await interaction.response.send_message(
            f"Your secret number has been set! Starting the game...",
            ephemeral=True,
        )

        # Trigger the game creation callback stored on the bot
        # This is set by the game cog's chosen command
        callback = getattr(interaction.client, "_chosen_game_callback", None)
        if callback:
            await callback(
                channel=interaction.channel,
                min_val=self.min_val,
                max_val=self.max_val,
                target=chosen_number,
                picker_id=self.game_creator_id,
            )


# --------------------------------------------------------------------------- #
#  Number Picker View — button that opens the NumberPickerModal
# --------------------------------------------------------------------------- #

class NumberPickerView(discord.ui.View):
    """
    View with a single button that opens the NumberPickerModal.

    Sent in response to the /guessthenum chosen command so the
    picker can privately enter the hidden number.
    """

    def __init__(self, min_val: int, max_val: int, game_creator_id: int):
        """
        Initialise the view with range info and the game creator.

        Args:
            min_val: Minimum possible number in the range.
            max_val: Maximum possible number in the range.
            game_creator_id: User ID of the person who started the game.
        """
        super().__init__(timeout=60)
        self.min_val = min_val
        self.max_val = max_val
        self.game_creator_id = game_creator_id

    @discord.ui.button(label="Pick a Number", style=discord.ButtonStyle.primary)
    async def pick_number_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """Open the NumberPickerModal when the button is clicked."""
        modal = NumberPickerModal(
            min_val=self.min_val,
            max_val=self.max_val,
            game_creator_id=self.game_creator_id,
        )
        await interaction.response.send_modal(modal)

    async def on_timeout(self) -> None:
        """Disable all buttons when the view times out."""
        for child in self.children:
            child.disabled = True
