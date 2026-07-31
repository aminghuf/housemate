# Housemate Bot — Project Specification

A Telegram bot for managing a shared household: trash duty rotation, bills
splitting, a shared shopping list, and cleaning turns. This document is the
full spec to hand to Claude Code to scaffold and implement the project.

Repo: https://github.com/aminghuf/housemate.git

---

## 1. Goals

- Single bot, used by all housemates, gated behind membership in a specific
  Telegram **channel** (only channel members can register/use the bot).
- Automates daily trash-duty reminders based on a fixed weekly collection
  schedule, with a fair round-robin rotation.
- Lets any housemate create a bill, auto-splits it evenly, and tracks who
  has paid via inline buttons in the channel.
- Lets any housemate add items to a shared shopping list, visible/pinned in
  the channel, with the ability to check items off.
- Automates weekly cleaning-turn assignment (3 sections) with a rotating
  schedule and completion tracking.
- Keeps a queryable history of trash duty and cleaning for transparency.
- Admin can configure reminder times and (later) other settings without
  touching code.

### Non-goals for v1
- No unequal/custom bill splitting (v1 = equal split only; flag as a clear
  extension point in the code).
- No multi-house / multi-channel support — one bot instance = one house.
- No payment processing — "paid" is a self-reported honor-system checkbox.
- No i18n framework — UI strings live in one place (see §9) so they're easy
  to translate/edit by hand later.

---

## 2. Tech stack

- **Language**: Python 3.12+
- **Bot framework**: [aiogram v3](https://docs.aiogram.dev/) (async, native
  inline keyboard + callback query support, router-based structure)
- **Database**: SQLite via SQLAlchemy 2.0 (async, `aiosqlite` driver) +
  Alembic for migrations. Chosen for simplicity; schema should stay
  ORM-based so swapping to Postgres later is a config change, not a rewrite.
- **Scheduler**: APScheduler (AsyncIOScheduler), persisted job store
  (SQLAlchemyJobStore against the same SQLite file) so scheduled reminders
  survive restarts.
- **Bot run mode**: long polling by default (simplest for a single-VPS
  Docker deployment); structure the entrypoint so switching to webhook mode
  (aiohttp web server) is a config flag, not a rewrite — this is what keeps
  the door open to a serverless-style deployment later.
- **Packaging/deploy**: Docker + Docker Compose, single service + a named
  volume for the SQLite file. `.env` for secrets/config.
- **Timezone**: Europe/Rome for all scheduling (configurable via env var).

### Suggested project layout

```
housemate/
├── bot/
│   ├── __init__.py
│   ├── main.py                 # entrypoint: build bot, dispatcher, scheduler
│   ├── config.py                # env-based settings (pydantic-settings)
│   ├── db/
│   │   ├── models.py             # SQLAlchemy models
│   │   ├── session.py
│   │   └── migrations/           # alembic
│   ├── middlewares/
│   │   └── membership.py         # channel-membership gate
│   ├── handlers/
│   │   ├── onboarding.py
│   │   ├── trash.py
│   │   ├── bills.py
│   │   ├── shopping.py
│   │   ├── cleaning.py
│   │   └── admin.py
│   ├── services/
│   │   ├── trash_schedule.py     # weekday -> trash type, paper/glass alternation
│   │   ├── rotation.py           # generic round-robin helper used by trash + cleaning
│   │   ├── bills.py
│   │   ├── shopping.py
│   │   └── cleaning.py
│   ├── scheduler/
│   │   └── jobs.py               # daily trash job, weekly cleaning job registration
│   └── strings.py                # all user-facing text (Persian/Italian mix) in one place
├── tests/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md
```

---

## 3. Access control & onboarding

- Bot has a configured `HOUSE_CHANNEL_ID` (the channel all housemates must
  belong to) and the bot must be an **admin of that channel** (needed to
  read membership via `getChatMember` and to post/pin messages).
- Flow when a new user messages the bot (`/start`):
  1. Bot calls `getChatMember(HOUSE_CHANNEL_ID, user_id)`.
  2. If status is not one of `member/administrator/creator` → reply with a
     message explaining they must join the channel first (include an
     invite link if configured), and stop.
  3. If they are a member → create/upsert a `User` row (telegram id,
     display name, username), mark `is_registered = true`, and show the
     main menu (reply keyboard or inline menu — see §9).
- Use an aiogram **middleware** to re-check channel membership on every
  incoming update (cheap check against a cached "last verified at"
  timestamp, re-verified e.g. every 6h, not on every single message) so
  someone who leaves the channel loses access gracefully with a clear
  message rather than silently.
- **Admin role**: one or more Telegram user IDs configured via env var
  (`ADMIN_IDS`). Admin-only commands are rejected with a friendly message
  for non-admins.
- First-time setup: an admin command `/setup_rotation` lets the admin
  define the initial housemate order used for trash duty (defaults to
  registration order if not set).

---

## 4. Data model (high-level)

- **User**: telegram_id (PK), display_name, username, is_registered,
  is_active (soft-remove a housemate without deleting history), joined_at.
- **TrashRotation**: ordered list (position, user_id) — the single shared
  round-robin queue used for daily trash duty. `current_position` tracked
  separately (see §5).
- **TrashLog**: id, date, trash_type, assigned_user_id, status
  (`pending` / `done` / `skipped_not_full`), responded_at, message_id (so
  we can edit it later).
- **Bill**: id, title, description (nullable), total_amount, created_by,
  created_at, per_person_amount (derived), channel_message_id.
- **BillShare**: bill_id, user_id, paid (bool), paid_at.
- **ShoppingItem**: id, title, added_by, added_at, purchased (bool),
  purchased_by, purchased_at.
- **ShoppingListMessage**: singleton row tracking the channel_message_id of
  the currently pinned shopping-list message (so it can be edited in
  place rather than spamming new pinned messages).
- **CleaningRotation**: ordered list (position, user_id) — shared queue,
  advances by 1 each week; section assignment is derived from position
  (see §7), not stored per-user.
- **CleaningLog**: id, week_start_date, user_id, section, status
  (`pending` / `done` / `skipped_not_needed`), responded_at, message_id.
- **Settings**: key/value table for admin-configurable things (trash
  reminder time, cleaning reminder time/day, paper/glass alternation
  anchor date, etc.) so these aren't hardcoded.

---

## 5. Trash duty

### 5.1 Fixed weekly schedule

| Day | Trash type |
|---|---|
| Monday | Umido |
| Tuesday | Carta e Cartone **or** Vetro (alternates every 15 days, starting with Carta e Cartone) |
| Wednesday | Plastica e Metalli |
| Thursday | Umido |
| Friday | Indifferenziato |
| Saturday | Umido |
| Sunday | *(no collection — no reminder)* |

- Implement the Tuesday alternation as: pick an **anchor date** (the first
  Tuesday the bot goes live, defaulting to "Carta e Cartone"), store it in
  `Settings`, and compute `weeks_since_anchor // 2 == 0/1` (i.e. genuinely
  alternate *every other Tuesday*, which is what "every 15 days" means in
  practice for a weekly-recurring day). Make this a small pure function in
  `services/trash_schedule.py` with unit tests — this is the one bit of
  date logic worth getting precisely right.

### 5.2 Rotation logic (single shared queue, one duty per day)

This is a **single round-robin queue over all housemates**, not one queue
per trash type — whoever's turn it is handles trash duty for that day,
whatever the scheduled type is.

- `current_position` points at who is "on duty" right now.
- Each day (Mon–Sat) at the **admin-configured reminder time**, the
  scheduler:
  1. Looks up today's trash type via §5.1.
  2. Creates a `TrashLog` row (`pending`) for the user currently at
     `current_position`.
  3. Posts a message to the channel, tagging that user, stating the trash
     type, with two inline buttons:
     - `✅ انداختم دور`
     - `❌ نیاز نبود / پر نشده هنوز`
- **On `انداختم دور` (done)**:
  - Edit the message to a confirmation (show ✅, who did it, timestamp),
    remove the buttons.
  - Mark `TrashLog.status = done`.
  - **Advance** `current_position` to the next person in the queue (their
    turn is complete; next collection day it's the next housemate).
- **On `نیاز نبود / پر نشده هنوز` (not needed yet)**:
  - Edit the message to reflect that (e.g. "بازبینی شد — لازم نبود").
  - Mark `TrashLog.status = skipped_not_full`.
  - **Do not advance** `current_position` — the same person is asked again
    on the next scheduled collection day for whatever type comes up. This
    is my interpretation of "rescheduled for the next throwing trash";
    flag this to Amin as the one behavioral assumption worth double
    -checking before it ships, since the alternative reading (skip to the
    next person, but re-ask this person next time it's *this same trash
    type*) is also plausible and would need a slightly different queue
    design (per-type sub-queues).
  - Only the tagged user's button press should count — reject other users'
    taps with a small toast ("این نوبت شما نیست") via `answer_callback_query`.
- **History**: a bot command (e.g. `/trash_history`) paginated list of past
  `TrashLog` entries (date, type, who, status).
- **Admin controls**: `/set_trash_reminder_time HH:MM`, and a way to
  reorder/insert/remove people from the rotation (e.g.
  `/trash_rotation` showing current order with inline reorder buttons, or
  simple admin commands to skip/manually reassign a stuck turn).

---

## 6. Bills

- Any registered user can start bill creation via a bot command / menu
  button (`/new_bill` or a "💸 صورتحساب جدید" menu item), driven by an
  aiogram **FSM** (finite state machine) conversation:
  1. Ask for **title** (required).
  2. Ask for **description** (optional — allow a "رد کردن / Skip" button).
  3. Ask for **total amount** (validate it's a positive number).
  4. Compute `per_person_amount = total_amount / active_user_count`
     (rounding: keep it exact to 2 decimals; put any rounding remainder on
     the bill creator so shares always sum to the total — note this as the
     v1 rule, and leave a clear seam for future custom splits).
  5. Confirm & save `Bill` + one `BillShare` row per active user.
- Post a message to the channel: title, description if present, total,
  per-person share, and **one inline button per housemate**
  (`نام کاربر — پرداخت نشده`). Each button's callback is scoped to that
  specific user+bill.
- When a user taps **their own** button: toggle `BillShare.paid`, edit the
  message to update just that person's line (e.g. `✅ نام کاربر`), leave
  everyone else's buttons as-is. If they tap someone else's button, reject
  with a toast ("فقط سهم خودتون رو می‌تونید علامت بزنید").
- When all shares are `paid`, edit the message header to show
  "✅ تسویه شد" (fully settled) and disable remaining buttons.
- Bot commands to view: `/my_bills` (bills where you owe money, unpaid
  only), `/bills_history` (all bills, paginated), and optionally a simple
  `/balance` that sums what each person currently owes across open bills.

---

## 7. Shopping list

- Any user can add an item via a command/menu (`/add_item` or inline
  prompt) — **title only**, no quantity/notes in v1 (explicitly per your
  spec; flag as an easy future add).
- Maintain **one live message** in the channel representing the current
  list (not one message per item — this avoids spam and matches "pinned
  list" better):
  - On the *first* item ever added (or after the list was emptied), post a
    new message, pin it, and store its `message_id` in
    `ShoppingListMessage`.
  - On subsequent additions, **edit** that same message to append the new
    item and re-render the full list with an inline "✅ خریداری شد" button
    per item.
  - When an item is marked purchased, either strike it through
    (`~item~`) and keep it visible for a bit, or remove it from the
    rendered list immediately and log it as purchased — pick removing
    immediately for a clean always-current list, since purchase history
    lives in `ShoppingItem.purchased=true` rows queryable via a bot
    command (`/shopping_history`) rather than needing to stay on screen.
  - If the list becomes empty, edit the message to something like
    "🧺 لیست خرید خالیه" rather than deleting/unpinning it, so the pin slot
    stays stable and future items just populate it again.
- Any user can mark any item purchased (unlike bills/trash, there's no
  "only you can click your own" restriction here — first to buy it wins).

---

## 8. Cleaning turns

- Three sections: 🍳 آشپزخانه (Kitchen), 🛋️ هال (Hall), 🚿 حمام (Bathroom).
- Weekly cycle, cleaning day **Sunday**, reminder posted by default at
  **Saturday 21:00** — both the reminder weekday/time are admin
  -configurable (`/set_cleaning_reminder <weekday> <HH:MM>`).
- Rotation: shared circular queue of housemates (`CleaningRotation`,
  separate from the trash queue). Each week, assign sections to the next
  3 people in the queue in order (kitchen → whoever's at `position`, hall →
  `position+1`, bathroom → `position+2`, wrapping around). After posting,
  advance `current_position` by 3 mod `len(queue)` so next week starts
  with a fresh trio. If there are **fewer than 3 active housemates**,
  handle gracefully — e.g. someone gets 2 sections that week — flag this
  edge case explicitly in the code with a TODO/comment since it's a real
  possibility in a small house.
- Reminder message: lists all three assignments with the responsible
  person tagged next to their section, each with their own pair of inline
  buttons:
  - `✅ تمیز کردم` (only that section's assignee's tap counts, others
    rejected with a toast, same pattern as bills)
  - `➖ نیازی نبود`
- On tap, edit just that section's line in the message to show the result
  (✅ done / ➖ not needed) and timestamp, leaving the other two sections'
  buttons live until they respond too.
- `CleaningLog` row created per section per week; history browsable via
  `/cleaning_history`.

---

## 9. Bot UX structure

- Use a **persistent reply keyboard** or inline main-menu with these top
  -level entries (exact icons/labels are placeholders, adjust freely):
  - 🗑️ نوبت زباله (trash: shows today's status / history)
  - 💸 صورتحساب‌ها (bills: new bill, my bills, history)
  - 🛒 لیست خرید (shopping list: view/add)
  - 🧹 نوبت نظافت (cleaning: this week / history)
  - ⚙️ تنظیمات *(admin only)*
- Keep **all user-facing strings in `bot/strings.py`** as named constants
  (not scattered f-strings in handlers) so wording can be tweaked or
  translated without hunting through logic code. Persian for
  conversational text, Italian for the trash-category names themselves
  (as given), matching how you'd actually want it to read.

---

## 10. Admin capabilities (v1)

- `/set_trash_reminder_time HH:MM`
- `/set_cleaning_reminder <weekday> HH:MM`
- `/trash_rotation` — view/reorder the trash duty queue
- `/cleaning_rotation` — view/reorder the cleaning queue
- `/add_housemate` / `/remove_housemate` (soft-deactivate, keep history)
- Admin actions should log to a small audit trail (who changed what,
  when) — simple table, nothing fancy.

---

## 11. Deployment

- `Dockerfile`: slim Python base image, install deps, copy code, run
  `python -m bot.main`.
- `docker-compose.yml`: one service, named volume mounted at e.g.
  `/data` for the SQLite file, env vars pulled from `.env`
  (`BOT_TOKEN`, `HOUSE_CHANNEL_ID`, `ADMIN_IDS`, `TIMEZONE`, `DB_PATH`).
- `.env.example` documenting every required variable.
- Migrations run automatically on container start (`alembic upgrade head`
  before launching the bot), or via a small entrypoint script.
- README should include: how to create the bot with @BotFather, how to
  add it as channel admin, how to get the channel's numeric ID, first-run
  setup steps (`/setup_rotation`), and local dev instructions (running
  without Docker for iteration).

---

## 12. Testing

- Unit tests for the pure logic: trash-schedule/alternation calculation
  (§5.1), rotation advancement (§5.2, §7), bill share computation & 
  rounding (§6).
- Integration-style tests for handlers can use aiogram's test utilities /
  mocked `Bot` object — not required to be exhaustive for v1, but the
  scheduling and money-math logic above should have real test coverage
  since bugs there are the most annoying to have in production.

---

## 13. Open questions / assumptions to confirm before/while building

1. **Trash "not needed" behavior** (§5.2): assumed same person is re-asked
   next collection day (queue doesn't advance) rather than skipping to the
   next person. Confirm this matches intent.
2. **Bill rounding**: assumed remainder goes to the bill creator so shares
   sum exactly to the total. Fine, or prefer distributing the odd cent
   to whoever's alphabetically/positionally first?
3. **Cleaning with <3 active housemates**: acceptable for someone to get
   2 sections some weeks, or should the bot rotate which section is
   skipped instead?
4. **Channel vs. group**: confirm it's genuinely a broadcast **channel**
   (bot can't read member messages there) and not a group/supergroup —
   this affects how `getChatMember` and posting work, and whether button
   taps happen in the channel itself (channel posts *can* have inline
   buttons and receive callback queries, but the tapping user must have
   started the bot privately first — worth confirming everyone will `/start`
   the bot in DM before using channel buttons).
5. Anything beyond v1 you already know you want soon (custom bill splits,
   recurring bills, multiple houses) — worth noting now even if not built,
   so the schema doesn't need a painful migration later.

---

## 14. Suggested build order for Claude Code

1. Scaffold project structure, config, DB models + migrations.
2. Onboarding + membership middleware + admin gate.
3. Trash schedule logic (with unit tests) + rotation service.
4. Trash reminder job + handlers (buttons, history).
5. Bills (FSM creation flow, channel posting, payment toggling, history).
6. Shopping list (single editable pinned message).
7. Cleaning turns (rotation, reminder, buttons, history).
8. Admin commands.
9. Dockerize, write README, `.env.example`.
10. Pass over all strings for consistency/tone.
