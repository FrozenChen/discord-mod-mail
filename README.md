# discord-mod-mail

A simple mod-mail system for Discord.

## Overview

The `discord-mod-mail` bot enables communication between Discord users and server staff via a private channel.

### Main features
*   Works through DMs and a private mod-mail channel.
*   Simple permission setup: permissions can be setup in the server integration settings.
*   Easy replies: messages sent to the bot via DM have the user ID in the message for easy copying.
*   Staff replies can be made anonymous (configurable).
*   Replies posted to the channel are re-posted by the bot and deleted (intended to prevent staff from modifying them later).
*   Supports attachments.
*   Supports ignoring users, and auto-ignoring spammers.

## Requirements

*   Python 3.8 or later.
*   `discord.py` 2.x (installed via `requirements.txt`).
*   A Discord Bot token.
*   A SQLite database (managed by the bot).

## Setup

1.  Clone the repository.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Copy `config.ini.example` to `config.ini` (or `data/config.ini` if running from a specific directory):
    ```bash
    cp config.ini.example config.ini
    ```
4.  Edit `config.ini` with your bot token, channel ID, and other settings.
5.  Run the bot:
    ```bash
    python main.py
    ```

## Configuration

### `config.ini`
See `config.ini.example` for all configuration options.

### Environment Variables
The bot supports the following optional environment variables:
*   `IS_DOCKER`: Set to `1` if running inside a Docker container.
*   `MODMAIL_DATA_DIR`: The directory containing `config.ini` and the SQLite database (default: `.`).
*   `COMMIT_SHA`: Used when `IS_DOCKER` is set to `1` to display the version.
*   `COMMIT_BRANCH`: Used when `IS_DOCKER` is set to `1` to display the version.

## Commands

*   `/message_modmail` - Sends a message to staff using modmail.
*   `/message_user <user>` - Messages a user using modmail, if user is omitted, messages the last user who contacted modmail.
*   `/message_user_ui <user>` - same as above but uses a modal for input.
*   `/mention_last_user` - Get @mention for the last user who contacted mod-mail.
*   `/ignore_user <user>` - Ignore messages from `<user>` with an optional reason, with optional notification to the user.
*   `/unignore_user <userid>` - Stop ignoring messages from `<userid>`.
*   `/ignored_users` - Lists ignored users.
*   `/fix_game` - Resets the bot activity.

## License
MIT license
