# Oracle VM Setup Guide — i4matrix Attendance Bot

## Overview

Two-layer reliability setup:

| Layer | What it does |
|-------|-------------|
| **systemd service** | Keeps the bot process alive 24/7, auto-restarts on crash |
| **cron job** | Independently fires attendance at 9:06 AM SL time even if the bot loop missed it |

---

## 1. Deploy the project

```bash
# SSH into your Oracle VM
ssh opc@<your-oracle-vm-ip>

# Clone or copy the project
sudo mkdir -p /opt/attendance-bot
sudo chown opc:opc /opt/attendance-bot
git clone https://github.com/raviy00/attendance-bot.git /opt/attendance-bot
# -- OR use scp/rsync to copy your local folder --
```

---

## 2. Create a dedicated user (security best practice)

```bash
sudo useradd -r -s /sbin/nologin botuser
sudo chown -R botuser:botuser /opt/attendance-bot
```

---

## 3. Install Python and dependencies

```bash
# Oracle Linux 8/9 — install Python 3.11
sudo dnf install python3.11 python3.11-venv -y

# Create the virtualenv
cd /opt/attendance-bot
python3.11 -m venv venv

# Install all dependencies (including tzdata for timezone support on Linux)
venv/bin/pip install -r requirements.txt
venv/bin/pip install tzdata        # needed for ZoneInfo on some Linux builds
```

---

## 4. Create the .env file on the server

```bash
sudo nano /opt/attendance-bot/.env
```

Paste your environment variables:

```env
DISCORD_TOKEN=your_token_here
AUTO_VOICE_CHANNEL_ID=1470684033712394251
AUTO_REPORT_CHANNEL_ID=1473185928188002345
```

Lock down permissions:

```bash
sudo chmod 600 /opt/attendance-bot/.env
sudo chown botuser:botuser /opt/attendance-bot/.env
```

---

## 5. Install the systemd service

```bash
# Copy the service file
sudo cp /opt/attendance-bot/oracle_setup/attendance-bot.service \
        /etc/systemd/system/attendance-bot.service

# Reload systemd, enable on boot, and start
sudo systemctl daemon-reload
sudo systemctl enable attendance-bot
sudo systemctl start attendance-bot

# Verify it is running
sudo systemctl status attendance-bot

# Watch live logs
sudo journalctl -u attendance-bot -f
```

---

## 6. Add the cron job (backup trigger at exactly 9:06 AM SL time)

The Oracle VM likely runs in **UTC**. Sri Lanka (Asia/Colombo) is UTC+5:30, so:
- **9:06 AM SL = 3:36 AM UTC**

```bash
# Open the crontab for botuser
sudo crontab -u botuser -e
```

Add this line:

```cron
# Auto-attendance at 9:06 AM Sri Lanka time (UTC 03:36), weekdays only
36 3 * * 1-5 /opt/attendance-bot/venv/bin/python /opt/attendance-bot/oracle_setup/attendance_trigger.py >> /var/log/attendance_trigger.log 2>&1
```

Create the log file so botuser can write to it:

```bash
sudo touch /var/log/attendance_trigger.log
sudo chown botuser:botuser /var/log/attendance_trigger.log
```

Verify the cron entry was saved:

```bash
sudo crontab -u botuser -l
```

---

## 7. Verify the Oracle VM timezone

Confirm the VM is in UTC (cron runs in UTC by default):

```bash
timedatectl
```

If the VM is set to a different timezone, adjust the cron time accordingly:

```bash
# To set the VM to UTC (recommended for servers)
sudo timedatectl set-timezone UTC
```

---

## 8. Open firewall port (if needed)

The bot only makes outbound connections to Discord — no inbound ports need opening.

If you have Oracle's **security list** blocking outbound HTTPS, allow it:

```bash
# Typically not needed — Oracle's default egress rule allows all outbound
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---

## Quick reference commands

```bash
# Check bot status
sudo systemctl status attendance-bot

# Restart bot
sudo systemctl restart attendance-bot

# Stop bot
sudo systemctl stop attendance-bot

# View live bot logs
sudo journalctl -u attendance-bot -f

# View cron trigger logs
tail -f /var/log/attendance_trigger.log

# Manually test the cron trigger script
sudo -u botuser /opt/attendance-bot/venv/bin/python \
    /opt/attendance-bot/oracle_setup/attendance_trigger.py
```

---

## How the two layers work together

```
09:06 AM SL time
      │
      ├─── discord.py tasks.loop fires (if bot process is healthy)
      │         └─ auto_attendance() in main.py
      │
      └─── cron fires attendance_trigger.py (independently)
                └─ connects → posts → disconnects
```

> **Note:** Both layers will run at 9:06 AM. The cron script is self-contained
> and will post its own message. If you prefer only one to run, you can either
> remove the `tasks.loop` from `main.py` (and rely fully on cron) or skip the
> cron job (and rely fully on the bot's loop). The cron-only approach is more
> reliable for production.
