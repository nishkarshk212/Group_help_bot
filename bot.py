import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple
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
        "/info – Get user information (reply/mention/ID/@username)\n"
        "/ban – Ban user (reply/mention/ID/@username)\n"
        "/unban – Unban user (reply/mention/ID/@username)\n"
        "/mute – Mute user (reply/mention/ID/@username)\n"
        "/unmute – Unmute user (reply/mention/ID/@username)\n"
        "/warn – Warn user (reply/mention/ID/@username)\n"
        "/warnings – Check user warnings\n"
        "/free – Manage user restrictions (reply/mention/ID/@username)\n"
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
    """Apply warning to user and auto-mute if 3 warnings reached"""
    key = (chat_id, target_id)
    count = warnings_store.get(key, 0) + 1
    warnings_store[key] = count
    
    if count >= 3:
        # Auto-mute for 24 hours
        until = datetime.now(timezone.utc) + timedelta(hours=24)
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
        return 3, True
    
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
    
    # Check if user is admin
    admin = await is_admin(context, chat_id, user_id)
    
    if admin:
        # Ignore admin edits
        return
    
    # Delete edited message
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
            'night': False
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


async def check_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check messages for filter keywords and respond with media"""
    msg = update.message
    if not msg or not msg.text:
        return
    
    chat_id = msg.chat.id
    text = msg.text.lower()
    
    # Check all filters for this chat
    for (filter_chat_id, keyword), data in filters_store.items():
        if filter_chat_id == chat_id and keyword in text:
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
        if action == "banstatus":
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
                        'night': False
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
                    'night': False
                }
            
            if restriction_type == "apply":
                # Apply the restrictions
                restrictions = user_restrictions[key]
                
                # Check if any restrictions are enabled
                has_restrictions = any(restrictions.values())
                
                if has_restrictions:
                    # Apply restrictions based on toggles
                    can_send_media = not restrictions['media']
                    
                    perms = ChatPermissions(
                        can_send_messages=True,  # Always allow text
                        can_send_audios=can_send_media,
                        can_send_documents=can_send_media,
                        can_send_photos=can_send_media,
                        can_send_videos=can_send_media,
                        can_send_video_notes=can_send_media,
                        can_send_voice_notes=can_send_media,
                        can_send_polls=not restrictions['spam'],
                        can_add_web_page_previews=not restrictions['spam']
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
    app.add_handler(CommandHandler("info", info_cmd, filters=filters.ChatType.GROUPS))
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
    app.add_handler(CommandHandler("setwelcomemessage", set_welcome_message, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setwelcomeimage", set_welcome_image, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("resetwelcome", reset_welcome, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("resetwelcomeimage", reset_welcome_image, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("service", service, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("setservice", set_service, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("resetservice", reset_service, filters=filters.ChatType.GROUPS))
    
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
