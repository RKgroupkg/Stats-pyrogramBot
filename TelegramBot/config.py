import json
import os
from os import getenv
from pathlib import Path
from dotenv import load_dotenv
from TelegramBot.logging import LOGGER

logger = LOGGER(__name__)

# Check for .env or config.env files
env_files = ["config.env", ".env"]
env_loaded = False

for env_file in env_files:
    if Path(env_file).exists():
        logger.info(f"Loading environment from {env_file}")
        load_dotenv(env_file)
        env_loaded = True
        break

if not env_loaded:
    logger.info("No .env file found, using system environment variables")

# Helper function to safely load JSON environment variables
def get_json_env(key, default=None):
    value = getenv(key)
    if not value:
        return default
    
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {key}: {e}")
        return default

# Load configuration with proper error handling
API_ID = int(getenv("API_ID", 0))
API_HASH = getenv("API_HASH", "")
BOT_TOKEN = getenv("BOT_TOKEN", "")

# Handle owner and sudo users
OWNER_USERID = get_json_env("OWNER_USERID", [])
SUDO_USERID = OWNER_USERID.copy()

try:
    sudo_users = get_json_env("SUDO_USERID", [])
    if sudo_users:
        SUDO_USERID += sudo_users
        logger.info(f"Added {len(sudo_users)} sudo user(s)")
    else:
        logger.info("No sudo users found in environment variables")
except Exception as error:
    logger.warning(f"Error processing sudo users: {error}")

# Ensure unique user IDs
SUDO_USERID = list(set(SUDO_USERID))
MONGO_URI = getenv("MONGO_URI", "")

# Validate essential configuration
if not API_ID or not API_HASH or not BOT_TOKEN:
    logger.critical("Missing essential configuration (API_ID, API_HASH, or BOT_TOKEN)")

if not OWNER_USERID:
    logger.warning("No owner user IDs specified")

if not MONGO_URI:
    logger.warning("MONGO_URI not specified, some features may be unavailable")