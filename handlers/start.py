from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
from config import (
    FREE_DAILY_LIMIT, DELETE_AFTER_MINUTES, VPLINK_API_KEY,
    UNLOCK_TOKEN_EXPIRY_MINUTES, HOW_TO_UNLOCK_LINK,
    REFERRAL_REQUIRED, REFERRAL_BONUS_HOURS
)
from utils.membership import check_membership, build_join_keyboard, no_groups_configured
from utils.scheduler import schedule_delete


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    await db.get_or_create_user(user.id, user.username)

    if args:
        param = args[0]

        # /start ref_<user_id>  →  referral link
        if param.startswith("ref_"):
            referrer_id_str = param[len("ref_"):]
            try:
                referrer_id = int(referrer_id_str)
                if referrer_id != user.id:
                    await db.set_referred_by(user.id, referrer_id)
            except ValueError:
                pass
            await update.message.reply_text(
                "👋 Welcome to *Uzeron Video Bot!*\n\n"
                "Videos are shared via special links in our community channel.\n"
                "Join our community and click a video link to get started! 🎬",
                parse_mode="Markdown"
            )
            return

        # /start generalad_<token>  →  came back from VPLink
        if param.startswith("generalad_"):
            token = param[len("generalad_"):]
            await handle_unlock_token(update, context, token)
            return

        # /start video_<uuid>  →  deliver a video
        if param.startswith("video_"):
            video_uuid = param[len("video_"):]
            await handle_video_request(update, context, video_uuid)
            return

        # /start getunlock  →  legacy fallback
        if param == "getunlock":
            await handle_getunlock(update, context)
            return

        # /start unlock_<token>  →  legacy fallback
        if param.startswith("unlock_"):
            token = param[len("unlock_"):]
            await handle_unlock_token(update, context, token)
            return

    # Default /start
    await update.message.reply_text(
        "👋 Welcome to *Uzeron Video Bot!*\n\n"
        "Videos are shared via special links in our community channel.\n"
        "Join our community and click a video link to get started! 🎬",
        parse_mode="Markdown"
    )


# ── VIDEO REQUEST ─────────────────────────────────────────────────────────────

async def handle_video_request(update: Update, context: ContextTypes.DEFAULT_TYPE, video_uuid: str):
    user = update.effective_user
    bot = context.bot

    # 1. Membership check
    if not await no_groups_configured():
        not_joined = await check_membership(bot, user.id)
        if not_joined:
            keyboard = build_join_keyboard(not_joined)
            context.user_data["pending_video"] = video_uuid
            await update.message.reply_text(
                "⚠️ *You need to join our community groups first!*\n\n"
                "Please join all the groups below, then tap the check button. 👇",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return

    # 2. Video exists?
    video = await db.get_video(video_uuid)
    if not video:
        await update.message.reply_text("❌ This video link is invalid or has been removed.")
        return

    # 3. Tier / daily limit check
    await db.reset_daily_count_if_needed(user.id)
    db_user = await db.get_user(user.id)

    if not db.is_user_unlocked(db_user):
        if db_user["watch_count"] >= FREE_DAILY_LIMIT:
            await send_limit_reached_message(update, context)
            return

    # 4. Send video
    delete_after = video["delete_after_mins"] or DELETE_AFTER_MINUTES
    sent = await bot.send_video(
        chat_id=user.id,
        video=video["file_id"],
        caption=(
            f"🎬 *{video['title'] or 'Video'}*\n\n"
            f"⏳ This video will be auto-deleted in *{delete_after} minutes*."
        ),
        parse_mode="Markdown"
    )

    # 5. Increment watch count
    if not db.is_user_unlocked(db_user):
        await db.increment_watch_count(user.id)
        remaining = FREE_DAILY_LIMIT - db_user["watch_count"] - 1
        if remaining > 0:
            await bot.send_message(
                chat_id=user.id,
                text=f"📊 Free videos remaining today: *{remaining}/{FREE_DAILY_LIMIT}*",
                parse_mode="Markdown"
            )
        else:
            await bot.send_message(
                chat_id=user.id,
                text="📊 You've used all your free videos for today.\n"
                     "Unlock 24h unlimited access whenever you need more! Use /unlock"
            )

    # 6. Schedule auto-delete
    delete_at = datetime.now(timezone.utc) + timedelta(minutes=delete_after)
    delivery_id = await db.save_delivery(
        user_id=user.id,
        video_uuid=video_uuid,
        message_id=sent.message_id,
        chat_id=user.id,
        delete_at=delete_at
    )
    await schedule_delete(
        bot=bot,
        job_queue=context.job_queue,
        chat_id=user.id,
        message_id=sent.message_id,
        delivery_id=delivery_id,
        delete_after_minutes=delete_after
    )

    # 7. Check if this user completing membership should complete a referral
    await _try_complete_referral(bot, user.id)


# ── MEMBERSHIP RE-CHECK CALLBACK ──────────────────────────────────────────────

async def recheck_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    bot = context.bot

    not_joined = await check_membership(bot, user.id)
    if not_joined:
        keyboard = build_join_keyboard(not_joined)
        await query.edit_message_text(
            "⚠️ You still haven't joined all required groups. Please join them first!",
            reply_markup=keyboard
        )
    else:
        await query.edit_message_text("✅ Great! You've joined all groups.")
        # Complete referral if applicable
        await _try_complete_referral(bot, user.id)
        # Deliver pending video
        pending = context.user_data.get("pending_video")
        if pending:
            context.user_data.pop("pending_video")
            await handle_video_request(update, context, pending)


async def _try_complete_referral(bot, user_id: int):
    """
    Check if this user was referred and has now joined all groups.
    If so, mark referral complete and notify referrer if they hit milestone.
    """
    referrer_id = await db.complete_referral(user_id)
    if not referrer_id:
        return

    # Get referrer's updated stats
    stats = await db.get_referral_stats(referrer_id)
    completed = stats["completed"]

    # Notify referrer of progress
    try:
        if completed % REFERRAL_REQUIRED == 0:
            # Hit a milestone — grant bonus access
            bonus_until = datetime.now(timezone.utc) + timedelta(hours=REFERRAL_BONUS_HOURS)
            # Extend existing unlock if already active
            referrer = await db.get_user(referrer_id)
            if db.is_user_unlocked(referrer) and referrer["unlocked_until"]:
                bonus_until = referrer["unlocked_until"] + timedelta(hours=REFERRAL_BONUS_HOURS)
            await db.set_unlocked_until(referrer_id, bonus_until)
            await bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"🎉 *Referral Milestone!*\n\n"
                    f"You've successfully referred *{completed} friends* who joined the community!\n\n"
                    f"✅ You've earned *{REFERRAL_BONUS_HOURS} hours* of unlimited access!\n"
                    f"_Access expires: {bonus_until.strftime('%d %b %Y, %H:%M UTC')}_"
                ),
                parse_mode="Markdown"
            )
        else:
            remaining_for_milestone = REFERRAL_REQUIRED - (completed % REFERRAL_REQUIRED)
            await bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"👥 *New Referral!*\n\n"
                    f"One of your invited friends just joined the community! ✅\n"
                    f"Total successful referrals: *{completed}*\n\n"
                    f"Invite *{remaining_for_milestone} more* to earn {REFERRAL_BONUS_HOURS}h unlimited access!"
                ),
                parse_mode="Markdown"
            )
    except Exception:
        pass  # Referrer may have blocked bot


# ── LIMIT REACHED ─────────────────────────────────────────────────────────────

async def send_limit_reached_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Watch Ad → Unlock 24h Access", callback_data="request_unlock")],
        [InlineKeyboardButton("👥 Invite Friends → Get 12h Free", callback_data="referral_info")],
    ])
    await update.message.reply_text(
        f"🚫 *You've reached your {FREE_DAILY_LIMIT} free videos for today!*\n\n"
        "Choose how to unlock more access:\n\n"
        "📺 *Watch Ad* — Get 24h unlimited access\n"
        f"👥 *Invite Friends* — Invite {REFERRAL_REQUIRED} friends, get {REFERRAL_BONUS_HOURS}h free\n\n"
        "Tap a button below 👇",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# ── WATCH AD CALLBACK ─────────────────────────────────────────────────────────

async def request_unlock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Generating your link...")
    user = query.from_user

    token = await db.create_unlock_token(user.id, UNLOCK_TOKEN_EXPIRY_MINUTES)
    bot_username = (await context.bot.get_me()).username
    destination = f"https://t.me/{bot_username}?start=generalad_{token}"
    vplink_url = await _create_vplink(VPLINK_API_KEY, destination) or destination

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Watch Ad to Unlock 24h Access", url=vplink_url)],
        [InlineKeyboardButton("❓ How to Unlock", url=HOW_TO_UNLOCK_LINK)],
        [InlineKeyboardButton("🔁 Get New Link", callback_data="request_unlock")],
    ])
    text = (
        "🔓 *Unlock 24-Hour Unlimited Access*\n\n"
        "1️⃣ Tap *Watch Ad* below\n"
        "2️⃣ Watch a short ad\n"
        "3️⃣ You'll be sent back here automatically ✅\n"
        "4️⃣ Enjoy *unlimited videos for 24 hours!* 🎉\n\n"
        f"⏱ _Complete within {UNLOCK_TOKEN_EXPIRY_MINUTES} minutes._\n\n"
        "📱 *iOS Users:* Copy the link and open in Chrome browser.\n\n"
        "_Tap 'Get New Link' if your current link expired._"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ── REFERRAL INFO CALLBACK ────────────────────────────────────────────────────

async def referral_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    stats = await db.get_referral_stats(user.id)
    completed = stats["completed"]
    remaining = REFERRAL_REQUIRED - (completed % REFERRAL_REQUIRED) if completed % REFERRAL_REQUIRED != 0 else 0
    if completed == 0:
        remaining = REFERRAL_REQUIRED

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share My Referral Link", switch_inline_query=referral_link)],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_limit")],
    ])
    await query.edit_message_text(
        f"👥 *Invite Friends — Get Free Access*\n\n"
        f"Share your referral link below.\n"
        f"When *{REFERRAL_REQUIRED} friends* join the bot AND our community groups, "
        f"you get *{REFERRAL_BONUS_HOURS} hours* of unlimited access! 🎉\n\n"
        f"📊 *Your Progress:*\n"
        f"✅ Successful referrals: *{completed}*\n"
        f"🎯 Need *{remaining} more* for next reward\n\n"
        f"🔗 *Your referral link:*\n`{referral_link}`\n\n"
        f"_(Tap to copy or use the Share button)_",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def back_to_limit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Watch Ad → Unlock 24h Access", callback_data="request_unlock")],
        [InlineKeyboardButton("👥 Invite Friends → Get 12h Free", callback_data="referral_info")],
    ])
    await query.edit_message_text(
        f"🚫 *You've reached your {FREE_DAILY_LIMIT} free videos for today!*\n\n"
        "Choose how to unlock more access:\n\n"
        "📺 *Watch Ad* — Get 24h unlimited access\n"
        f"👥 *Invite Friends* — Invite {REFERRAL_REQUIRED} friends, get {REFERRAL_BONUS_HOURS}h free\n\n"
        "Tap a button below 👇",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# ── /unlock COMMAND ───────────────────────────────────────────────────────────

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await _send_unlock_link(update, context, user.id)


async def _send_unlock_link(source, context, user_id: int):
    token = await db.create_unlock_token(user_id, UNLOCK_TOKEN_EXPIRY_MINUTES)
    bot_username = (await context.bot.get_me()).username
    destination = f"https://t.me/{bot_username}?start=generalad_{token}"
    vplink_url = await _create_vplink(VPLINK_API_KEY, destination) or destination

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Watch Ad to Unlock 24h Access", url=vplink_url)],
        [InlineKeyboardButton("❓ How to Unlock", url=HOW_TO_UNLOCK_LINK)],
        [InlineKeyboardButton("🔁 Get New Link", callback_data="request_unlock")],
    ])
    text = (
        "🔓 *Unlock 24-Hour Unlimited Access*\n\n"
        "1️⃣ Tap the link below\n"
        "2️⃣ Watch a short ad\n"
        "3️⃣ You'll be sent back here automatically ✅\n"
        "4️⃣ Enjoy *unlimited videos for 24 hours!* 🎉\n\n"
        f"⏱ _Complete within {UNLOCK_TOKEN_EXPIRY_MINUTES} minutes._\n\n"
        "📱 *iOS Users:* Copy the link and open in Chrome browser."
    )
    if hasattr(source, "message") and source.message:
        await source.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif hasattr(source, "edit_message_text"):
        await source.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ── /referral COMMAND ─────────────────────────────────────────────────────────

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    stats = await db.get_referral_stats(user.id)
    completed = stats["completed"]
    remaining = REFERRAL_REQUIRED - (completed % REFERRAL_REQUIRED)
    if completed % REFERRAL_REQUIRED == 0 and completed > 0:
        remaining = REFERRAL_REQUIRED

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share My Referral Link", switch_inline_query=referral_link)],
    ])
    await update.message.reply_text(
        f"👥 *Your Referral Dashboard*\n\n"
        f"Share your link and earn free access!\n\n"
        f"📊 *Stats:*\n"
        f"✅ Successful referrals: *{completed}*\n"
        f"🎯 Need *{remaining} more* for next {REFERRAL_BONUS_HOURS}h reward\n\n"
        f"🔗 *Your referral link:*\n`{referral_link}`\n\n"
        f"_Share this link. When {REFERRAL_REQUIRED} friends join the bot "
        f"AND all community groups, you get {REFERRAL_BONUS_HOURS}h unlimited access!_",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# ── VPLINK API ────────────────────────────────────────────────────────────────

async def _create_vplink(api_key: str, destination_url: str) -> str | None:
    import aiohttp
    import urllib.parse
    api_url = f"https://vplink.in/api?api={api_key}&url={urllib.parse.quote(destination_url, safe='')}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
                if data.get("status") == "success":
                    return data.get("shortenedUrl")
    except Exception as e:
        print(f"VPLink API error: {e}")
    return None


# ── GETUNLOCK / TOKEN HANDLERS ────────────────────────────────────────────────

async def handle_getunlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    activated = await db.consume_pending_unlock_token(user.id)
    if not activated:
        await _send_unlock_link(update, context, user.id)
        return
    until = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.set_unlocked_until(user.id, until)
    await update.message.reply_text(
        "🎉 *Unlocked! You now have unlimited access for 24 hours!*\n\n"
        "Go back to the channel and click any video link to watch. 🍿\n\n"
        f"_Access expires: {until.strftime('%d %b %Y, %H:%M UTC')}_",
        parse_mode="Markdown"
    )


async def handle_unlock_token(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user = update.effective_user
    unlocked_user_id = await db.consume_unlock_token(token)

    if not unlocked_user_id:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Try Again", callback_data="request_unlock")]
        ])
        await update.message.reply_text(
            "⏰ *Your unlock session expired.*\n\n"
            "Tap below to get a fresh link!",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    if unlocked_user_id != user.id:
        await update.message.reply_text(
            "❌ This unlock link was generated for a different account.\n"
            "Use /unlock to get your own link."
        )
        return

    until = datetime.now(timezone.utc) + timedelta(hours=24)
    await db.set_unlocked_until(user.id, until)
    await update.message.reply_text(
        "🎉 *Unlocked! You now have unlimited access for 24 hours!*\n\n"
        "Go back to the channel and click any video link to watch. 🍿\n\n"
        f"_Access expires: {until.strftime('%d %b %Y, %H:%M UTC')}_",
        parse_mode="Markdown"
    )
