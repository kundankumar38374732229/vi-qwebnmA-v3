from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

import database as db


async def get_groups():
    """Get required groups from DB. Falls back to config if DB is empty."""
    groups = await db.get_required_groups()
    if groups:
        return groups
    # Fallback to config if DB has no groups yet
    from config import REQUIRED_GROUPS, REQUIRED_GROUP_INFO
    result = []
    for i, chat_id in enumerate(REQUIRED_GROUPS):
        info = REQUIRED_GROUP_INFO[i] if i < len(REQUIRED_GROUP_INFO) else {}
        result.append({
            "chat_id": chat_id,
            "title": info.get("name", f"Group {i+1}"),
            "invite_link": info.get("invite", "")
        })
    return result


async def check_membership(bot: Bot, user_id: int) -> list:
    """
    Returns list of groups the user has NOT joined.
    Each item is a dict with chat_id, title, invite_link.
    Empty list = user is in all groups.
    """
    groups = await get_groups()
    not_joined = []
    for group in groups:
        try:
            member = await bot.get_chat_member(
                chat_id=group["chat_id"], user_id=user_id
            )
            if member.status in ("left", "kicked", "banned"):
                not_joined.append(group)
        except TelegramError:
            not_joined.append(group)
    return not_joined


def build_join_keyboard(not_joined: list) -> InlineKeyboardMarkup:
    """Build inline keyboard with join buttons for groups user hasn't joined."""
    buttons = []
    for group in not_joined:
        if group.get("invite_link"):
            buttons.append([
                InlineKeyboardButton(
                    text=f"➕ Join {group['title']}",
                    url=group["invite_link"]
                )
            ])
    buttons.append([
        InlineKeyboardButton(
            text="✅ I've Joined All — Check Again",
            callback_data="recheck_membership"
        )
    ])
    return InlineKeyboardMarkup(buttons)


async def no_groups_configured() -> bool:
    groups = await get_groups()
    return len(groups) == 0
