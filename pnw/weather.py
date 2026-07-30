"""PNW winter storm-season overlay."""
from coastal_common.weather_labels import build_weather_line

TIMEZONE = "America/Los_Angeles"

STORM_SEASON_START = (10, 15)  # Oct 15
STORM_SEASON_END = (4, 15)     # Apr 15


def in_storm_season(now_pt):
    month_day = (now_pt.month, now_pt.day)
    return month_day >= STORM_SEASON_START or month_day <= STORM_SEASON_END


def storm_overlay_block(now_pt):
    if not in_storm_season(now_pt):
        return ""
    return (
        "⛔ WINTER STORM SEASON (Oct 15–Apr 15): Expect sneaker waves and "
        "cold-water risk. Follow beach flags and NWS / park closures."
    )


def apply_storm_overlay(advisory, now_pt):
    block = storm_overlay_block(now_pt)
    if not block or "WINTER STORM SEASON" in advisory:
        return advisory

    lines = advisory.split("\n", 1)
    header = lines[0]
    rest = lines[1].lstrip("\n") if len(lines) > 1 else ""
    if rest:
        return f"{header}\n\n{block}\n\n{rest}"
    return f"{header}\n\n{block}"


__all__ = [
    "TIMEZONE",
    "in_storm_season",
    "storm_overlay_block",
    "apply_storm_overlay",
    "build_weather_line",
]
