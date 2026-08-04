"""
attendance_trigger.py
─────────────────────
Standalone cron-triggered script that fires the auto-attendance job.

This script is completely independent of the discord.py tasks.loop scheduler.
It connects to Discord, takes attendance in the configured voice channel, posts
the report to the configured text channel, then disconnects cleanly.

Run directly on the Oracle VM at 09:06 AM (Asia/Colombo) via cron.

Cron entry (UTC 03:36 = SL 09:06):
    36 3 * * 1-5 /opt/attendance-bot/venv/bin/python /opt/attendance-bot/oracle_setup/attendance_trigger.py >> /var/log/attendance_trigger.log 2>&1
"""

import asyncio
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import traceback

import discord
from dotenv import load_dotenv

# ── resolve paths relative to THIS file, not cwd ────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)          # so we can import attendance.py

from attendance import record_attendance  # noqa: E402  (after sys.path fix)

# ── env ──────────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

TOKEN             = os.getenv("DISCORD_TOKEN")
VOICE_CHANNEL_ID  = os.getenv("AUTO_VOICE_CHANNEL_ID")
REPORT_CHANNEL_ID = os.getenv("AUTO_REPORT_CHANNEL_ID")
SL_TZ             = ZoneInfo("Asia/Colombo")


def log(msg: str) -> None:
    ts = datetime.now(SL_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{ts}] {msg}", flush=True)


async def run() -> None:
    if not TOKEN:
        log("ERROR: DISCORD_TOKEN not set. Aborting.")
        return
    if not VOICE_CHANNEL_ID or not REPORT_CHANNEL_ID:
        log("ERROR: AUTO_VOICE_CHANNEL_ID or AUTO_REPORT_CHANNEL_ID not set. Aborting.")
        return

    # Skip weekends
    now = datetime.now(SL_TZ)
    if now.weekday() >= 5:
        log(f"Skipping: today is {now.strftime('%A')} (weekend).")
        return

    intents = discord.Intents.default()
    intents.members      = True
    intents.voice_states = True

    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        log(f"Logged in as {client.user} -- running attendance trigger ...")
        try:
            voice_channel = client.get_channel(int(VOICE_CHANNEL_ID))
            if voice_channel is None:
                voice_channel = await client.fetch_channel(int(VOICE_CHANNEL_ID))

            report_channel = client.get_channel(int(REPORT_CHANNEL_ID))
            if report_channel is None:
                report_channel = await client.fetch_channel(int(REPORT_CHANNEL_ID))

            if not isinstance(voice_channel, discord.VoiceChannel):
                log(f"ERROR: Channel {VOICE_CHANNEL_ID} is not a voice channel.")
                await client.close()
                return

            if len(voice_channel.members) == 0:
                await report_channel.send(
                    "Auto-Attendance (9:06 AM): No one is in the voice channel right now. "
                    "No attendance recorded."
                )
                log("Voice channel is empty -- notified report channel.")
                await client.close()
                return

            num_members = len(voice_channel.members)
            xlsx_path   = record_attendance(voice_channel)
            xlsx_file   = discord.File(xlsx_path)

            await report_channel.send(
                content=(
                    f"Auto-Attendance Report -- 9:06 AM Sri Lanka Time\n"
                    f"Attendance recorded for {num_members} member(s) in {voice_channel.mention}!\n"
                    f"Here is the i4matrix Attendance Report (open in Excel or Google Sheets for colors!)"
                ),
                file=xlsx_file,
            )
            log(f"Attendance posted -- {num_members} member(s) in #{voice_channel.name}")

        except Exception as exc:
            log(f"ERROR: {exc}")
            traceback.print_exc()
        finally:
            await client.close()

    await client.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(run())
