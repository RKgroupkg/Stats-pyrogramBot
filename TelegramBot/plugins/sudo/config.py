from pyrogram import filters
from pyrogram.enums import ParseMode, ChatType
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
import json
import logging
import re
import time
from typing import Dict, List, Any, Union, Optional

from TelegramBot import bot
from TelegramBot.database import database
from TelegramBot.config import get_config_manager, OWNER_USERID, SUDO_USERID

# Configure logging
logger = logging.getLogger("config_editor")

# Constants
CONFIG_TIMEOUT = 600  # 10 minutes timeout for config sessions
MAX_BUTTONS_PER_ROW = 3
PAGE_SIZE = 8  # Number of bots to show per page

# Active editor sessions: {user_id: session_data}
active_sessions = {}

# Get config manager instance
config_manager = get_config_manager()

# Helper Functions
def is_authorized(user_id: int) -> bool:
    """Check if a user ID is authorized to use the config editor."""
    if SUDO_USERID is None:
        sudo_users = []
    elif isinstance(SUDO_USERID, list):
        sudo_users = SUDO_USERID
    else:
        sudo_users = [SUDO_USERID]
    
    # Ensure OWNER_USERID is valid
    owner_id = OWNER_USERID if OWNER_USERID is not None else 0
    
    authorized_users = [owner_id] + sudo_users
    return user_id in authorized_users
    

def get_main_menu(page: int = 0) -> InlineKeyboardMarkup:
    """Generate the main config menu with pagination."""
    all_bots = config_manager.get_all_bots()
    bot_names = sorted(list(all_bots.keys()))
    
    # Paginate the bot list
    total_pages = max(1, (len(bot_names) + PAGE_SIZE - 1) // PAGE_SIZE)
    start_idx = page * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, len(bot_names))
    current_page_bots = bot_names[start_idx:end_idx]
    
    keyboard = []
    
    # Add bot buttons
    for i in range(0, len(current_page_bots), MAX_BUTTONS_PER_ROW):
        row = []
        for bot_name in current_page_bots[i:i+MAX_BUTTONS_PER_ROW]:
            row.append(
                InlineKeyboardButton(
                    bot_name, 
                    callback_data=f"config_view_{bot_name}"
                )
            )
        keyboard.append(row)
    
    # Add navigation and action buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"config_page_{page-1}"))
    
    nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="config_noop"))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"config_page_{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    # Add action buttons
    keyboard.append([
        InlineKeyboardButton("➕ Add Bot", callback_data="config_add_new"),
        InlineKeyboardButton("🔄 Refresh", callback_data="config_refresh")
    ])
    
    keyboard.append([
        InlineKeyboardButton("❌ Close", callback_data="config_close")
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_bot_menu(bot_name: str) -> InlineKeyboardMarkup:
    """Generate the menu for a specific bot."""
    keyboard = [
        [
            InlineKeyboardButton("✏️ Edit Config", callback_data=f"config_edit_{bot_name}"),
            InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"config_delete_{bot_name}")
        ],
        [
            InlineKeyboardButton("◀️ Back", callback_data="config_main"),
            InlineKeyboardButton("❌ Close", callback_data="config_close")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_confirm_delete_menu(bot_name: str) -> InlineKeyboardMarkup:
    """Generate the confirmation menu for bot deletion."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"config_confirm_delete_{bot_name}"),
            InlineKeyboardButton("❌ No, Cancel", callback_data=f"config_view_{bot_name}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_edit_menu(bot_name: str) -> InlineKeyboardMarkup:
    """Generate the edit menu for a bot's configuration."""
    bot_config = config_manager.get_bot_config(bot_name)
    if not bot_config:
        return get_main_menu()
    
    keyboard = []
    
    # Add fields as buttons
    for key, value in bot_config.items():
        if key == "name":  # Skip the name field added by get_bot_config
            continue
        
        # Truncate value for display if needed
        display_value = str(value)
        if len(display_value) > 15:
            display_value = display_value[:12] + "..."
        
        keyboard.append([
            InlineKeyboardButton(
                f"{key}: {display_value}", 
                callback_data=f"config_edit_field_{bot_name}_{key}"
            )
        ])
    
    # Add action buttons
    keyboard.append([
        InlineKeyboardButton("➕ Add Field", callback_data=f"config_add_field_{bot_name}"),
    ])
    
    keyboard.append([
        InlineKeyboardButton("💾 Save", callback_data=f"config_save_{bot_name}"),
        InlineKeyboardButton("◀️ Back", callback_data=f"config_view_{bot_name}"),
    ])
    
    return InlineKeyboardMarkup(keyboard)

def format_bot_config(bot_name: str) -> str:
    """Format a bot's configuration for display."""
    bot_config = config_manager.get_bot_config(bot_name)
    if not bot_config:
        return f"⚠️ Bot '{bot_name}' not found!"
    
    text = f"🤖 **Bot Configuration: {bot_name}**\n\n"
    
    # Format each field
    for key, value in sorted(bot_config.items()):
        if key == "name":  # Skip the name field added by get_bot_config
            continue
        
        # Format based on type
        if isinstance(value, dict):
            text += f"**{key}**: `{json.dumps(value, indent=2)}`\n"
        elif isinstance(value, list):
            text += f"**{key}**: `{json.dumps(value)}`\n"
        else:
            text += f"**{key}**: `{value}`\n"
    
    return text

def cleanup_expired_sessions():
    """Remove expired editor sessions."""
    current_time = time.time()
    expired_keys = [
        user_id for user_id, session in active_sessions.items()
        if current_time - session.get("timestamp", 0) > CONFIG_TIMEOUT
    ]
    
    for user_id in expired_keys:
        del active_sessions[user_id]

def parse_value(value_str: str) -> Any:
    """Parse a string value into appropriate Python type."""
    value_str = value_str.strip()
    
    try:
        # Try to parse as JSON first
        return json.loads(value_str)
    except json.JSONDecodeError:
        # Handle other value types
        if value_str.lower() == "true":
            return True
        elif value_str.lower() == "false":
            return False
        elif value_str.isdigit():
            return int(value_str)
        elif value_str.replace(".", "", 1).isdigit() and value_str.count(".") == 1:
            return float(value_str)
        else:
            return value_str  # Keep as string

async def handle_unauthorized(message: Message) -> bool:
    """Handle unauthorized access attempt."""
    user_id = message.from_user.id
    if not is_authorized(user_id):
        await message.reply("⚠️ You are not authorized to use this command.")
        return True
    return False

# Command handlers
@bot.on_message(filters.command("config"))
async def config_command(_, message: Message):
    """Handle the /config command to start the configuration process."""
    user_id = message.from_user.id
    
    # Check if user is authorized
    if await handle_unauthorized(message):
        return
    
    # Start a new config session
    active_sessions[user_id] = {
        "timestamp": time.time(),
        "current_action": "main_menu",
        "data": {},
        "message_id": None,
        "chat_id": message.chat.id
    }
    
    # Send the main menu
    response = await message.reply(
        "🛠️ **Bot Configuration Manager**\n\n"
        "Select a bot to view or edit its configuration:",
        reply_markup=get_main_menu()
    )
    
    # Store the message ID for future updates
    active_sessions[user_id]["message_id"] = response.id

# Callback query handlers
@bot.on_callback_query(filters.regex("^config_"))
async def config_callback_handler(_, callback: CallbackQuery):
    """Handle all configuration-related callbacks."""
    user_id = callback.from_user.id
    query_data = callback.data
    
    # Check if user is authorized
    if not is_authorized(user_id):
        return await callback.answer("⚠️ You are not authorized to use this feature.", show_alert=True)
    
    # Initialize or update the session
    if user_id not in active_sessions:
        active_sessions[user_id] = {
            "timestamp": time.time(),
            "current_action": "main_menu",
            "data": {},
            "message_id": callback.message.id,
            "chat_id": callback.message.chat.id
        }
    else:
        active_sessions[user_id]["timestamp"] = time.time()
        active_sessions[user_id]["message_id"] = callback.message.id
        active_sessions[user_id]["chat_id"] = callback.message.chat.id
    
    session = active_sessions[user_id]
    cleanup_expired_sessions()
    
    # Handle different callback actions
    try:
        if query_data == "config_main":
            # Main menu
            await callback.edit_message_text(
                "🛠️ **Bot Configuration Manager**\n\n"
                "Select a bot to view or edit its configuration:",
                reply_markup=get_main_menu()
            )
            session["current_action"] = "main_menu"
            
        elif query_data == "config_refresh":
            # Refresh the config
            config_manager.reload_config()
            await callback.answer("✅ Configuration reloaded successfully!")
            await callback.edit_message_text(
                "🛠️ **Bot Configuration Manager**\n\n"
                "Select a bot to view or edit its configuration:",
                reply_markup=get_main_menu()
            )
            
        elif query_data == "config_close":
            # Close the config editor
            await callback.edit_message_text("❌ Configuration manager closed.")
            if user_id in active_sessions:
                del active_sessions[user_id]
                
        elif query_data.startswith("config_page_"):
            # Pagination
            page = int(query_data.split("_")[-1])
            await callback.edit_message_text(
                "🛠️ **Bot Configuration Manager**\n\n"
                "Select a bot to view or edit its configuration:",
                reply_markup=get_main_menu(page)
            )
            
        elif query_data.startswith("config_view_"):
            # View bot config
            bot_name = query_data[12:]
            await callback.edit_message_text(
                format_bot_config(bot_name),
                reply_markup=get_bot_menu(bot_name),
                parse_mode=ParseMode.MARKDOWN
            )
            session["current_action"] = "view_bot"
            session["data"]["bot_name"] = bot_name
            
        elif query_data.startswith("config_edit_"):
            # Edit bot config
            if query_data.startswith("config_edit_field_"):
                # Edit specific field
                parts = query_data.split("_")
                bot_name = parts[3]
                field_name = parts[4]
                
                session["current_action"] = "edit_field"
                session["data"]["bot_name"] = bot_name
                session["data"]["field_name"] = field_name
                
                bot_config = config_manager.get_bot_config(bot_name)
                current_value = bot_config.get(field_name, "")
                
                await callback.edit_message_text(
                    f"🔄 **Editing '{field_name}' for bot '{bot_name}'**\n\n"
                    f"Current value: `{current_value}`\n\n"
                    "Please send a new value for this field. Send:\n"
                    "- JSON for objects and arrays\n"
                    "- Plain text for strings\n"
                    "- Number for numeric values\n"
                    "- 'true' or 'false' for booleans\n\n"
                    "Type /cancel to cancel editing.",
                    parse_mode=ParseMode.MARKDOWN
                )
                
            else:
                # Edit bot (show all fields)
                bot_name = query_data.split("_")[-1]
                await callback.edit_message_text(
                    f"✏️ **Editing Bot: {bot_name}**\n\n"
                    "Select a field to edit or add a new field:",
                    reply_markup=get_edit_menu(bot_name),
                    parse_mode=ParseMode.MARKDOWN
                )
                session["current_action"] = "edit_bot"
                session["data"]["bot_name"] = bot_name
                
        elif query_data.startswith("config_delete_"):
            # Delete bot confirmation
            bot_name = query_data[14:]
            await callback.edit_message_text(
                f"⚠️ **Are you sure you want to delete bot '{bot_name}'?**\n\n"
                "This action cannot be undone.",
                reply_markup=get_confirm_delete_menu(bot_name),
                parse_mode=ParseMode.MARKDOWN
            )
            session["current_action"] = "confirm_delete"
            session["data"]["bot_name"] = bot_name
            
        elif query_data.startswith("config_confirm_delete_"):
            # Execute bot deletion
            bot_name = query_data[21:]
            success = config_manager.remove_bot_config(bot_name)
            
            if success:
                config_manager.save_config()
                await callback.answer(f"✅ Bot '{bot_name}' deleted successfully!")
                await callback.edit_message_text(
                    "🛠️ **Bot Configuration Manager**\n\n"
                    "Select a bot to view or edit its configuration:",
                    reply_markup=get_main_menu()
                )
                session["current_action"] = "main_menu"
            else:
                await callback.answer(f"❌ Failed to delete bot '{bot_name}'!", show_alert=True)
                
        elif query_data.startswith("config_add_field_"):
            # Add a new field to bot
            bot_name = query_data[17:]
            
            session["current_action"] = "add_field"
            session["data"]["bot_name"] = bot_name
            
            await callback.edit_message_text(
                f"➕ **Adding a new field to bot '{bot_name}'**\n\n"
                "Please send the field name.\n\n"
                "Type /cancel to cancel.",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif query_data.startswith("config_save_"):
            # Save bot config
            bot_name = query_data[12:]
            success = config_manager.save_config()
            
            if success:
                await callback.answer("✅ Configuration saved successfully!")
                await callback.edit_message_text(
                    format_bot_config(bot_name),
                    reply_markup=get_bot_menu(bot_name),
                    parse_mode=ParseMode.MARKDOWN
                )
                session["current_action"] = "view_bot"
            else:
                await callback.answer("❌ Failed to save configuration!", show_alert=True)
                
        elif query_data == "config_add_new":
            # Add a new bot
            session["current_action"] = "add_bot_name"
            
            await callback.edit_message_text(
                "➕ **Adding a new bot**\n\n"
                "Please send the bot name.\n\n"
                "Type /cancel to cancel.",
                parse_mode=ParseMode.MARKDOWN
            )
            
        elif query_data == "config_noop":
            # No operation (used for page number display)
            await callback.answer()
            
        else:
            # Unknown callback
            await callback.answer("⚠️ Unknown action!", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error handling callback: {e}", exc_info=True)
        await callback.answer(f"❌ Error: {str(e)[:200]}", show_alert=True)

# Message filter for catching configuration input
def config_filter(_, __, message):
    """Filter messages for the config editor."""
    if not message.from_user:
        return False
        
    user_id = message.from_user.id
    
    # Only process messages from users with active sessions
    if user_id not in active_sessions:
        return False
    
    # Skip command messages except /cancel
    if message.text and message.text.startswith('/') and not message.text.startswith('/cancel'):
        return False
    
    # Don't process messages in groups unless it's a reply to the bot's message
    if message.chat.type != ChatType.PRIVATE:
        session = active_sessions.get(user_id, {})
        bot_message_id = session.get("message_id")
        if not message.reply_to_message or message.reply_to_message.id != bot_message_id:
            return False
    
    return True

# Message handlers for interactive editing
@bot.on_message(filters.create(config_filter))
async def handle_config_message(_, message: Message):
    """Handle messages for the config editor."""
    user_id = message.from_user.id
    
    # Safety check for session existence
    if user_id not in active_sessions:
        return
    
    # Check if message is /cancel
    if message.text and message.text.startswith('/cancel'):
        return await handle_cancel_command(_, message)
    
    session = active_sessions[user_id]
    session["timestamp"] = time.time()
    
    # Create a response function that works in both private and group chats
    async def send_response(text, reply_markup=None):
        if message.chat.type == ChatType.PRIVATE:
            return await message.reply(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            # In groups, edit the original message or reply to it
            if session.get("message_id"):
                try:
                    return await bot.edit_message_text(
                        message.chat.id,
                        session["message_id"],
                        text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    return await message.reply(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                return await message.reply(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    try:
        if session["current_action"] == "edit_field":
            # Handle field editing
            bot_name = session["data"]["bot_name"]
            field_name = session["data"]["field_name"]
            
            # Get the current bot config
            bot_config = config_manager.get_bot_config(bot_name).copy()
            if "name" in bot_config:
                del bot_config["name"]  # Remove name field added by get_bot_config
            
            # Parse the new value
            new_value = message.text.strip()
            try:
                parsed_value = parse_value(new_value)
                bot_config[field_name] = parsed_value
            except Exception as e:
                return await send_response(
                    f"⚠️ Error parsing value: {str(e)}\n\n"
                    "Please try again or type /cancel to cancel."
                )
            
            # Update the configuration
            success = config_manager.update_bot_config(bot_name, bot_config)
            
            if success:
                # Return to the edit menu
                response = await send_response(
                    f"✅ Field '{field_name}' updated successfully!",
                    reply_markup=get_edit_menu(bot_name)
                )
                if hasattr(response, 'id'):
                    session["message_id"] = response.id
                session["current_action"] = "edit_bot"
            else:
                await send_response(
                    f"❌ Failed to update field '{field_name}'!",
                    reply_markup=get_edit_menu(bot_name)
                )
                
        elif session["current_action"] == "add_field":
            # Handle adding a new field (step 1: field name)
            bot_name = session["data"]["bot_name"]
            field_name = message.text.strip()
            
            # Validate field name
            if not re.match(r'^[a-zA-Z0-9_]+$', field_name):
                return await send_response(
                    "⚠️ Invalid field name. Use only letters, numbers, and underscores.\n\n"
                    "Please try again or type /cancel to cancel."
                )
            
            # Store field name and ask for value
            session["data"]["field_name"] = field_name
            session["current_action"] = "add_field_value"
            
            response = await send_response(
                f"👍 Field name '{field_name}' accepted.\n\n"
                f"Now, please send the value for field '{field_name}'.\n\n"
                "- JSON for objects and arrays\n"
                "- Plain text for strings\n"
                "- Number for numeric values\n"
                "- 'true' or 'false' for booleans\n\n"
                "Type /cancel to cancel."
            )
            if hasattr(response, 'id'):
                session["message_id"] = response.id
            
        elif session["current_action"] == "add_field_value":
            # Handle adding a new field (step 2: field value)
            bot_name = session["data"]["bot_name"]
            field_name = session["data"]["field_name"]
            
            # Get the current bot config
            bot_config = config_manager.get_bot_config(bot_name).copy()
            if "name" in bot_config:
                del bot_config["name"]  # Remove name field added by get_bot_config
            
            # Parse the new value
            new_value = message.text.strip()
            try:
                parsed_value = parse_value(new_value)
                bot_config[field_name] = parsed_value
            except Exception as e:
                return await send_response(
                    f"⚠️ Error parsing value: {str(e)}\n\n"
                    "Please try again or type /cancel to cancel."
                )
            
            # Update the configuration
            success = config_manager.update_bot_config(bot_name, bot_config)
            
            if success:
                # Return to the edit menu
                response = await send_response(
                    f"✅ Field '{field_name}' added successfully!",
                    reply_markup=get_edit_menu(bot_name)
                )
                if hasattr(response, 'id'):
                    session["message_id"] = response.id
                session["current_action"] = "edit_bot"
            else:
                await send_response(
                    f"❌ Failed to add field '{field_name}'!",
                    reply_markup=get_edit_menu(bot_name)
                )
                
        elif session["current_action"] == "add_bot_name":
            # Handle adding a new bot (step 1: bot name)
            bot_name = message.text.strip()
            
            # Validate bot name
            if not re.match(r'^[a-zA-Z0-9_]+$', bot_name):
                return await send_response(
                    "⚠️ Invalid bot name. Use only letters, numbers, and underscores.\n\n"
                    "Please try again or type /cancel to cancel."
                )
            
            # Check if bot already exists
            if config_manager.get_bot_config(bot_name):
                return await send_response(
                    f"⚠️ A bot with the name '{bot_name}' already exists.\n\n"
                    "Please choose a different name or type /cancel to cancel."
                )
            
            # Store bot name and proceed to config creation
            session["data"]["bot_name"] = bot_name
            session["current_action"] = "add_bot_config"
            
            response = await send_response(
                f"👍 Bot name '{bot_name}' accepted.\n\n"
                f"Now, please send the initial configuration for bot '{bot_name}' as JSON.\n\n"
                "Example:\n"
                "```\n"
                "{\n"
                '  "token": "YOUR_BOT_TOKEN",\n'
                '  "prefix": "!",\n'
                '  "enabled": true\n'
                "}\n"
                "```\n\n"
                "Or send 'empty' to create an empty configuration.\n"
                "Type /cancel to cancel."
            )
            if hasattr(response, 'id'):
                session["message_id"] = response.id
            
        elif session["current_action"] == "add_bot_config":
            # Handle adding a new bot (step 2: initial config)
            bot_name = session["data"]["bot_name"]
            config_text = message.text.strip()
            
            if config_text.lower() == "empty":
                # Create empty config
                bot_config = {}
            else:
                # Parse JSON config
                try:
                    bot_config = json.loads(config_text)
                    if not isinstance(bot_config, dict):
                        return await send_response(
                            "⚠️ Configuration must be a JSON object (dictionary).\n\n"
                            "Please try again or type /cancel to cancel."
                        )
                except json.JSONDecodeError as e:
                    return await send_response(
                        f"⚠️ Invalid JSON: {str(e)}\n\n"
                        "Please try again or type /cancel to cancel."
                    )
            
            # Update the configuration
            success = config_manager.update_bot_config(bot_name, bot_config)
            
            if success:
                config_manager.save_config()
                # Return to the main menu
                response = await send_response(
                    f"✅ Bot '{bot_name}' added successfully!",
                    reply_markup=get_main_menu()
                )
                if hasattr(response, 'id'):
                    session["message_id"] = response.id
                session["current_action"] = "main_menu"
            else:
                await send_response(
                    f"❌ Failed to add bot '{bot_name}'!\n\n"
                    "Please try again or type /cancel to cancel."
                )
    
    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await send_response(f"❌ Error: {str(e)[:200]}")

# Cancel command handler
@bot.on_message(filters.command("cancel"))
async def handle_cancel_command(_, message: Message):
    """Cancel the current config action."""
    user_id = message.from_user.id
    
    # Check if user has an active session
    if user_id not in active_sessions:
        # Only respond in private chats if there's no active session
        if message.chat.type == ChatType.PRIVATE:
            return await message.reply("⚠️ No active configuration session to cancel.")
        return
    
    session = active_sessions[user_id]
    
    # Create a response function that works in both private and group chats
    async def send_cancel_response(text, reply_markup=None):
        if message.chat.type == ChatType.PRIVATE:
            return await message.reply(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            # In groups, edit the original message
            if session.get("message_id") and session.get("chat_id") == message.chat.id:
                try:
                    return await bot.edit_message_text(
                        message.chat.id,
                        session["message_id"],
                        text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    return await message.reply(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
            else:
                return await message.reply(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    # Return to main menu
    response = await send_cancel_response(
        "🛠️ **Bot Configuration Manager**\n\n"
        "Action cancelled. Select a bot to view or edit its configuration:",
        reply_markup=get_main_menu()
    )
    
    if hasattr(response, 'id'):
        session["message_id"] = response.id
    session["current_action"] = "main_menu"
    session["data"] = {}