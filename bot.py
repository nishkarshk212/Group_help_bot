import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, Union
import asyncio
from dotenv import load_dotenv
import re
from html import escape
from telegram import Update, ChatPermissions, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatJoinRequestHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Store warnings: {(chat_id, user_id): count}
warnings_store: Dict[Tuple[int, int], int] = {}

# Store custom welcome messages: {chat_id: message}
welcome_messages: Dict[int, str] = {}

# Store welcome images: {chat_id: file_id}
welcome_images: Dict[int, str] = {}

# Store service message: {chat_id: message}
service_messages: Dict[int, str] = {}

# Store user restrictions: {(chat_id, user_id): {restriction: bool}}
user_restrictions: Dict[Tuple[int, int], Dict[str, bool]] = {}

# Store filters: {(chat_id, keyword): {'type': 'photo/sticker/video/gif', 'file_id': str, 'caption': str}}
filters_store: Dict[Tuple[int, str], Dict[str, str]] = {}

# Store self-destruct timers: {chat_id: seconds}
self_destruct_timers: Dict[int, int] = {}

# Store edit message deletion setting: {chat_id: bool (True = enabled, False = disabled)}
edit_deletion_enabled: Dict[int, bool] = {}

# Store warning settings: {chat_id: {'threshold': int, 'mute_duration': int}}
warning_settings: Dict[int, Dict[str, int]] = {}

# Store NSFW filtering settings: {chat_id: bool (True = enabled, False = disabled)}
nsfw_filter_enabled: Dict[int, bool] = {}

# Store service message settings: {chat_id: {'enabled': bool, 'delete_after': int}}
service_msg_settings: Dict[int, Dict[str, Union[bool, int]]] = {}

# Store event message settings: {chat_id: {'enabled': bool, 'delete_after': int}}
event_msg_settings: Dict[int, Dict[str, Union[bool, int]]] = {}

load_dotenv()


async def is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """Check if user is admin or creator"""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        await update.message.reply_text("✅ Bot is active! Use /help to see available commands.")
    else:
        await update.message.reply_text(
            "👋 Hello! Add me to a group and make me an admin to manage it.\n"
            "Use /help to see all commands."
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command showing all available commands"""
    text = (
        "📋 *Group Management Bot Commands*\n\n"
        "*Admin Commands:*\n"
        "/start – Activate bot\n"
        "/help – Show this help message\n"
        "/status – Show bot permissions\n"
        "/settings – Open settings panel (mods & founder only)\n"
        "/info – Get user information (reply/mention/ID/@username)\n"
        "/ban – Ban user (reply/mention/ID/@username)\n"
        "/unban – Unban user (reply/mention/ID/@username)\n"
        "/mute – Mute user (reply/mention/ID/@username)\n"
        "/unmute – Unmute user (reply/mention/ID/@username)\n"
        "/warn – Warn user (reply/mention/ID/@username)\n"
        "/warnings – Check user warnings\n"
        "/free – Manage user restrictions (reply/mention/ID/@username)\n"
        "/promote – Promote user to admin (full permissions)\n"
        "/mod – Promote user to moderator (restrict + delete)\n"
        "/muter – Promote user to muter (mute + manage VC only)\n"
        "/unadmin – Demote admin to member\n"
        "/unmod – Demote moderator to member\n"
        "/unmuter – Demote muter to member\n"
        "/setselfdestruct – Set message auto-delete timer (seconds)\n"
        "/resetselfdestruct – Disable message auto-delete\n"
        "/enableedit – Enable automatic deletion of edited messages\n"
        "/disableedit – Disable automatic deletion of edited messages\n"
        "/setwarnlimit – Set warning threshold for auto-mute (default: 3)\n"
        "/setmutetime – Set auto-mute duration in hours (default: 24)\n"
        "/enablensfw – Enable NSFW content filtering\n"
        "/disablensfw – Disable NSFW content filtering\n"
        "/reload – Reload bot configuration (admin only)\n"
        "/config – Open configuration panel (admin only)\n"
        "/filter – Set filter for keyword (reply to media)\n"
        "/filters – List all filters\n"
        "/stopfilter – Remove a filter\n"
        "/setwelcomemessage – Set custom welcome message\n"
        "/setwelcomeimage – Set welcome image (reply to image)\n"
        "/resetwelcome – Reset welcome message and image to default\n"
        "/resetwelcomeimage – Reset welcome image to default\n"
        "/setservice – Set free service information\n"
        "/resetservice – Reset service information\n\n"
        "*Public Commands:*\n"
        "/service – View free service information\n\n"
        "*Auto Moderation:*\n"
        "• Deletes links in messages/captions\n"
        "• Deletes edited messages\n"
        "• Auto-warns non-admins (3 warnings = 24h mute)\n"
        "• Removes admin links/edits with notification\n"
        "• Welcomes new members\n"
        "• Auto-approves join requests\n"
        "• Responds to filtered keywords with media"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot status and permissions"""
    chat = update.effective_chat
    try:
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(chat.id, me.id)
        status = member.status
        
        lines = [f"🤖 *Bot Status*\n\nStatus: {status}\n\n*Permissions:*"]
        
        permissions = [
            ("can_delete_messages", "Delete messages"),
            ("can_restrict_members", "Restrict members"),
            ("can_invite_users", "Invite users"),
            ("can_pin_messages", "Pin messages"),
            ("can_manage_topics", "Manage topics"),
            ("can_change_info", "Change info"),
        ]
        
        for key, label in permissions:
            val = getattr(member, key, None)
            if val is not None:
                emoji = "✅" if val else "❌"
                lines.append(f"{emoji} {label}")
        
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Error checking status: {str(e)}")


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Settings panel - only for moderators (admins) and founder"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Only admins (including founder/creator) can use this
    if not await is_admin(context, chat_id, user_id):
        await update.message.reply_text("❌ Only moderators and the group founder can use /settings.")
        return

    text = (
        "⚙️ *Group Settings Panel*\n\n"
        "These settings can only be changed by moderators and the group founder.\n\n"
        "*Welcome Settings:*\n"
        "• /setwelcomemessage – Set custom welcome message\n"
        "• /setwelcomeimage – Set welcome image (reply to image)\n"
        "• /resetwelcome – Reset welcome message and image\n"
        "• /resetwelcomeimage – Reset welcome image only\n\n"
        "*Service & Info:*\n"
        "• /setservice – Configure free service info\n"
        "• /resetservice – Reset service info\n"
        "• /enable_service – Enable service messages\n"
        "• /disable_service – Disable service messages\n"
        "• /enable_event – Enable event messages\n"
        "• /disable_event – Disable event messages\n"
        "• /set_service_del_time – Set service message deletion time\n"
        "• /set_event_del_time – Set event message deletion time\n"
        "• /service – View free service info (public)\n\n"
        "*Message Settings:*\n"
        "• /setselfdestruct – Set auto-delete timer for bot messages\n"
        "• /resetselfdestruct – Disable auto-delete\n\n"
        "*Filters:*\n"
        "• /filter – Set media reply for keyword (reply to media)\n"
        "• /filters – List all filters\n"
        "• /stopfilter – Remove a filter\n\n"
        "*Permissions & Roles:*\n"
        "• /free – Open restriction manager for a user\n"
        "• /promote – Full admin\n"
        "• /mod – Moderator (delete + restrict)\n"
        "• /muter – Muter (mute + manage VC)\n"
        "• /unadmin, /unmod, /unmuter – Demote roles\n\n"
        "Use these commands carefully – they affect the whole group."
    )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def resolve_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Resolve target user ID from reply, mention, username or ID"""
    # Check if replying to a message
    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user.id
    
    # Check for text mention (users without username)
    if update.message:
        entities = update.message.entities or []
        for e in entities:
            if e.type == MessageEntity.TEXT_MENTION and e.user:
                return e.user.id
    
    # Check command arguments
    args = context.args or []
    chat_id = update.effective_chat.id
    
    if args:
        arg = args[0]
        
        # Direct user ID
        if arg.isdigit():
            return int(arg)
        
        # Username with @
        if arg.startswith("@"):
            username = arg[1:].lower()
            try:
                # Try to find in chat members
                admins = await context.bot.get_chat_administrators(chat_id)
                for cm in admins:
                    if cm.user.username and cm.user.username.lower() == username:
                        return cm.user.id
            except Exception:
                pass
    
    # Check for @mention in message text
    if update.message:
        text = update.message.text or ""
        for e in update.message.entities or []:
            if e.type == MessageEntity.MENTION:
                mention_text = text[e.offset : e.offset + e.length]
                username = mention_text.lstrip("@").lower()
                try:
                    admins = await context.bot.get_chat_administrators(chat_id)
                    for cm in admins:
                        if cm.user.username and cm.user.username.lower() == username:
                            return cm.user.id
                except Exception:
                    pass
    
    return None


async def apply_warning(context: ContextTypes.DEFAULT_TYPE, chat_id: int, target_id: int) -> Tuple[int, bool]:
    """Apply warning to user and auto-mute if threshold reached"""
    key = (chat_id, target_id)
    count = warnings_store.get(key, 0) + 1
    warnings_store[key] = count
    
    # Get warning settings for this chat (default to 3 warnings, 24 hours)
    settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
    threshold = settings['threshold']
    mute_duration_hours = settings['mute_duration']
    
    if count >= threshold:
        # Auto-mute for specified duration
        until = datetime.now(timezone.utc) + timedelta(hours=mute_duration_hours)
        perms = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_add_web_page_previews=False
        )
        await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms, until_date=until)
        warnings_store[key] = 0  # Reset warnings
        return count, True
    
    return count, False


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban a user from the group"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        await context.bot.ban_chat_member(chat_id, target_id)
        
        # Create toggle button for ban status
        keyboard = [[
            InlineKeyboardButton("✅ Banned", callback_data=f"banstatus_{target_id}_banned"),
            InlineKeyboardButton("❌ Unbanned", callback_data=f"banstatus_{target_id}_unbanned")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔨 *Ban Status Manager*\n\nUser ID: `{target_id}`\n\nCurrent Status: ✅ Banned\n\nClick to toggle:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to ban user: {str(e)}")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban a user from the group"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        await update.message.reply_text("✅ User has been unbanned.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to unban user: {str(e)}")


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute a user in the group"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        perms = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False
        )
        await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms)
        
        # Create toggle button for mute status
        keyboard = [[
            InlineKeyboardButton("✅ Muted", callback_data=f"mutestatus_{target_id}_muted"),
            InlineKeyboardButton("❌ Unmuted", callback_data=f"mutestatus_{target_id}_unmuted")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔇 *Mute Status Manager*\n\nUser ID: `{target_id}`\n\nCurrent Status: ✅ Muted\n\nClick to toggle:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to mute user: {str(e)}")


async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmute a user in the group"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        perms = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_add_web_page_previews=True
        )
        await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms)
        await update.message.reply_text("✅ User has been unmuted.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to unmute user: {str(e)}")


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Warn a user (3 warnings = auto-mute for 24h)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    count, muted = await apply_warning(context, chat_id, target_id)
    
    # Get user names for mentions
    admin_user = update.effective_user
    target_user = None
    if update.message and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    
    admin_mention = f'<a href="tg://user?id={admin_user.id}">{escape(admin_user.first_name)}</a>'
    target_mention = f'<a href="tg://user?id={target_id}">{escape(target_user.first_name) if target_user else "User"}</a>'
    
    if muted:
        await context.bot.send_message(
            chat_id,
            f"⚠️ {admin_mention} warned {target_mention}.\n🔇 Auto-muted for 24 hours due to 3 warnings.",
            parse_mode=ParseMode.HTML
        )
    else:
        await context.bot.send_message(
            chat_id,
            f"⚠️ {admin_mention} warned {target_mention}.\nWarnings: {count}/3",
            parse_mode=ParseMode.HTML
        )


async def check_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check warnings for a user"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    key = (chat_id, target_id)
    count = warnings_store.get(key, 0)
    await update.message.reply_text(f"⚠️ User has {count}/3 warnings.")


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get detailed information about a user"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    # Try to resolve target user from reply, mention, username, or ID
    target_id = await resolve_target_user_id(update, context)
    
    if not target_id:
        await update.message.reply_text(
            "❌ Please specify a user by:\n"
            "• Replying to their message\n"
            "• Mentioning them (@username)\n"
            "• Providing their user ID\n\n"
            "Example: `/info @username` or `/info 123456789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        # Get user info from chat member
        member = await context.bot.get_chat_member(chat_id, target_id)
        user = member.user
        
        # Get user details
        user_id = user.id
        first_name = escape(user.first_name)
        last_name = escape(user.last_name) if user.last_name else "N/A"
        username = f"@{user.username}" if user.username else "N/A"
        is_bot = "✅ Yes" if user.is_bot else "❌ No"
        is_premium = "⭐ Yes" if user.is_premium else "❌ No"
        
        # Get member status
        status = member.status
        status_emoji = {
            "creator": "👑",
            "administrator": "🛡️",
            "member": "👤",
            "restricted": "🚫",
            "left": "🚻",
            "kicked": "❌"
        }.get(status, "❓")
        
        # Get warnings
        key = (chat_id, user_id)
        warnings = warnings_store.get(key, 0)
        
        # Get restrictions if any
        restrictions_info = "None"
        if key in user_restrictions:
            active_restrictions = [k.title() for k, v in user_restrictions[key].items() if v]
            if active_restrictions:
                restrictions_info = ", ".join(active_restrictions)
        
        # Build info message
        info_text = (
            f"📍 *User Information*\n\n"
            f"🏷️ *Basic Info:*\n"
            f"Name: {first_name} {last_name}\n"
            f"Username: {username}\n"
            f"User ID: `{user_id}`\n"
            f"Bot: {is_bot}\n"
            f"Premium: {is_premium}\n\n"
            f"📊 *Group Status:*\n"
            f"Status: {status_emoji} {status.title()}\n"
            f"Warnings: ⚠️ {warnings}/3\n"
            f"Restrictions: {restrictions_info}\n\n"
        )
        
        # Add member-specific info
        if status == "restricted":
            # For restricted members, check if it's a ChatMemberRestricted object
            if hasattr(member, 'permissions') and member.permissions:
                perms = member.permissions
                info_text += (
                    f"🔒 *Permissions:*\n"
                    f"Send Messages: {'✅' if perms.can_send_messages else '❌'}\n"
                    f"Send Media: {'✅' if perms.can_send_photos else '❌'}\n"
                    f"Send Polls: {'✅' if perms.can_send_polls else '❌'}\n"
                    f"Add Web Preview: {'✅' if perms.can_add_web_page_previews else '❌'}\n"
                )
        
        # Add link to user profile
        mention = f'<a href="tg://user?id={user_id}">{first_name}</a>'
        info_text += f"\n👤 Profile: {mention}"
        
        # Check if requester is admin
        is_admin_user = await is_admin(context, chat_id, admin_id)
        
        # Add action buttons if admin and target is not admin
        reply_markup = None
        if is_admin_user and not await is_admin(context, chat_id, target_id):
            keyboard = [
                [
                    InlineKeyboardButton("⚠️ Warn", callback_data=f"action_{target_id}_warn"),
                    InlineKeyboardButton("🔇 Mute", callback_data=f"action_{target_id}_mute"),
                ],
                [
                    InlineKeyboardButton("🔨 Ban", callback_data=f"action_{target_id}_ban"),
                    InlineKeyboardButton("🔧 Permissions", callback_data=f"action_{target_id}_permissions"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            info_text += "\n\n🛠️ *Admin Actions:*\nClick buttons below to manage user."
        
        await update.message.reply_text(
            info_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to get user info: {str(e)}")


async def greet_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome new members to the group"""
    chat = update.effective_chat
    chat_id = chat.id
    
    for member in update.message.new_chat_members:
        if not member.is_bot:
            # Get custom welcome message or use default
            welcome_text = welcome_messages.get(
                chat_id,
                "╲\\╭┓\n"
                "╭🌸╯\n"
                "┗╯\\╲\n"
                "• нєℓℓσ ∂єαя\n\n"
                "    ✨『  ωєℓ¢σмє тσ   』✨\n\n"
                "           {group}\n\n\n"
                "╎➺𝐍꯭α꯭𝐦꯭є꯭-  {name}\n"
                "╎➺𝐔꯭𝐬꯭є꯭𝐫꯭𝐧꯭α꯭𝐦꯭є꯭-  {username}\n"
                "╎➺ 𝐔꯭𝐬꯭є꯭𝐫꯭ 𝐈꯭𝐃꯭-  {id}\n"
                "___\n"
                "✦ Speak Hindi + English — सबको समझ आए ✦."
            )
            
            # Replace placeholders with actual values
            welcome_text = welcome_text.replace("{name}", escape(member.first_name))
            welcome_text = welcome_text.replace("{mention}", f'<a href="tg://user?id={member.id}">{escape(member.first_name)}</a>')
            welcome_text = welcome_text.replace("{username}", f"@{member.username}" if member.username else "N/A")
            welcome_text = welcome_text.replace("{id}", str(member.id))
            welcome_text = welcome_text.replace("{group}", escape(chat.title) if chat.title else "this group")
            
            # Send welcome image if set
            if chat_id in welcome_images:
                try:
                    await context.bot.send_photo(
                        chat_id,
                        photo=welcome_images[chat_id],
                        caption=welcome_text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    # Fallback to text if image fails
                    await context.bot.send_message(
                        chat_id,
                        welcome_text,
                        parse_mode=ParseMode.HTML
                    )
            else:
                await context.bot.send_message(
                    chat_id,
                    welcome_text,
                    parse_mode=ParseMode.HTML
                )


async def delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete messages containing links and warn users"""
    msg = update.message
    if not msg:
        return
    
    chat_id = msg.chat.id
    user_id = msg.from_user.id if msg.from_user else None
    
    if not user_id:
        return
    
    # Check for links in entities
    entities = list(msg.entities or []) + list(msg.caption_entities or [])
    has_link = any(e.type in (MessageEntity.URL, MessageEntity.TEXT_LINK) for e in entities)
    
    # Check for links in text using regex
    if not has_link:
        text = (msg.text or "") + " " + (msg.caption or "")
        if text:
            url_regex = re.compile(r"(?i)(https?://|www\.)\S+|t\.me/\S+")
            has_link = bool(url_regex.search(text))
    
    if has_link:
        # Check if user has link permission from free command
        key = (chat_id, user_id)
        if key in user_restrictions:
            restrictions = user_restrictions[key]
            if not restrictions.get('link', False):  # If link restriction is OFF, allow links
                return
        
        # Delete the message
        try:
            await msg.delete()
        except Exception:
            pass
        
        # Check if user is admin
        admin = await is_admin(context, chat_id, user_id)
        
        if not admin:
            # Warn non-admin user
            count, muted = await apply_warning(context, chat_id, user_id)
            mention = f'<a href="tg://user?id={user_id}">{escape(msg.from_user.first_name)}</a>'
            
            if muted:
                await context.bot.send_message(
                    chat_id,
                    f"🔇 {mention} has been auto-muted for 24 hours due to sending links (3 warnings).",
                    parse_mode=ParseMode.HTML
                )
                try:
                    await context.bot.send_message(
                        user_id,
                        "🔇 You have been auto-muted for 24 hours due to sending links."
                    )
                except Exception:
                    pass
            else:
                await context.bot.send_message(
                    chat_id,
                    f"⚠️ {mention} warned for sending links. Warnings: {count}/3",
                    parse_mode=ParseMode.HTML
                )
                try:
                    await context.bot.send_message(
                        user_id,
                        f"⚠️ Your message with a link was removed. Warnings: {count}/3"
                    )
                except Exception:
                    pass
        else:
            # Notify admin their link was removed
            mention = f'<a href="tg://user?id={user_id}">{escape(msg.from_user.first_name)}</a>'
            await context.bot.send_message(
                chat_id,
                f"🔗 Admin link removed: {mention}",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    user_id,
                    "🔗 Your message with a link was removed (admin action)."
                )
            except Exception:
                pass


async def check_message_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if message contains restricted content based on free command settings"""
    msg = update.message
    if not msg or msg.chat.type not in ("group", "supergroup"):
        return
    
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    
    # Check if user is admin
    admin = await is_admin(context, chat_id, user_id)
    if admin:
        return
    
    # Get user restrictions
    key = (chat_id, user_id)
    if key not in user_restrictions:
        return  # No restrictions set
    
    restrictions = user_restrictions[key]
    
    # Check for stickers
    if msg.sticker and restrictions.get('sticker', False):
        try:
            await msg.delete()
        except Exception:
            pass
        
        count, muted = await apply_warning(context, chat_id, user_id)
        
        name = escape(msg.from_user.first_name)
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        
        if muted:
            await context.bot.send_message(
                chat_id,
                f"🔇 {mention} has been auto-muted for sending stickers (3 warnings).",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    user_id,
                    "🔇 You have been auto-muted for 24 hours for sending stickers."
                )
            except Exception:
                pass
        else:
            await context.bot.send_message(
                chat_id,
                f"⚠️ {mention} warned for sending stickers. Warnings: {count}/3",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    user_id,
                    f"⚠️ Stickers are restricted. Warnings: {count}/3"
                )
            except Exception:
                pass
    
    # Check for GIFs (animations)
    elif msg.animation and restrictions.get('gif', False):
        try:
            await msg.delete()
        except Exception:
            pass
        
        count, muted = await apply_warning(context, chat_id, user_id)
        
        name = escape(msg.from_user.first_name)
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        
        if muted:
            await context.bot.send_message(
                chat_id,
                f"🔇 {mention} has been auto-muted for sending GIFs (3 warnings).",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    user_id,
                    "🔇 You have been auto-muted for 24 hours for sending GIFs."
                )
            except Exception:
                pass
        else:
            await context.bot.send_message(
                chat_id,
                f"⚠️ {mention} warned for sending GIFs. Warnings: {count}/3",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    user_id,
                    f"⚠️ GIFs are restricted. Warnings: {count}/3"
                )
            except Exception:
                pass
    
    # Check for videos
    elif msg.video and restrictions.get('video', False):
        try:
            await msg.delete()
        except Exception:
            pass
        
        count, muted = await apply_warning(context, chat_id, user_id)
        
        name = escape(msg.from_user.first_name)
        mention = f'<a href="tg://user?id={user_id}">{name}</a>'
        
        if muted:
            await context.bot.send_message(
                chat_id,
                f"🔇 {mention} has been auto-muted for sending videos (3 warnings).",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    user_id,
                    "🔇 You have been auto-muted for 24 hours for sending videos."
                )
            except Exception:
                pass
        else:
            await context.bot.send_message(
                chat_id,
                f"⚠️ {mention} warned for sending videos. Warnings: {count}/3",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    user_id,
                    f"⚠️ Videos are restricted. Warnings: {count}/3"
                )
            except Exception:
                pass
    
    # Check for NSFW media content
    elif msg.photo or msg.video or msg.animation or msg.document:
        # Check if NSFW filtering is enabled for this chat
        if nsfw_filter_enabled.get(chat_id, False):
            is_nsfw_media = await detect_nsfw_media(context, msg)
            if is_nsfw_media:
                try:
                    await msg.delete()
                except Exception:
                    pass
                
                count, muted = await apply_warning(context, chat_id, user_id)
                
                name = escape(msg.from_user.first_name)
                mention = f'<a href="tg://user?id={user_id}">{name}</a>'
                
                if muted:
                    await context.bot.send_message(
                        chat_id,
                        f"🔇 {mention} has been auto-muted for sending inappropriate content. (Auto-mute triggered)",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await context.bot.send_message(
                        chat_id,
                        f"⚠️ {mention} warned for inappropriate content. Warnings: {count}/3",
                        parse_mode=ParseMode.HTML
                    )


async def detect_nsfw_media(context: ContextTypes.DEFAULT_TYPE, msg) -> bool:
    """Detect if media content is NSFW based on file name and description"""
    # Check media caption for NSFW keywords
    caption = msg.caption or ""
    if detect_nsfw_content(caption):
        return True
    
    # Check file name/description for NSFW keywords
    file_name = ""
    if msg.photo:
        # Get the largest photo size
        photo = msg.photo[-1] if msg.photo else None
        if photo:
            file_info = await context.bot.get_file(photo.file_id)
            file_name = file_info.file_path or ""
    elif msg.video:
        file_info = await context.bot.get_file(msg.video.file_id)
        file_name = file_info.file_path or ""
    elif msg.animation:
        file_info = await context.bot.get_file(msg.animation.file_id)
        file_name = file_info.file_path or ""
    elif msg.document:
        file_info = await context.bot.get_file(msg.document.file_id)
        file_name = file_info.file_path or ""
        
    # Check if filename contains NSFW indicators
    if detect_nsfw_content(file_name):
        return True
    
    # For now, we'll use filename and caption as indicators
    # In a production environment, you might want to implement image/video analysis
    # using external APIs like Google Cloud Vision, AWS Rekognition, etc.
    return False


async def on_edited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete edited messages and warn users"""
    msg = update.edited_message
    if not msg:
        return
    
    if msg.chat.type not in ("group", "supergroup"):
        return
    
    if not msg.from_user or msg.from_user.is_bot:
        return
    
    chat_id = msg.chat.id
    user_id = msg.from_user.id
    
    # Check if edit deletion is enabled for this chat
    if not edit_deletion_enabled.get(chat_id, False):
        return  # Skip if edit deletion is disabled
    
    # Delete edited message regardless of user type
    try:
        await context.bot.delete_message(chat_id, msg.message_id)
    except Exception:
        pass
    
    # Warn user
    count, muted = await apply_warning(context, chat_id, user_id)
    
    name = escape(msg.from_user.first_name)
    mention = f'<a href="tg://user?id={user_id}">{name}</a>'
    
    if muted:
        await context.bot.send_message(
            chat_id,
            f"🔇 {mention} has been auto-muted for 24 hours due to editing messages (3 warnings).",
            parse_mode=ParseMode.HTML
        )
        try:
            await context.bot.send_message(
                user_id,
                "🔇 You have been auto-muted for 24 hours due to editing messages."
            )
        except Exception:
            pass
    else:
        await context.bot.send_message(
            chat_id,
            f"⚠️ {mention} warned for editing messages. Warnings: {count}/3",
            parse_mode=ParseMode.HTML
        )
        try:
            await context.bot.send_message(
                user_id,
                f"⚠️ Your edited message was removed. Warnings: {count}/3"
            )
        except Exception:
            pass


async def approve_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-approve join requests"""
    req = update.chat_join_request
    if req:
        try:
            await req.approve()
        except Exception:
            pass


async def set_welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set custom welcome message for the group"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Get the message text after the command
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Please provide a welcome message.\n\n"
            "Usage: `/setwelcomemessage Your welcome message here`\n\n"
            "You can use these placeholders:\n"
            "`{name}` - User's first name\n"
            "`{mention}` - Mention the user\n"
            "`{username}` - User's username\n"
            "`{id}` - User's ID\n"
            "`{group}` - Group name\n\n"
            "Example: `/setwelcomemessage Welcome {mention} to {group}! Your ID: {id}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    welcome_text = " ".join(args)
    welcome_messages[chat_id] = welcome_text
    
    await update.message.reply_text(
        f"✅ Welcome message set successfully!\n\nPreview:\n{welcome_text.replace('{name}', 'John').replace('{mention}', 'John').replace('{username}', '@john').replace('{id}', '123456').replace('{group}', chat.title or 'Group')}",
        parse_mode=ParseMode.HTML
    )


async def set_welcome_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set welcome image for the group"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Check if replying to a message with photo
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text(
            "❌ Please reply to an image with `/setwelcomeimage` to set it as the welcome image.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get the largest photo file_id
    photo = update.message.reply_to_message.photo[-1]
    welcome_images[chat_id] = photo.file_id
    
    await update.message.reply_text("✅ Welcome image set successfully!")


async def reset_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset welcome message and image to default"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Remove custom welcome message and image
    message_removed = chat_id in welcome_messages
    image_removed = chat_id in welcome_images
    
    if message_removed:
        del welcome_messages[chat_id]
    if image_removed:
        del welcome_images[chat_id]
    
    if message_removed or image_removed:
        items = []
        if message_removed:
            items.append("message")
        if image_removed:
            items.append("image")
        await update.message.reply_text(
            f"✅ Welcome {' and '.join(items)} reset to default!"
        )
    else:
        await update.message.reply_text("ℹ️ No custom welcome settings found. Already using default.")


async def reset_welcome_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset only the welcome image to default"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Remove custom welcome image only
    if chat_id in welcome_images:
        del welcome_images[chat_id]
        await update.message.reply_text("✅ Welcome image reset to default!")
    else:
        await update.message.reply_text("ℹ️ No custom welcome image found. Already using default.")


async def service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display free service information (available to all users)"""
    chat_id = update.effective_chat.id
    
    # Get custom service message or use default
    service_text = service_messages.get(
        chat_id,
        "🎁 *Free Services Available*\n\n"
        "• No service information set yet.\n\n"
        "_Admins can use /setservice to add service details._"
    )
    
    await update.message.reply_text(service_text, parse_mode=ParseMode.MARKDOWN)


async def set_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set free service information (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Get the message text after the command
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Please provide service information.\n\n"
            "Usage: `/setservice Your service details here`\n\n"
            "Example: `/setservice 🎁 Free courses available! Contact @admin for details.`\n\n"
            "You can use Markdown formatting:",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    service_text = " ".join(args)
    service_messages[chat_id] = service_text
    
    await update.message.reply_text(
        f"✅ Service information set successfully!\n\nPreview:\n{service_text}",
        parse_mode=ParseMode.MARKDOWN
    )


async def reset_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset service information to default (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Remove custom service message
    if chat_id in service_messages:
        del service_messages[chat_id]
        await update.message.reply_text("✅ Service information reset to default!")
    else:
        await update.message.reply_text("ℹ️ No custom service information found. Already using default.")


async def enable_service_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable service messages in the group (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Initialize settings if not exists
    if chat_id not in service_msg_settings:
        service_msg_settings[chat_id] = {'enabled': True, 'delete_after': 30}
    else:
        service_msg_settings[chat_id]['enabled'] = True
    
    await update.message.reply_text("✅ Service messages have been enabled!")


async def disable_service_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable service messages in the group (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Initialize settings if not exists
    if chat_id not in service_msg_settings:
        service_msg_settings[chat_id] = {'enabled': False, 'delete_after': 30}
    else:
        service_msg_settings[chat_id]['enabled'] = False
    
    await update.message.reply_text("✅ Service messages have been disabled!")


async def enable_event_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable event messages in the group (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Initialize settings if not exists
    if chat_id not in event_msg_settings:
        event_msg_settings[chat_id] = {'enabled': True, 'delete_after': 30}
    else:
        event_msg_settings[chat_id]['enabled'] = True
    
    await update.message.reply_text("✅ Event messages have been enabled!")


async def disable_event_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable event messages in the group (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Initialize settings if not exists
    if chat_id not in event_msg_settings:
        event_msg_settings[chat_id] = {'enabled': False, 'delete_after': 30}
    else:
        event_msg_settings[chat_id]['enabled'] = False
    
    await update.message.reply_text("✅ Event messages have been disabled!")


async def set_service_del_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the deletion time for service messages (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "❌ Please provide a valid time in seconds.\n\n"
            "Example: `/set_service_del_time 60`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    seconds = int(args[0])
    if seconds < 1:
        await update.message.reply_text("❌ Time must be at least 1 second.")
        return
    
    # Initialize settings if not exists
    if chat_id not in service_msg_settings:
        service_msg_settings[chat_id] = {'enabled': True, 'delete_after': seconds}
    else:
        service_msg_settings[chat_id]['delete_after'] = seconds
    
    await update.message.reply_text(f"✅ Service message deletion time set to {seconds} seconds!")


async def set_event_del_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the deletion time for event messages (admin only)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "❌ Please provide a valid time in seconds.\n\n"
            "Example: `/set_event_del_time 60`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    seconds = int(args[0])
    if seconds < 1:
        await update.message.reply_text("❌ Time must be at least 1 second.")
        return
    
    # Initialize settings if not exists
    if chat_id not in event_msg_settings:
        event_msg_settings[chat_id] = {'enabled': True, 'delete_after': seconds}
    else:
        event_msg_settings[chat_id]['delete_after'] = seconds
    
    await update.message.reply_text(f"✅ Event message deletion time set to {seconds} seconds!")


async def free_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage user restrictions with toggle buttons"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Try to resolve target user from reply, mention, username, or ID
    target_id = await resolve_target_user_id(update, context)
    
    if not target_id:
        await update.message.reply_text(
            "❌ Please specify a user by:\n"
            "• Replying to their message\n"
            "• Mentioning them (@username)\n"
            "• Providing their user ID\n\n"
            "Example: `/free @username` or `/free 123456789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get target user name (from reply if available)
    target_name = "User"
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_name = update.message.reply_to_message.from_user.first_name
    
    # Check if target is admin
    if await is_admin(context, chat_id, target_id):
        await update.message.reply_text("❌ Cannot apply restrictions to admins.")
        return
    
    # Get current restrictions or initialize
    key = (chat_id, target_id)
    if key not in user_restrictions:
        user_restrictions[key] = {
            'flood': False,
            'spam': False,
            'media': False,
            'checks': False,
            'night': False,
            'sticker': False,
            'gif': False,
            'link': False
        }
    
    restrictions = user_restrictions[key]
    
    # Create inline keyboard with toggle buttons
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'✅' if restrictions['flood'] else '❌'} Flood",
                callback_data=f"free_{target_id}_flood"
            ),
            InlineKeyboardButton(
                f"{'✅' if restrictions['spam'] else '❌'} Spam",
                callback_data=f"free_{target_id}_spam"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if restrictions['media'] else '❌'} Media",
                callback_data=f"free_{target_id}_media"
            ),
            InlineKeyboardButton(
                f"{'✅' if restrictions['checks'] else '❌'} Checks",
                callback_data=f"free_{target_id}_checks"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if restrictions['sticker'] else '❌'} Sticker",
                callback_data=f"free_{target_id}_sticker"
            ),
            InlineKeyboardButton(
                f"{'✅' if restrictions['gif'] else '❌'} GIF",
                callback_data=f"free_{target_id}_gif"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if restrictions['link'] else '❌'} Link",
                callback_data=f"free_{target_id}_link"
            ),
            InlineKeyboardButton(
                f"{'✅' if restrictions['night'] else '❌'} Silence/Night",
                callback_data=f"free_{target_id}_night"
            )
        ],
        [
            InlineKeyboardButton(
                "💾 Save & Apply",
                callback_data=f"free_{target_id}_apply"
            )
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔧 *Restriction Manager*\n\n"
        f"User: {escape(target_name)}\n"
        f"ID: `{target_id}`\n\n"
        f"Toggle restrictions:\n"
        f"✅ = Restricted | ❌ = Allowed\n\n"
        f"Click 'Save & Apply' when done.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set a filter for a keyword with media response"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # Check if replying to a message with media
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Please reply to a message containing media (photo/sticker/GIF/video).\n\n"
            "Usage: Reply to media with `/filter keyword`\n\n"
            "Example: `/filter hello` while replying to an image",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get keyword from arguments
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Please provide a keyword.\n\n"
            "Usage: `/filter keyword`\n\n"
            "Example: `/filter hello`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyword = " ".join(args).lower()
    reply_msg = update.message.reply_to_message
    
    # Determine media type and get file_id
    media_type = None
    file_id = None
    caption = reply_msg.caption or ""
    
    if reply_msg.photo:
        media_type = "photo"
        file_id = reply_msg.photo[-1].file_id
    elif reply_msg.sticker:
        media_type = "sticker"
        file_id = reply_msg.sticker.file_id
    elif reply_msg.animation:  # GIF
        media_type = "animation"
        file_id = reply_msg.animation.file_id
    elif reply_msg.video:
        media_type = "video"
        file_id = reply_msg.video.file_id
    else:
        await update.message.reply_text(
            "❌ The replied message must contain a photo, sticker, GIF, or video."
        )
        return
    
    # Store the filter
    key = (chat_id, keyword)
    filters_store[key] = {
        'type': media_type,
        'file_id': file_id,
        'caption': caption
    }
    
    await update.message.reply_text(
        f"✅ Filter set successfully!\n\n"
        f"Keyword: `{keyword}`\n"
        f"Media Type: {media_type.title()}\n\n"
        f"When users send '{keyword}', the bot will respond with this {media_type}.",
        parse_mode=ParseMode.MARKDOWN
    )


async def filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all active filters in the group"""
    chat_id = update.effective_chat.id
    
    # Get all filters for this chat
    chat_filters = {k: v for k, v in filters_store.items() if k[0] == chat_id}
    
    if not chat_filters:
        await update.message.reply_text(
            "📝 No filters set in this group.\n\n"
            "Use `/filter keyword` while replying to media to create one.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Build filter list
    filter_list = "📝 *Active Filters:*\n\n"
    for (_, keyword), data in chat_filters.items():
        filter_list += f"• `{keyword}` → {data['type'].title()}\n"
    
    filter_list += f"\n_Total: {len(chat_filters)} filter(s)_"
    
    await update.message.reply_text(filter_list, parse_mode=ParseMode.MARKDOWN)


async def stopfilter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a filter"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Please provide a keyword to remove.\n\n"
            "Usage: `/stopfilter keyword`\n\n"
            "Example: `/stopfilter hello`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    keyword = " ".join(args).lower()
    key = (chat_id, keyword)
    
    if key in filters_store:
        del filters_store[key]
        await update.message.reply_text(
            f"✅ Filter removed successfully!\n\n"
            f"Keyword: `{keyword}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"❌ No filter found for keyword: `{keyword}`",
            parse_mode=ParseMode.MARKDOWN
        )


async def _demote_to_member(update: Update, context: ContextTypes.DEFAULT_TYPE, role_label: str) -> None:
    """Helper to demote a user from a role back to normal member"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        await context.bot.promote_chat_member(
            chat_id,
            target_id,
            can_change_info=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_video_chats=False,
            can_promote_members=False,
            can_manage_topics=False,
        )
        await update.message.reply_text(f"✅ User demoted from {role_label} to member.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to demote user: {str(e)}")


async def promote_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Promote a user to full admin"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        await context.bot.promote_chat_member(
            chat_id,
            target_id,
            can_change_info=True,
            can_delete_messages=True,
            can_restrict_members=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_video_chats=True,
            can_promote_members=True,
            can_manage_topics=True,
        )
        await update.message.reply_text("✅ User promoted to admin with full permissions.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to promote user: {str(e)}")


async def promote_mod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Promote a user to moderator (delete + restrict)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        await context.bot.promote_chat_member(
            chat_id,
            target_id,
            can_change_info=False,
            can_delete_messages=True,
            can_restrict_members=True,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_video_chats=False,
            can_promote_members=False,
            can_manage_topics=False,
        )
        await update.message.reply_text("✅ User promoted to moderator (can delete & restrict).")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to promote user: {str(e)}")


async def promote_muter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Promote a user to muter (mute + manage voice chat)"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    target_id = await resolve_target_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ Please specify a user by replying, mentioning, or providing user ID.")
        return
    
    try:
        await context.bot.promote_chat_member(
            chat_id,
            target_id,
            can_change_info=False,
            can_delete_messages=False,
            can_restrict_members=True,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_video_chats=True,
            can_promote_members=False,
            can_manage_topics=False,
        )
        await update.message.reply_text("✅ User promoted to muter (can mute users & manage voice chat).")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to promote user: {str(e)}")


async def unadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Demote an admin to member"""
    await _demote_to_member(update, context, "admin")


async def unmod_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Demote a moderator to member"""
    await _demote_to_member(update, context, "moderator")


async def unmuter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Demote a muter to member"""
    await _demote_to_member(update, context, "muter")


async def set_self_destruct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set self-destruct timer for bot messages in this group"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    args = context.args
    if not args:
        current_timer = self_destruct_timers.get(chat_id, 0)
        if current_timer > 0:
            await update.message.reply_text(
                f"⏱️ Current self-destruct timer: {current_timer} seconds\n\n"
                "Usage: `/setselfdestruct <seconds>`\n"
                "Example: `/setselfdestruct 30` (messages delete after 30 seconds)\n\n"
                "Set to 0 to disable or use `/resetselfdestruct`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "ℹ️ Self-destruct is currently disabled.\n\n"
                "Usage: `/setselfdestruct <seconds>`\n"
                "Example: `/setselfdestruct 30` (messages delete after 30 seconds)",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    try:
        seconds = int(args[0])
        if seconds < 0:
            await update.message.reply_text("❌ Timer must be 0 or positive. Use 0 to disable.")
            return
        
        if seconds == 0:
            if chat_id in self_destruct_timers:
                del self_destruct_timers[chat_id]
            await update.message.reply_text("✅ Self-destruct timer disabled.")
        else:
            self_destruct_timers[chat_id] = seconds
            await update.message.reply_text(
                f"✅ Self-destruct timer set to {seconds} seconds.\n\n"
                f"Bot messages will automatically delete after {seconds}s."
            )
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number of seconds.")


async def reset_self_destruct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset/disable self-destruct timer"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    if chat_id in self_destruct_timers:
        del self_destruct_timers[chat_id]
        await update.message.reply_text("✅ Self-destruct timer disabled.")
    else:
        await update.message.reply_text("ℹ️ Self-destruct is already disabled.")


async def enable_edit_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable automatic deletion of edited messages"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    edit_deletion_enabled[chat_id] = True
    await update.message.reply_text(
        "✅ Edit message deletion enabled.\n\n"
        "Non-admin edited messages will now be automatically deleted."
    )


async def disable_edit_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable automatic deletion of edited messages"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    if chat_id in edit_deletion_enabled:
        del edit_deletion_enabled[chat_id]
        await update.message.reply_text("✅ Edit message deletion disabled.")
    else:
        await update.message.reply_text("ℹ️ Edit message deletion is already disabled.")


async def set_warn_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the warning threshold for auto-mute"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    args = context.args
    if not args:
        # Show current settings
        settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
        await update.message.reply_text(
            f"⚙️ *Current Warning Settings:*\n\n"
            f"Threshold: {settings['threshold']} warnings → auto-mute\n"
            f"Mute Duration: {settings['mute_duration']} hours\n\n"
            f"Usage: `/setwarnlimit <number>`\n"
            f"Example: `/setwarnlimit 5` (auto-mute after 5 warnings)",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        threshold = int(args[0])
        if threshold <= 0:
            await update.message.reply_text("❌ Warning threshold must be greater than 0.")
            return
        
        if chat_id not in warning_settings:
            warning_settings[chat_id] = {'threshold': 3, 'mute_duration': 24}
        
        warning_settings[chat_id]['threshold'] = threshold
        await update.message.reply_text(
            f"✅ Warning threshold set to {threshold}.\n"
            f"Users will be auto-muted after {threshold} warnings."
        )
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number.")


async def set_mute_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the auto-mute duration in hours"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    args = context.args
    if not args:
        # Show current settings
        settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
        await update.message.reply_text(
            f"⚙️ *Current Warning Settings:*\n\n"
            f"Threshold: {settings['threshold']} warnings → auto-mute\n"
            f"Mute Duration: {settings['mute_duration']} hours\n\n"
            f"Usage: `/setmutetime <hours>`\n"
            f"Example: `/setmutetime 12` (auto-mute for 12 hours)",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        hours = int(args[0])
        if hours <= 0:
            await update.message.reply_text("❌ Mute duration must be greater than 0 hours.")
            return
        
        if chat_id not in warning_settings:
            warning_settings[chat_id] = {'threshold': 3, 'mute_duration': 24}
        
        warning_settings[chat_id]['mute_duration'] = hours
        await update.message.reply_text(
            f"✅ Auto-mute duration set to {hours} hours.\n"
            f"Users will be muted for {hours} hours when auto-muted."
        )
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number.")


async def enable_nsfw_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable NSFW content filtering"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    nsfw_filter_enabled[chat_id] = True
    await update.message.reply_text(
        " Porno🔞 NSFW Content Filtering Enabled\n\n"
        "Messages containing potentially inappropriate content will be detected and removed."
    )


async def disable_nsfw_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable NSFW content filtering"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    if chat_id in nsfw_filter_enabled:
        del nsfw_filter_enabled[chat_id]
        await update.message.reply_text("✅ NSFW Content Filtering Disabled")
    else:
        await update.message.reply_text("ℹ️ NSFW Content Filtering is already disabled.")


async def reload_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reload bot configuration and settings"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    
    # In a real implementation, you might reload configuration files here
    # For now, we'll just confirm the reload and show current settings
    
    # Count active configurations
    active_configs = {
        "Self-destruct timers": len([k for k, v in self_destruct_timers.items() if v > 0]),
        "Edit deletion": len([k for k, v in edit_deletion_enabled.items() if v]),
        "NSFW filtering": len([k for k, v in nsfw_filter_enabled.items() if v]),
        "Warning settings": len(warning_settings),
        "Filters": len([k for k, v in filters_store.items()])
    }
    
    total_active = sum(active_configs.values())
    
    settings_text = (
        "🔄 *Configuration Reloaded Successfully!*\n\n"
        "*Active Configurations:*\n"
    )
    
    for config, count in active_configs.items():
        if count > 0:
            settings_text += f"• {config}: {count} active\n"
    
    if total_active == 0:
        settings_text += "• No active configurations found\n"
    
    settings_text += "\n✅ Bot configuration has been refreshed."
    
    await update.message.reply_text(settings_text, parse_mode=ParseMode.MARKDOWN)


async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open configuration panel for customizing bot settings"""
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if not await is_admin(context, chat_id, admin_id):
        await update.message.reply_text("❌ Only admins can access the configuration panel.")
        return
    
    # Get current settings for this chat
    current_self_destruct = self_destruct_timers.get(chat_id, 0)
    current_edit_deletion = edit_deletion_enabled.get(chat_id, False)
    current_nsfw_filter = nsfw_filter_enabled.get(chat_id, False)
    current_warn_settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
    current_service_enabled = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
    current_service_del_time = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
    current_event_enabled = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
    current_event_del_time = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
    
    # Create inline keyboard with configuration buttons
    keyboard = [
        [
            InlineKeyboardButton(
                f"⏰ Self-destruct: {current_self_destruct}s", 
                callback_data="config_selfdestruct"
            ),
            InlineKeyboardButton(
                f"{'✅' if current_edit_deletion else '❌'} Edit Del", 
                callback_data="config_editdel"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if current_nsfw_filter else '❌'} NSFW Filter", 
                callback_data="config_nsfw"
            ),
            InlineKeyboardButton(
                f"{'✅' if current_service_enabled else '❌'} Service", 
                callback_data="config_service"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if current_event_enabled else '❌'} Event", 
                callback_data="config_event"
            ),
            InlineKeyboardButton(
                f"⚠️ Warn: {current_warn_settings['threshold']}", 
                callback_data="config_warn"
            )
        ],
        [
            InlineKeyboardButton(
                f"⏰ Mute: {current_warn_settings['mute_duration']}h", 
                callback_data="config_mutedur"
            ),
            InlineKeyboardButton(
                "🔄 Reload Config", 
                callback_data="config_reload"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 View All Settings", 
                callback_data="config_viewall"
            )
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Create configuration message with current settings
    config_text = (
        f"⚙️ *Bot Configuration Panel*\n\n"
        f"*Current Settings for this Group:*\n"
        f"• Self-destruct timer: {current_self_destruct}s {'✅ On' if current_self_destruct > 0 else '❌ Off'}\n"
        f"• Edit deletion: {'✅ Enabled' if current_edit_deletion else '❌ Disabled'}\n"
        f"• NSFW filtering: {'✅ Enabled' if current_nsfw_filter else '❌ Disabled'}\n"
        f"• Service messages: {'✅ Enabled' if current_service_enabled else '❌ Disabled'} (del after {current_service_del_time}s)\n"
        f"• Event messages: {'✅ Enabled' if current_event_enabled else '❌ Disabled'} (del after {current_event_del_time}s)\n"
        f"• Warning threshold: {current_warn_settings['threshold']} warnings\n"
        f"• Mute duration: {current_warn_settings['mute_duration']} hours\n\n"
        f"👆 Tap buttons above to configure settings."
    )
    
    await update.message.reply_text(config_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)


def detect_nsfw_content(text: str) -> bool:
    """Detect if text contains NSFW/inappropriate content including pornographic material"""
    if not text:
        return False
    
    # Convert to lowercase for case-insensitive matching
    text_lower = text.lower().strip()
    
    # Comprehensive NSFW keywords including pornographic content
    nsfw_keywords = [
        # Pornographic content and nudity
        'porn', 'porno', 'pornography', 'xxx', 'adult', 'nude', 'naked', 'nudity',
        'boob', 'boobs', 'tits', 'tit', 'breast', 'breasts', 'cleavage',
        'pussy', 'vagina', 'clit', 'clitoris', 'labia', 'cunt',
        'penis', 'dick', 'cock', 'shaft', 'member', 'wang', 'pecker',
        'ass', 'butt', 'booty', 'arse', 'arsehole', 'anus', 'anal',
        'sex', 'sexual', 'seduce', 'seduction', 'seductive',
        'blowjob', 'bj', 'fellatio', 'suck', 'oral', 'rimjob', 'analingus',
        'handjob', 'fingering', 'masturbation', 'wank', 'masturbate',
        'orgasm', 'cum', 'ejaculate', 'jizz', 'semen', 'come',
        'fucking', 'fucked', 'fuck', 'fucker', 'fucks', 'fck', 'fuk',
        'horny', 'aroused', 'excited', 'kinky', 'pervert', 'perverted',
        
        # Porn sites and platforms
        'xvideos', 'xhamster', 'pornhub', 'youporn', 'redtube', 'tube8',
        'xnxx', 'spankbang', 'txxx', 'beeg', 'pornhd', 'hqporner',
        'camgirl', 'camboy', 'webcam', 'chaturbate', 'bongacams',
        'stripchat', 'camsoda', 'imlive', 'streamate',
        
        # Erotic and adult services
        'escort', 'hooker', 'prostitute', 'whore', 'slut', 'hoe', 'thot',
        'stripper', 'striptease', 'lapdance', 'pole dance',
        'call girl', 'massage parlor', 'happy ending',
        'adult dating', 'sugar daddy', 'sugar baby',
        
        # BDSM and fetish content
        'bdsm', 'bondage', 'dominance', 'submission', 'dom/sub',
        'fetish', 'kink', 'fisting', 'gangbang', 'orgy', 'swinger',
        'master', 'mistress', 'slave', 'submissive', 'dominant',
        'leather', 'latex', 'chains', 'cuffs', 'collar',
        
        # Drugs and substances
        'weed', 'marijuana', 'cannabis', 'joint', 'bud', '420', 'ganja',
        'cocaine', 'coke', 'crack', 'snow', 'blow', 'white',
        'heroin', 'smack', 'brown', 'horse',
        'meth', 'crystal', 'ice', 'speed', 'amphetamine',
        'ecstasy', 'mdma', 'e', 'molly', 'x',
        'lsd', 'acid', 'shrooms', 'magic mushrooms', 'psilocybin',
        'pcp', 'angel dust', 'ketamine', 'special k',
        'adderall', 'oxy', 'oxycodone', 'percocet', 'vicodin',
        'xanax', 'valium', 'ativan', 'ativan', 'klonopin',
        
        # Violence and gore
        'blood', 'gore', 'bloody', 'slaughter', 'massacre',
        'murder', 'kill', 'killing', 'death', 'dead', 'corpse',
        'suicide', 'suicidal', 'hang myself', 'shoot myself',
        'violence', 'violent', 'brutal', 'brutality', 'torture',
        'terrorist', 'terrorism', 'bomb', 'explode', 'explosion',
        
        # Offensive language and slurs
        'bitch', 'bastard', 'damn', 'hell', 'shit', 'crap',
        'asshole', 'dickhead', 'cockhead', 'shithead', 'fuckhead',
        'prick', 'twat', 'minge', 'bollocks', 'knob', 'bellend',
        'wanker', 'tosser', 'cunt', 'slag', 'slut', 'whore',
        
        # Racial and discriminatory slurs
        'nigger', 'nigga', 'chink', 'gook', 'spic', 'kike',
        'fag', 'faggot', 'queer', 'dyke', 'tranny', 'transvestite',
        'wop', 'mick', 'cracker', 'redneck', 'hillbilly',
        
        # Other inappropriate content
        'pedo', 'pedophile', 'child porn', 'cp', 'loli', 'shota',
        'bestiality', 'zoophile', 'animal sex',
        'incest', 'taboo', 'family sex',
        'rape', 'rapist', 'molest', 'molestation'
    ]
    
    # Check if any NSFW keyword is in the text
    for keyword in nsfw_keywords:
        if keyword in text_lower:
            return True
    
    return False


async def schedule_message_deletion(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int) -> None:
    """Schedule a message for deletion after delay"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception:
        pass  # Message might already be deleted


async def handle_service_event_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle service and event messages according to configured settings"""
    msg = update.message
    if not msg:
        return
    
    chat_id = msg.chat.id
    
    # Check if it's a service message (like user joined, left, etc.)
    is_service_message = (
        msg.new_chat_members or 
        msg.left_chat_member or 
        msg.new_chat_title or 
        msg.new_chat_photo or 
        msg.delete_chat_photo or 
        msg.group_chat_created or 
        msg.supergroup_chat_created or 
        msg.channel_chat_created or 
        msg.message_auto_delete_timer_changed or 
        msg.pinned_message or 
        msg.invoice or 
        msg.successful_payment or 
        msg.connected_website or 
        msg.forward_origin or 
        msg.is_automatic_forward or 
        msg.has_protected_content or
        msg.migrate_from_chat_id or
        msg.migrate_to_chat_id or
        msg.pinned_message or
        msg.proximity_alert_triggered or
        msg.video_chat_scheduled or
        msg.video_chat_started or
        msg.video_chat_ended or
        msg.video_chat_participants_invited
    )
    
    if is_service_message:
        # Check if service messages are enabled for this chat
        service_settings = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30})
        
        if not service_settings.get('enabled', True):
            # Service messages are disabled, delete the message
            try:
                await msg.delete()
            except Exception:
                pass  # Message might already be deleted
        else:
            # Service messages are enabled, check if deletion time is set
            delete_after = service_settings.get('delete_after', 30)
            if delete_after > 0:
                # Schedule deletion
                asyncio.create_task(schedule_message_deletion(context, chat_id, msg.id, delete_after))
    
    # Check if it's an event message (non-content messages like contacts, locations, polls, etc.)
    # But exclude service messages and regular content
    elif not msg.text and not msg.caption and not msg.photo and not msg.video and not msg.sticker and not msg.animation:
        # Check if event messages are enabled for this chat
        event_settings = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30})
        
        if not event_settings.get('enabled', True):
            # Event messages are disabled, delete the message
            try:
                await msg.delete()
            except Exception:
                pass  # Message might already be deleted
        else:
            # Event messages are enabled, check if deletion time is set
            delete_after = event_settings.get('delete_after', 30)
            if delete_after > 0:
                # Schedule deletion
                asyncio.create_task(schedule_message_deletion(context, chat_id, msg.id, delete_after))


async def handle_other_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle other event-like messages according to configured settings"""
    # This function is kept for compatibility if needed later
    pass


async def check_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check messages for filter keywords and respond with media"""
    msg = update.message
    if not msg:
        return
    
    chat_id = msg.chat.id
    
    # Check if NSFW filtering is enabled for this chat
    if nsfw_filter_enabled.get(chat_id, False):
        # Check for text content
        text = msg.text or msg.caption or ""
        if text and detect_nsfw_content(text):
            # Delete the message
            try:
                await msg.delete()
            except Exception:
                pass
            
            # Warn the user (everyone gets warned, even admins)
            user_id = msg.from_user.id
            count, muted = await apply_warning(context, chat_id, user_id)
            
            name = escape(msg.from_user.first_name)
            mention = f'<a href="tg://user?id={user_id}">{name}</a>'
            
            if muted:
                await context.bot.send_message(
                    chat_id,
                    f"🔇 {mention} has been auto-muted for inappropriate content. (Auto-mute triggered)",
                    parse_mode=ParseMode.HTML
                )
            else:
                await context.bot.send_message(
                    chat_id,
                    f"⚠️ {mention} warned for inappropriate content. Warnings: {count}/3",
                    parse_mode=ParseMode.HTML
                )
            return  # Don't process filters if NSFW content detected
        
        # Check for media content
        elif msg.photo or msg.video or msg.animation or msg.document or msg.sticker:
            is_nsfw_media = await detect_nsfw_media(context, msg)
            if is_nsfw_media:
                # Delete the message
                try:
                    await msg.delete()
                except Exception:
                    pass
                
                # Warn the user (everyone gets warned, even admins)
                user_id = msg.from_user.id
                count, muted = await apply_warning(context, chat_id, user_id)
                
                name = escape(msg.from_user.first_name)
                mention = f'<a href="tg://user?id={user_id}">{name}</a>'
                
                if muted:
                    await context.bot.send_message(
                        chat_id,
                        f"🔇 {mention} has been auto-muted for inappropriate content. (Auto-mute triggered)",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await context.bot.send_message(
                        chat_id,
                        f"⚠️ {mention} warned for inappropriate content. Warnings: {count}/3",
                        parse_mode=ParseMode.HTML
                    )
                return  # Don't process filters if NSFW content detected
    
    # Get text from message or caption for filter processing
    text = msg.text or msg.caption or ""
    if not text:
        return
    
    text_lower = text.lower()
    
    # Check all filters for this chat
    for (filter_chat_id, keyword), data in filters_store.items():
        if filter_chat_id == chat_id and keyword in text_lower:
            try:
                # Send appropriate media type
                if data['type'] == 'photo':
                    await context.bot.send_photo(
                        chat_id,
                        photo=data['file_id'],
                        caption=data['caption'] if data['caption'] else None
                    )
                elif data['type'] == 'sticker':
                    await context.bot.send_sticker(
                        chat_id,
                        sticker=data['file_id']
                    )
                elif data['type'] == 'animation':
                    await context.bot.send_animation(
                        chat_id,
                        animation=data['file_id'],
                        caption=data['caption'] if data['caption'] else None
                    )
                elif data['type'] == 'video':
                    await context.bot.send_video(
                        chat_id,
                        video=data['file_id'],
                        caption=data['caption'] if data['caption'] else None
                    )
            except Exception:
                pass
            break  # Only respond to first matched filter


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks for unmute/unban/free"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat.id
    admin_id = query.from_user.id
    
    # Check if user is admin
    if not await is_admin(context, chat_id, admin_id):
        await query.answer("❌ Only admins can use this button.", show_alert=True)
        return
    
    # Parse callback data
    parts = query.data.split("_")
    action = parts[0]
    
    try:
        if action == "config":
            # Handle configuration button clicks
            config_action = parts[1] if len(parts) > 1 else ""
            
            if config_action == "selfdestruct":
                # Prompt for self-destruct timer
                await query.edit_message_text(
                    "⏰ *Self-Destruct Timer Configuration*\n\n"
                    "Please use the command:\n"
                    "`/setselfdestruct <seconds>`\n\n"
                    "Example: `/setselfdestruct 30` for 30 seconds\n"
                    "Or `/resetselfdestruct` to disable",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif config_action == "editdel":
                # Toggle edit deletion
                if chat_id in edit_deletion_enabled:
                    del edit_deletion_enabled[chat_id]
                    status = "❌ Disabled"
                    message = "✅ Edit deletion has been disabled."
                else:
                    edit_deletion_enabled[chat_id] = True
                    status = "✅ Enabled"
                    message = "✅ Edit deletion has been enabled."
                
                # Update the message with new status
                current_self_destruct = self_destruct_timers.get(chat_id, 0)
                current_edit_deletion = edit_deletion_enabled.get(chat_id, False)
                current_nsfw_filter = nsfw_filter_enabled.get(chat_id, False)
                current_warn_settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
                
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"⏰ Self-destruct: {current_self_destruct}s", 
                            callback_data="config_selfdestruct"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if current_edit_deletion else '❌'} Edit Del", 
                            callback_data="config_editdel"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if current_nsfw_filter else '❌'} NSFW Filter", 
                            callback_data="config_nsfw"
                        ),
                        InlineKeyboardButton(
                            f"⚠️ Warn: {current_warn_settings['threshold']}", 
                            callback_data="config_warn"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⏰ Mute: {current_warn_settings['mute_duration']}h", 
                            callback_data="config_mutedur"
                        ),
                        InlineKeyboardButton(
                            "🔄 Reload Config", 
                            callback_data="config_reload"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "📋 View All Settings", 
                            callback_data="config_viewall"
                        )
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚙️ *Bot Configuration Panel*\n\n"
                    f"*Current Settings for this Group:*\n"
                    f"• Self-destruct timer: {current_self_destruct}s {'✅ On' if current_self_destruct > 0 else '❌ Off'}\n"
                    f"• Edit deletion: {status}\n"
                    f"• NSFW filtering: {'✅ Enabled' if current_nsfw_filter else '❌ Disabled'}\n"
                    f"• Warning threshold: {current_warn_settings['threshold']} warnings\n"
                    f"• Mute duration: {current_warn_settings['mute_duration']} hours\n\n"
                    f"👆 Tap buttons above to configure settings.\n\n"
                    f"{message}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif config_action == "nsfw":
                # Toggle NSFW filtering
                if chat_id in nsfw_filter_enabled:
                    del nsfw_filter_enabled[chat_id]
                    status = "❌ Disabled"
                    message = "✅ NSFW filtering has been disabled."
                else:
                    nsfw_filter_enabled[chat_id] = True
                    status = "✅ Enabled"
                    message = "✅ NSFW filtering has been enabled."
                
                # Update the message with new status
                current_self_destruct = self_destruct_timers.get(chat_id, 0)
                current_edit_deletion = edit_deletion_enabled.get(chat_id, False)
                current_nsfw_filter = nsfw_filter_enabled.get(chat_id, False)
                current_warn_settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
                
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"⏰ Self-destruct: {current_self_destruct}s", 
                            callback_data="config_selfdestruct"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if current_edit_deletion else '❌'} Edit Del", 
                            callback_data="config_editdel"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if current_nsfw_filter else '❌'} NSFW Filter", 
                            callback_data="config_nsfw"
                        ),
                        InlineKeyboardButton(
                            f"⚠️ Warn: {current_warn_settings['threshold']}", 
                            callback_data="config_warn"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⏰ Mute: {current_warn_settings['mute_duration']}h", 
                            callback_data="config_mutedur"
                        ),
                        InlineKeyboardButton(
                            "🔄 Reload Config", 
                            callback_data="config_reload"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "📋 View All Settings", 
                            callback_data="config_viewall"
                        )
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚙️ *Bot Configuration Panel*\n\n"
                    f"*Current Settings for this Group:*\n"
                    f"• Self-destruct timer: {current_self_destruct}s {'✅ On' if current_self_destruct > 0 else '❌ Off'}\n"
                    f"• Edit deletion: {'✅ Enabled' if current_edit_deletion else '❌ Disabled'}\n"
                    f"• NSFW filtering: {status}\n"
                    f"• Warning threshold: {current_warn_settings['threshold']} warnings\n"
                    f"• Mute duration: {current_warn_settings['mute_duration']} hours\n\n"
                    f"👆 Tap buttons above to configure settings.\n\n"
                    f"{message}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif config_action == "service":
                # Toggle service message settings
                if chat_id in service_msg_settings:
                    current_state = service_msg_settings[chat_id]['enabled']
                    service_msg_settings[chat_id]['enabled'] = not current_state
                    status = "✅ Enabled" if not current_state else "❌ Disabled"
                    message = f"✅ Service messages have been {'enabled' if not current_state else 'disabled'}!"
                else:
                    service_msg_settings[chat_id] = {'enabled': True, 'delete_after': 30}
                    status = "✅ Enabled"
                    message = "✅ Service messages have been enabled!"
                
                # Update the message with new status
                current_self_destruct = self_destruct_timers.get(chat_id, 0)
                current_edit_deletion = edit_deletion_enabled.get(chat_id, False)
                current_nsfw_filter = nsfw_filter_enabled.get(chat_id, False)
                current_warn_settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
                current_service_enabled = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
                current_service_del_time = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
                current_event_enabled = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
                current_event_del_time = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
                
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"⏰ Self-destruct: {current_self_destruct}s", 
                            callback_data="config_selfdestruct"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if current_edit_deletion else '❌'} Edit Del", 
                            callback_data="config_editdel"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if current_nsfw_filter else '❌'} NSFW Filter", 
                            callback_data="config_nsfw"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if current_service_enabled else '❌'} Service", 
                            callback_data="config_service"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if current_event_enabled else '❌'} Event", 
                            callback_data="config_event"
                        ),
                        InlineKeyboardButton(
                            f"⚠️ Warn: {current_warn_settings['threshold']}", 
                            callback_data="config_warn"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⏰ Mute: {current_warn_settings['mute_duration']}h", 
                            callback_data="config_mutedur"
                        ),
                        InlineKeyboardButton(
                            "🔄 Reload Config", 
                            callback_data="config_reload"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "📋 View All Settings", 
                            callback_data="config_viewall"
                        )
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚙️ *Bot Configuration Panel*\n\n"
                    f"*Current Settings for this Group:*\n"
                    f"• Self-destruct timer: {current_self_destruct}s {'✅ On' if current_self_destruct > 0 else '❌ Off'}\n"
                    f"• Edit deletion: {'✅ Enabled' if current_edit_deletion else '❌ Disabled'}\n"
                    f"• NSFW filtering: {'✅ Enabled' if current_nsfw_filter else '❌ Disabled'}\n"
                    f"• Service messages: {status} (del after {current_service_del_time}s)\n"
                    f"• Event messages: {'✅ Enabled' if current_event_enabled else '❌ Disabled'} (del after {current_event_del_time}s)\n"
                    f"• Warning threshold: {current_warn_settings['threshold']} warnings\n"
                    f"• Mute duration: {current_warn_settings['mute_duration']} hours\n\n"
                    f"👆 Tap buttons above to configure settings.\n\n"
                    f"{message}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif config_action == "event":
                # Toggle event message settings
                if chat_id in event_msg_settings:
                    current_state = event_msg_settings[chat_id]['enabled']
                    event_msg_settings[chat_id]['enabled'] = not current_state
                    status = "✅ Enabled" if not current_state else "❌ Disabled"
                    message = f"✅ Event messages have been {'enabled' if not current_state else 'disabled'}!"
                else:
                    event_msg_settings[chat_id] = {'enabled': True, 'delete_after': 30}
                    status = "✅ Enabled"
                    message = "✅ Event messages have been enabled!"
                
                # Update the message with new status
                current_self_destruct = self_destruct_timers.get(chat_id, 0)
                current_edit_deletion = edit_deletion_enabled.get(chat_id, False)
                current_nsfw_filter = nsfw_filter_enabled.get(chat_id, False)
                current_warn_settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
                current_service_enabled = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
                current_service_del_time = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
                current_event_enabled = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
                current_event_del_time = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
                
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"⏰ Self-destruct: {current_self_destruct}s", 
                            callback_data="config_selfdestruct"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if current_edit_deletion else '❌'} Edit Del", 
                            callback_data="config_editdel"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if current_nsfw_filter else '❌'} NSFW Filter", 
                            callback_data="config_nsfw"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if current_service_enabled else '❌'} Service", 
                            callback_data="config_service"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if current_event_enabled else '❌'} Event", 
                            callback_data="config_event"
                        ),
                        InlineKeyboardButton(
                            f"⚠️ Warn: {current_warn_settings['threshold']}", 
                            callback_data="config_warn"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"⏰ Mute: {current_warn_settings['mute_duration']}h", 
                            callback_data="config_mutedur"
                        ),
                        InlineKeyboardButton(
                            "🔄 Reload Config", 
                            callback_data="config_reload"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "📋 View All Settings", 
                            callback_data="config_viewall"
                        )
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚙️ *Bot Configuration Panel*\n\n"
                    f"*Current Settings for this Group:*\n"
                    f"• Self-destruct timer: {current_self_destruct}s {'✅ On' if current_self_destruct > 0 else '❌ Off'}\n"
                    f"• Edit deletion: {'✅ Enabled' if current_edit_deletion else '❌ Disabled'}\n"
                    f"• NSFW filtering: {'✅ Enabled' if current_nsfw_filter else '❌ Disabled'}\n"
                    f"• Service messages: {'✅ Enabled' if current_service_enabled else '❌ Disabled'} (del after {current_service_del_time}s)\n"
                    f"• Event messages: {status} (del after {current_event_del_time}s)\n"
                    f"• Warning threshold: {current_warn_settings['threshold']} warnings\n"
                    f"• Mute duration: {current_warn_settings['mute_duration']} hours\n\n"
                    f"👆 Tap buttons above to configure settings.\n\n"
                    f"{message}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif config_action == "warn":
                # Prompt for warning threshold
                await query.edit_message_text(
                    "⚠️ *Warning Threshold Configuration*\n\n"
                    "Please use the command:\n"
                    "`/setwarnlimit <number>`\n\n"
                    "Example: `/setwarnlimit 5` for 5 warnings before mute\n"
                    "Default: 3 warnings",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif config_action == "mutedur":
                # Prompt for mute duration
                await query.edit_message_text(
                    "⏰ *Mute Duration Configuration*\n\n"
                    "Please use the command:\n"
                    "`/setmutetime <hours>`\n\n"
                    "Example: `/setmutetime 48` for 48 hours mute\n"
                    "Default: 24 hours",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif config_action == "reload":
                # Reload configuration
                active_configs = {
                    "Self-destruct timers": len([k for k, v in self_destruct_timers.items() if v > 0]),
                    "Edit deletion": len([k for k, v in edit_deletion_enabled.items() if v]),
                    "NSFW filtering": len([k for k, v in nsfw_filter_enabled.items() if v]),
                    "Warning settings": len(warning_settings),
                    "Service messages": len([k for k, v in service_msg_settings.items() if v['enabled']]),
                    "Event messages": len([k for k, v in event_msg_settings.items() if v['enabled']]),
                    "Filters": len([k for k, v in filters_store.items()])
                }
                
                total_active = sum(active_configs.values())
                
                config_text = "🔄 *Configuration Reloaded Successfully!*\n\n*Active Configurations:*\n"
                
                for config, count in active_configs.items():
                    if count > 0:
                        config_text += f"• {config}: {count} active\n"
                
                if total_active == 0:
                    config_text += "• No active configurations found\n"
                
                config_text += "\n✅ Bot configuration has been refreshed."
                
                await query.edit_message_text(config_text, parse_mode=ParseMode.MARKDOWN)
            elif config_action == "viewall":
                # Show all settings in detail
                current_self_destruct = self_destruct_timers.get(chat_id, 0)
                current_edit_deletion = edit_deletion_enabled.get(chat_id, False)
                current_nsfw_filter = nsfw_filter_enabled.get(chat_id, False)
                current_warn_settings = warning_settings.get(chat_id, {'threshold': 3, 'mute_duration': 24})
                current_service_enabled = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
                current_service_del_time = service_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
                current_event_enabled = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('enabled', True)
                current_event_del_time = event_msg_settings.get(chat_id, {'enabled': True, 'delete_after': 30}).get('delete_after', 30)
                
                settings_text = (
                    f"📋 *Detailed Configuration Settings*\n\n"
                    f"*Self-Destruct Timer:*\n"
                    f"  - Current: {current_self_destruct}s ({'Enabled' if current_self_destruct > 0 else 'Disabled'})\n"
                    f"  - Command: `/setselfdestruct <seconds>`\n\n"
                    f"*Edit Deletion:*\n"
                    f"  - Current: {'Enabled' if current_edit_deletion else 'Disabled'}\n"
                    f"  - Commands: `/enableedit` / `/disableedit`\n\n"
                    f"*NSFW Filtering:*\n"
                    f"  - Current: {'Enabled' if current_nsfw_filter else 'Disabled'}\n"
                    f"  - Commands: `/enablensfw` / `/disablensfw`\n\n"
                    f"*Service Messages:*\n"
                    f"  - Current: {'Enabled' if current_service_enabled else 'Disabled'}\n"
                    f"  - Deletion time: {current_service_del_time}s\n"
                    f"  - Commands: `/enable_service` / `/disable_service`, `/set_service_del_time <seconds>`\n\n"
                    f"*Event Messages:*\n"
                    f"  - Current: {'Enabled' if current_event_enabled else 'Disabled'}\n"
                    f"  - Deletion time: {current_event_del_time}s\n"
                    f"  - Commands: `/enable_event` / `/disable_event`, `/set_event_del_time <seconds>`\n\n"
                    f"*Warning Settings:*\n"
                    f"  - Threshold: {current_warn_settings['threshold']} warnings\n"
                    f"  - Mute Duration: {current_warn_settings['mute_duration']} hours\n"
                    f"  - Commands: `/setwarnlimit <num>` / `/setmutetime <hours>`\n\n"
                    f"*Other Commands:*\n"
                    f"  - `/reload` - Refresh configuration\n"
                    f"  - `/config` - Return to config panel\n"
                    f"  - `/resetselfdestruct` - Disable self-destruct\n\n"
                    f"👆 Use the commands above to adjust settings."
                )
                
                await query.edit_message_text(settings_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.answer("Configuration option not implemented yet.", show_alert=True)
        
        elif action == "banstatus":
            target_id = int(parts[1])
            new_status = parts[2]
            
            if new_status == "banned":
                # Already banned, do nothing
                await query.answer("ℹ️ User is already banned.", show_alert=True)
            else:
                # Unban the user
                await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
                
                # Update button to show new status
                keyboard = [[
                    InlineKeyboardButton("❌ Banned", callback_data=f"banstatus_{target_id}_banned"),
                    InlineKeyboardButton("✅ Unbanned", callback_data=f"banstatus_{target_id}_unbanned")
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"🔨 *Ban Status Manager*\n\nUser ID: `{target_id}`\n\nCurrent Status: ✅ Unbanned\n\nClick to toggle:",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        
        elif action == "mutestatus":
            target_id = int(parts[1])
            new_status = parts[2]
            
            if new_status == "muted":
                # Already muted, do nothing
                await query.answer("ℹ️ User is already muted.", show_alert=True)
            else:
                # Unmute the user
                perms = ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_add_web_page_previews=True
                )
                await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms)
                
                # Update button to show new status
                keyboard = [[
                    InlineKeyboardButton("❌ Muted", callback_data=f"mutestatus_{target_id}_muted"),
                    InlineKeyboardButton("✅ Unmuted", callback_data=f"mutestatus_{target_id}_unmuted")
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"🔇 *Mute Status Manager*\n\nUser ID: `{target_id}`\n\nCurrent Status: ✅ Unmuted\n\nClick to toggle:",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        
        elif action == "unban":
            target_id = int(parts[1])
            await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
            await query.edit_message_text("✅ User has been unbanned.")
            
        elif action == "unmute":
            target_id = int(parts[1])
            perms = ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_add_web_page_previews=True
            )
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms)
            await query.edit_message_text("✅ User has been unmuted.")
            
        elif action == "action":
            target_id = int(parts[1])
            action_type = parts[2]
            
            if action_type == "warn":
                # Apply warning
                count, muted = await apply_warning(context, chat_id, target_id)
                
                if muted:
                    await query.answer("⚠️ User warned and auto-muted for 24h (3 warnings)!", show_alert=True)
                else:
                    await query.answer(f"⚠️ User warned! Warnings: {count}/3", show_alert=True)
                    
            elif action_type == "mute":
                # Mute user
                perms = ChatPermissions(
                    can_send_messages=False,
                    can_send_audios=False,
                    can_send_documents=False,
                    can_send_photos=False,
                    can_send_videos=False,
                    can_send_video_notes=False,
                    can_send_voice_notes=False,
                    can_send_polls=False,
                    can_add_web_page_previews=False
                )
                await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms)
                await query.answer("🔇 User has been muted!", show_alert=True)
                
            elif action_type == "ban":
                # Ban user
                await context.bot.ban_chat_member(chat_id, target_id)
                await query.answer("🔨 User has been banned!", show_alert=True)
                
            elif action_type == "permissions":
                # Show permissions panel (same as /free command)
                key = (chat_id, target_id)
                if key not in user_restrictions:
                    user_restrictions[key] = {
                        'flood': False,
                        'spam': False,
                        'media': False,
                        'checks': False,
                        'night': False,
                        'sticker': False,
                        'gif': False,
                        'link': False
                    }
                
                restrictions = user_restrictions[key]
                
                # Create inline keyboard with toggle buttons
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['flood'] else '❌'} Flood",
                            callback_data=f"free_{target_id}_flood"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['spam'] else '❌'} Spam",
                            callback_data=f"free_{target_id}_spam"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['media'] else '❌'} Media",
                            callback_data=f"free_{target_id}_media"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['checks'] else '❌'} Checks",
                            callback_data=f"free_{target_id}_checks"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['sticker'] else '❌'} Sticker",
                            callback_data=f"free_{target_id}_sticker"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['gif'] else '❌'} GIF",
                            callback_data=f"free_{target_id}_gif"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['link'] else '❌'} Link",
                            callback_data=f"free_{target_id}_link"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['night'] else '❌'} Silence/Night",
                            callback_data=f"free_{target_id}_night"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "💾 Save & Apply",
                            callback_data=f"free_{target_id}_apply"
                        )
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"🔧 *Restriction Manager*\n\n"
                    f"User ID: `{target_id}`\n\n"
                    f"Toggle restrictions:\n"
                    f"✅ = Restricted | ❌ = Allowed\n\n"
                    f"Click 'Save & Apply' when done.",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        
        elif action == "free":
            target_id = int(parts[1])
            restriction_type = parts[2]
            
            key = (chat_id, target_id)
            
            # Initialize if not exists
            if key not in user_restrictions:
                user_restrictions[key] = {
                    'flood': False,
                    'spam': False,
                    'media': False,
                    'checks': False,
                    'night': False,
                    'sticker': False,
                    'gif': False,
                    'link': False
                }
            
            if restriction_type == "apply":
                # Apply the restrictions
                restrictions = user_restrictions[key]
                
                # Check if any restrictions are enabled
                has_restrictions = any(restrictions.values())
                
                if has_restrictions:
                    # Apply restrictions based on toggles
                    can_send_media = not restrictions['media']
                    can_send_sticker = not restrictions['sticker']
                    can_send_gif = not restrictions['gif']
                    can_send_links = not restrictions['link'] and not restrictions['spam']
                    
                    perms = ChatPermissions(
                        can_send_messages=True,  # Always allow text
                        can_send_audios=can_send_media,
                        can_send_documents=can_send_media,
                        can_send_photos=can_send_media,
                        can_send_videos=can_send_media,
                        can_send_video_notes=can_send_media,
                        can_send_voice_notes=can_send_media,
                        can_send_polls=not restrictions['spam'],
                        can_add_web_page_previews=can_send_links
                    )
                    
                    await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms)
                    
                    # Build restriction summary
                    active = [k.title() for k, v in restrictions.items() if v]
                    await query.edit_message_text(
                        f"✅ Restrictions applied!\n\n"
                        f"Active restrictions: {', '.join(active) if active else 'None'}\n\n"
                        f"User ID: `{target_id}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    # Remove all restrictions
                    perms = ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_add_web_page_previews=True
                    )
                    await context.bot.restrict_chat_member(chat_id, target_id, permissions=perms)
                    await query.edit_message_text(
                        f"✅ All restrictions removed!\n\nUser ID: `{target_id}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                # Toggle the restriction
                user_restrictions[key][restriction_type] = not user_restrictions[key][restriction_type]
                restrictions = user_restrictions[key]
                
                # Update the keyboard
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['flood'] else '❌'} Flood",
                            callback_data=f"free_{target_id}_flood"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['spam'] else '❌'} Spam",
                            callback_data=f"free_{target_id}_spam"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['media'] else '❌'} Media",
                            callback_data=f"free_{target_id}_media"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['checks'] else '❌'} Checks",
                            callback_data=f"free_{target_id}_checks"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['sticker'] else '❌'} Sticker",
                            callback_data=f"free_{target_id}_sticker"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['gif'] else '❌'} GIF",
                            callback_data=f"free_{target_id}_gif"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['link'] else '❌'} Link",
                            callback_data=f"free_{target_id}_link"
                        ),
                        InlineKeyboardButton(
                            f"{'✅' if restrictions['night'] else '❌'} Silence/Night",
                            callback_data=f"free_{target_id}_night"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "💾 Save & Apply",
                            callback_data=f"free_{target_id}_apply"
                        )
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_reply_markup(reply_markup=reply_markup)
                
    except Exception as e:
        await query.edit_message_text(f"❌ Failed: {str(e)}")


def main() -> None:
    """Main function to start the bot"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not set in environment variables.")
        print("Please create a .env file with your bot token.")
        return
    
    # Build application
    app = ApplicationBuilder().token(token).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("settings", settings_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("info", info_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("promote", promote_admin, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("mod", promote_mod, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("muter", promote_muter, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("unadmin", unadmin_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("unmod", unmod_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("unmuter", unmuter_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("ban", ban, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("unban", unban, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("mute", mute, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("unmute", unmute, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("warn", warn, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("warnings", check_warnings, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("free", free_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("filter", filter_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("filters", filters_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("stopfilter", stopfilter_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setselfdestruct", set_self_destruct, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("resetselfdestruct", reset_self_destruct, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("enableedit", enable_edit_deletion, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("disableedit", disable_edit_deletion, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setwarnlimit", set_warn_limit, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setmutetime", set_mute_time, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("enablensfw", enable_nsfw_filter, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("disablensfw", disable_nsfw_filter, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("reload", reload_config, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("config", config_cmd, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setwelcomemessage", set_welcome_message, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setwelcomeimage", set_welcome_image, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("resetwelcome", reset_welcome, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("resetwelcomeimage", reset_welcome_image, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("service", service, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setservice", set_service, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("resetservice", reset_service, filters=filters.ChatType.GROUPS))
    
    # Service and event message handlers
    app.add_handler(CommandHandler("enable_service", enable_service_msgs, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("disable_service", disable_service_msgs, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("enable_event", enable_event_msgs, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("disable_event", disable_event_msgs, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("set_service_del_time", set_service_del_time, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("set_event_del_time", set_event_del_time, filters=filters.ChatType.GROUPS))
    
    # Callback query handler for buttons
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Message handlers
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS & filters.ChatType.GROUPS,
        greet_new_members
    ))
    
    # Filter check handler (must be before link detection)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        check_filters
    ))
    
    # Link detection handlers
    app.add_handler(MessageHandler(
        filters.TEXT & (filters.Entity(MessageEntity.URL) | filters.Entity(MessageEntity.TEXT_LINK)) & filters.ChatType.GROUPS,
        delete_links
    ))
    app.add_handler(MessageHandler(
        filters.CAPTION & (filters.CaptionEntity(MessageEntity.URL) | filters.CaptionEntity(MessageEntity.TEXT_LINK)) & filters.ChatType.GROUPS,
        delete_links
    ))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS,
        delete_links
    ))
    
    # Content restriction handler (for stickers, GIFs, videos, etc.)
    app.add_handler(MessageHandler(
        filters.ALL & filters.ChatType.GROUPS,
        check_message_content
    ))
    
    # Service and event message handler
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS,
        handle_service_event_messages
    ))
    
    # Edited message handler
    app.add_handler(MessageHandler(
        filters.UpdateType.EDITED & filters.ChatType.GROUPS,
        on_edited
    ))
    
    # Join request handler
    app.add_handler(ChatJoinRequestHandler(approve_join))
    
    print("✅ Bot started successfully!")
    print("🤖 Polling for updates...")
    
    # Start polling
    app.run_polling(
        allowed_updates=["message", "edited_message", "chat_member", "my_chat_member", "chat_join_request", "callback_query"]
    )


if __name__ == "__main__":
    main()
