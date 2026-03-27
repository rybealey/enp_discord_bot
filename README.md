# ENP Bot — AnubisRP Police Activity Tracker

A Discord bot that polls the AnubisRP livefeed API every 15 seconds, filters for police activity (arrests, charges, pardons), and stores it in a local SQLite database. Server members with the right roles can query the data through Discord commands.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Edit `.env` and add your Discord bot token and configure allowed roles:

```
DISCORD_TOKEN=your_bot_token_here
ALLOWED_ROLES=Admin,Moderator
POLL_INTERVAL=15
```

### 3. Create a Discord bot

1. Go to https://discord.com/developers/applications
2. Create a new application
3. Go to **Bot** → click **Reset Token** → copy the token into `.env`
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Go to **OAuth2** → **URL Generator** → select `bot` scope
6. Under Bot Permissions, select: `Send Messages`, `Read Message History`, `View Channels`
7. Use the generated URL to invite the bot to your server

### 4. Run the bot

```bash
python bot.py
```

## Commands

All commands require one of the configured `ALLOWED_ROLES`.

| Command | Description |
|---------|-------------|
| `!recent [count]` | Show the most recent police events (default: 10, max: 25) |
| `!officer <name>` | Look up recent actions by a specific officer |
| `!suspect <name>` | Look up recent police actions against a specific player |
| `!arrests [count]` | Show recent arrests |
| `!charges [count]` | Show recent charges |
| `!pardons [count]` | Show recent pardons |
| `!stats` | Show total recorded events and bot configuration |

## Database Schema

The `police_events` table stores:

| Column | Description |
|--------|-------------|
| `officer` | The officer who performed the action |
| `perpetrator` | The player who was acted upon |
| `action` | `arrested`, `charged`, or `pardoned` |
| `details` | Extra info (e.g., arrest duration, charge name) |
| `timestamp` | Unix timestamp from the API |

## Version Management

This project uses [bump2version](https://github.com/c4urself/bump2version) for semantic versioning.

```bash
bump2version patch   # 0.1.0 → 0.1.1
bump2version minor   # 0.1.0 → 0.2.0
bump2version major   # 0.1.0 → 1.0.0
```

## Project Structure

```
enp_bot/
├── bot.py             # Discord bot, commands, and background polling task
├── api_poller.py      # API fetching and police event parsing/filtering
├── database.py        # SQLite schema, inserts, and queries
├── requirements.txt
├── setup.cfg          # Project metadata and version
├── .bumpversion.cfg   # Version bump configuration
├── .env.example
├── .gitignore
└── README.md
```
