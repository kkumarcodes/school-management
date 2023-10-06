""" Little methods to help with formatting and content in texts and emails
"""
import pytz
from datetime import datetime
from cwnotifications.constants.timezone_abbreviations import TIMEZONE_ABBREVIATIONS


def format_datetime(dt: datetime, timezone: str) -> str:
    """ Display a date and time in a set timezone, and indicate timezone abbreviation
        If we don't have an abbreviation for the timzone provided, then we just return a date and not time
    """
    tz = pytz.timezone(timezone)
    if timezone in TIMEZONE_ABBREVIATIONS:
        return f"{dt.astimezone(tz).strftime('%b %d')} at {dt.astimezone(tz).strftime('%-I:%M%p')} {TIMEZONE_ABBREVIATIONS[timezone]}"
    return f"{dt.astimezone(tz).strftime('%b %d')}"
