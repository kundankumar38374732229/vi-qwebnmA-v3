from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters
from telegram.constants import ParseMode
from telegram.error import TelegramError

import database as db
from config import DELETE_AFTER_MINUTES

# Conversation states
WAITING_FOR_VIDEO = 1
WAITING_FOR_TITLE = 2


def admin_only(func):
    """Decorator to restrict handler to admins only."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not await db.is_admin(user_id):
            await update.message.reply_text("🚫 You don't have admin access.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ── UPLOAD VIDEO ──────────────────────────────────────────────────────────────

@admin_only
async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Clear any stuck state
    context.user_data.pop("pending_upload_file_id", None)
    await update.message.reply_text(
        "📤 *Upload a Video*\n\n"
        "Send me the video file now.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_VIDEO


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sends a video — bot asks for title."""
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        return ConversationHandler.END

    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text("❌ Please send a video file.")
        return WAITING_FOR_VIDEO

    context.user_data["pending_upload_file_id"] = video.file_id
    await update.message.reply_text(
        "✅ Video received!\n\n"
        "Now send me a *title* for this video\n"
        "_(or send /skip to leave it untitled)_",
        parse_mode="Markdown"
    )
    return WAITING_FOR_TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sends title for the video."""
    title = update.message.text.strip() if update.message.text else None

    file_id = context.user_data.pop("pending_upload_file_id", None)
    if not file_id:
        await update.message.reply_text("❌ Session expired. Please use /upload again.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    video_uuid = await db.save_video(
        file_id=file_id,
        title=title,
        uploaded_by=user_id,
        delete_after_mins=DELETE_AFTER_MINUTES
    )

    bot_username = (await context.bot.get_me()).username
    deep_link = f"https://t.me/{bot_username}?start=video_{video_uuid}"

    await update.message.reply_text(
        f"🎬 Video saved!\n\n"
        f"Title: {title or 'Untitled'}\n\n"
        f"Share this link in your channel:\n"
        f"{deep_link}",
    )
    return ConversationHandler.END


async def skip_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skip for title."""
    file_id = context.user_data.pop("pending_upload_file_id", None)
    if not file_id:
        await update.message.reply_text("❌ Session expired. Please use /upload again.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    video_uuid = await db.save_video(
        file_id=file_id,
        title=None,
        uploaded_by=user_id,
        delete_after_mins=DELETE_AFTER_MINUTES
    )

    bot_username = (await context.bot.get_me()).username
    deep_link = f"https://t.me/{bot_username}?start=video_{video_uuid}"

    await update.message.reply_text(
        f"🎬 Video saved (Untitled)\n\n"
        f"Share this link in your channel:\n"
        f"{deep_link}",
    )
    return ConversationHandler.END


async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_upload_file_id", None)
    await update.message.reply_text("❌ Upload cancelled.")
    return ConversationHandler.END


# ── LIST VIDEOS ───────────────────────────────────────────────────────────────

@admin_only
async def list_videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    videos = await db.list_videos()
    if not videos:
        await update.message.reply_text("📭 No videos uploaded yet.")
        return

    bot_username = (await context.bot.get_me()).username

    # Send each video as a separate message to avoid length/parse issues
    await update.message.reply_text(f"📋 Total videos: {len(videos)}\n\nSending list...")

    for v in videos:
        link = f"https://t.me/{bot_username}?start=video_{v['uuid']}"
        title = v['title'] or 'Untitled'
        uploaded = v['uploaded_at'].strftime('%d %b %Y')
        # Plain text — no markdown to avoid parse errors with special chars in titles
        await update.message.reply_text(
            f"🎬 {title}\n"
            f"📅 {uploaded}\n"
            f"🔗 {link}"
        )


# ── DELETE VIDEO ──────────────────────────────────────────────────────────────

@admin_only
async def delete_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /deletevideo <uuid>\n"
            "Get the UUID from /listvideos"
        )
        return

    video_uuid = context.args[0]
    video = await db.get_video(video_uuid)
    if not video:
        await update.message.reply_text("❌ Video not found.")
        return

    await db.delete_video(video_uuid)
    await update.message.reply_text(
        f"🗑 Video '{video['title'] or 'Untitled'}' deleted."
    )


# ── STATS ─────────────────────────────────────────────────────────────────────

@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = await db.get_stats()
    await update.message.reply_text(
        f"📊 Bot Statistics\n\n"
        f"👥 Total Users: {stats['total_users']}\n"
        f"🎬 Total Videos: {stats['total_videos']}\n"
        f"▶️ Total Deliveries: {stats['total_deliveries']}\n"
        f"🔓 Currently Unlocked: {stats['unlocked_now']}"
    )


# ── ADD / REMOVE ADMIN ────────────────────────────────────────────────────────

@admin_only
async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config import SUPER_ADMIN_IDS
    if update.effective_user.id not in SUPER_ADMIN_IDS:
        await update.message.reply_text("🚫 Only super admins can add admins.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        new_admin_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    await db.add_admin(new_admin_id, update.effective_user.id)
    await update.message.reply_text(f"✅ User {new_admin_id} is now an admin.")


@admin_only
async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config import SUPER_ADMIN_IDS
    if update.effective_user.id not in SUPER_ADMIN_IDS:
        await update.message.reply_text("🚫 Only super admins can remove admins.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    await db.remove_admin(target_id)
    await update.message.reply_text(f"✅ User {target_id} removed from admins.")


# ── BROADCAST ─────────────────────────────────────────────────────────────────

@admin_only
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Forward any message to all users.
    Usage: Reply to a message with /broadcast
    OR: /broadcast Your text message here (supports links)

    To broadcast a photo/video/link — just REPLY to that message with /broadcast
    """
    replied = update.message.reply_to_message

    if not replied and not context.args:
        await update.message.reply_text(
            "📢 How to broadcast:\n\n"
            "Option 1 — Reply to any message with /broadcast\n"
            "(works for text, photos, videos, links, anything)\n\n"
            "Option 2 — /broadcast Your text here\n"
            "(text only)"
        )
        return

    pool_conn = await db.get_pool()
    async with pool_conn.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")

    sent = 0
    failed = 0

    status_msg = await update.message.reply_text(f"📢 Broadcasting to {len(rows)} users...")

    for row in rows:
        try:
            if replied:
                # Forward the replied-to message directly
                await replied.copy(chat_id=row["user_id"])
            else:
                # Text broadcast
                text = " ".join(context.args)
                await context.bot.send_message(
                    chat_id=row["user_id"],
                    text=f"📢 Announcement\n\n{text}",
                    disable_web_page_preview=False
                )
            sent += 1
        except TelegramError:
            failed += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"📢 Broadcast complete!\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )


# ── GROUP MANAGEMENT ──────────────────────────────────────────────────────────

@admin_only
async def add_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addgroup <chat_id> <name> <invite_link>
    Example: /addgroup -1001234567890 UzeronMain https://t.me/+xxxxxxxx
    """
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /addgroup <chat_id> <name> <invite_link>\n\n"
            "Example:\n/addgroup -1001234567890 UzeronMain https://t.me/+xxxxxxxx\n\n"
            "To get chat_id: forward a message from the group to @userinfobot"
        )
        return
    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid chat_id. Must be a number like -1001234567890")
        return

    name = context.args[1]
    invite_link = context.args[2]

    await db.add_required_group(chat_id, name, invite_link)
    await update.message.reply_text(
        f"✅ Group added!\n\n"
        f"Name: {name}\n"
        f"Chat ID: {chat_id}\n"
        f"Invite: {invite_link}"
    )


@admin_only
async def remove_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /removegroup <chat_id>
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: /removegroup <chat_id>\n"
            "Use /listgroups to see current group IDs."
        )
        return
    try:
        chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid chat_id.")
        return

    await db.remove_required_group(chat_id)
    await update.message.reply_text(f"✅ Group {chat_id} removed.")


@admin_only
async def list_groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /listgroups — show all required groups
    """
    groups = await db.get_required_groups()
    if not groups:
        await update.message.reply_text(
            "📭 No groups configured in database.\n\n"
            "Add one with:\n/addgroup <chat_id> <name> <invite_link>"
        )
        return

    lines = [f"📋 Required Groups ({len(groups)} total)\n"]
    for g in groups:
        lines.append(
            f"• {g['title']}\n"
            f"  ID: {g['chat_id']}\n"
            f"  Link: {g['invite_link']}\n"
        )
    await update.message.reply_text("\n".join(lines))
