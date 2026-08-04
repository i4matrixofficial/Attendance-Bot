import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import traceback
from datetime import time as dt_time, datetime
from zoneinfo import ZoneInfo

from attendance import record_attendance

# ── Sri Lanka timezone (UTC+5:30) ─────────────────────────────────────────────
SL_TZ = ZoneInfo("Asia/Colombo")
AUTO_ATTENDANCE_TIME = dt_time(hour=9, minute=6, tzinfo=SL_TZ)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set. Please check your .env file.")

# Set up bot intents
intents = discord.Intents.default()
intents.members = True       # Privileged: must be enabled in Developer Portal
intents.message_content = True
intents.voice_states = True  # Required to see who is in voice channels

class AttendanceBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Synced slash commands.")

bot = AttendanceBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

    # Start the daily auto-attendance scheduler
    if not auto_attendance.is_running():
        auto_attendance.start()
        print(f'⏰ Auto-attendance scheduled for 9:06 AM Sri Lanka time daily')

# ── Scheduled auto-attendance (9:06 AM Sri Lanka time) ─────────────────────────
@tasks.loop(time=AUTO_ATTENDANCE_TIME)
async def auto_attendance():
    """Automatically take attendance at 9:06 AM Sri Lanka time on weekdays."""
    # Skip weekends (Saturday = 5, Sunday = 6)
    if datetime.now(SL_TZ).weekday() >= 5:
        print("⏭️ Skipping auto-attendance (weekend)")
        return

    voice_channel_id  = os.getenv('AUTO_VOICE_CHANNEL_ID')
    report_channel_id = os.getenv('AUTO_REPORT_CHANNEL_ID')

    if not voice_channel_id or not report_channel_id:
        print('⚠️ AUTO_VOICE_CHANNEL_ID or AUTO_REPORT_CHANNEL_ID not set. Skipping auto-attendance.')
        return

    try:
        # Fetch the voice channel
        voice_channel = bot.get_channel(int(voice_channel_id))
        if voice_channel is None:
            voice_channel = await bot.fetch_channel(int(voice_channel_id))

        # Fetch the text channel to post the report
        report_channel = bot.get_channel(int(report_channel_id))
        if report_channel is None:
            report_channel = await bot.fetch_channel(int(report_channel_id))

        if not isinstance(voice_channel, discord.VoiceChannel):
            print(f'❌ AUTO_VOICE_CHANNEL_ID ({voice_channel_id}) is not a voice channel.')
            return

        if len(voice_channel.members) == 0:
            await report_channel.send(
                '⚠️ **Auto-Attendance (9:06 AM):** No one is in the voice channel right now. '
                'No attendance recorded.'
            )
            print('⚠️ Auto-attendance: voice channel is empty.')
            return

        num_members = len(voice_channel.members)
        xlsx_path = record_attendance(voice_channel)
        xlsx_file = discord.File(xlsx_path)

        await report_channel.send(
            content=(
                f'📋 **Auto-Attendance Report** — 9:06 AM Sri Lanka Time\n'
                f'✅ Attendance recorded for **{num_members}** member(s) in {voice_channel.mention}!\n'
                f'Here is the i4matrix Attendance Report 📊 (open in Excel or Google Sheets for colors!)'
            ),
            file=xlsx_file,
        )
        print(f'✅ Auto-attendance posted: {num_members} members in #{voice_channel.name}')

    except Exception as e:
        print(f'❌ Auto-attendance error: {e}')
        traceback.print_exc()

@auto_attendance.before_loop
async def before_auto_attendance():
    """Wait until the bot is fully ready before starting the schedule."""
    await bot.wait_until_ready()

# ── Autocomplete: dynamically fetch voice channels so list is always up-to-date ──
async def channel_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    try:
        # fetch_channels() makes a live API call – guaranteed to be current
        all_channels = await interaction.guild.fetch_channels()
        voice_channels = [c for c in all_channels if isinstance(c, discord.VoiceChannel)]
    except Exception:
        voice_channels = interaction.guild.voice_channels  # fallback to cache

    return [
        app_commands.Choice(name=vc.name, value=vc.name)
        for vc in voice_channels
        if current.lower() in vc.name.lower()
    ][:25]

# ── Slash command ──────────────────────────────────────────────────────────────
@bot.tree.command(name="track", description="Record attendance for a voice channel and attach the CSV here")
@app_commands.describe(channel="Pick the voice channel from the list, or leave empty to use your current one.")
@app_commands.default_permissions(manage_events=True)
@app_commands.autocomplete(channel=channel_autocomplete)
async def track(interaction: discord.Interaction, channel: str = None):
    # Defer immediately – gives us 15 min instead of 3 s
    await interaction.response.defer(ephemeral=False)

    target_channel = None

    # 1️⃣  User supplied a channel name → find it via live API call
    if channel is not None:
        clean = channel.strip().lower()
        try:
            all_channels = await interaction.guild.fetch_channels()
        except Exception:
            all_channels = interaction.guild.channels

        for ch in all_channels:
            if isinstance(ch, discord.VoiceChannel) and ch.name.strip().lower() == clean:
                target_channel = ch
                break

        if target_channel is None:
            channel_list = ", ".join(
                f"`{c.name}`" for c in all_channels if isinstance(c, discord.VoiceChannel)
            )
            await interaction.followup.send(
                f"❌ Could not find a voice channel named **{channel}**.\n"
                f"Available voice channels: {channel_list or 'none found'}"
            )
            return

    # 2️⃣  No channel supplied → fetch live member data to get voice state
    if target_channel is None:
        try:
            # fetch_member() makes a live REST call – no stale-cache issues
            live_member = await interaction.guild.fetch_member(interaction.user.id)
            if live_member.voice and live_member.voice.channel:
                target_channel = live_member.voice.channel
        except Exception as e:
            print(f"fetch_member error: {e}")

    if target_channel is None:
        # Build a list of currently occupied voice channels for a helpful hint
        try:
            all_channels = await interaction.guild.fetch_channels()
            occupied = [
                f"`{c.name}`" for c in all_channels
                if isinstance(c, discord.VoiceChannel) and len(c.members) > 0
            ]
        except Exception:
            occupied = []

        hint = f"\nOccupied voice channels right now: {', '.join(occupied)}" if occupied else ""
        await interaction.followup.send(
            f"❌ **Discord still can't detect your voice channel.**\n"
            f"Please pick your channel from the autocomplete list when typing `/track channel:`{hint}"
        )
        return

    # 3️⃣  Generate and send the CSV
    try:
        if len(target_channel.members) == 0:
            await interaction.followup.send(f"⚠️ {target_channel.mention} is currently empty. No attendance recorded.")
            return

        num_members = len(target_channel.members)
        csv_path = record_attendance(target_channel)

        csv_file = discord.File(csv_path)
        await interaction.followup.send(
            content=(
                f"✅ Attendance recorded for **{num_members}** member(s) in {target_channel.mention}!\n"
                f"Here is the i4matrix Attendance Report 📊 (open in Excel or Google Sheets for colors!)"
            ),
            file=csv_file,
        )

    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: `{e}`")
        print(f"Tracking Error: {e}")
        traceback.print_exc()

# ── Text command fallback (works even if slash commands have issues) ────────────
@bot.command(name="track")
@commands.has_permissions(manage_events=True)
async def track_text(ctx, *, channel_name: str = None):
    """Fallback text command: !track [channel name]"""
    target_channel = None

    if channel_name:
        clean = channel_name.strip().lower()
        for vc in ctx.guild.voice_channels:
            if vc.name.strip().lower() == clean:
                target_channel = vc
                break
        if target_channel is None:
            await ctx.send(f"❌ Could not find voice channel: `{channel_name}`")
            return
    else:
        if ctx.author.voice and ctx.author.voice.channel:
            target_channel = ctx.author.voice.channel
        else:
            await ctx.send("❌ You are not in a voice channel. Use `!track General` to specify one.")
            return

    if len(target_channel.members) == 0:
        await ctx.send(f"⚠️ {target_channel.mention} is empty. No attendance recorded.")
        return

    num_members = len(target_channel.members)
    csv_path = record_attendance(target_channel)
    csv_file = discord.File(csv_path)
    await ctx.send(
        content=f"✅ Attendance for **{num_members}** member(s) in {target_channel.mention} 📋",
        file=csv_file,
    )

if __name__ == '__main__':
    bot.run(TOKEN)
