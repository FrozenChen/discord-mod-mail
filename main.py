#!/usr/bin/env python3

from __future__ import annotations
import asyncio
import configparser
import random
from io import BytesIO

import asqlite
import sqlite3
from os import environ
from os.path import join
from subprocess import check_output, CalledProcessError
from sys import version_info
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from typing import Optional
    from discord import Member, User
    from datetime import datetime

version = "2.0.0"
SIZE_LIMIT = 0x800000
SIZE_DIFF = 0x800

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
    except FileNotFoundError as e:
        print("git not found, not showing commit")
        commit = "<unknown>"

    try:
        branch = check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode()[
            :-1
        ]
    except CalledProcessError as e:
        print(f"Checking for git branch failed: {type(e).__name__} {e}")
        branch = "<unknown>"
    except FileNotFoundError as e:
        print("git not found, not showing branch")
        branch = "<unknown>"

print(f"Starting discord-mod-mail {version}!")

config = configparser.ConfigParser()
config.read(join(data_dir, "config.ini"))


class ModMail(discord.Client):
    pool: asqlite.Pool
    prefix: str
    channel: discord.TextChannel
    config: configparser.ConfigParser
    already_ready: bool
    last_id: Optional[int]

    async def setup_hook(self):
        self.already_ready = False
        self.last_id = None
        self.prefix = config["Main"]["command_prefix"]
        self.pool = await asqlite.create_pool(database_file)
        async with self.pool.acquire() as conn:
            if (await conn.fetchone("PRAGMA user_version"))[0] == 0:
                print("Setting up", database_file)
                await conn.execute("PRAGMA application_id = 0x4D6F644D")
                await conn.execute("PRAGMA user_version = 1")
                with open("schema.sql", "r", encoding="utf-8") as f:
                    await conn.executescript(f.read())

    async def on_ready(self):
        if self.already_ready:
            return
        post_startup_message = config["Main"].getboolean(
            "post_startup_message", fallback=True
        )
        channel = self.get_channel(int(config["Main"]["channel_id"]))
        if not channel or type(channel) is not discord.TextChannel:
            print(f'Channel with ID {config["Main"]["channel_id"]} not found.')
            await self.close()
            return
        self.channel = channel
        print("{0.user} is now ready.".format(client))
        startup_message = (
            f"{self.user} is now ready. Version {version}, branch {branch}, commit {commit[0:7]}, "
            f"Python {pyver}"
        )
        if post_startup_message:
            await self.channel.send(startup_message)
        print(startup_message)
        self.already_ready = True

    async def on_message(self, message: discord.Message):
        author = message.author
        if message.author.bot:
            return
        if not self.already_ready:
            return

        if type(message.channel) is discord.DMChannel:
            if await self.is_ignored(author.id):
                return

            if author.id not in anti_spam_check:
                anti_spam_check[author.id] = 0

            anti_spam_check[author.id] += 1
            if anti_spam_check[author.id] >= int(config["AntiSpam"]["messages"]):
                await self.add_ignore(author.id, "Automatic anti-spam ignore")
                await self.channel.send(
                    f"{author.id} {author.mention} auto-ignored due to spam. "
                    f'Use `{config["Main"]["command_prefix"]}unignore` to reverse.'
                )
                anti_spam_check[author.id] = 0
                return

            # for the purpose of nicknames, if anys
            for server in self.guilds:
                member = server.get_member(author.id)
                if member:
                    author = member
                break

            embed = discord.Embed(
                color=gen_color(author.id), description=message.content
            )
            if isinstance(author, discord.Member) and author.nick:
                author_name = f"{author.nick} ({author})"
            else:
                author_name = str(author)
            embed.set_author(
                name=author_name,
                icon_url=author.avatar.url
                if author.avatar
                else author.default_avatar.url,
            )

            to_send = f"{author.id}"
            if message.attachments:
                attachment_urls = []
                for attachment in message.attachments:
                    attachment_urls.append(
                        f"[{attachment.filename}]({attachment.url}) "
                        f"({attachment.size} bytes)"
                    )
                attachment_msg = "\N{BULLET} " + "\n\N{BULLET} ".join(attachment_urls)
                embed.add_field(name="Attachments", value=attachment_msg, inline=False)
            await self.channel.send(to_send, embed=embed)
            await message.add_reaction("\N{WHITE HEAVY CHECK MARK}")
            self.last_id = author.id
            await asyncio.sleep(int(config["AntiSpam"]["seconds"]))
            anti_spam_check[author.id] -= 1

        elif message.channel == self.channel:
            if not message.content.startswith(self.prefix):
                return
            args = list(message.content[len(self.prefix) :].split(maxsplit=1))

            # #Nothing after the prefix
            if not args:
                return
            if args[0].isdigit():
                args[0] = int(args[0])  # type: ignore
            match args:
                case ["ignore" | "qignore" | "unignore"]:
                    await self.channel.send("Did you forget to enter an ID?")
                case ["ignore", params]:
                    user_id_str, *reason = params.split(maxsplit=1)
                    await self.handle_ignore(
                        message, user_id_str, reason[0] if reason else None
                    )
                case ["qignore", params]:
                    user_id_str, *reason = params.split(maxsplit=1)
                    await self.handle_ignore(
                        message, user_id_str, reason[0] if reason else None, quiet=True
                    )
                case ["unignore", params]:
                    user_id_str, *_ = params.split(maxsplit=1)
                    await self.handle_unignore(message, user_id_str)
                case [int(user_id), *message_content]:
                    if not (message_content or message.attachments):
                        await self.channel.send("Did you forget to enter a message?")
                        return
                    await self.handle_staff_reply(
                        message, user_id, message_content[0] if message_content else ""
                    )
                case ["r", *message_content]:
                    if self.last_id:
                        if not (message_content or message.attachments):
                            await self.channel.send(
                                "Did you forget to enter a message?"
                            )
                            return
                        await self.handle_staff_reply(
                            message,
                            self.last_id,
                            message_content[0] if message_content else "",
                        )
                    else:
                        await self.channel.send(
                            "There is no last message in the current session."
                        )
                        return
                case ["m", *_]:
                    if self.last_id:
                        await self.channel.send(f"{self.last_id} <@!{self.last_id}>")
                    else:
                        await self.channel.send(
                            "There is no last message in the current session."
                        )
                        return
                case ["fixgame", *_]:
                    await self.change_presence(activity=None)
                    await self.change_presence(
                        activity=discord.Game(name=config["Main"]["playing"])
                    )
                    await self.channel.send("Game presence re-set.")
            await asyncio.sleep(2)
            anti_duplicate_replies[args[0]] = False

    async def handle_ignore(
        self,
        message: discord.Message,
        user_id_str: str,
        reason: Optional[str],
        *,
        quiet=False,
    ):
        assert message.guild is not None
        try:
            user_id = int(user_id_str)
        except ValueError:
            await self.channel.send("Could not convert to int.")
            return

        member = message.guild.get_member(user_id)

        if await self.add_ignore(user_id, reason, quiet):
            if not quiet:
                to_send = "Your messages are being ignored by staff."
                if reason:
                    to_send += " Reason: " + reason

                if member:
                    try:
                        await member.send(to_send)
                    except discord.errors.Forbidden:
                        await self.channel.send(
                            f"{member.mention} has disabled DMs or is not in a "
                            f"shared server, not sending reason."
                        )
                else:
                    await self.channel.send(
                        "Failed to find user with ID, not sending reason."
                    )
            await self.channel.send(
                f"{message.author.mention} {user_id} is now ignored. Messages from this user will not appear. "
                f"Use `{self.prefix}unignore` to reverse."
            )
        else:
            await self.channel.send(
                f"{message.author.mention} {user_id} is already ignored."
            )

    async def handle_unignore(self, message, user_id_str):
        try:
            user_id = int(user_id_str)
            member = message.guild.get_member(user_id)
        except ValueError:
            await self.channel.send("Could not convert to int.")
            return

        ignored = await self.is_ignored(user_id)
        if ignored:
            is_quiet = ignored[0]
            if not is_quiet:
                to_send = "Your messages are no longer being ignored by staff."
                if member:
                    try:
                        await member.send(to_send)
                    except discord.errors.Forbidden:
                        await self.channel.send(
                            f"{member.mention} has disabled DMs or is not in "
                            f"a shared server, not sending notification."
                        )
                else:
                    await self.channel.send(
                        "Failed to find user with ID, not sending notification."
                    )
        if await self.remove_ignore(user_id):
            await self.channel.send(
                f"{message.author.mention} {user_id} is no longer ignored. Messages from this user will appear "
                f"again. Use `{self.prefix}ignore` to reverse."
            )
        else:
            await self.channel.send(
                f"{message.author.mention} {user_id} is not ignored."
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

    async def handle_staff_reply(
        self, message: discord.Message, user_id: int, message_content: str = ""
    ):
        assert message.guild is not None
        member = message.guild.get_member(user_id)
        if not member:
            return await self.channel.send("Failed to find member.")
        if member.bot:
            return await self.channel.send("You can't send messages to bots.")
        author = message.author
        embed = discord.Embed(color=gen_color(user_id), description=message_content)
        if config["Main"].getboolean("anonymous_staff"):
            to_send = "Staff reply: "
        else:
            to_send = f"{author.mention}: "
        to_send += message_content

        try:
            attachments, progress_msg = await self.handle_attachments(message)
        except ValueError:
            return

        if progress_msg:
            await progress_msg.edit(
                content=f"Sending message with {len(attachments)} " f"attachments..."
            )
        try:
            staff_msg = await member.send(to_send, files=attachments)
        except discord.Forbidden:
            return await self.channel.send(
                f"{author.mention} {member.mention} has disabled DMs"
            )
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
        if progress_msg:
            await progress_msg.delete()
        await message.delete()

    async def handle_attachments(
        self, message: discord.Message
    ) -> tuple[list[discord.File], Optional[discord.Message]]:
        attachments = []
        if not message.attachments:
            return attachments, None
        # first check the size of all attachments
        # the 0x800 number is arbitrary, just in case
        # in reality, the file size needs to be like 0x200 smaller than the supposed limit
        error_messages = []
        warning_messages = []
        for a in message.attachments:
            if a.size > SIZE_LIMIT:
                error_messages.append(
                    f"`{discord.utils.escape_markdown(a.filename)}` "
                    f"is too large to send in a direct message."
                )
            elif a.size > SIZE_LIMIT - 0x1000:
                warning_messages.append(
                    f"`{discord.utils.escape_markdown(a.filename)}` "
                    f"is very close to the file size limit of the "
                    f"destination. It may fail to send."
                )

        if error_messages:
            final = "\n".join(error_messages)
            final += (
                f"\nLimit: {SIZE_LIMIT} bytes ({SIZE_LIMIT / (1024 * 1024):.02f} MiB)"
            )
            final += (
                f"\nRecommended Maximum: {SIZE_LIMIT - SIZE_DIFF} bytes "
                f"({(SIZE_LIMIT - SIZE_DIFF) / (1024 * 1024):.02f} MiB)"
            )
            await message.channel.send(final)
            raise ValueError

        if warning_messages:
            final = "\n".join(warning_messages)
            final += (
                f"\nLimit: {SIZE_LIMIT} bytes ({SIZE_LIMIT / (1024 * 1024):.02f} MiB)"
            )
            final += (
                f"\nRecommended Maximum: {SIZE_LIMIT - SIZE_DIFF} bytes "
                f"({(SIZE_LIMIT - SIZE_DIFF) / (1024 * 1024):.02f} MiB)"
            )
            await message.channel.send(final)

        count = len(message.attachments)
        progress_msg = await self.channel.send(f"Downloading attachments... 0/{count}")
        for idx, a in enumerate(message.attachments, 1):
            buffer = BytesIO()
            await a.save(buffer, seek_begin=True)
            attachments.append(discord.File(buffer, a.filename))
            await progress_msg.edit(content=f"Downloading attachments... {idx}/{count}")
        return attachments, progress_msg


def gen_color(user_id: int):
    random.seed(user_id)
    c_r = random.randint(0, 255)
    c_g = random.randint(0, 255)
    c_b = random.randint(0, 255)
    return discord.Color((c_r << 16) + (c_g << 8) + c_b)


anti_spam_check = {}

anti_duplicate_replies = {}

if __name__ == "__main__":
    print(f"Starting discord-mod-mail {version}!")
    intents = discord.Intents(
        guilds=True, members=True, messages=True, message_content=True, dm_typing=True
    )
    client = ModMail(
        max_messages=100,
        activity=discord.Activity(name=config["Main"]["playing"]),
        intents=intents,
    )
    client.run(config["Main"]["token"])
