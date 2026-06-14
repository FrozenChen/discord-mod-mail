import random
from typing import TYPE_CHECKING, Optional

import discord
from discord import ui, app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from main import ModMail


def gen_color(user_id: int):
    random.seed(user_id)
    c_r = random.randint(0, 255)
    c_g = random.randint(0, 255)
    c_b = random.randint(0, 255)
    return discord.Color((c_r << 16) + (c_g << 8) + c_b)


class MessageModMailModal(ui.Modal, title="Message ModMail"):
    message = ui.TextInput(
        label="Message", style=discord.TextStyle.paragraph, required=True
    )

    files = discord.ui.Label(
        text="Files",
        description="Upload any relevant files or images to your message.",
        component=discord.ui.FileUpload(
            max_values=4,
            required=False,
        ),
    )

    async def on_submit(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, interaction: discord.Interaction["ModMail"]
    ):
        assert isinstance(self.files.component, discord.ui.FileUpload)
        await interaction.response.defer(ephemeral=True)
        await interaction.client.handle_member_message(
            interaction.user, self.message.value, self.files.component.values
        )
        await interaction.followup.send(
            "Your message was sent to staff!", ephemeral=True
        )


class MessageUserModal(ui.Modal, title="Message User"):
    message = ui.TextInput(
        label="Message", style=discord.TextStyle.paragraph, required=True
    )

    files = discord.ui.Label(
        text="Files",
        description="Upload any relevant files or images to your message.",
        component=discord.ui.FileUpload(
            max_values=4,
            required=False,
        ),
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, interaction: discord.Interaction["ModMail"]
    ):
        assert isinstance(self.files.component, discord.ui.FileUpload)
        await interaction.response.defer(ephemeral=True)
        await interaction.client.handle_staff_message(
            interaction,
            self.member,
            interaction.user,
            self.message.value,
            self.files.component.values,
        )


class MailCog(commands.Cog):

    @app_commands.command(name="message_modmail")
    async def message_modmail(self, interaction: discord.Interaction["ModMail"]):
        """Message staff via ModMail"""
        if await interaction.client.is_ignored(interaction.user.id):
            await interaction.response.send_message(
                f"You cannot use {interaction.client.command_mention[self.message_modmail.name]} as you have been ignored",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(MessageModMailModal())

    @app_commands.guild_only()
    @app_commands.command(name="message_user")
    async def message_user(
        self,
        interaction: discord.Interaction["ModMail"],
        member: Optional[discord.Member],
        message: str,
        file: Optional[discord.Attachment],
    ):
        """Message user via ModMail. Limited to only 1 file.

        Args:
            member: User to message. If missing, messages the last member that sent a message via modmail.
            message: Message to send
            file: Optional file to send to the user.
        """
        if member is None:
            if interaction.client.last_sender:
                member = interaction.client.last_sender
            else:
                await interaction.response.send_message(
                    "There is no last message in the current session.", ephemeral=True
                )
                return

        if member.bot:
            await interaction.response.send_message(
                "You can't send messages to bots.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        await interaction.client.handle_staff_message(
            interaction, member, interaction.user, message, [file] if file else []
        )

    @app_commands.guild_only()
    @app_commands.command(name="message_user_ui")
    async def message_user_modal(
        self,
        interaction: discord.Interaction["ModMail"],
        member: Optional[discord.Member],
    ):
        """Message user via ModMail. Limited to only 1 file.

        Args:
            member: User to message. If missing, messages last member that sent a message via modmail.

        """
        if member is None:
            if interaction.client.last_sender:
                member = interaction.client.last_sender
            else:
                await interaction.response.send_message(
                    "There is no last message in the current session.", ephemeral=True
                )
                return

        if member.bot:
            await interaction.response.send_message(
                "You can't send messages to bots.", ephemeral=True
            )
            return
        await interaction.response.send_modal(MessageUserModal(member))

    @app_commands.guild_only()
    @app_commands.command()
    async def ignore_user(
        self,
        interaction: discord.Interaction["ModMail"],
        member: discord.Member,
        reason: Optional[str] = None,
        quiet: bool = False,
    ):
        """Add users to the ignore list

        Args:
            member: User to ignore
            reason: Reason for ignoring
            quiet: If to suppress the notification for the user. Defaults to False.
        """

        dm_failed = False

        if await interaction.client.add_ignore(member.id, reason, quiet):
            if not quiet:
                to_send = "Your messages are being ignored by staff."
                if reason:
                    to_send += " Reason: " + reason

                try:
                    await member.send(to_send)
                except discord.errors.Forbidden:
                    dm_failed = True
            await interaction.response.send_message(
                "Ignored user successfully", ephemeral=True
            )
            await interaction.client.channel.send(
                f"{interaction.user} added {member.mention} {member} to the ignore list. This user won't be able to use {interaction.client.command_mention[self.message_modmail.name]}. "
                f"Use {interaction.client.command_mention[self.unignore_user.name]} to reverse.{" (Bot failed to notify member of this action)" if dm_failed else ""}"
            )
        else:
            await interaction.response.send_message(
                f"{member.mention} {member.id} is already ignored.",
                ephemeral=True,
            )

    @app_commands.guild_only()
    @app_commands.command()
    async def unignore_user(
        self, interaction: discord.Interaction["ModMail"], member: discord.Member
    ):
        """Removes user from the ignore list

        Args:
            member: User to remove
        """

        dm_failed = False
        ignored = await interaction.client.is_ignored(member.id)

        if ignored:
            is_quiet = ignored[0]
            if not is_quiet:
                to_send = "Your messages are no longer being ignored by staff."
                try:
                    await member.send(to_send)
                except discord.errors.Forbidden:
                    dm_failed = True

        if await interaction.client.remove_ignore(member.id):
            await interaction.response.send_message(
                "Unignored user successfully", ephemeral=True
            )
            await interaction.client.channel.send(
                f"{interaction.user} removed {member.mention} {member} from the ignore list. This user will now be able to use {interaction.client.command_mention[self.message_modmail.name]} again. "
                f"Use {interaction.client.command_mention[self.ignore_user.name]} to reverse.{" (Bot failed to notify member of this action)" if dm_failed else ""}"
            )
        else:
            await interaction.response.send_message(
                f"{member.mention} {member} is not ignored.", ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command()
    async def mention_last_user(self, interaction: discord.Interaction["ModMail"]):
        """Mentions the last user"""
        if interaction.client.last_sender:
            await interaction.response.send_message(
                f"{interaction.client.last_sender.id} {interaction.client.last_sender}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "There is no last message in the current session.", ephemeral=True
            )

    @app_commands.guild_only()
    @app_commands.command()
    async def fix_game(self, interaction: discord.Interaction["ModMail"]):
        """Attempts to fix the bot activity"""
        await interaction.client.change_presence(activity=None)
        await interaction.client.change_presence(
            activity=discord.Game(name=interaction.client.config["Main"]["playing"])
        )
        await interaction.response.send_message("Game presence re-set.", ephemeral=True)
