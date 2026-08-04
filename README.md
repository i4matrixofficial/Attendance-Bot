# Attendance Bot

A Discord bot that records attendance from a voice channel and generates a colored Excel report.

## Features
- Records attendance for members present in a selected voice channel
- Excludes bots from attendance data
- Generates an Excel report with styled formatting
- Supports manual tracking via slash command and text command
- Supports automatic attendance at 9:06 AM Sri Lanka time on weekdays

## Requirements
- Python 3.10+
- discord.py
- python-dotenv
- openpyxl

## Installation
1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file with:
   ```env
   DISCORD_TOKEN=your_discord_bot_token
   AUTO_VOICE_CHANNEL_ID=your_voice_channel_id
   AUTO_REPORT_CHANNEL_ID=your_report_channel_id
   ```

## Running locally
```bash
python main.py
```

## Commands
- `/track` – record attendance for a selected voice channel
- `!track` – fallback text command

## Deployment
This project is prepared for Railway deployment using the included `railway.toml` and `runtime.txt` files.

## Project structure
- `main.py` – Discord bot entry point and scheduling logic
- `attendance.py` – attendance report generation
- `requirements.txt` – Python dependencies
- `data/` – generated attendance report files

## Notes
- The bot requires Discord gateway intents for members and voice states.
- The automatic scheduler depends on the bot process staying online at the scheduled time.
