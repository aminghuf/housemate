# Housemate Bot

A Telegram bot for managing a shared household: trash duty rotation, bill
splitting, a shared shopping list, and weekly cleaning turns — gated behind
membership in a household Telegram channel.

## Features (v1)

- 🗑️ **Trash duty** — fixed weekly collection schedule (with the
  Tuesday Carta e Cartone / Vetro alternation), single round-robin queue,
  daily reminder with ✅/❌ buttons, history.
- 💸 **Bills** — anyone creates a bill via a guided conversation, split
  evenly among active housemates, posted to the channel with a
  pay-yourself-off button per person, `/my_bills`, `/bills_history`,
  `/balance`.
- 🛒 **Shopping list** — one live, pinned message in the channel; add
  items, mark purchased, `/shopping_history`.
- 🧹 **Cleaning turns** — weekly rotation across 3 sections (kitchen,
  hall, bathroom), reminder with per-section ✅/➖ buttons, history.
- ⚙️ **Admin** — configurable reminder times, rotation reordering,
  add/remove housemates, audit log.

See [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md) (the original spec handed
to Claude Code) for the full design rationale. A few open questions from
that spec were resolved before building — see
[Design decisions](#design-decisions) below.

## Tech stack

Python 3.12+, [aiogram v3](https://docs.aiogram.dev/), SQLAlchemy 2.0 (async,
`aiosqlite`) + Alembic, APScheduler, Docker Compose. Long polling by default.

## Project layout

```
housemate/
├── bot/
│   ├── main.py                 # entrypoint
│   ├── config.py                # env-based settings
│   ├── strings.py                # all user-facing text
│   ├── db/                       # models, session, alembic migrations
│   ├── middlewares/               # DB session + channel-membership gate
│   ├── handlers/                  # aiogram routers per feature
│   ├── services/                   # business logic (DB-touching + pure)
│   └── scheduler/                   # APScheduler job registration
├── tests/                         # pytest — pure logic + rotation DB helpers
├── Dockerfile / docker-compose.yml
├── entrypoint.sh                   # alembic upgrade head && run bot
└── .env.example
```

## Setup

### 1. Create the bot

Message [@BotFather](https://t.me/BotFather) on Telegram, `/newbot`, and
copy the token it gives you into `.env` as `BOT_TOKEN`.

### 2. Add the bot to your household channel

The bot must be an **admin** of the channel (needed to read membership via
`getChatMember` and to post/pin messages):

1. Create (or use an existing) Telegram **channel** for the household.
2. Add the bot as a member, then promote it to **admin** (any permissions
   preset is fine, but make sure "Post Messages" and "Pin Messages" are on).

### 3. Get the channel's numeric ID

Easiest way: forward any message from the channel to
[@userinfobot](https://t.me/userinfobot) (or add
[@RawDataBot](https://t.me/RawDataBot) to the channel briefly) — it'll show
a `channel_id` like `-1001234567890`. Put that in `.env` as
`HOUSE_CHANNEL_ID`.

> **Important:** it must be a genuine broadcast **channel**, not a group or
> supergroup — see [Design decisions](#design-decisions) below for why.

### 4. Configure `.env`

```bash
cp .env.example .env
```

Fill in `BOT_TOKEN`, `HOUSE_CHANNEL_ID`, `ADMIN_IDS` (your numeric Telegram
user ID — get it from [@userinfobot](https://t.me/userinfobot) in a DM), and
adjust `TIMEZONE` if not Europe/Rome.

### 5. First-run setup

Once the bot is running (see below):

1. Every housemate should DM the bot and send `/start` — this is required
   even for people who'll only interact via the channel's inline buttons,
   since Telegram only delivers channel-post button taps to users who've
   already started a conversation with the bot.
2. Housemates are added to both rotations in registration order by
   default. An admin can reorder with `/setup_rotation <id1> <id2> ...`
   (or `/trash_rotation`, `/cleaning_rotation` later on).

## Local development (without Docker)

```bash
python -m venv .venv
.venv\Scripts\activate          # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt

alembic upgrade head
python -m bot.main
```

Run tests with:

```bash
pytest
```

## Docker deployment

```bash
docker compose up -d --build
```

This runs `alembic upgrade head` automatically on container start (see
`entrypoint.sh`), then starts the bot. The SQLite file lives in the named
`housemate_data` volume at `/data/housemate.db` regardless of what
`DB_PATH` is set to for local dev — `docker-compose.yml` overrides it.

## CI/CD: auto-deploy to a Hetzner VPS via Docker Hub

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs on every
push to `main`: run tests → build the image → push it to Docker Hub as
`aminghuf/housemate:latest` (and `:<commit-sha>`) → SSH into the VPS and
`docker compose pull && docker compose up -d`.

One-time setup, done outside this repo (nothing here can do these steps for
you — they touch your Docker Hub account and your server):

**1. Docker Hub access token** — Docker Hub → Account Settings → Security →
New Access Token. Use a token, not your password.

**2. A dedicated SSH deploy key** (don't reuse a personal key):

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f deploy_key -N ""
```

Add `deploy_key.pub`'s contents to `~/.ssh/authorized_keys` for the deploy
user on the VPS. Keep `deploy_key` (the private half) for the next step —
don't commit it anywhere.

**3. GitHub repo secrets** — repo → Settings → Secrets and variables →
Actions → New repository secret:

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Your Docker Hub username |
| `DOCKERHUB_TOKEN` | The access token from step 1 |
| `VPS_HOST` | Your Hetzner VPS's IP or hostname |
| `VPS_USER` | The SSH user the deploy key was added for |
| `VPS_SSH_KEY` | Contents of `deploy_key` (the private key) |
| `VPS_PORT` | Only if SSH isn't on port 22 |

**4. One-time VPS setup:**

```bash
# On the VPS, as the deploy user:
curl -fsSL https://get.docker.com | sh   # if Docker isn't installed yet

mkdir -p /opt/housemate && cd /opt/housemate
# Copy this repo's docker-compose.yml here (scp it, or paste it manually) —
# `image:` is what matters; the `build: .` line is a no-op with no
# Dockerfile present, `docker compose up -d` without `--build` never
# triggers a build once the image has been pulled.

cp .env.example .env
nano .env   # fill in BOT_TOKEN, HOUSE_CHANNEL_ID, ADMIN_IDS, etc.
# make sure DB_PATH=/data/housemate.db to match the volume mount

docker login   # only needed if aminghuf/housemate is a private repo
docker compose pull
docker compose up -d
```

After that, every push to `main` redeploys automatically. To roll back,
SSH in and run `docker compose pull` after re-pushing an older commit (or
manually retag/pull a specific `:<sha>` and restart).

## Admin commands

| Command | Description |
|---|---|
| `/announce [text]` | Post an announcement to the channel (asks for text + confirms before posting if no text is given inline) |
| `/set_trash_reminder_time HH:MM` | Change the daily trash reminder time |
| `/set_cleaning_reminder <weekday> HH:MM` | Change the weekly cleaning reminder (weekday: `0`-`6`, Monday=`0`, or `mon`..`sun`) |
| `/trash_rotation [id1 id2 ...]` | View, or reorder, the trash duty queue |
| `/cleaning_rotation [id1 id2 ...]` | View, or reorder, the cleaning queue |
| `/setup_rotation id1 id2 ...` | Set the initial trash duty order |
| `/add_housemate <telegram_id> <name>` | Manually register a housemate |
| `/remove_housemate <telegram_id>` | Soft-deactivate a housemate (history kept) |

All admin actions are written to an audit log (`AuditLog` table).

## Design decisions

A few things flagged as open questions in the original spec were resolved
before/while building this v1:

1. **Trash "not needed yet"**: the same person is re-asked at the next
   collection day — the queue does **not** advance. Only "✅ انداختم دور"
   advances the rotation.
2. **Bill rounding**: any odd-cent remainder from an uneven split goes to
   the bill's creator, so shares always sum exactly to the total. Money is
   stored as integer cents internally (not floating-point) to avoid
   rounding drift.
3. **Cleaning with fewer than 3 active housemates**: the rotation simply
   wraps, so someone gets assigned 2 (or all 3) sections that week — no
   special-casing.
4. **Channel, not group**: confirmed — this is a broadcast channel.
   Remember that channel-post inline buttons only reach users who have
   already DM'd the bot (`/start`), which is why step 5.1 above matters.

## Extension points intentionally left for later

- Custom (non-equal) bill splits — `services/bills.py::compute_shares_cents`
  is the seam to extend.
- Shopping list item quantity/notes.
- Multi-house / multi-channel support.
- Webhook run mode (`RUN_MODE=webhook` is read from config but not yet
  implemented — `bot/main.py` raises `NotImplementedError` if set).
