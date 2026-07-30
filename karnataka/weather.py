"""Karnataka monsoon overlay + Open-Meteo marine sea-level bundle."""
from coastal_common.openmeteo import fetch_marine_sea_levels
from coastal_common.weather_labels import build_weather_line

TIMEZONE = "Asia/Kolkata"

MONSOON_START = (5, 16)   # May 16
MONSOON_END = (9, 25)     # September 25


def in_monsoon_season(now_ist):
    month_day = (now_ist.month, now_ist.day)
    return MONSOON_START <= month_day <= MONSOON_END


def monsoon_overlay_block(now_ist):
    if not in_monsoon_season(now_ist):
        return ""
    return (
        "⛔ MONSOON (May 16–Sep 25): Treat water access as high risk. "
        "Follow district orders and red flags."
    )


def apply_monsoon_overlay(advisory, now_ist):
    block = monsoon_overlay_block(now_ist)
    if not block or "MONSOON" in advisory:
        return advisory

    lines = advisory.split("\n", 1)
    header = lines[0]
    rest = lines[1].lstrip("\n") if len(lines) > 1 else ""
    if rest:
        return f"{header}\n\n{block}\n\n{rest}"
    return f"{header}\n\n{block}"


def fetch_marine_bundle(latitude, longitude, now_ist):
    return fetch_marine_sea_levels(
        latitude, longitude, now_ist, TIMEZONE, forecast_days=3
    )


__all__ = [
    "TIMEZONE",
    "in_monsoon_season",
    "monsoon_overlay_block",
    "apply_monsoon_overlay",
    "fetch_marine_bundle",
    "build_weather_line",
]
