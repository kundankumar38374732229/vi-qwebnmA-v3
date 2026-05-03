import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# 🔧 EDIT THESE VALUES BEFORE RUNNING THE BOT
# ─────────────────────────────────────────────

# Your bot token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Neon.tech PostgreSQL connection string
# Format: postgresql://user:password@host/dbname?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL", "YOUR_NEON_DATABASE_URL_HERE")

# Your VPLink API key
# Get it from: vplink.in → Dashboard → Tools → API
# The bot calls this API to generate a unique monetized short link per user
VPLINK_API_KEY = os.getenv("VPLINK_API_KEY", "YOUR_VPLINK_API_KEY_HERE")

# ─────────────────────────────────────────────
# 📖 HOW TO UNLOCK TUTORIAL LINK
# Link to your channel/video that shows users how to complete the VPLink ad
# Example: "https://t.me/YourChannel/123"  or  "https://t.me/YourChannel"
# ─────────────────────────────────────────────
HOW_TO_UNLOCK_LINK = os.getenv("HOW_TO_UNLOCK_LINK", "https://t.me/YourChannelHere")

# ─────────────────────────────────────────────
# 👥 REFERRAL SETTINGS
# ─────────────────────────────────────────────
# How many successful referrals needed to earn bonus access
REFERRAL_REQUIRED = 5
# How many hours of access earned per referral milestone
REFERRAL_BONUS_HOURS = 12

# ─────────────────────────────────────────────
# 👥 REQUIRED COMMUNITY GROUPS / CHANNELS
# Add the chat_id of every group/channel users must join
# To get a chat_id: forward a message from the group to @userinfobot
# Example: [-1001234567890, -1009876543210]
# ─────────────────────────────────────────────
REQUIRED_GROUPS = [-1003956042185, -1003918741759,
    # -1001234567890,   # ← Replace with your actual group IDs
    # -1009876543210,
]

# Human-readable names and invite links for each group above
# Must be in the SAME ORDER as REQUIRED_GROUPS
REQUIRED_GROUP_INFO = [
   {"name": "Uzeron", "invite": "https://t.me/Uzeron_AdsBot"},
    {"name": "Uzeron Community", "invite": "https://t.me/UzeronCommunity"},
]

# ─────────────────────────────────────────────
# ⚙️ BOT SETTINGS (safe defaults, change if needed)
# ─────────────────────────────────────────────

# Telegram user IDs of super admins (can add other admins)
# To get your user_id: message @userinfobot
SUPER_ADMIN_IDS = [ 8178921750,
    # 123456789,   # ← Your Telegram user ID
]

# How many minutes before auto-deleting a video from user's chat
DELETE_AFTER_MINUTES = 30

# Free tier daily video limit
FREE_DAILY_LIMIT = 3

# How many minutes an unlock token stays valid after generation
# User must click VPLink and land on bot within this window
UNLOCK_TOKEN_EXPIRY_MINUTES = 15

# Timezone for daily reset (midnight in this timezone resets free quota)
RESET_TIMEZONE = "UTC"
