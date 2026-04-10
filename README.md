<p align="center">
  <img src="assets/enp_bot.gif" alt="ENP Bot" width="300">
</p>

<p align="center">
  <strong>AnubisRP Police Activity Tracker</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.5.0-orange?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/discord.py-2.3+-5865F2?style=flat-square&logo=discord&logoColor=white" alt="discord.py">
  <img src="https://img.shields.io/badge/database-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/deploy-Railway-0B0D0E?style=flat-square&logo=railway&logoColor=white" alt="Railway">
</p>

---

A Discord bot that polls the AnubisRP livefeed API, filters for police activity (arrests, charges, pardons, releases), and stores it in a local SQLite database. It tracks individual shifts with timezone classification (OC/EU/NA), provides weekly analytics, and automatically announces new deployments. All data is scoped to the current week (Monday 00:00 GMT).

## Features

- **Live Police Feed** — Polls the AnubisRP API every 15 seconds for arrests, charges, pardons, and releases
- **Officer & Suspect Lookup** — Query activity by officer or player name (current week only)
- **Weekly Leaderboard** — Every current ENP officer ranked by arrest count, publicly visible, resets each Monday (UTC)
- **Managerial Tracking** — Parses the livefeed for hires, send-homes, fires, and voluntary quits affecting ENP and posts an announcement for each
- **Graphing** — Dark-themed public bar charts for weekly action breakdowns, including timezone-segmented shift graphs
- **Shift Tracking** — Live and historical shift data per officer, grouped by rank
- **Individual Shift Logging** — Polls every minute and logs each new shift with a timestamp for timezone classification
- **Timezone Classification** — Shifts are categorized into OC (08:00–16:00 GMT), EU (16:00–00:00 GMT), and NA (00:00–08:00 GMT)
- **Weekly Shift Snapshots** — Automatically logs shift data every Sunday at 23:55 UTC
- **Ephemeral Responses** — Most command responses are private to the invoking user; `/leaderboard` and `/graph` are public
- **Deployment Notifications** — Announces new versions to a designated channel on each Railway deploy

## Commands

Most responses are ephemeral (only visible to you); `/leaderboard` and `/graph` are public. Data is scoped to the current week (Monday 00:00 GMT onward). Use `/help` in Discord for a quick reference.

### Police Activity

| Command | Description | Visibility |
|---------|-------------|------------|
| `/recent [count]` | Police events this week (default: 10, max: 25) | Ephemeral |
| `/officer <name>` | Officer activity this week | Ephemeral |
| `/suspect <name>` | Player activity this week | Ephemeral |
| `/arrests [count]` | Arrests this week | Ephemeral |
| `/charges [count]` | Charges this week | Ephemeral |
| `/pardons [count]` | Pardons this week | Ephemeral |
| `/releases [count]` | Prison releases this week | Ephemeral |

### Shifts & Leaderboard

| Command | Description | Visibility |
|---------|-------------|------------|
| `/shifts [date]` | Live shift overview, or historical data by date (`YYYY-MM-DD`) | Ephemeral |
| `/sum <scope>` | Total sum of logged shifts (Weekly or Total) | Ephemeral |
| `/leaderboard` | Every current ENP officer ranked by weekly arrests | **Public** |
| `/graph <action>` | Bar graph by action type or shifts by timezone | **Public** |

### Utility

| Command | Description | Visibility |
|---------|-------------|------------|
| `/help` | Command guide with usage info | Ephemeral |
| `/about` | Bot info, version, and configuration | Ephemeral |

### `/graph`

Accepts a dropdown choice of **Arrests**, **Charges**, **Pardons**, **Releases**, or **Shifts** and renders a horizontal bar chart styled to match Discord's dark theme, embedded as an image.

- **Arrests / Charges / Pardons / Releases** — Single-color bar chart ranked by officer count
- **Shifts** — Stacked bar chart with each bar segmented by timezone (OC = blue, EU = orange, NA = green), showing which time windows each officer works in

### `/shifts`

- **Without `date`** — Fetches live data from the AnubisRP Corp API and displays weekly/total shifts per officer, grouped by rank with requirement status indicators.
- **With `date`** (e.g. `/shifts date:2026-03-29`) — Pulls from stored weekly snapshots in the database. If no data exists for the given date, available snapshot dates are listed.

## Background Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `poll_livefeed` | Every 15s (configurable) | Fetches the livefeed API and stores new police events plus ENP managerial events (hires, send-homes, fires, quits) |
| `poll_shifts` | Every 1 minute | Polls the corp API, logs new shifts, and mirrors the current ENP roster to the local cache |
| `weekly_shift_snapshot` | Sundays at 23:55 UTC | Snapshots each officer's weekly and total shifts to the database, posts the weekly graph |
| `dst_check` | Daily at 03:00 UTC | Auto-toggles UK BST detection for timezone classification |

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
| `LIVEFEED_CHANNEL_ID` | Channel ID for livefeed events and deploy announcements | Yes |
| `SHIFTS_CHANNEL_ID` | Channel ID for weekly shift graph posts (defaults to `LIVEFEED_CHANNEL_ID`) | No |
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
| `action` | `TEXT` | `arrested`, `charged`, `pardoned`, or `released` |
| `details` | `TEXT` | Extra info (e.g., arrest duration, charge name) |
| `raw_text` | `TEXT` | Full raw text from the API |
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

### `shift_log`

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` | Auto-incrementing primary key |
| `username` | `TEXT` | Officer username |
| `rank` | `TEXT` | Base rank (tier stripped) |
| `weekly_shifts` | `INTEGER` | Cumulative weekly count at time of log |
| `total_shifts` | `INTEGER` | Cumulative total count at time of log |
| `timestamp` | `INTEGER` | Unix timestamp (UTC) when the shift was detected |

### `shift_cache`

| Column | Type | Description |
|--------|------|-------------|
| `username` | `TEXT` | Officer username (primary key) |
| `weekly_shifts` | `INTEGER` | Last-known weekly shift count |

### `timezones`

| Column | Type | Description |
|--------|------|-------------|
| `label` | `TEXT` | Timezone label: `OC`, `EU`, or `NA` (primary key) |
| `start_hour` | `INTEGER` | Start hour in GMT (inclusive) |
| `end_hour` | `INTEGER` | End hour in GMT (exclusive) |

### `corp_roster`

Cached snapshot of who is currently in ENP, refreshed every minute by `poll_shifts`. Used to filter livefeed `sent_home` events (which do not include a corp name) by checking whether the manager is in the ENP roster.

| Column | Type | Description |
|--------|------|-------------|
| `username` | `TEXT` | Officer username (primary key) |
| `rank` | `TEXT` | Current base rank |
| `first_seen` | `INTEGER` | Unix timestamp the officer first appeared in the corp |
| `last_seen` | `INTEGER` | Unix timestamp of the most recent confirmation |

### `roster_events`

Append-only log of every ENP managerial event parsed out of the livefeed.

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` | Primary key from the livefeed API (dedupes across polls) |
| `event_type` | `TEXT` | `hired`, `sent_home`, `fired`, or `quit` |
| `member` | `TEXT` | The affected officer |
| `actor` | `TEXT` | The manager who performed the action (null for `quit`) |
| `details` | `TEXT` | Extra info — e.g. send-home duration in minutes |
| `raw_text` | `TEXT` | Full raw text from the livefeed |
| `timestamp` | `INTEGER` | Unix timestamp from the livefeed event |
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
├── bot.py             # Slim entrypoint: bot setup, on_ready, error handler, main()
├── config.py          # Constants, env vars, version, logging
├── helpers.py         # Shared formatting helpers and graph rendering
├── api_poller.py      # Livefeed API fetching and police event parsing/filtering
├── database.py        # SQLite schema, inserts, and queries
├── cogs/
│   ├── activity.py    # /recent, /officer, /suspect, /arrests, /charges, /pardons, /releases
│   ├── shifts.py      # /leaderboard, /shifts, /sum + poll_shifts & weekly_shift_snapshot tasks
│   ├── graphs.py      # /graph (action and shift graphs)
│   ├── utility.py     # /help, /about
│   ├── livefeed.py    # poll_livefeed background task
│   └── dst.py         # dst_check background task
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

## Still on the Agenda

The following features are planned but blocked on additional support from the AnubisRP developers — they cannot be implemented reliably until the API exposes the necessary data:

- [ ] **Tracking tickets issued** — No event for ticket issuance is currently exposed by the AnubisRP livefeed or corp APIs.
- [ ] **Tracking cops' start-work and stop-work times more efficiently** — Today the bot infers shifts by polling `weekly_shifts` deltas every minute, which gives shift counts but not precise on-duty/off-duty timestamps. A direct on-duty event from the API would replace this polling-and-diffing workaround.
- [ ] **Tracking heist initiations and completions** — Heist start/end events are not present in any API surface the bot has access to.

If you are an AnubisRP developer and would like to discuss exposing any of the above, please reach out via the ENP Discord.
