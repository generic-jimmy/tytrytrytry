# Telegram group management bot — Control Center

One FastAPI process serves the Telegram webhook, the admin web dashboard, and
the dashboard's JSON API. The dashboard is a vanilla-JS SPA with Three.js
background animation, dark/light themes, and 14 management views.

## What's new in this upgrade

The original bot shipped with five server-rendered pages (login, dashboard,
purgatory, queue, settings, modlog) and a basic CSS stylesheet. This upgrade
adds a complete single-page application on top of the same FastAPI backend,
plus eight new database tables and ~30 new API endpoints.

### New dashboard (vanilla JS + Three.js)

- **Single-page app** at `/app` with hash-based routing — no build step, no framework, just ES2015+ modules loaded via `<script>` tags.
- **Three.js animated background** — particle network that reacts to mouse movement and pauses when the tab is hidden.
- **Dark / light theme** toggle with `localStorage` persistence.
- **Collapsible sidebar** with grouped nav: Overview, Moderation, Automation, System.
- **Group switcher** with live search across all your groups.
- **Toast notifications**, modals, drawers, and skeletons for async loading states.
- **Chart.js** for all charts (activity, distributions, trends).
- **Fully responsive** — works on mobile with a slide-out sidebar.
- Legacy server-rendered pages still available at `/dashboard` as a fallback.

### 14 dashboard views

| View | What it does |
|---|---|
| **Dashboard** | Real-time stats cards, 24h activity chart with metric switcher (messages / mod actions / AI calls), recent actions feed, quick-action cards. |
| **Analytics** | 7-day stacked bar chart, severity doughnut, action distribution, category bars, top-10 members leaderboard. |
| **Members** | Searchable/filterable list (by name, username, ID, status). Click a row for a profile drawer with reputation, message count, warn/ban/mute history, and quick mute/ban/reset-reputation actions. |
| **Purgatory** | Card grid of new members awaiting approval, with avatar, suspicious badge, language/premium/joined details, and bulk approve/deny/ban. Toggle "always allow" from the UI. |
| **Flagged Queue** | Borderline AI flags with confidence meter, severity badge, and Mark-as-violation / Dismiss actions. Filter by status. |
| **Appeals** | Users can submit appeals via `/bappeal <reason>` in the group. Admins approve (auto-unbans/unmutes) or deny with optional note. |
| **Mod Log** | Every moderation action with action-type filter and pagination. |
| **Audit Trail** | Every dashboard-driven change — who edited what setting, when, with what payload. |
| **AI Configuration** | Model picker (8 free OpenRouter models), temperature slider, confidence threshold slider, enabled-categories chips, auto-ban/auto-flag toggles, custom system prompt editor, **live test playground** to send a sample message and see the model's classification. |
| **Rules & Triggers** | Build custom slash commands (`/discord` → response) and auto-response rules (trigger phrase → bot reply) with contains/exact/regex match types and case-sensitivity toggle. |
| **Scheduled Posts** | Schedule messages for a future UTC time, optionally repeat daily at a fixed hour. A background poller ships them every 30 seconds. |
| **Filters** | Word/link blocklist with delete-on-match. |
| **Settings** | General (welcome, rules), moderation (AI, purgatory, warn limit, slow mode), night mode (UTC hours), mod-log channel, theme preference. All in one form. |
| **System Health** | Live status of bot, rate limiter (calls this period / max), total AI calls + failures, in-memory tracker counts, plus a quick reference of in-group verification commands. Auto-refreshes every 10s. |

### New bot commands

| Command | Who | What |
|---|---|---|
| `/bappeal <reason>` | anyone | Submit an appeal for a recent moderation action against you. Lands in the dashboard Appeals tab. |
| `/breputation` | anyone | Show your reputation, message count, warns, mute/ban status in this group. |
| `/<custom>` | anyone | Any custom command defined in the dashboard — e.g. `/discord` if you've added one with that trigger. |

### New backend features

- **Per-group AI configuration** stored in DB — model, temperature, confidence threshold, custom system prompt, enabled categories, auto-ban/auto-flag toggles. The dashboard's AI Configuration view edits this directly.
- **User profiles** — every message bumps a per-(group, user) counter; warns/bans/mutes update flags; reputation is tracked with deltas on positive/negative actions.
- **Hourly analytics rollups** — `analytics_snapshots` table aggregates message/mod/flag/new-member/AI-call counts per hour, keeping dashboard queries fast even after months of data.
- **Audit events** — every dashboard mutation (settings save, AI prompt edit, custom command add, etc.) is logged with the admin's Telegram ID and a short detail string.
- **Scheduled message poller** — async background task started by FastAPI's lifespan handler, polls every 30s for due messages, supports daily repeats.
- **Rate limiter with stats** — the OpenRouter rate limiter now exposes `total_calls`, `total_failures`, and `calls_last_period` so the System Health view can show real-time usage.

### New database tables

`user_profiles`, `custom_commands`, `auto_responses`, `scheduled_messages`,
`ai_config`, `appeals`, `analytics_snapshots`, `audit_events`. Existing
tables (`groups`, `admins`, `warns`, `mod_log`, `flagged_messages`,
`filters`, `purgatory_entries`) are unchanged — `init_models()` creates
the new ones alongside on first boot.

## 1. Create the bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram, `/newbot`, get your token.
2. `/setjoingroups` → enable, so it can be added to groups.
3. `/setprivacy` → **disable** — the bot needs to see group messages to moderate them, not just commands.
4. Note your bot's username (without the `@`) — you'll need it for `TELEGRAM_BOT_USERNAME`.

## 2. Set up Supabase

1. Create a project at supabase.com.
2. Dashboard → Connect → copy the **Session pooler** connection string (port `5432`), not the direct connection — the direct connection is IPv6-only and some hosting platforms (Railway, notably) can't reach it.
3. Put it in `.env` as `DATABASE_URL`.

## 3. Configure `.env`

```
cp .env.example .env
```

Fill in every value — see the comments in `.env.example`. Generate the random secrets with `openssl rand -hex 32`.

`.env` is gitignored. **Never commit it.** In production, set the same variables as secrets/env vars in your hosting platform's dashboard instead — the Docker image never contains any credentials.

## 4. Install & run locally

```
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8080
```

Use a Python version matching the Dockerfile (3.12+) to avoid dependency-wheel issues. For local testing, Telegram needs a public HTTPS URL to send webhooks to — use `ngrok http 8080` and set `BASE_URL` to the ngrok URL, or just test in production once deployed.

## 5. Verify everything works

```
python verify.py
```

This runs 170+ structural checks: Python syntax, third-party imports, app module imports, SQLAlchemy model integrity, all 27+ API endpoints registered, all 24+ bot command handlers registered, every frontend asset file present, every CDN/script reference in index.html, every JS file passes `node --check` syntax validation, and the settings module constructs cleanly with mock env vars.

## 6. Telegram Login Widget domain

The web dashboard's login uses Telegram's Login Widget, which only works on a domain you've registered with BotFather:

```
/setdomain
```

Enter your deployed domain (e.g. `yourbot.fly.dev`). It won't render on an unregistered domain.

## 7. Deploy

Same Dockerfile, any of the three:

- **Fly.io**: `fly launch` (detects the Dockerfile), `fly secrets set KEY=value` for each `.env` variable, `fly deploy`.
- **Render**: New → Web Service → connect the repo → detects the Dockerfile → add each `.env` variable under Environment.
- **Railway**: New Project → Deploy from repo → detects the Dockerfile → add each `.env` variable under Variables.

Set `BASE_URL` to whatever domain the platform gives you *before* first boot — the app registers its Telegram webhook against it on startup.

## Commands

Every admin/moderation command is prefixed with **`b`** (e.g. `/bwarn`, `/bmute`) specifically so it won't collide with Rose's commands (`/warn`, `/mute`, ...) if both bots are in the same group. `/start` is left unprefixed since that's a Telegram-wide convention every bot answers to; `/bhelp` in the group lists everything.

| Command | Who | What |
|---|---|---|
| `/bwarn` `/bmute` `/bkick` `/bban` | admin, reply to a message | standard moderation actions |
| `/bunmute` | admin, reply | lift a mute |
| `/bunban <user_id>` | admin | unban (no message to reply to once banned) |
| `/bwarnlimit <n>` | admin | auto-mute a user once they hit n warns (default 3) |
| `/baddfilter word\|link <pattern>` `/bremovefilter <pattern>` `/bfilters` | admin | word/link blocklist |
| `/brules` | anyone | show group rules |
| `/bsetrules <text>` | admin | set group rules |
| `/bnightmode on\|off [start end]` | admin | delete non-admin messages during set UTC hours |
| `/bslowmode <seconds>` | admin | minimum gap between a user's messages |
| `/bpurgatory on\|off` | admin | toggle the new-member approval gate |
| `/bcleanbots` | admin | sweep the *admin* list for unauthorized bots (see limitation below) |
| `/bsetlogchannel <channel_id>` | admin | mirror every mod action to a channel |
| `/bsetwelcome <text>` or `/bsetwelcome ai <prompt>` | admin | static or AI-generated welcome message |
| `/bsummarize` | admin, reply | AI summary of a message/pasted text |
| `/bai <instruction>` | admin, reply | plain-English → warn/mute/kick/ban, via AI |
| `/bappeal <reason>` | anyone | appeal a recent moderation action against you |
| `/breputation` | anyone | show your reputation in this group |
| `/<custom>` | anyone | any custom command defined in the dashboard |

## Purgatory

New members are muted the instant they join and held in a review queue instead of getting a normal welcome message. An admin approves, denies (kicks, can rejoin later), or bans them from the dashboard's **Purgatory** tab — modeled on the approve/deny panel you shared, adapted to what Telegram actually exposes about a user (no OS/CPU/IP/hardware data like a game-server panel would have; instead: name, username, language, Telegram Premium status, join time).

- New joins land in **Pending**, or **Suspicious** if they have no username and either a digit-heavy name or no profile photo — a weak signal, just enough to sort them into a separate tab.
- The **Always allow** toggle (top right of the Purgatory page, and mirrored as a checkbox on Settings) disables the gate entirely — new members join normally with the regular welcome message, same as before this feature existed.
- Purgatory is **on by default** for new groups.

## Bot blocking

Any bot that isn't this bot or one of the usernames in `ALLOWED_BOT_USERNAMES` (`.env`, defaults to `MissRose_bot`) gets banned the instant it joins — no approval flow, immediate. `/bcleanbots` additionally sweeps the current *administrators* list for unauthorized bots.

**Limitation to know about:** Telegram's Bot API doesn't expose a full member list to bots (a privacy restriction, not an oversight), so there's no way to retroactively scan every regular member for bots that joined before this feature existed, or that were added by someone other than through the normal join flow. Enforcement is real-time from here forward, plus the admin-list sweep.

## Project structure

```
.
├── app/
│   ├── main.py                  # FastAPI app + lifespan (scheduler start)
│   ├── config.py                # pydantic-settings env config
│   ├── db.py                    # async SQLAlchemy engine
│   ├── models.py                # 15 tables (8 new in this upgrade)
│   ├── auth.py                  # Telegram Login Widget verification
│   ├── bot/
│   │   ├── __init__.py          # aiogram Bot + Dispatcher
│   │   ├── handlers.py          # 24+ command handlers + auto-mod
│   │   ├── moderation.py        # AI classify, filters, flood, slow mode
│   │   ├── openrouter.py        # Free-model fallback + rate limiter
│   │   └── purgatory.py         # New-member approval flow
│   └── dashboard/
│       ├── routes.py            # Jinja2 routes (legacy + SPA shell)
│       ├── api.py               # 27+ JSON API endpoints (new)
│       ├── templates/
│       │   ├── index.html       # SPA shell (new)
│       │   ├── login.html
│       │   └── dashboard.html   # legacy fallback
│       └── static/
│           ├── css/
│           │   ├── app.css      # theme + shell (new)
│           │   └── views.css    # per-view styles (new)
│           └── js/
│               ├── api.js       # API client (new)
│               ├── ui.js        # toast/modal/drawer helpers (new)
│               ├── background.js # Three.js particle network (new)
│               ├── app.js       # router + shell (new)
│               └── views/       # 14 view modules (new)
│                   ├── dashboard.js
│                   ├── analytics.js
│                   ├── members.js
│                   ├── purgatory.js
│                   ├── flags.js
│                   ├── appeals.js
│                   ├── modlog.js
│                   ├── audit.js
│                   ├── ai.js
│                   ├── automation.js
│                   ├── scheduled.js
│                   ├── filters.js
│                   ├── settings.js
│                   └── health.js
├── Dockerfile
├── requirements.txt
├── .env.example
├── verify.py                    # structural verification script (new)
└── README.md
```

## What's here vs. what's next

**Implemented:** everything in the command table above, the full SPA dashboard with 14 views, per-group AI configuration with live test playground, user profiles with reputation, custom commands, auto-responses, scheduled messages with daily repeats, warning appeals, audit trail, analytics rollups, system health monitoring, Three.js animated background, dark/light theme, full mobile responsiveness, and the verification script.

Reasonable next steps, not yet built: CAPTCHA as a lighter-weight alternative to full Purgatory review, Alembic migrations (the app currently just `create-tables-if-missing` on boot — fine now, not once there's real data you don't want to lose on a schema change), WebSocket push for real-time updates (currently the dashboard polls), moving the in-memory flood/slow-mode trackers to Redis if you ever run more than one instance, and CSV export of analytics/mod-log data.
