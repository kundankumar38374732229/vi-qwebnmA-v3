# Uzeron Video Bot 🎬

A Telegram bot for the Uzeron community. Admins upload videos, bot generates secure deep links, users must join community groups to watch. Free tier: 3 videos/day. Unlimited 24h access via VPLink monetization.

---

## Project Structure

```
uzeron_video_bot/
├── bot.py              # Entry point — run this
├── config.py           # ⚙️ All your settings (edit this first)
├── database.py         # DB connection and all queries
├── handlers/
│   ├── start.py        # /start, video delivery, unlock flow
│   └── admin.py        # Upload, list, delete, stats, broadcast
├── utils/
│   ├── membership.py   # Group membership checks
│   └── scheduler.py    # Auto-delete job scheduling
├── requirements.txt
├── .env.example        # Copy to .env and fill in
└── railway.toml        # Railway deployment config
```

---

## Setup Guide

### Step 1 — Create your Telegram Bot
1. Message @BotFather on Telegram
2. Send `/newbot` and follow instructions
3. Copy your **bot token**

### Step 2 — Set up Neon.tech Database
1. Go to [neon.tech](https://neon.tech) and create a free account
2. Create a new project
3. Go to **Dashboard → Connection Details**
4. Copy the **Connection string** (starts with `postgresql://`)

### Step 3 — Set up VPLink API Key
1. Create account at [vplink.in](https://vplink.in)
2. Login → Dashboard → **Tools → API**
3. Copy your **API Key**
4. Add it to your `.env` as `VPLINK_API_KEY=...`

The bot calls VPLink's API automatically to generate a **unique monetized link per user** every time someone requests an unlock. You don't need to manually create any links — the bot handles it entirely.

### Step 4 — Configure the Bot

Open `config.py` and fill in:

```python
# 1. Your Telegram user ID (message @userinfobot to get it)
SUPER_ADMIN_IDS = [123456789]

# 2. Required groups (message @userinfobot after forwarding a group message to get chat_id)
REQUIRED_GROUPS = [-1001234567890, -1009876543210]

REQUIRED_GROUP_INFO = [
    {"name": "Uzeron Main", "invite": "https://t.me/+xxxxxxxx"},
    {"name": "Uzeron Updates", "invite": "https://t.me/+yyyyyyyy"},
]
```

Or use `.env` file (copy `.env.example` to `.env`):
```
BOT_TOKEN=your_token
DATABASE_URL=postgresql://...
UNLOCK_SHORTLINK=https://vplink.in/abc123
```

### Step 5 — Run Locally (for testing)

```bash
pip install -r requirements.txt
python bot.py
```

### Step 6 — Deploy to Railway

1. Push your code to a GitHub repo (make sure `.env` is in `.gitignore`)
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add environment variables in Railway dashboard:
   - `BOT_TOKEN`
   - `DATABASE_URL`
   - `UNLOCK_SHORTLINK`
4. Deploy — Railway reads `railway.toml` automatically

**Keep it awake:** Set up a free [UptimeRobot](https://uptimerobot.com) monitor pinging your Railway URL every 5 minutes.

---

## Admin Commands

| Command | Description |
|---|---|
| Send a video | Upload a video — bot will ask for title and generate a link |
| `/upload` | Same as above but via command |
| `/listvideos` | Show all uploaded videos with their deep links |
| `/deletevideo <uuid>` | Delete a video |
| `/stats` | View total users, videos, deliveries, unlocked users |
| `/addadmin <user_id>` | Grant admin access (super admin only) |
| `/removeadmin <user_id>` | Remove admin access (super admin only) |
| `/broadcast <message>` | Send a message to all bot users |

---

## How the Unlock Flow Works

```
User hits 3-video daily limit
        ↓
Bot sends message with "Unlock 24h" button
        ↓
User taps → bot sends your ONE VPLink (same for everyone)
        ↓
User completes ad → lands on bot via t.me/YourBot?start=getunlock
        ↓
Bot generates a fresh single-use token
        ↓
Bot sends user an "Activate" button with the token in the URL
        ↓
User taps Activate → 24h unlimited access granted ✅
```

**You only need ONE VPLink URL. The bot handles all the token uniqueness internally.**

---

## Where to Edit Things

| What | File | Variable |
|---|---|---|
| Bot token | `config.py` or `.env` | `BOT_TOKEN` |
| Database URL | `config.py` or `.env` | `DATABASE_URL` |
| VPLink API key | `config.py` or `.env` | `VPLINK_API_KEY` |
| Required groups | `config.py` | `REQUIRED_GROUPS` + `REQUIRED_GROUP_INFO` |
| Super admin IDs | `config.py` | `SUPER_ADMIN_IDS` |
| Auto-delete time | `config.py` | `DELETE_AFTER_MINUTES` |
| Daily free limit | `config.py` | `FREE_DAILY_LIMIT` |
| Unlock token expiry | `config.py` | `UNLOCK_TOKEN_EXPIRY_MINUTES` |
