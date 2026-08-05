import os
from datetime import datetime
from typing import Optional

import discord
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from attendance_db import get_logged_dates, get_month_records

COLOR_HEADER_BG = "1A2B4A"
COLOR_HEADER_FG = "FFFFFF"
COLOR_META_BG = "2C3E6B"
COLOR_META_FG = "FFFFFF"
COLOR_COL_HDR_BG = "3A5BA0"
COLOR_COL_HDR_FG = "FFFFFF"
COLOR_GREEN = "D6F5DD"
COLOR_YELLOW = "FDF1CC"
COLOR_RED = "FCE8E8"
COLOR_BORDER = "AAAAAA"


def _fill(hex_color: str):
    return PatternFill("solid", fgColor=hex_color)


def _font(hex_color: str, bold: bool = False, size: int = 11):
    return Font(color=hex_color, bold=bold, size=size, name="Calibri")


def _border():
    thin = Side(style="thin", color=COLOR_BORDER)
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _center():
    return Alignment(horizontal="center", vertical="center", wrap_text=True)


def _left():
    return Alignment(horizontal="left", vertical="center")


def _tier_color(percentage: float) -> str:
    if percentage >= 90:
        return COLOR_GREEN
    if percentage >= 70:
        return COLOR_YELLOW
    return COLOR_RED


async def generate_monthly_report(
    guild: discord.Guild,
    channel: discord.VoiceChannel,
    year: int,
    month: int,
) -> Optional[str]:
    """Generate a styled monthly attendance summary workbook and return its path."""
    records = await get_month_records(channel.id, year, month)
    logged_dates = await get_logged_dates(channel.id, year, month)

    if not records or not logged_dates:
        return None

    if not os.path.exists("data"):
        os.makedirs("data")

    safe_channel = "".join(
        c for c in channel.name if c.isalnum() or c in (" ", "_", "-")
    ).strip().replace(" ", "_")
    filename = f"Monthly_Attendance_{safe_channel}_{year}-{month:02d}.xlsx"
    filepath = os.path.join("data", filename)

    wb = Workbook()
    ws = wb.active
    ws.title = "Monthly Summary"

    col_widths = [5, 34, 16, 16, 16]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.merge_cells("A1:E1")
    ws["A1"] = "🏢 i4matrix Monthly Attendance Summary"
    ws["A1"].fill = _fill(COLOR_HEADER_BG)
    ws["A1"].font = _font(COLOR_HEADER_FG, bold=True, size=16)
    ws["A1"].alignment = _center()
    ws["A1"].border = _border()

    date_text = datetime(year, month, 1).strftime("%B %Y")
    meta = [
        ("Server", guild.name),
        ("Voice Channel", channel.name),
        ("Month", date_text),
        ("Days Tracked", str(len(logged_dates))),
    ]

    for idx, (label, value) in enumerate(meta, start=2):
        ws[f"A{idx}"] = label
        ws[f"B{idx}"] = value
        ws.merge_cells(f"B{idx}:E{idx}")
        ws[f"A{idx}"].fill = _fill(COLOR_META_BG)
        ws[f"A{idx}"].font = _font(COLOR_META_FG, bold=True, size=10)
        ws[f"A{idx}"].alignment = _left()
        ws[f"A{idx}"].border = _border()
        ws[f"B{idx}"].fill = _fill(COLOR_META_BG)
        ws[f"B{idx}"].font = _font(COLOR_META_FG, size=10)
        ws[f"B{idx}"].alignment = _left()
        ws[f"B{idx}"].border = _border()

    header_row = 6
    headers = ["#", "Member", "Days Present", "Days Tracked", "Attendance %"]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.fill = _fill(COLOR_COL_HDR_BG)
        cell.font = _font(COLOR_COL_HDR_FG, bold=True)
        cell.alignment = _center()
        cell.border = _border()

    for idx, (member_id, stats) in enumerate(records.items(), start=1):
        row = header_row + idx
        present = stats["present"]
        total = stats["total"]
        percentage = (present / total * 100) if total else 0.0
        bg = _tier_color(percentage)

        row_values = [idx, stats["name"], present, total, f"{percentage:.0f}%"]
        for col, value in enumerate(row_values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.fill = _fill(bg)
            cell.font = _font("000000", bold=(col == 2))
            cell.alignment = _center() if col != 2 else _left()
            cell.border = _border()

    ws.freeze_panes = f"A{header_row + 1}"
    wb.save(filepath)
    return filepath
