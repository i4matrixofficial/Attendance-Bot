import calendar
import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import traceback
from datetime import time as dt_time, datetime
from zoneinfo import ZoneInfo

from attendance import record_attendance
from attendance_db import init_db
from monthly_report import (
    generate_daily_report,
    generate_monthly_report,
    generate_weekly_report,
)

# ── Sri Lanka timezone (UTC+5:30) ─────────────────────────────────────────────
SL_TZ = ZoneInfo("Asia/Colombo")
AUTO_ATTENDANCE_TIME = dt_time(hour=9, minute=6, tzinfo=SL_TZ)
MONTHLY_REPORT_TIME = dt_time(hour=18, minute=0, tzinfo=SL_TZ)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

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
        await init_db()

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            await self.tree.sync(guild=guild)
            print(f"Synced slash commands to guild {GUILD_ID}.")
        else:
            await self.tree.sync()
            print("Synced slash commands globally. This may take a few minutes to appear.")

    async def on_connect(self):
        if GUILD_ID:
            print(f"Bot connected. Using GUILD_ID={GUILD_ID} for immediate slash-command sync.")
        else:
            print("Bot connected. GUILD_ID is not set, using global slash-command sync.")

bot = AttendanceBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

    if GUILD_ID:
        guild = discord.Object(id=int(GUILD_ID))
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} slash commands for guild {GUILD_ID} on_ready().")

    # Start the daily auto-attendance scheduler
    if not auto_attendance.is_running():
        auto_attendance.start()
        print(f'⏰ Auto-attendance scheduled for 9:06 AM Sri Lanka time daily')

    if not monthly_attendance_check.is_running():
        monthly_attendance_check.start()
        print(f'📅 Monthly attendance check scheduled for 6:00 PM Sri Lanka time daily')

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
        xlsx_path = await record_attendance(voice_channel)
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

@tasks.loop(time=MONTHLY_REPORT_TIME)
async def monthly_attendance_check():
    """Generate a monthly attendance summary on the last day of each month."""
    today = datetime.now(SL_TZ).date()
    last_day = calendar.monthrange(today.year, today.month)[1]

    if today.day != last_day:
        return

    report_channel_id = os.getenv('AUTO_REPORT_CHANNEL_ID')
    voice_channel_id = os.getenv('AUTO_VOICE_CHANNEL_ID')

    if not report_channel_id or not voice_channel_id:
        print('⚠️ AUTO_REPORT_CHANNEL_ID or AUTO_VOICE_CHANNEL_ID not set. Skipping monthly attendance report.')
        return

    try:
        voice_channel = bot.get_channel(int(voice_channel_id))
        if voice_channel is None:
            voice_channel = await bot.fetch_channel(int(voice_channel_id))

        if not isinstance(voice_channel, discord.VoiceChannel):
            print(f'❌ AUTO_VOICE_CHANNEL_ID ({voice_channel_id}) is not a voice channel.')
            return

        report_channel = bot.get_channel(int(report_channel_id))
        if report_channel is None:
            report_channel = await bot.fetch_channel(int(report_channel_id))

        xlsx_path = await generate_monthly_report(voice_channel.guild, voice_channel, today.year, today.month)
        if xlsx_path is None:
            await report_channel.send(
                f'⚠️ No attendance data recorded yet for {today.strftime("%B %Y")}. '
                'Monthly report cannot be generated.'
            )
            return

        await report_channel.send(
            content=(
                f'📊 **Monthly Attendance Summary** — {today.strftime("%B %Y")}'
                '\nHere is the monthly attendance report for the configured voice channel.'
            ),
            file=discord.File(xlsx_path),
        )
        print(f'✅ Monthly attendance report posted for {today.strftime("%B %Y")}.')
    except Exception as e:
        print(f'❌ Monthly attendance error: {e}')
        traceback.print_exc()

@monthly_attendance_check.before_loop
async def before_monthly_attendance_check():
    await bot.wait_until_ready()

# ── Autocomplete: dynamically fetch voice channels so list is always up-to-date ─────────────────────────────────
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
        csv_path = await record_attendance(target_channel)

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

# ── Monthly report slash command ─────────────────────────────────────────────
@bot.tree.command(name="dailyreport", description="Generate a daily attendance report")
@app_commands.describe(
    day="Day number. Defaults to today.",
    month="Month number (1-12). Defaults to the current month.",
    year="Year number. Defaults to the current year."
)
@app_commands.default_permissions(manage_events=True)
async def dailyreport(
    interaction: discord.Interaction,
    day: int = None,
    month: int = None,
    year: int = None,
):
    await interaction.response.defer(ephemeral=False)

    now = datetime.now(SL_TZ)
    chosen_year = year or now.year
    chosen_month = month or now.month
    chosen_day = day or now.day

    try:
        target_date = datetime(chosen_year, chosen_month, chosen_day).date()
    except ValueError:
        await interaction.followup.send("❌ Invalid date provided.")
        return

    target_channel_id = os.getenv('AUTO_VOICE_CHANNEL_ID')
    if not target_channel_id:
        await interaction.followup.send('⚠️ AUTO_VOICE_CHANNEL_ID not set. Cannot generate report.')
        return

    try:
        voice_channel = bot.get_channel(int(target_channel_id))
        if voice_channel is None:
            voice_channel = await bot.fetch_channel(int(target_channel_id))

        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.followup.send('❌ Configured AUTO_VOICE_CHANNEL_ID is not a voice channel.')
            return

        xlsx_path = await generate_daily_report(voice_channel.guild, voice_channel, target_date)
        if xlsx_path is None:
            await interaction.followup.send(f'⚠️ No attendance data for {target_date.isoformat()}.')
            return

        await interaction.followup.send(
            content=(
                f'📊 **Daily Attendance Summary** — {target_date.isoformat()}'
                '\nHere is the daily attendance report.'
            ),
            file=discord.File(xlsx_path),
        )
    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: `{e}`")
        print(f"Daily report error: {e}")
        traceback.print_exc()


@bot.tree.command(name="weeklyreport", description="Generate a weekly attendance summary report")
@app_commands.describe(
    week="ISO week number. Defaults to the current week.",
    year="Year number. Defaults to the current year."
)
@app_commands.default_permissions(manage_events=True)
async def weeklyreport(
    interaction: discord.Interaction,
    week: int = None,
    year: int = None,
):
    await interaction.response.defer(ephemeral=False)

    now = datetime.now(SL_TZ)
    chosen_year = year or now.year
    chosen_week = week or now.isocalendar()[1]

    if not (1 <= chosen_week <= 53):
        await interaction.followup.send("❌ Week must be between 1 and 53.")
        return

    target_channel_id = os.getenv('AUTO_VOICE_CHANNEL_ID')
    if not target_channel_id:
        await interaction.followup.send('⚠️ AUTO_VOICE_CHANNEL_ID not set. Cannot generate report.')
        return

    try:
        voice_channel = bot.get_channel(int(target_channel_id))
        if voice_channel is None:
            voice_channel = await bot.fetch_channel(int(target_channel_id))

        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.followup.send('❌ Configured AUTO_VOICE_CHANNEL_ID is not a voice channel.')
            return

        xlsx_path = await generate_weekly_report(voice_channel.guild, voice_channel, chosen_year, chosen_week)
        if xlsx_path is None:
            await interaction.followup.send(f'⚠️ No attendance data for week {chosen_year}-W{chosen_week:02d}.')
            return

        await interaction.followup.send(
            content=(
                f'📊 **Weekly Attendance Summary** — {chosen_year}-W{chosen_week:02d}'
                '\nHere is the weekly attendance report.'
            ),
            file=discord.File(xlsx_path),
        )
    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: `{e}`")
        print(f"Weekly report error: {e}")
        traceback.print_exc()


@bot.tree.command(name="monthlyreport", description="Generate a monthly attendance summary report")
@app_commands.describe(
    month="Month number (1-12). Defaults to the current month.",
    year="Year number. Defaults to the current year."
)
@app_commands.default_permissions(manage_events=True)
async def monthlyreport(
    interaction: discord.Interaction,
    month: int = None,
    year: int = None,
):
    await interaction.response.defer(ephemeral=False)

    now = datetime.now(SL_TZ)
    chosen_month = month or now.month
    chosen_year = year or now.year

    if not (1 <= chosen_month <= 12):
        await interaction.followup.send("❌ Month must be between 1 and 12.")
        return

    target_channel_id = os.getenv('AUTO_VOICE_CHANNEL_ID')
    if not target_channel_id:
        await interaction.followup.send('⚠️ AUTO_VOICE_CHANNEL_ID not set. Cannot generate report.')
        return

    try:
        voice_channel = bot.get_channel(int(target_channel_id))
        if voice_channel is None:
            voice_channel = await bot.fetch_channel(int(target_channel_id))

        if not isinstance(voice_channel, discord.VoiceChannel):
            await interaction.followup.send('❌ Configured AUTO_VOICE_CHANNEL_ID is not a voice channel.')
            return

        xlsx_path = await generate_monthly_report(voice_channel.guild, voice_channel, chosen_year, chosen_month)
        if xlsx_path is None:
            await interaction.followup.send(f'⚠️ No attendance data for {chosen_year}-{chosen_month:02d}.')
            return

        await interaction.followup.send(
            content=(
                f'📊 **Monthly Attendance Summary** — {chosen_year}-{chosen_month:02d}'
                '\nHere is the monthly attendance report.'
            ),
            file=discord.File(xlsx_path),
        )
    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: `{e}`")
        print(f"Monthly report error: {e}")
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
    csv_path = await record_attendance(target_channel)
    csv_file = discord.File(csv_path)
    await ctx.send(
        content=f"✅ Attendance for **{num_members}** member(s) in {target_channel.mention} 📋",
        file=csv_file,
    )

@bot.command(name="monthlyreport")
@commands.has_permissions(manage_events=True)
async def monthlyreport_text(ctx, month: int = None, year: int = None):
    """Fallback text command: !monthlyreport [month] [year]"""
    now = datetime.now(SL_TZ)
    chosen_month = month or now.month
    chosen_year = year or now.year

    if not (1 <= chosen_month <= 12):
        await ctx.send("❌ Month must be between 1 and 12.")
        return

    target_channel_id = os.getenv('AUTO_VOICE_CHANNEL_ID')
    if not target_channel_id:
        await ctx.send('⚠️ AUTO_VOICE_CHANNEL_ID not set. Cannot generate report.')
        return

    voice_channel = ctx.guild.get_channel(int(target_channel_id))
    if voice_channel is None:
        voice_channel = await ctx.guild.fetch_channel(int(target_channel_id))

    if not isinstance(voice_channel, discord.VoiceChannel):
        await ctx.send('❌ Configured AUTO_VOICE_CHANNEL_ID is not a voice channel.')
        return

    xlsx_path = await generate_monthly_report(ctx.guild, voice_channel, chosen_year, chosen_month)
    if xlsx_path is None:
        await ctx.send(f'⚠️ No attendance data for {chosen_year}-{chosen_month:02d}.')
        return

    await ctx.send(
        content=f"📊 Monthly Attendance Summary — {chosen_year}-{chosen_month:02d}",
        file=discord.File(xlsx_path),
    )

if __name__ == '__main__':
    bot.run(TOKEN)
