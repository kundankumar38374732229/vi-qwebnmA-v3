import asyncio
import logging

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

import database as db
from config import BOT_TOKEN
from handlers.start import (
    start_handler,
    recheck_membership_callback,
    request_unlock_callback,
    referral_info_callback,
    back_to_limit_callback,
    unlock_command,
    referral_command,
)
from handlers.admin import (
    upload_command,
    receive_video,
    receive_title,
    skip_title,
    list_videos_command,
    delete_video_command,
    stats_command,
    add_admin_command,
    remove_admin_command,
    broadcast_command,
    add_group_command,
    remove_group_command,
    list_groups_command,
    WAITING_FOR_VIDEO,
    WAITING_FOR_TITLE,
)
from utils.scheduler import reschedule_pending_on_startup

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    await db.init_db()
    await reschedule_pending_on_startup(
        bot=application.bot,
        job_queue=application.job_queue
    )
    logger.info("🤖 Uzeron Video Bot is running!")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Upload conversation
    upload_conv = ConversationHandler(
        entry_points=[
            CommandHandler("upload", upload_command),
            MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video),
        ],
        states={
            WAITING_FOR_VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video),
            ],
            WAITING_FOR_TITLE: [
                CommandHandler("skip", skip_title),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(upload_conv)

    # User commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("referral", referral_command))

    # Admin commands
    app.add_handler(CommandHandler("listvideos", list_videos_command))
    app.add_handler(CommandHandler("deletevideo", delete_video_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("addadmin", add_admin_command))
    app.add_handler(CommandHandler("removeadmin", remove_admin_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("addgroup", add_group_command))
    app.add_handler(CommandHandler("removegroup", remove_group_command))
    app.add_handler(CommandHandler("listgroups", list_groups_command))

    # Callback queries
    app.add_handler(CallbackQueryHandler(recheck_membership_callback, pattern="^recheck_membership$"))
    app.add_handler(CallbackQueryHandler(request_unlock_callback, pattern="^request_unlock$"))
    app.add_handler(CallbackQueryHandler(referral_info_callback, pattern="^referral_info$"))
    app.add_handler(CallbackQueryHandler(back_to_limit_callback, pattern="^back_to_limit$"))

    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
