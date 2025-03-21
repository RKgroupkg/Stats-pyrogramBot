import asyncio
from TelegramBot import bot
from TelegramBot.logging import LOGGER
from TelegramBot import config
from TelegramBot.helpers.pinger import BackgroundPinger

LOGGER(__name__).info("client successfully initiated....")

pinger = BackgroundPinger(
  client=bot,
  admin_chat_id=config.CHANNEL_ID,
  status_message_id=244
)


# 
if __name__ == "__main__":
    # Create a background task for the pinger
    bot.loop.create_task(pinger.start())
    
    
    # Start the bot (this will handle messages and commands)
    bot.run()