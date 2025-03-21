import asyncio
import time
import logging
from typing import Dict, Optional, List, Any, Union
from datetime import datetime
import html
from dataclasses import dataclass, asdict
from enum import Enum, auto

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import MessageNotModified

from TelegramBot.helpers.async_pinger import AsyncPinger, PingResult
from TelegramBot.config import get_config_manager

# Configure logging with proper format
logger = logging.getLogger('background_pinger')


class RedeployStatus(Enum):
    """Enum to represent redeploy status."""
    SUCCESS = auto()
    FAILED = auto()
    COOLDOWN = auto()
    UNAUTHORIZED = auto()


@dataclass
class RedeployInfo:
    """Data class to store redeploy information."""
    time: str
    success: bool
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class BotStatusEntry:
    """Data class to store bot status information."""
    result: PingResult
    timestamp: str
    config: Dict[str, Any]
    last_redeploy: Optional[RedeployInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "result": self.result,
            "timestamp": self.timestamp,
            "config": self.config,
        }
        if self.last_redeploy:
            result["last_redeploy"] = self.last_redeploy.to_dict()
        return result


class BackgroundPinger:
    """
    Background service that pings URLs at specified intervals and updates status messages.
    
    This class monitors the health of specified services (bots) by pinging their URLs
    periodically and updating a status message in a Telegram chat.
    """
    
    def __init__(
        self,
        client: Client,
        admin_chat_id: Optional[int] = None,
        status_message_id: Optional[int] = None,
        ping_concurrency: int = 5
    ):
        """
        Initialize the BackgroundPinger.
        
        Args:
            client: Pyrogram client instance
            admin_chat_id: Chat ID where status messages will be sent
            status_message_id: ID of the message to update with status
            ping_concurrency: Maximum number of concurrent pings
        """
        self.client = client
        self.admin_chat_id = admin_chat_id
        self.status_message_id = status_message_id
        self.pinger = AsyncPinger(
            max_retries=2,
            retry_delay=1.0,
            timeout=30.0,
            concurrent_limit=ping_concurrency
        )
        
        # Get the config manager instance
        self.config_manager = get_config_manager()
        
        self.running = False
        self.tasks: List[asyncio.Task] = []
        self.last_results: Dict[str, BotStatusEntry] = {}
        self.update_lock = asyncio.Lock()
        
        # Create task tracking dictionary
        self.bot_tasks: Dict[str, asyncio.Task] = {}
        
        # Message update throttling
        self.last_message_update = 0
        self.message_update_interval = 5  # seconds

    async def ping_bot(self, bot_config: Dict[str, Any]) -> Optional[PingResult]:
        """
        Ping a bot URL and return the result.
        
        Args:
            bot_config: Bot configuration dictionary
            
        Returns:
            PingResult if successful, None otherwise
        """
        url = bot_config.get("url", "")
        if not url:
            logger.warning(f"No URL provided for bot: {bot_config.get('name', 'unknown')}")
            return None
            
        try:
            results = await self.pinger.ping_multiple([url])
            return results[0] if results else None
        except Exception as e:
            logger.error(f"Error pinging {url}: {e}", exc_info=True)
            return None

    async def ping_and_update(self, bot_config: Dict[str, Any]):
        """
        Continuously ping a bot and update its status.
        
        Args:
            bot_config: Bot configuration dictionary
        """
        url = bot_config.get("url", "")
        bot_name = bot_config.get("name", url)
        ping_interval = bot_config.get("ping_interval", 300)
        
        logger.info(f"Starting background ping for {bot_name} ({url}) every {ping_interval} seconds")
        
        consecutive_errors = 0
        max_consecutive_errors = 3
        backoff_multiplier = 1.0
        
        while self.running:
            try:
                # Check if bot config has been updated
                fresh_config = self.config_manager.get_bot_config(bot_name)
                if fresh_config:
                    # Update local config with fresh values
                    for key, value in fresh_config.items():
                        bot_config[key] = value
                    
                    # Check if ping interval changed
                    new_interval = bot_config.get("ping_interval", 300)
                    if new_interval != ping_interval:
                        logger.info(f"Ping interval for {bot_name} changed from {ping_interval}s to {new_interval}s")
                        ping_interval = new_interval
                
                start_time = time.time()
                result = await self.ping_bot(bot_config)
                
                if result:
                    # Reset error counter on successful ping
                    consecutive_errors = 0
                    backoff_multiplier = 1.0
                    
                    # Create status entry
                    entry = BotStatusEntry(
                        result=result,
                        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        config=bot_config,
                    )
                    
                    # Preserve last redeploy info if exists
                    if url in self.last_results and self.last_results[url].last_redeploy:
                        entry.last_redeploy = self.last_results[url].last_redeploy
                    
                    self.last_results[url] = entry
                    
                    # Update status message if needed
                    current_time = time.time()
                    if (self.admin_chat_id and self.status_message_id and 
                            (current_time - self.last_message_update >= self.message_update_interval)):
                        await self.update_status_message()
                        self.last_message_update = current_time
                    
                    # Automatic redeploy logic
                    if (not result.is_success() and 
                            bot_config.get("redeploy_url") and 
                            bot_config.get("auto_redeploy", False)):
                        
                        redeploy_status = await self._check_redeploy_eligibility(url)
                        
                        if redeploy_status == RedeployStatus.SUCCESS:
                            await self.trigger_redeploy(url, automatic=True)
                            logger.info(f"Automatic redeploy triggered for {bot_name}")
                        elif redeploy_status == RedeployStatus.COOLDOWN:
                            logger.info(f"Skipping redeploy for {bot_name} due to cooldown")
                
                elapsed = time.time() - start_time
                sleep_time = max(0.1, ping_interval - elapsed)
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                logger.info(f"Ping task for {bot_name} was cancelled")
                break
            except Exception as e:
                logger.error(f"Error in ping loop for {bot_name}: {e}", exc_info=True)
                
                # Implement exponential backoff for errors
                consecutive_errors += 1
                if consecutive_errors > max_consecutive_errors:
                    backoff_multiplier = min(backoff_multiplier * 1.5, 5.0)  # Cap at 5x
                
                # Use backoff for the sleep time
                adjusted_interval = ping_interval * backoff_multiplier
                logger.warning(f"Using backoff for {bot_name}: sleeping for {adjusted_interval:.1f}s")
                await asyncio.sleep(adjusted_interval)

    async def _check_redeploy_eligibility(self, url: str) -> RedeployStatus:
        """
        Check if a bot is eligible for redeploy.
        
        Args:
            url: Bot URL
            
        Returns:
            RedeployStatus enum indicating eligibility
        """
        if url not in self.last_results:
            return RedeployStatus.FAILED
            
        entry = self.last_results[url]
        if entry.last_redeploy:
            try:
                last_time = entry.last_redeploy.time
                last_time_dt = datetime.strptime(last_time, "%Y-%m-%d %H:%M:%S")
                time_since_last = (datetime.now() - last_time_dt).total_seconds()
                cooldown = entry.config.get("redeploy_cooldown", 300)  # Default 5-minute cooldown
                
                if time_since_last < cooldown:
                    return RedeployStatus.COOLDOWN
            except ValueError:
                logger.warning(f"Invalid last_redeploy time format: {last_time}")
        
        return RedeployStatus.SUCCESS
    
    def get_inline_keyboard(self) -> Optional[InlineKeyboardMarkup]:
        """
        Generate inline keyboard for status message.
        
        Returns:
            InlineKeyboardMarkup or None if no bots are configured
        """
        if not self.last_results:
            return None

        bots = sorted(
            self.last_results.items(),
            key=lambda x: x[1].config.get("name", x[0])
        )

        buttons = []
        for url, data in bots:
            config = data.config
            bot_name = config.get("name", url)
            url_bot = config.get("url_bot")
            if url_bot:
                buttons.append(InlineKeyboardButton(bot_name, url=url_bot))

        if not buttons:
            return None

        # Arrange buttons in rows of 2
        keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        
        # Add control buttons at the bottom
        control_buttons = []
        control_buttons.append(InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status"))
        control_buttons.append(InlineKeyboardButton("⚙️ Config", callback_data="manage_config"))
        keyboard.append(control_buttons)
        
        return InlineKeyboardMarkup(keyboard)

    def format_status_message(self) -> str:
        """
        Format the status message with current bot statuses.
        
        Returns:
            Formatted status message string
        """
        message = (
            "╭━━━━━━━━━━━━━━━━━━━━━╮\n"
            "│ 📊 Bot Status Report                    │\n"
            "╰━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        )

        if not self.last_results:
            message += "◇ No bots have been checked yet.\n"
        else:
            bots = sorted(
                self.last_results.items(),
                key=lambda x: x[1].config.get("name", x[0])
            )

            for url, data in bots:
                result = data.result
                timestamp = data.timestamp
                config = data.config
                bot_name = config.get("name", url)
                last_redeploy = data.last_redeploy

                status_emoji = "●" if result.is_success() else "○"
                status_text = (
                    f"{result.status_code}" if result.is_success() else f"{result.status.value}"
                )
                response_time = (
                    f"{result.response_time:.2f}s" if result.response_time else "N/A"
                )

                # Escape HTML special characters
                bot_name = html.escape(str(bot_name))
                status_text = html.escape(str(status_text))
                response_time = html.escape(str(response_time))
                timestamp = html.escape(str(timestamp))

                message += (
                    f"◇ <b>{bot_name}</b>\n"
                    f"  ○ 𝚂𝚝𝚊𝚝𝚞𝚜: [{status_emoji}] <i>{status_text}</i>\n"
                    f"  ○ 𝚁𝚎𝚜𝚙𝚘𝚗𝚜𝚎 𝚃𝚒𝚖𝚎: <i>{response_time}</i>\n"
                    f"  ○ 𝙻𝚊𝚜𝚝 𝙲𝚑𝚎𝚌𝚔: <i>{timestamp}</i>\n"
                )

                # Add redeploy info if available
                if last_redeploy:
                    redeploy_time = html.escape(str(last_redeploy.time))
                    redeploy_status = "Success" if last_redeploy.success else "Failed"
                    reason = f" ({html.escape(last_redeploy.reason)})" if last_redeploy.reason else ""
                    message += (
                        f"  ○ <blockquote>𝚁𝚎𝚍𝚎𝚙𝚕𝚘𝚢: {redeploy_status}{reason} at {redeploy_time}</blockquote>\n"
                    )

                message += "\n"

        return message.rstrip()

    async def update_status_message(self):
        """Update the status message in the admin chat."""
        if not self.admin_chat_id or not self.status_message_id:
            return

        try:
            async with self.update_lock:
                message_text = self.format_status_message()
                if len(message_text) > 4096:
                    message_text = message_text[:4093] + "..."
                inline_keyboard = self.get_inline_keyboard()

                await self.client.edit_message_text(
                    chat_id=self.admin_chat_id,
                    message_id=self.status_message_id,
                    text=message_text,
                    reply_markup=inline_keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            logger.debug("Updated status message")
        except MessageNotModified:
            # It's normal if message hasn't changed
            pass
        except Exception as e:
            logger.error(f"Failed to update status message: {e}")
            if "parse mode" in str(e).lower():
                try:
                    # Try without parse mode as fallback
                    await self.client.edit_message_text(
                        chat_id=self.admin_chat_id,
                        message_id=self.status_message_id,
                        text=message_text,
                        reply_markup=inline_keyboard,
                        parse_mode=None
                    )
                except Exception as fallback_e:
                    logger.error(f"Fallback update also failed: {fallback_e}")

    async def trigger_redeploy(self, url: str, automatic: bool = False) -> bool:
        """
        Trigger a redeploy for a bot.
        
        Args:
            url: Bot URL
            automatic: Whether this is an automatic redeploy
            
        Returns:
            True if successful, False otherwise
        """
        if url not in self.last_results:
            logger.warning(f"Cannot redeploy unknown URL: {url}")
            return False
            
        bot_data = self.last_results[url]
        config = bot_data.config
        redeploy_url = config.get("redeploy_url")
        
        if not redeploy_url:
            logger.warning(f"No redeploy URL for {config.get('name', url)}")
            return False
            
        if not automatic and not config.get("can_people_redeploy", False):
            logger.info(f"Redeploy skipped for {config.get('name', url)}: can_people_redeploy is False")
            return False
            
        try:
            result = await self.pinger.ping_multiple([redeploy_url])
            success = result[0].is_success() if result else False
            redeploy_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            redeploy_info = RedeployInfo(
                time=redeploy_time,
                success=success,
                reason="Auto" if automatic else "Manual"
            )
            
            self.last_results[url].last_redeploy = redeploy_info
            
            logger.info(
                f"Redeploy triggered for {config.get('name', url)}: "
                f"{'Success' if success else 'Failed'} at {redeploy_time}"
            )
            
            if self.admin_chat_id and self.status_message_id:
                await self.update_status_message()
                
            return success
        except Exception as e:
            logger.error(f"Error triggering redeploy for {config.get('name', url)}: {e}")
            return False

    async def start(self):
        """Start the background pinger with the current configuration."""
        if self.running:
            logger.warning("Background pinger is already running")
            return

        self.running = True
        
        # Get all bot configurations from the config manager
        bot_configs = self.config_manager.get_all_bots()
        
        for bot_name, bot_config in bot_configs.items():
            # Skip bots marked as disabled
            if bot_config.get("disabled", False):
                logger.info(f"Skipping disabled bot: {bot_name}")
                continue
                
            task = asyncio.create_task(self.ping_and_update(bot_config))
            self.tasks.append(task)
            self.bot_tasks[bot_name] = task

        logger.info(f"Started background pinger with {len(self.tasks)} bots")

    async def stop(self):
        """Stop the background pinger."""
        if not self.running:
            return

        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
                
        # Wait for tasks to finish
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            
        self.tasks = []
        self.bot_tasks = {}
        await self.pinger.close()  # Close the session 
        logger.info("Stopped background pinger")

    async def reload_config(self):
        """Reload the configuration and restart the pinger."""
        # Force config manager to reload
        self.config_manager.reload_config()
        
        # Restart the pinger with the new configuration
        await self.stop()
        await self.start()
        logger.info("Reloaded configuration and restarted background pinger")
        
    async def add_or_update_bot(self, bot_name: str, bot_config: Dict[str, Any]) -> bool:
        """
        Add or update a bot in the configuration and start monitoring it.
        
        Args:
            bot_name: Name of the bot
            bot_config: Bot configuration
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate required fields
            if not bot_config.get("url"):
                logger.error(f"Missing required URL for bot {bot_name}")
                return False
                
            # Update the config
            bot_config["name"] = bot_name
            success = self.config_manager.update_bot_config(bot_name, bot_config)
            if not success:
                return False
                
            # Save changes to disk
            self.config_manager.save_config()
            
            # If already running, stop the current task for this bot and start a new one
            if self.running:
                if bot_name in self.bot_tasks and not self.bot_tasks[bot_name].done():
                    self.bot_tasks[bot_name].cancel()
                    # Wait for task to cancel
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(self.bot_tasks[bot_name], return_exceptions=True), 
                            timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout waiting for task to cancel for bot {bot_name}")
                
                # Start a new task for this bot
                task = asyncio.create_task(self.ping_and_update(bot_config))
                self.tasks.append(task)
                self.bot_tasks[bot_name] = task
                logger.info(f"Started monitoring bot: {bot_name}")
            
            return True
        except Exception as e:
            logger.error(f"Error adding/updating bot {bot_name}: {e}", exc_info=True)
            return False
            
    async def remove_bot(self, bot_name: str) -> bool:
        """
        Remove a bot from the configuration and stop monitoring it.
        
        Args:
            bot_name: Name of the bot
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Stop monitoring this bot if running
            if bot_name in self.bot_tasks and self.running:
                if not self.bot_tasks[bot_name].done():
                    self.bot_tasks[bot_name].cancel()
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(self.bot_tasks[bot_name], return_exceptions=True), 
                            timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout waiting for task to cancel for bot {bot_name}")
                
                # Remove from tasks list
                if self.bot_tasks[bot_name] in self.tasks:
                    self.tasks.remove(self.bot_tasks[bot_name])
                del self.bot_tasks[bot_name]
            
            # Remove from config
            success = self.config_manager.remove_bot_config(bot_name)
            if success:
                # Save changes to disk
                self.config_manager.save_config()
                logger.info(f"Removed bot: {bot_name}")
            
            # Remove from last results
            urls_to_remove = []
            for url, entry in self.last_results.items():
                if entry.config.get("name") == bot_name:
                    urls_to_remove.append(url)
            
            for url in urls_to_remove:
                del self.last_results[url]
            
            return success
        except Exception as e:
            logger.error(f"Error removing bot {bot_name}: {e}", exc_info=True)
            return False
            
    async def get_bot_status(self, bot_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the current status of all bots or a specific bot.
        
        Args:
            bot_name: Optional name of the bot to get status for
            
        Returns:
            Dictionary with bot statuses
        """
        result = {}
        
        if bot_name:
            # Get status for a specific bot
            for url, entry in self.last_results.items():
                if entry.config.get("name") == bot_name:
                    result[bot_name] = entry.to_dict()
                    break
        else:
            # Get status for all bots
            for url, entry in self.last_results.items():
                bot_name = entry.config.get("name", url)
                result[bot_name] = entry.to_dict()
                
        return result