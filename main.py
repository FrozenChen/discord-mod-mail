#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import configparser
import io
import sqlite3
from os import environ
from os.path import join
from pathlib import Path
from subprocess import check_output, CalledProcessError
from sys import version_info
from typing import TYPE_CHECKING, Optional

import asqlite
import discord
from discord.ext import commands

from utils import MailCog, gen_color

if TYPE_CHECKING:
    from discord import Member, User
    from datetime import datetime
    from configparser import ConfigParser

version = "3.0.0"

is_docker = environ.get("IS_DOCKER", 0)
data_dir = environ.get("MODMAIL_DATA_DIR", ".")

database_file = join(data_dir, "modmail_data.sqlite")

pyver = "{0[0]}.{0[1]}.{0[2]}".format(version_info)
if version_info[3] != "final":
    pyver += "{0[3][0]}{0[4]}".format(version_info)

if is_docker:
    commit = environ.get("COMMIT_SHA", "<unknown>")
    branch = environ.get("COMMIT_BRANCH", "<unknown>")
else:
    try:
        commit = check_output(["git", "rev-parse", "HEAD"]).decode("ascii")[:-1]
    except CalledProcessError as e:
        print(f"Checking for git commit failed: {type(e).__name__} {e}")
        commit = "<unknown>"
    except FileNotFoundError:
        print("git not found, not showing commit")
        commit = "<unknown>"

    try:
        branch = check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode()[
            :-1
        ]
    except CalledProcessError as e:
        print(f"Checking for git branch failed: {type(e).__name__} {e}")
        branch = "<unknown>"
    except FileNotFoundError:
        print("git not found, not showing branch")
        branch = "<unknown>"

if not Path(join(data_dir, "config.ini")).is_file():
    print("Missing config file")
    exit(-1)
config = configparser.ConfigParser()
config.read(join(data_dir, "config.ini"))


class ModMail(commands.Bot):
    pool: asqlite.Pool
    prefix: str
    config: ConfigParser
    channel: discord.TextChannel
    already_ready: bool
    last_sender: Optional[discord.Member]
    command_mention: dict[str, str] = {}

    def __init__(
        self, max_messages: int, activity: discord.Activity, intents: discord.Intents
    ):
        super().__init__(
            [], max_messages=max_messages, activity=activity, intents=intents
        )
        self.config = config

    async def setup_tree(self):
        await self.add_cog(MailCog())
        synced_commands = await self.tree.sync()
        for command in synced_commands:
            self.command_mention[command.name] = f"</{command.name}:{command.id}>"

    async def setup_hook(self):
        self.already_ready = False
        self.last_sender = None
        self.pool = await asqlite.create_pool(database_file)
        async with self.pool.acquire() as conn:
            if (await conn.fetchone("PRAGMA user_version"))[0] == 0:
                print("Setting up", database_file)
                await conn.execute("PRAGMA application_id = 0x4D6F644D")
                await conn.execute("PRAGMA user_version = 1")
                with open("schema.sql", "r", encoding="utf-8") as f:
                    await conn.executescript(f.read())
        await self.setup_tree()

    async def on_ready(self):
        if self.already_ready:
            return
        post_startup_message = config["Main"].getboolean(
            "post_startup_message", fallback=True
        )
        channel = self.get_channel(int(config["Main"]["channel_id"]))
        if not channel or not isinstance(channel, discord.TextChannel):
            print(f'Channel with ID {config["Main"]["channel_id"]} not found.')
            await self.close()
            return
        self.channel = channel
        startup_message = (
            f"{self.user} is now ready. Version {version}, branch {branch}, commit {commit[0:7]}, "
            f"Python {pyver}"
        )
        print(startup_message)
        if post_startup_message:
            await self.channel.send(startup_message)
        self.already_ready = True

    async def handle_member_message(
        self,
        user: discord.User | discord.Member,
        message: str,
        files: list[discord.Attachment],
    ) -> None:

        if user.id not in anti_spam_check:
            anti_spam_check[user.id] = 0

        anti_spam_check[user.id] += 1
        if anti_spam_check[user.id] >= int(config["AntiSpam"]["messages"]):
            await self.add_ignore(user.id, "Automatic anti-spam ignore")
            await self.channel.send(
                f"{user.id} {user.mention} auto-ignored due to spam. "
                f'Use `{config["Main"]["command_prefix"]}unignore` to reverse.'
            )
            anti_spam_check[user.id] = 0
            return
        try:
            if isinstance(user, discord.User):
                try:
                    member = await self.channel.guild.fetch_member(user.id)
                except discord.NotFound:
                    member = user
            else:
                member = user

            embed = discord.Embed()
            embed.description = message

            if isinstance(member, discord.Member) and member.nick:
                author_name = f"{member.nick} ({member})"
            else:
                author_name = str(member)

            embed.set_author(
                name=author_name,
                icon_url=(
                    member.avatar.url if member.avatar else member.default_avatar.url
                ),
            )

            embed.colour = gen_color(user.id)

            to_send = f"{user.id}"
            if files:
                attachment_urls = []
                for attachment in files:
                    attachment_urls.append(
                        f"[{attachment.filename}]({attachment.url}) "
                        f"({attachment.size} bytes)"
                    )
                attachment_msg = "\N{BULLET} " + "\n\N{BULLET} ".join(attachment_urls)
                embed.add_field(name="Attachments", value=attachment_msg, inline=False)
            await self.channel.send(to_send, embed=embed)
            self.last_sender = member  # pyright: ignore[reportAttributeAccessIssue]
        finally:
            await asyncio.sleep(int(config["AntiSpam"]["seconds"]))
            anti_spam_check[user.id] -= 1

    async def handle_staff_message(
        self,
        interaction: discord.Interaction[ModMail],
        member: discord.User | discord.Member,
        author: discord.User | discord.Member,
        message: str,
        attachments: list[discord.Attachment],
    ):
        embed = discord.Embed(color=gen_color(member.id), description=message)
        if config["Main"].getboolean("anonymous_staff"):
            to_send = "Staff reply: "
        else:
            to_send = f"{author.mention}: "
        to_send += message

        files = []
        if attachments:
            for file in attachments:
                data = io.BytesIO(await file.read())
                files.append(discord.File(filename=file.filename, fp=data))

        try:
            staff_msg = await member.send(to_send, files=files)
        except discord.Forbidden:
            await interaction.followup.send(
                f"{author.mention} {member.mention} has disabled DMs", ephemeral=True
            )
            return

        header_message = f"{author.mention} replying to {member.id} {member.mention}"
        if await self.is_ignored(member.id):
            header_message += " (replies ignored)"

        # add attachment links to mod-mail message
        if staff_msg.attachments:
            attachment_urls = []
            for attachment in staff_msg.attachments:
                attachment_urls.append(
                    f"[{attachment.filename}]({attachment.url}) "
                    f"({attachment.size} bytes)"
                )
            attachment_msg = "\N{BULLET} " + "\n\N{BULLET} ".join(attachment_urls)
            embed.add_field(name="Attachments", value=attachment_msg, inline=False)

        await self.channel.send(header_message, embed=embed)
        await interaction.followup.send(
            f"Successfully messaged {member}!", ephemeral=True
        )

    async def on_typing(
        self,
        channel: discord.abc.MessageableChannel,
        user: Member | User,
        when: datetime,
    ):
        if isinstance(channel, discord.DMChannel):
            if not await self.is_ignored(user.id):
                await self.channel.typing()

    async def is_ignored(self, user_id: int) -> "Optional[tuple[int, Optional[str]]]":
        async with self.pool.acquire() as conn:
            res = await conn.fetchone(
                "SELECT quiet, reason FROM ignored WHERE user_id = ?", (user_id,)
            )
            if res:
                return res[0], res[1]

    async def add_ignore(
        self, user_id: int, reason: Optional[str] = None, is_quiet: bool = False
    ) -> bool:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO ignored VALUES (?, ?, ?)", (user_id, is_quiet, reason)
                )
                await conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    async def remove_ignore(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM ignored WHERE user_id = ?", (user_id,)
            )
            return res.get_cursor().rowcount


anti_spam_check = {}

if __name__ == "__main__":
    print(f"Starting discord-mod-mail {version}!")
    client = ModMail(
        max_messages=100,
        activity=discord.Activity(name=config["Main"]["playing"]),
        intents=discord.Intents(guilds=True, dm_typing=True),
    )
    client.run(config["Main"]["token"])
