<p align="center">
  <img src="assets/enp_bot.gif" alt="ENP Bot" width="300">
</p>

<p align="center">
  <strong>AnubisRP Police Activity Tracker</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.2.0-orange?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/discord.py-2.3+-5865F2?style=flat-square&logo=discord&logoColor=white" alt="discord.py">
  <img src="https://img.shields.io/badge/database-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/deploy-Railway-0B0D0E?style=flat-square&logo=railway&logoColor=white" alt="Railway">
</p>

---

A Discord bot that polls the AnubisRP livefeed API, filters for police activity (arrests, charges, pardons), and stores it in a local SQLite database. It also tracks weekly shift data for all officers and automatically announces new deployments.

## Features

- **Live Police Feed** — Polls the AnubisRP API every 15 seconds for arrests, charges, and pardons
- **Officer & Suspect Lookup** — Query activity by officer or player name
- **Weekly Leaderboard** — Ranked arrest counts reset each Monday (UTC)
- **Graphing** — Dark-themed bar charts for weekly action breakdowns
- **Shift Tracking** — Live and historical shift data per officer, grouped by rank
- **Weekly Shift Snapshots** — Automatically logs shift data every Sunday at 23:55 UTC
- **Deployment Notifications** — Announces new versions to a designated channel on each Railway deploy

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
| `/shifts [date]` | Live shift overview, or historical data by date (`YYYY-MM-DD`) |
| `/stats` | Bot version, event totals, and configuration |

### `/graph`

Accepts a dropdown choice of **Arrests**, **Charges**, or **Pardons** and renders a horizontal bar chart styled to match Discord's dark theme, embedded as an image.

### `/shifts`

- **Without `date`** — Fetches live data from the AnubisRP Corp API and displays weekly/total shifts per officer, grouped by rank with requirement status indicators.
- **With `date`** (e.g. `/shifts date:2026-03-29`) — Pulls from stored weekly snapshots in the database. If no data exists for the given date, available snapshot dates are listed.

## Background Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `poll_livefeed` | Every 15s (configurable) | Fetches the livefeed API and stores new police events |
| `weekly_shift_snapshot` | Sundays at 23:55 UTC | Snapshots each officer's weekly and total shifts to the database |

## Deployment Notifications

On each Railway deploy, the bot compares the current `RAILWAY_GIT_COMMIT_SHA` against the last announced commit. If it's new, an embed is posted to the configured update channel:

> **Software Update -- vX.X.X**
>
> Commit: `a553c7d`
> Message: ui: improve /shifts formatting

This is tracked via a `bot_meta` table to avoid duplicate announcements on reconnects.

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
3. Go to **Bot** > click **Reset Token** > copy the token into `.env`
4. Go to **OAuth2** > **URL Generator** > select `bot` and `applications.commands` scopes
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

1. In your Railway service, go to **Settings** > **Volumes**
2. Click **Add Volume**
3. Set the **Mount Path** to `/data`

### 3. Set environment variables

In your Railway service, go to **Variables** and add:

| Variable | Value | Required |
|----------|-------|----------|
| `DISCORD_TOKEN` | Your bot token | Yes |
| `ALLOWED_ROLES` | `Admin,Moderator` (comma-separated) | Yes |
| `POLL_INTERVAL` | `15` | No (default: 15) |
| `DB_PATH` | `/data` | Yes (Railway) |

`DB_PATH` must match the volume mount path. This tells the bot to write `enp_bot.db` to the persistent volume instead of the ephemeral filesystem.

Railway automatically provides `RAILWAY_GIT_COMMIT_SHA` and `RAILWAY_GIT_COMMIT_MESSAGE` for deployment notifications.

### 4. Deploy

Railway will automatically build and deploy on push. The bot runs as a worker process (no exposed port needed).

## Database Schema

### `police_events`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` | Primary key from the API |
| `officer` | `TEXT` | The officer who performed the action |
| `perpetrator` | `TEXT` | The player who was acted upon |
| `action` | `TEXT` | `arrested`, `charged`, or `pardoned` |
| `details` | `TEXT` | Extra info (e.g., arrest duration, charge name) |
| `timestamp` | `INTEGER` | Unix timestamp from the API |
| `created_at` | `TEXT` | Row insertion time |

### `shift_snapshots`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` | Auto-incrementing primary key |
| `username` | `TEXT` | Officer username |
| `rank` | `TEXT` | Base rank (tier stripped) |
| `weekly_shifts` | `INTEGER` | Shift count for the week |
| `total_shifts` | `INTEGER` | Cumulative shift count |
| `week_ending` | `TEXT` | Snapshot date (`YYYY-MM-DD`) |
| `created_at` | `TEXT` | Row insertion time |

### `bot_meta`

| Column | Type | Description |
|--------|------|-------------|
| `key` | `TEXT` | Unique key (e.g. `last_announced_commit`) |
| `value` | `TEXT` | Stored value |

## Version Management

This project uses [bump2version](https://github.com/c4urself/bump2version) for semantic versioning.

```bash
bump2version patch   # 1.1.1 -> 1.1.2
bump2version minor   # 1.1.1 -> 1.2.0
bump2version major   # 1.1.1 -> 2.0.0
```

## Project Structure

```
enp_bot/
├── bot.py             # Discord bot, commands, background tasks, and deploy announcements
├── api_poller.py      # API fetching and police event parsing/filtering
├── database.py        # SQLite schema, inserts, and queries
├── assets/
│   └── enp_bot.gif    # ENP Bot logo
├── Procfile           # Railway process definition
├── requirements.txt
├── setup.cfg          # Project metadata and version
├── .bumpversion.cfg   # Version bump configuration
├── .env.example
├── .gitignore
└── README.md
```
