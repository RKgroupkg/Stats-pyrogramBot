import json
import os
import logging
from typing import Dict, Any, Optional
import threading
import time
from functools import lru_cache

# Configure logging
logger = logging.getLogger("config_manager")

class ConfigManager:
    """
    A thread-safe singleton class for managing bot configurations.
    This class loads configurations from a JSON file and provides
    methods to access and modify them.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, config_path: str = "bot_config.json", auto_reload: bool = False, reload_interval: int = 300):
        """
        Initialize the ConfigManager.
        
        Args:
            config_path: Path to the configuration file
            auto_reload: Whether to automatically reload the configuration periodically
            reload_interval: Time interval in seconds for auto-reload
        """
        # Only initialize once
        if self._initialized:
            return
            
        self._initialized = True
        self.config_path = config_path
        self.auto_reload = auto_reload
        self.reload_interval = reload_interval
        self._config = {}
        self._last_modified = 0
        self._reload_thread = None
        self._running = False
        self._config_lock = threading.Lock()
        
        # Load the initial configuration
        self.reload_config()
        
        # Start auto-reload if enabled
        if self.auto_reload:
            self._start_auto_reload()
    
    def _load_config_from_file(self) -> Dict[str, Any]:
        """Load configuration from the file."""
        try:
            if not os.path.exists(self.config_path):
                logger.error(f"Configuration file not found: {self.config_path}")
                return {"bot_aliases": {}}
                
            # Check if file was modified
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime <= self._last_modified:
                logger.debug("Configuration file not modified since last load")
                return self._config
                
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                
            # Update the last modified time
            self._last_modified = current_mtime
            
            # Ensure the config has the expected structure
            if "bot_aliases" not in config:
                # If the root object directly contains bot configs, wrap them
                config = {"bot_aliases": config}
                
            logger.info(f"Loaded configuration with {len(config['bot_aliases'])} bots")
            return config
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse configuration file: {e}")
            return {"bot_aliases": {}}
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return {"bot_aliases": {}}
    
    def reload_config(self) -> bool:
        """
        Reload the configuration from the file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            new_config = self._load_config_from_file()
            with self._config_lock:
                self._config = new_config
            return True
        except Exception as e:
            logger.error(f"Error reloading configuration: {e}")
            return False
    
    def _auto_reload_loop(self):
        """Background thread for auto-reloading configuration."""
        while self._running:
            try:
                time.sleep(self.reload_interval)
                if self._running:  # Check again after sleep
                    self.reload_config()
            except Exception as e:
                logger.error(f"Error in auto-reload loop: {e}")
    
    def _start_auto_reload(self):
        """Start the auto-reload background thread."""
        if self._reload_thread is not None and self._reload_thread.is_alive():
            return
            
        self._running = True
        self._reload_thread = threading.Thread(target=self._auto_reload_loop, daemon=True)
        self._reload_thread.start()
        logger.info("Started auto-reload thread")
    
    def stop_auto_reload(self):
        """Stop the auto-reload background thread."""
        self._running = False
        if self._reload_thread is not None:
            self._reload_thread.join(timeout=1.0)
            self._reload_thread = None
            logger.info("Stopped auto-reload thread")
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get the current configuration."""
        with self._config_lock:
            return self._config.copy()
    
    @lru_cache(maxsize=64)
    def get_bot_config(self, bot_name: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific bot.
        
        Args:
            bot_name: Name of the bot
            
        Returns:
            Optional[Dict]: bot configuration or None if not found
        """
        with self._config_lock:
            bot_config = self._config.get("bot_aliases", {}).get(bot_name)
            if bot_config:
                # Create a copy with the name added
                bot_config = bot_config.copy()
                bot_config["name"] = bot_name
            return bot_config
    
    def get_all_bots(self) -> Dict[str, Dict[str, Any]]:
        """
        Get configurations for all bots.
        
        Returns:
            Dict: Dictionary of bot configurations with names
        """
        with self._config_lock:
            bots = {}
            for bot_name, bot_config in self._config.get("bot_aliases", {}).items():
                config_with_name = bot_config.copy()
                config_with_name["name"] = bot_name
                bots[bot_name] = config_with_name
            return bots
    
    def save_config(self) -> bool:
        """
        Save the current configuration back to the file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with self._config_lock:
                with open(self.config_path, 'w') as f:
                    json.dump(self._config, f, indent=2)
                self._last_modified = os.path.getmtime(self.config_path)
            logger.info(f"Configuration saved to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False
    
    def update_bot_config(self, bot_name: str, config: Dict[str, Any]) -> bool:
        """
        Update or add a bot configuration.
        
        Args:
            bot_name: Name of the bot
            config: bot configuration
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with self._config_lock:
                if "bot_aliases" not in self._config:
                    self._config["bot_aliases"] = {}
                self._config["bot_aliases"][bot_name] = config
                
            # Clear the cache for this bot
            self.get_bot_config.cache_clear()
            
            return True
        except Exception as e:
            logger.error(f"Failed to update bot configuration: {e}")
            return False
    
    def remove_bot_config(self, bot_name: str) -> bool:
        """
        Remove a bot configuration.
        
        Args:
            bot_name: Name of the bot
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with self._config_lock:
                if "bot_aliases" in self._config and bot_name in self._config["bot_aliases"]:
                    del self._config["bot_aliases"][bot_name]
                    
            # Clear the cache for this bot
            self.get_bot_config.cache_clear()
            
            return True
        except Exception as e:
            logger.error(f"Failed to remove bot configuration: {e}")
            return False

# Create a default instance
config_manager = ConfigManager()

# For easy importing
def get_config_manager(config_path: str = None, auto_reload: bool = None, reload_interval: int = None) -> ConfigManager:
    """
    Get or create the ConfigManager instance with optional new settings.
    
    Args:
        config_path: Optional new path to the configuration file
        auto_reload: Optional new auto-reload setting
        reload_interval: Optional new reload interval
        
    Returns:
        ConfigManager: The singleton ConfigManager instance
    """
    global config_manager
    
    if config_path is not None or auto_reload is not None or reload_interval is not None:
        # Create with new settings
        new_config_path = config_path or config_manager.config_path
        new_auto_reload = auto_reload if auto_reload is not None else config_manager.auto_reload
        new_reload_interval = reload_interval or config_manager.reload_interval
        
        # Stop current auto-reload if running
        config_manager.stop_auto_reload()
        
        # Create new instance (will reuse singleton)
        config_manager = ConfigManager(
            config_path=new_config_path,
            auto_reload=new_auto_reload,
            reload_interval=new_reload_interval
        )
    
    return config_manager