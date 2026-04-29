from datetime import datetime, timezone, timedelta
from telegram import Bot
from telegram.error import TelegramError

import database as db


async def schedule_delete(bot: Bot, job_queue, chat_id: int, message_id: int,
                          delivery_id: int, delete_after_minutes: int):
    """Schedule a message for deletion after N minutes."""
    delay_seconds = delete_after_minutes * 60
    delete_at = datetime.now(timezone.utc) + timedelta(minutes=delete_after_minutes)

    # Save to DB so we can recover if bot restarts
    # (delivery already saved before this call, we just confirm delete_at is set)

    job_queue.run_once(
        callback=_delete_job,
        when=delay_seconds,
        data={"bot": bot, "chat_id": chat_id, "message_id": message_id, "delivery_id": delivery_id},
        name=f"del_{delivery_id}"
    )


async def _delete_job(context):
    data = context.job.data
    bot: Bot = data["bot"]
    chat_id = data["chat_id"]
    message_id = data["message_id"]
    delivery_id = data["delivery_id"]

    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError:
        pass  # User may have deleted it manually or blocked bot

    await db.mark_delivery_deleted(delivery_id)


async def reschedule_pending_on_startup(bot: Bot, job_queue):
    """
    On bot startup, re-queue any deletions that were scheduled but not yet done.
    Also immediately delete any that are already overdue.
    """
    # Overdue — delete right away
    overdue = await db.get_pending_deletions()
    for d in overdue:
        try:
            await bot.delete_message(chat_id=d["chat_id"], message_id=d["message_id"])
        except TelegramError:
            pass
        await db.mark_delivery_deleted(d["id"])

    # Future — re-schedule
    future = await db.get_future_deletions()
    now = datetime.now(timezone.utc)
    for d in future:
        delay = (d["delete_at"] - now).total_seconds()
        if delay < 0:
            delay = 0
        job_queue.run_once(
            callback=_delete_job,
            when=delay,
            data={"bot": bot, "chat_id": d["chat_id"],
                  "message_id": d["message_id"], "delivery_id": d["id"]},
            name=f"del_{d['id']}"
        )

    print(f"✅ Rescheduled {len(future)} pending deletions. Cleared {len(overdue)} overdue.")
