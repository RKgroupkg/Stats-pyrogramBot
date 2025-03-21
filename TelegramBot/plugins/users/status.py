import json
import time
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Union
from functools import wraps

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from TelegramBot import bot
from TelegramBot.database import database
from TelegramBot.helpers.filters import is_ratelimited
from TelegramBot.config import OWNER_USERID, SUDO_USERID, LOG_CHANNEL
from TelegramBot.config import get_config_manager
from TelegramBot.helpers.async_pinger import AsyncPinger

# Constants for callback data prefixes
PREFIX_PING = "PING_"
PREFIX_CHECK = "CHK_"
PREFIX_REDEPLOY = "RDP_"
PREFIX_REPORT = "RPT_"
PREFIX_REPORT_TYPE = "RTYPE_"
PREFIX_CLOSE = "CLOSE_"
PREFIX_BACK = "BACK_"
PREFIX_ADMIN = "ADM_"
STATUS_PREFIX = "STATUS_"

# Error report types
ERROR_TYPES = {
    "1": "Bot not responding.",
    "2": "Command not working.",
    "3": "Bot is working super slow.",
    "4": "Upload/download speed seems to be slow.",
    "5": "Other issue",
}

# Cache for last deploy times and bot status
cache = {
    "last_deploy": {},
    "bot_status": {},
    "last_check": {}
}

# Initialize AsyncPinger with default settings
default_pinger = AsyncPinger(max_retries=3, retry_delay=1.0, timeout=10.0, concurrent_limit=1)


def is_admin(user_id: int) -> bool:
    """Check if user is an admin (owner or sudo user)."""
    return user_id in [OWNER_USERID] + SUDO_USERID


def format_timestamp(timestamp: Optional[float] = None) -> str:
    """Format timestamp in a consistent way."""
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def get_bot_config() -> Dict:
    """Get bot configuration dictionary from config manager."""
    try:
        config_manager = get_config_manager()
        return config_manager.get_all_bots()
    except Exception as e:
        # Fallback to empty config on error
        print(f"Error loading bot config: {e}")
        return {}


def verify_callback_initiator(func):
    """Decorator to verify the callback was initiated by the same user."""
    @wraps(func)
    async def wrapper(_, callback_query: CallbackQuery):
        if not callback_query.message.reply_to_message:
            await callback_query.answer("Invalid request. Please try again.", show_alert=True)
            return
            
        if callback_query.from_user.id != callback_query.message.reply_to_message.from_user.id:
            await callback_query.answer("This action was not initiated by you.", show_alert=True)
            return
            
        return await func(_, callback_query)
    return wrapper


def create_bot_keyboard(for_admin: bool = False) -> InlineKeyboardMarkup:
    """Create inline keyboard with bot buttons."""
    bots_config = get_bot_config()
    buttons = []
    
    # Create a button for each bot
    for bot_name in bots_config:
        # Skip disabled bots for non-admins
        if bots_config[bot_name].get("disabled", False) and not for_admin:
            continue
            
        # Create a button with bot name and callback data
        display_name = bot_name
        
        # For admins, add a marker to disabled bots
        if for_admin and bots_config[bot_name].get("disabled", False):
            display_name = f"[!] {bot_name}"
            
        # Add status indicator if available
        if bot_name in cache["bot_status"]:
            status_emoji = "🟢" if cache["bot_status"][bot_name] else "🔴"
            display_name = f"{status_emoji} {display_name}"
            
        buttons.append(
            InlineKeyboardButton(
                display_name, 
                callback_data=f"{PREFIX_PING}{bot_name}"
            )
        )
    
    # Arrange buttons in pairs (2 per row)
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    
    # Add action buttons at the bottom
    bottom_buttons = [InlineKeyboardButton("✖ Close", callback_data=f"{PREFIX_CLOSE}bots")]
    
    # Add refresh button for admins
    if for_admin:
        bottom_buttons.insert(0, InlineKeyboardButton("🔄 Refresh All", callback_data=f"{STATUS_PREFIX}REFRESH"))
    
    keyboard.append(bottom_buttons)
    
    return InlineKeyboardMarkup(keyboard)


async def ping_bot(bot_info: Dict) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Ping a bot URL and return status information.
    
    Returns:
        Tuple of (is_online, response_time, status_code)
    """
    url = bot_info.get('url', '')
    if not url:
        return False, None, "No URL configured"
        
    max_retries = bot_info.get('retries', 3)
    timeout = bot_info.get('timeout', 10.0)
    
    pinger = AsyncPinger(
        max_retries=max_retries,
        retry_delay=1.0,
        timeout=timeout,
        concurrent_limit=1
    )
    
    try:
        results = await pinger.ping_multiple([url])
        result = results[0] if results else None
        await pinger.close() # close the session
        
        if result and result.is_success():
            return True, result.response_time, str(result.status_code)
        elif result:
            return False, result.response_time, str(result.status.value)
        else:
            return False, None, "Connection failed"
            
    except Exception as e:
        return False, None, str(e)


async def update_bot_status(bot_name: str, bot_info: Dict) -> Dict:
    """
    Update bot status in cache and return status information.
    """
    is_online, response_time, status_code = await ping_bot(bot_info)
    
    # Update cache
    cache["bot_status"][bot_name] = is_online
    cache["last_check"][bot_name] = format_timestamp()
    
    return {
        "is_online": is_online,
        "response_time": response_time,
        "status_code": status_code,
        "checked_at": cache["last_check"][bot_name]
    }


async def get_user_bot_info(bot_name: str, bot_info: Dict) -> str:
    """Create a simplified bot info message for regular users."""
    # Get or update status
    if bot_name not in cache["bot_status"] or bot_name not in cache["last_check"]:
        status = await update_bot_status(bot_name, bot_info)
    else:
        status = {
            "is_online": cache["bot_status"].get(bot_name, False),
            "response_time": None,
            "checked_at": cache["last_check"].get(bot_name, "N/A")
        }
    
    # Format status information
    status_text = "🟢 Online" if status["is_online"] else "🔴 Offline"
    response_time = f"{status['response_time']:.2f}s" if status.get('response_time') else "N/A"
    last_deploy = cache["last_deploy"].get(bot_name, "♧ Unknown")
    
    message = (
        f"𝖡𝗈𝗍 𝖲𝗍𝖺𝗍𝗎𝗌:    {bot_name}\n\n"
        f"𝖲𝗍𝖺𝗍𝗎𝗌:    {status_text}\n"
        f"𝖫𝖺𝗌𝗍 𝖣𝖾𝗉𝗅𝗈𝗒:    {last_deploy}\n"
        f"𝖯𝗂𝗇𝗀 𝗍𝗂𝗆𝖾:    {response_time}\n"
        f"𝖫𝖺𝗌𝗍 𝖢𝗁𝖾𝖼𝗄𝖾𝖽:    {status['checked_at']}\n"
    )
    
    return message


async def get_admin_bot_info(bot_name: str, bot_info: Dict) -> str:
    """Create a detailed bot info message for admins."""
    # Get or update status
    if bot_name not in cache["bot_status"] or bot_name not in cache["last_check"]:
        status = await update_bot_status(bot_name, bot_info)
    else:
        status = {
            "is_online": cache["bot_status"].get(bot_name, False),
            "response_time": None, 
            "status_code": None,
            "checked_at": cache["last_check"].get(bot_name, "N/A")
        }
    
    # Format status information
    status_text = "🟢 Online" if status["is_online"] else "🔴 Offline"
    response_time = f"{status['response_time']:.2f}s" if status.get('response_time') else "N/A"
    last_deploy = cache["last_deploy"].get(bot_name, "♧ Unknown")
    
    message = (
        f"Bot Info (𝙰𝚍𝚖𝚒𝚗): {bot_name}\n\n"
        f"𝖲𝗍𝖺𝗍𝗎𝗌:    {status_text}\n"
        f"𝖲𝗍𝖺𝗍𝗎𝗌 𝖢𝗈𝖽𝖾:    {status.get('status_code', 'N/A')}\n"
        f"𝖫𝖺𝗌𝗍 𝖣𝖾𝗉𝗅𝗈𝗒:    {last_deploy}\n"
        f"𝖱𝖾𝗍𝗋𝗂𝖾𝗌:    {bot_info.get('retries', 3)}\n"
        f"𝖯𝗂𝗇𝗀 𝖨𝗇𝗍𝖾𝗋𝗏𝖺𝗅:    {bot_info.get('ping_interval', 60)} s\n"
        f"𝖳𝗂𝗆𝖾𝗈𝗎𝗍:    {bot_info.get('timeout', 10)} s\n"
        f"𝖯𝗂𝗇𝗀 𝗍𝗂𝗆𝖾:    {response_time}\n"
        f"𝖫𝖺𝗌𝗍 𝖢𝗁𝖾𝖼𝗄𝖾𝖽:    {status['checked_at']}\n"
    )
    
    # Add optional information if available
    if bot_info.get('auto_redeploy'):
        message += f"𝖠𝗎𝗍𝗈 𝖽𝖾𝗉𝗅𝗈𝗒:    𝗘𝗻𝗮𝗯𝗹𝗲𝗱\n"
        if bot_info.get('redeploy_url'):
            message += f"𝖱𝖾𝖽𝖾𝗉𝗅𝗈𝗒 𝖴𝖱𝖫:    {bot_info['redeploy_url']}\n"
        message += f"𝖱𝖾𝖽𝖾𝗉𝗅𝗈𝗒 𝖢𝗈𝗈𝗅𝖽𝗈𝗐𝗇:    {bot_info.get('redeploy_cooldown', 0)} s\n"
    else:
        message += "𝖠𝗎𝗍𝗈 𝖱𝖾𝖽𝖾𝗉𝗅𝗈𝗒:    𝗗𝗶𝘀𝗮𝗯𝗹𝗲𝗱\n"
    
    if bot_info.get('can_people_redeploy'):
        message += "𝖬𝖺𝗇𝗎𝖺𝗅 𝖱𝖾𝖽𝖾𝗉𝗅𝗈𝗒:    𝗔𝗹𝗹𝗼𝘄𝗲𝗱\n"
    else:
        message += "𝖬𝖺𝗇𝗎𝖺𝗅 𝖱𝖾𝖽𝖾𝗉𝗅𝗈𝗒:    𝗡𝗼𝘁 𝗮𝗹𝗹𝗼𝘄𝗲𝗱\n"
        
    if bot_info.get('url_bot'):
        message += f"𝖡𝗈𝗍 𝖴𝖱𝖫:    {bot_info['url_bot']}\n"
        
    if bot_info.get('disabled'):
        message += "\n[!] 𝗡𝗢𝗧𝗘: This bot is currently disabled."
    
    return message


@bot.on_callback_query(filters.regex(f"^{STATUS_PREFIX}"))
@verify_callback_initiator
async def handle_status_commands(_, callback_query: CallbackQuery):
    """Handler for status menu and refresh actions."""
    command = callback_query.data.replace(STATUS_PREFIX, "")
    user_id = callback_query.from_user.id
    is_user_admin = is_admin(user_id)
    
    if command == "STATE":
        # Different menu for admins
        if is_user_admin:
            keyboard = create_bot_keyboard(for_admin=True)
            await callback_query.message.edit_text(
                "🖥️ 𝖠𝖣𝖬𝖨𝖭 𝖲𝗂𝗍𝖾 𝖲𝗍𝖺𝗍𝗎𝗌\n\n"
                "Select a bot to check detailed status:",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            keyboard = create_bot_keyboard(for_admin=False)
            await callback_query.message.edit_text(
                "🤖 𝖡𝗈𝗍 𝖲𝗍𝖺𝗍𝗎𝗌\n\n"
                "Select a bot to check status:",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            
        await callback_query.answer()
        
    elif command == "REFRESH" and is_user_admin:
        await callback_query.answer("Refreshing all bot statuses...", show_alert=False)
        
        # Get all bot configs and update their status
        bots_config = get_bot_config()
        refresh_tasks = []
        
        for bot_name, bot_info in bots_config.items():
            refresh_tasks.append(update_bot_status(bot_name, bot_info))
        
        # Wait for all refresh tasks to complete
        if refresh_tasks:
            await asyncio.gather(*refresh_tasks)
        
        # Recreate keyboard with updated statuses
        keyboard = create_bot_keyboard(for_admin=True)
        
        await callback_query.message.edit_text(
            "🖥️ 𝖠𝖣𝖬𝖨𝖭 𝖲𝗂𝗍𝖾 𝖲𝗍𝖺𝗍𝗎𝗌 (🔄 Refreshed)\n\n"
            "Select a bot to check detailed status:",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )


@bot.on_callback_query(filters.regex(f"^{PREFIX_PING}|^{PREFIX_CLOSE}"))
@verify_callback_initiator
async def handle_bot_callback(_, callback_query: CallbackQuery):
    """Callback handler for bot ping requests."""
    # Handle close action
    if callback_query.data.startswith(PREFIX_CLOSE):
        await callback_query.message.delete()
        return await callback_query.answer("Menu closed")
    
    # Extract bot name from callback data
    bot_name = callback_query.data.replace(PREFIX_PING, "")
    user_id = callback_query.from_user.id
    is_user_admin = is_admin(user_id)
    
    # Get bot configuration
    bots_config = get_bot_config()
    
    # Check if bot exists in config
    if bot_name not in bots_config:
        return await callback_query.answer(
            f"Bot '{bot_name}' not found in configuration.", 
            show_alert=True
        )
    
    # Store bot info in temporary variable for processing
    bot_info = bots_config[bot_name]
    
    # Create different views for admin vs regular users
    try:
        if is_user_admin:
            message = await get_admin_bot_info(bot_name, bot_info)
        else:
            message = await get_user_bot_info(bot_name, bot_info)
    except Exception as e:
        error_message = str(e)[:100] if is_user_admin else "Failed to get bot information."
        return await callback_query.answer(f"Error: {error_message}", show_alert=True)
    
    # Create action buttons based on bot configuration and user role
    buttons = []
    
    # Add check status button for everyone
    buttons.append(InlineKeyboardButton("🔍 Check Status", callback_data=f"{PREFIX_CHECK}{bot_name}"))
    
    # Add redeploy button if allowed and user is admin or redeploy is allowed for users
    if (is_user_admin or bot_info.get('can_people_redeploy', False)) and bot_info.get('redeploy_url'):
        buttons.append(InlineKeyboardButton("🔄 Redeploy", callback_data=f"{PREFIX_REDEPLOY}{bot_name}"))
    
    # Add report error button for non-admin users
    if not is_user_admin:
        buttons.append(InlineKeyboardButton("⚠️ Report Error", callback_data=f"{PREFIX_REPORT}{bot_name}"))
    
    # Arrange buttons in rows
    keyboard = [buttons]
    
    # Add back button
    if is_user_admin:
        back_row = [InlineKeyboardButton("◄ Back", callback_data=f"{PREFIX_BACK}ADMIN_bots")]
    else:
        back_row = [InlineKeyboardButton("◄ Back", callback_data=f"{PREFIX_BACK}USER_bots")]
    
    keyboard.append(back_row)
    
    # Update the message with bot info and buttons
    await callback_query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback_query.answer()


@bot.on_callback_query(filters.regex(f"^{PREFIX_BACK}"))
@verify_callback_initiator
async def show_bots_menu(_, callback_query: CallbackQuery):
    """Callback handler to return to the bots menu."""
    back_to = callback_query.data.replace(PREFIX_BACK, "")
    is_admin_menu = back_to.startswith("ADMIN_")
    
    keyboard = create_bot_keyboard(for_admin=is_admin_menu)
    
    if is_admin_menu:
        await callback_query.edit_message_text(
            "🖥️ 𝖠𝖣𝖬𝖨𝖭 𝖲𝗂𝗍𝖾 𝖲𝗍𝖺𝗍𝗎𝗌\n\n"
            "Select a bot to check detailed status:",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await callback_query.edit_message_text(
            "🤖 𝖡𝗈𝗍 𝖲𝗍𝖺𝗍𝗎𝗌\n\n"
            "Select a bot to check status:",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    
    await callback_query.answer()


@bot.on_callback_query(filters.regex(f"^{PREFIX_CHECK}|^{PREFIX_REDEPLOY}"))
@verify_callback_initiator
async def handle_bot_actions(_, callback_query: CallbackQuery):
    """Callback handler for bot check and redeploy actions."""
    user_id = callback_query.from_user.id
    is_user_admin = is_admin(user_id)
    
    # Determine action type
    is_check = callback_query.data.startswith(PREFIX_CHECK)
    is_redeploy = callback_query.data.startswith(PREFIX_REDEPLOY)
    
    if is_check:
        bot_name = callback_query.data.replace(PREFIX_CHECK, "")
        action = "CHECK"
    elif is_redeploy:
        bot_name = callback_query.data.replace(PREFIX_REDEPLOY, "")
        action = "REDEPLOY"
    else:
        return await callback_query.answer("Invalid action", show_alert=True)
    
    # Get bot configuration
    bots_config = get_bot_config()
    
    # Check if bot exists in config
    if bot_name not in bots_config:
        return await callback_query.answer(
            f"Bot '{bot_name}' not found in configuration.", 
            show_alert=True
        )
    
    bot_info = bots_config[bot_name]
    
    # Verify permissions for redeploy
    if is_redeploy and not is_user_admin and not bot_info.get('can_people_redeploy', False):
        return await callback_query.answer(
            "You don't have permission to redeploy this bot.", 
            show_alert=True
        )
    
    # Inform user that action is in progress
    await callback_query.answer(f"{action.capitalize()} in progress...", show_alert=False)
    
    try:
        current_text = callback_query.message.text
        
        if is_check:
            # Ping the bot
            await callback_query.edit_message_text(
                current_text + "\n\n[⏳] Checking bot status...",
                reply_markup=callback_query.message.reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Update status
            status = await update_bot_status(bot_name, bot_info)
            
            if status:
                status_text = "✅ ONLINE" if status["is_online"] else "❌ OFFLINE"
                response_time = f"{status['response_time']:.2f}s" if status.get("response_time") else "N/A"
                
                # Different status reports for admin vs user
                if is_user_admin:
                    status_message = (
                        f"\n\n[🔍] Status Check Results:\n"
                        f"Status: {status_text}\n"
                        f"Response: {status.get('status_code', 'N/A')}\n"
                        f"Time: {response_time}\n"
                        f"Checked at: {status['checked_at']}"
                    )
                else:
                    status_message = (
                        f"\n\n[🔍] Status Check Results:\n"
                        f"Status: {status_text}\n"
                        f"Time: {response_time}\n"
                        f"Checked at: {status['checked_at']}"
                    )
                
                await callback_query.edit_message_text(
                    current_text + status_message,
                    reply_markup=callback_query.message.reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await callback_query.edit_message_text(
                    current_text + "\n\n[❌] Failed to check bot status.",
                    reply_markup=callback_query.message.reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        elif is_redeploy:
            # Check if redeploy URL is configured
            if not bot_info.get('redeploy_url'):
                return await callback_query.edit_message_text(
                    current_text + "\n\n[❌] No redeploy URL configured for this bot.",
                    reply_markup=callback_query.message.reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
            # Trigger redeploy
            await callback_query.edit_message_text(
                current_text + "\n\n[⏳] Triggering redeploy...",
                reply_markup=callback_query.message.reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            redeploy_url = bot_info.get('redeploy_url', '')
            pinger = AsyncPinger(
                max_retries=1,
                retry_delay=1.0,
                timeout=bot_info.get('timeout', 30.0),
                concurrent_limit=1
            )
            
            results = await pinger.ping_multiple([redeploy_url])
            result = results[0] if results else None
            await pinger.close() # close the session
            
            if result and result.is_success():
                # Update last deploy time in cache
                cache["last_deploy"][bot_name] = format_timestamp()
                
                # Update bot status after redeploy
                await asyncio.sleep(2)  # Give some time for redeploy to kick in
                await update_bot_status(bot_name, bot_info)
                
                await callback_query.edit_message_text(
                    current_text + "\n\n[✅] Redeploy triggered successfully.",
                    reply_markup=callback_query.message.reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Log to admin channel
                if LOG_CHANNEL and not is_user_admin:
                    try:
                        log_message = (
                            f"[ℹ️] BOT REDEPLOYED\n"
                            f"Bot: {bot_name}\n"
                            f"User: {callback_query.from_user.first_name} (ID: {callback_query.from_user.id})\n"
                            f"Time: {format_timestamp()}"
                        )
                        await bot.send_message(LOG_CHANNEL, log_message)
                    except Exception as e:
                        print(f"Failed to send redeploy log: {e}")
                
            else:
                error_code = result.status.value if result else "Connection failed"
                await callback_query.edit_message_text(
                    current_text + f"\n\n[❌] Failed to trigger redeploy. Error: {error_code}",
                    reply_markup=callback_query.message.reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
    
    except Exception as e:
        # Handle errors
        error_msg = str(e)[:100] if is_user_admin else "An error occurred"
        await callback_query.edit_message_text(
            current_text + f"\n\n[❌] Error: {error_msg}",
            reply_markup=callback_query.message.reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )


@bot.on_callback_query(filters.regex(f"^{PREFIX_REPORT}"))
@verify_callback_initiator
async def handle_report_error(_, callback_query: CallbackQuery):
    """Callback handler for error reporting."""
    bot_name = callback_query.data.replace(PREFIX_REPORT, "")
    
    # Create error type selection buttons
    buttons = []
    for key, error_type in ERROR_TYPES.items():
        buttons.append([
            InlineKeyboardButton(
                f"{key}. {error_type}", 
                callback_data=f"{PREFIX_REPORT_TYPE}{bot_name}_{key}"
            )
        ])
    
    # Add cancel button
    buttons.append([
        InlineKeyboardButton(
            "❌ Cancel", 
            callback_data=f"{PREFIX_PING}{bot_name}"
        )
    ])
    
    await callback_query.edit_message_text(
        f"⚠️ Report an issue with {bot_name}\n\n"
        "Please select the type of issue:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback_query.answer()


@bot.on_callback_query(filters.regex(f"^{PREFIX_REPORT_TYPE}"))
@verify_callback_initiator
async def handle_report_submission(_, callback_query: CallbackQuery):
    """Handle error report submission."""
    # Extract bot name and error type from callback data
    data_parts = callback_query.data.replace(PREFIX_REPORT_TYPE, "").split("_")
    if len(data_parts) != 2:
        return await callback_query.answer("Invalid report data", show_alert=True)
    
    bot_name, error_type_id = data_parts
    error_type = ERROR_TYPES.get(error_type_id, "Unknown issue")
    
    # Get bot configuration
    bots_config = get_bot_config()
    
    # Check if bot exists in config
    if bot_name not in bots_config:
        return await callback_query.answer(
            f"Bot '{bot_name}' not found in configuration.", 
            show_alert=True
        )
    
    # Log the error report to the admin channel
    if LOG_CHANNEL:
        try:
            report_message = (
                f"[⚠️] ERROR REPORT\n"
                f"Bot: {bot_name}\n"
                f"Error Type: {error_type}\n"
                f"Reported by: {callback_query.from_user.first_name} (ID: {callback_query.from_user.id})\n"
                f"Time: {format_timestamp()}"
            )
            await bot.send_message(LOG_CHANNEL, report_message)
        except Exception as e:
            print(f"Failed to send error report: {e}")
    
    # Notify the user that the report has been submitted
    await callback_query.edit_message_text(
        f"✅ Your error report for {bot_name} has been submitted.\n"
        f"Error Type: {error_type}\n\n"
        "Thank you for helping us improve!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◄ Back to Bot Info", callback_data=f"{PREFIX_PING}{bot_name}"),InlineKeyboardButton("FeedBack ^_^",url="https://t.me/Feedback_rkbot?start=start" )]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback_query.answer()
      