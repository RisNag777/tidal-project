"""NOAA CO-OPS high/low tide timing for PNW stations."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from coastal_common.tide_clocks import format_tide_clock_at, high_until_clock

PACIFIC = ZoneInfo("America/Los_Angeles")
UNCERTAIN = {
    "tide_summary": "Tide timing uncertain — use local shoreline markers.",
}


def _parse_noaa_time(value):
    naive = datetime.strptime(value, "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=PACIFIC)


def fetch_noaa_hilo(station_id, now_pt, days=2):
    """
    Return list of {"when": datetime, "type": "H"|"L", "v": height_str}.

    Note: NOAA predictions are astronomical. Weather setup (low pressure,
    onshore wind, river runoff) can raise or lower actual water vs the table.
    """
    begin = now_pt.strftime("%Y%m%d")
    end = (now_pt + timedelta(days=days)).strftime("%Y%m%d")
    response = requests.get(
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
        params={
            "product": "predictions",
            "application": "tidal-project-pnw",
            "begin_date": begin,
            "end_date": end,
            "datum": "MLLW",
            "station": str(station_id),
            "time_zone": "lst_ldt",
            "units": "english",
            "interval": "hilo",
            "format": "json",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(payload["error"].get("message", "NOAA error"))
    events = []
    for row in payload.get("predictions") or []:
        kind = (row.get("type") or "").upper()
        if kind not in ("H", "L"):
            continue
        events.append(
            {
                "when": _parse_noaa_time(row["t"]),
                "type": kind,
                "v": row.get("v"),
            }
        )
    return events


def compute_tide_timing_from_hilo(events, now_pt):
    if not events or now_pt is None:
        return UNCERTAIN

    upcoming = [event for event in events if event["when"] >= now_pt - timedelta(minutes=20)]
    if not upcoming:
        return UNCERTAIN

    adjusted = []
    for event in upcoming:
        delta = abs((event["when"] - now_pt).total_seconds())
        if delta <= 20 * 60:
            adjusted.append({**event, "when": now_pt})
        else:
            adjusted.append(event)
    upcoming = adjusted

    next_high = next((e for e in upcoming if e["type"] == "H"), None)
    next_low = next((e for e in upcoming if e["type"] == "L"), None)
    if next_high is None and next_low is None:
        return UNCERTAIN

    if next_high is None:
        after = [e for e in upcoming if e["when"] > next_low["when"] and e["type"] == "H"]
        next_high = after[0] if after else None
    if next_low is None:
        after = [e for e in upcoming if e["when"] > next_high["when"] and e["type"] == "L"]
        next_low = after[0] if after else None

    if next_high is None or next_low is None:
        return {"tide_summary": "No clear high/low signal in the next day."}

    high_mins = max(int((next_high["when"] - now_pt).total_seconds() // 60), 0)
    low_mins = max(int((next_low["when"] - now_pt).total_seconds() // 60), 0)

    high_clock = format_tide_clock_at(next_high["when"])
    low_clock = format_tide_clock_at(next_low["when"])
    until_clock = high_until_clock(next_high["when"], next_low["when"])

    if high_mins == 0:
        summary = (
            f"Peak High now ({high_clock}), high until {until_clock} "
            f"| Next Low {low_clock}"
        )
    elif low_mins == 0:
        summary = (
            f"Peak Low now ({low_clock}) | Next High {high_clock}, "
            f"high until {until_clock}"
        )
    elif high_mins < low_mins:
        summary = (
            f"Peak High {high_clock}, high until {until_clock} "
            f"| Next Low {low_clock}"
        )
    else:
        summary = (
            f"Peak Low {low_clock} | Next High {high_clock}, "
            f"high until {until_clock}"
        )
    return {"tide_summary": summary, "source": "noaa"}


def tide_timing_for_station(station, now_pt):
    station_id = station.get("noaa_station_id")
    if not station_id:
        return UNCERTAIN
    try:
        events = fetch_noaa_hilo(station_id, now_pt)
        return compute_tide_timing_from_hilo(events, now_pt)
    except Exception as exc:
        print(f"⚠️ NOAA tide fetch failed ({station_id}): {exc}")
        return UNCERTAIN
