<div align="center">
<h1>Server Monitor Bot<br>[ Pyrogram version ]</h1>
<img src="https://telegra.ph/file/4621c1419e443ebb01b2b.jpg" align="center" style="width: 100%" />
</div>

------

<div align="center">
<h1><b>About this repository</b></h1>
</div>

This Telegram bot monitors your render/koyeb servers and automatically redeploys them when they go down. It's built on top of the Pyrogram Bot Boilerplate, providing a robust foundation for server monitoring and management through Telegram.

## Features

- **Server Monitoring**: Regularly pings your render/koyeb servers to check their status
- **Automatic Redeployment**: Redeploys servers when they go down, ensuring maximum uptime
- **Status Checking**: Use `/start` then "status" to see the current server status via inline buttons
- **Admin Configuration**: Use `/config` to set up monitoring parameters (admin-only)
- **Service Continuity**: Ensures your Telegram bot services stay up and running

## Commands

- `/start` - Start the bot and get the main menu
- `status` - Check the status of your servers via inline buttons
- `/config` - Configure ping intervals and server endpoints (admin-only)

## Getting Started

### Prerequisites

- Python 3.8 or higher
- Telegram Bot Token (from @BotFather)
- Render/Koyeb API credentials

### Installation

1. Clone this repository:
```
git clone https://github.com/yourusername/server-monitor-bot && cd server-monitor-bot
```

2. Install the required packages:
```
pip3 install -U -r requirements.txt
```

3. Edit the configuration file:
```
nano config.env
```

4. Start the bot:
```
bash start
```

### Configuration

In the `config.env` file, you'll need to set the following variables:

```
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
MONGO_URI=your_mongo_uri
OWNER_ID=your_telegram_id
SUDO_USERS=comma_separated_ids
RENDER_API_KEY=your_render_api_key
KOYEB_API_KEY=your_koyeb_api_key
PING_INTERVAL=300  # in seconds
```

## Deployment

To run the bot 24/7, you can use tmux:

```
sudo apt install tmux -y
tmux && bash start
```

Now the bot will run continuously even if you log out from the server.

## Advanced Usage

### Custom Ping Intervals

You can set different ping intervals for different servers through the `/config` command.

### Multiple Server Support

The bot can monitor multiple Render/Koyeb servers simultaneously. Add them through the configuration interface.

### Notification Settings

Configure who gets notified when a server goes down or when it's successfully redeployed.

------

<div align="center">
<h1><b>File Structure</b></h1>
</div>

```
├── Dockerfile                          
├── LICENSE
├── README.md
├── config.env                         ( For storing all the  environment variables)
├── requirements.txt                   ( For keeping all the library name wich project is using)
├── TelegramBot
│   │
│   ├── __init__.py                   ( Initializing the bot from here.)
│   ├── __main__.py                   ( Starting the bot from here.)
│   ├── config.py                     ( Importing and storing all envireonment variables from config.env)
│   ├── logging.py                    ( Help in logging and get log file)
│   │
│   ├── assets                        ( An assets folder to keep all type of assets like thumbnail, font, constants, etc.)
│   │   └── __init__.py
│   │   ├── font.ttf
│   │   └── template.png
│   │
│   ├── database                      (Sperate folder to manage database related stuff for bigger projects.)
│   │   ├── __init__.py
│   │   ├── database.py              (contain functions related to handle database operations all over the bor)
│   │   └── MongoDb.py               (Contain a MongoDB class to handle CRUD operations on MongoDB collection )
│   │  
│   ├── helpers                       ( Contain all the file wich is imported and  used all over the code. It act as backbone of code.)
│   │   ├── __init__.py
│   │   ├── filters.py 
│   │   ├── decorators.py            ( Contain all the python decorators)
│   │   ├── ratelimiter.py           (Contain RateLimiter class that handle ratelimiting part of the bot.)
│   │   ├── functions.py             ( Contain all the functions wich is used all over the code. )
│   │   ├── async_pinger.py
│   │   └──  pinger.py
│   │
│   ├── plugins                       ( plugins folder contain all the plugins commands via wich user interact)  
│   │   ├── __init__.py 
│   │   ├── developer
│   │   │   ├── __init__.py
│   │   │   ├── terminal.py
│   │   │   └── updater.py
│   │   │
│   │   ├── sudo
│   │   │   ├── __init__.py
│   │   │   ├── speedtest.py
│   │   │   ├── dbstats.py
│   │   │   └── serverstats.py
│   │   │   
│   │   └── users
│   │       ├── __init__.py
│   │       ├── alive.py
│   │       ├── start.py
│   │       ├── status.py
│   │       └── paste.py
│   │      
│   └── version.py         
└── start
```
-------
  
<div align="center">
<h1><b>Copyright and License</b></h1>
</div>
<br>
<img src="https://telegra.ph/file/b5850b957f081cfe5f0a6.png" align="right" width="110">
  

* copyright (C) 2023 by [RKgroupkg](https://github.com/RKgroupkg)
* Licensed under the terms of the [The MIT License](https://github.com/RKgroupkg/Pyrogram-Bot/blob/main/LICENSE)

<div align="center">
<img src="https://img.shields.io/badge/License-MIT-green.svg" align="center">
</div>




<p align="center">
  <a href="https://t.me/rkgroup_update">
    <img src="https://img.shields.io/static/v1?label=Join&message=Telegram%20Channel&color=blueviolet&style=for-the-badge&logo=telegram&logoColor=white" alt="Rkgroup Channel" />
  </a>
  <a href="https://telegram.me/Rkgroup_helpbot">
    <img src="https://img.shields.io/static/v1?label=Join&message=Telegram%20Group&color=blueviolet&style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Group" />
  </a>
</p>


-------
