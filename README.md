# ENP Bot — AnubisRP Police Activity Tracker

A Discord bot that polls the AnubisRP livefeed API every 15 seconds, filters for police activity (arrests, charges, pardons), and stores it in a local SQLite database. Server members with the right roles can query the data through Discord commands.

## Local Setup

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
4. Go to **OAuth2** → **URL Generator** → select `bot` and `applications.commands` scopes
5. Under Bot Permissions, select: `Send Messages`, `Read Message History`, `View Channels`
6. Use the generated URL to invite the bot to your server

### 4. Run the bot

```bash
python bot.py
```

## Railway Deployment

### 1. Create a new project on Railway

1. Link your GitHub repo or push directly via the Railway CLI
2. Railway will auto-detect the `Procfile` and run the bot as a **worker** service

### 2. Add a volume for persistent storage

The SQLite database needs to survive redeployments. Without a volume, your data is lost on every deploy.

1. In your Railway service, go to **Settings** → **Volumes**
2. Click **Add Volume**
3. Set the **Mount Path** to `/data`

### 3. Set environment variables

In your Railway service, go to **Variables** and add:

| Variable | Value |
|----------|-------|
| `DISCORD_TOKEN` | Your bot token |
| `ALLOWED_ROLES` | `Admin,Moderator` (comma-separated) |
| `POLL_INTERVAL` | `15` |
| `DB_PATH` | `/data` |

`DB_PATH` must match the volume mount path. This tells the bot to write `enp_bot.db` to the persistent volume instead of the ephemeral filesystem.

### 4. Deploy

Railway will automatically build and deploy on push. The bot runs as a worker process (no exposed port needed).

## Commands

All responses are displayed as color-coded Discord embeds with relative timestamps.

| Command | Description |
|---------|-------------|
| `/recent [count]` | Show the most recent police events (default: 10, max: 25) |
| `/officer <name>` | Look up recent actions by a specific officer |
| `/suspect <name>` | Look up recent police actions against a specific player |
| `/arrests [count]` | Show recent arrests (red embed) |
| `/charges [count]` | Show recent charges (orange embed) |
| `/pardons [count]` | Show recent pardons (green embed) |
| `/leaderboard [count]` | Top officers by weekly arrest count (gold embed) |
| `/graph <action>` | Bar graph of officers by action type for the current week |
| `/stats` | Bot version, event totals, and configuration |

The `/graph` command accepts a dropdown choice of **Arrests**, **Charges**, or **Pardons** and renders a horizontal bar chart styled to match Discord's dark theme, embedded as an image.

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
├── Procfile           # Railway process definition
├── requirements.txt
├── setup.cfg          # Project metadata and version
├── .bumpversion.cfg   # Version bump configuration
├── .env.example
├── .gitignore
└── README.md
```
