import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
TIDES_FILE = Path(__file__).resolve().parent / "data" / "soi_tides.json"


def _meters_to_feet(height_m):
    return round(height_m * 3.28084, 1)


def format_tide_clock(event):
    height_m = event.get("height_m")
    if height_m is None and "height" in event:
        height_m = event["height"]

    if "date" in event and "time" in event and ":" in str(event.get("time", "")):
        time_label = event["time"]
        if time_label.startswith("0"):
            time_label = time_label[1:]
    else:
        tide_time = _parse_tide_time(event["date"])
        time_label = tide_time.strftime("%I:%M %p")
        if time_label.startswith("0"):
            time_label = time_label[1:]

    # Pressure fallback has no real height — avoid printing "0.0 ft / 0.00m".
    if height_m is None:
        return time_label
    return f"{time_label} ({_meters_to_feet(height_m)} ft / {height_m:.2f}m)"


def _parse_tide_time(date_str):
    normalized = date_str.replace("Z", "+00:00")
    if len(normalized) >= 5 and normalized[-5] in "+-" and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    return datetime.fromisoformat(normalized).astimezone(IST)


def _event_datetime(event):
    if "date" in event and "time" in event:
        return datetime.strptime(
            f"{event['date']} {event['time']}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=IST)
    return _parse_tide_time(event["date"])


def _minutes_until(now_ist, event):
    return int((_event_datetime(event) - now_ist).total_seconds() // 60)


def _load_soi_tides():
    try:
        with open(TIDES_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _resolve_soi_port(station):
    if station.get("soi_pdf_port"):
        return station["soi_pdf_port"].upper()
    reference = (station.get("soi_reference_port") or "").lower()
    if "karwar" in reference:
        return "KARWAR"
    if "mangal" in reference:
        return "MANGLORE"
    if "gang" in reference or "bhatkal" in reference:
        return "GANGRA"
    return None


def _summarize_soi_tides(station, now_ist):
    payload = _load_soi_tides()
    if not payload:
        return None

    port_code = _resolve_soi_port(station)
    if not port_code:
        return None

    current_month = now_ist.strftime("%Y-%m")
    if payload.get("month") != current_month:
        return None

    port_data = (payload.get("ports") or {}).get(port_code)
    if not port_data:
        return None

    events = port_data.get("events") or []
    if not events:
        return None

    parsed = []
    for event in events:
        tide_time = _event_datetime(event)
        if tide_time >= now_ist - timedelta(hours=6):
            parsed.append({**event, "tide_time": tide_time})

    if not parsed:
        return None

    parsed.sort(key=lambda item: item["tide_time"])
    future = [event for event in parsed if event["tide_time"] >= now_ist]
    next_high = next((event for event in future if event["type"] == "high"), None)
    next_low = next((event for event in future if event["type"] == "low"), None)

    today = now_ist.date()
    tomorrow = today + timedelta(days=1)
    today_highs = [
        event for event in parsed
        if event["type"] == "high" and event["tide_time"].date() == today
    ]
    today_lows = [
        event for event in parsed
        if event["type"] == "low" and event["tide_time"].date() == today
    ]
    tomorrow_highs = [
        event for event in parsed
        if event["type"] == "high" and event["tide_time"].date() == tomorrow
    ]
    tomorrow_lows = [
        event for event in parsed
        if event["type"] == "low" and event["tide_time"].date() == tomorrow
    ]

    clock_parts = []
    if next_high:
        mins = _minutes_until(now_ist, next_high)
        if mins <= 45:
            clock_parts.append(
                f"Approaching high tide at {format_tide_clock(next_high)}"
            )
        else:
            clock_parts.append(f"Next high: {format_tide_clock(next_high)}")
    if next_low:
        clock_parts.append(f"Next low: {format_tide_clock(next_low)}")

    ref_port = station.get("soi_reference_port", port_code.title())
    tide_clock_line = (
        " | ".join(clock_parts)
        if clock_parts
        else "Tide data unavailable — use local markers."
    )
    return {
        "source": "survey_of_india",
        "soi_reference_port": ref_port,
        "soi_pdf_port": port_code,
        "tide_month": payload.get("month"),
        "tide_clock_line": f"{tide_clock_line} (SOI: {port_code})",
        "tide_summary": tide_clock_line,
        "today_highs": today_highs,
        "today_lows": today_lows,
        "tomorrow_highs": tomorrow_highs,
        "tomorrow_lows": tomorrow_lows,
        "next_high": next_high,
        "next_low": next_low,
    }


def _summarize_pressure_tides(pressures, start_idx, now_ist):
    window = pressures[start_idx:start_idx + 12]
    if len(window) < 3:
        return {
            "source": "pressure_fallback",
            "tide_clock_line": "Tide timing uncertain — use local shoreline markers.",
            "tide_summary": "Tide timing is uncertain due to limited forecast data.",
            "today_highs": [],
            "today_lows": [],
            "tomorrow_highs": [],
            "tomorrow_lows": [],
        }

    highest_idx = window.index(max(window))
    lowest_idx = window.index(min(window))
    high_time = now_ist + timedelta(hours=highest_idx)
    low_time = now_ist + timedelta(hours=lowest_idx)

    def pseudo_event(when, tide_type):
        return {
            "date": when.strftime("%Y-%m-%d"),
            "time": when.strftime("%H:%M"),
            "height_m": None,
            "type": tide_type,
            "tide_time": when,
        }

    today_highs = [pseudo_event(high_time, "high")] if highest_idx == 0 else []
    today_lows = [pseudo_event(low_time, "low")] if lowest_idx == 0 else []
    next_high = None if highest_idx == 0 else pseudo_event(high_time, "high")
    next_low = None if lowest_idx == 0 else pseudo_event(low_time, "low")

    parts = []
    if next_high:
        parts.append(f"Next high (est.): {format_tide_clock(next_high)}")
    elif today_highs:
        parts.append(f"High water likely now ({format_tide_clock(today_highs[0])})")
    if next_low:
        parts.append(f"Next low (est.): {format_tide_clock(next_low)}")
    elif today_lows:
        parts.append(f"Low water likely now ({format_tide_clock(today_lows[0])})")

    summary = " | ".join(parts) if parts else "Tide timing is uncertain."
    if parts:
        summary += " Heights unavailable until Survey of India posts this month's tables."
    return {
        "source": "pressure_fallback",
        "tide_clock_line": summary,
        "tide_summary": summary,
        "today_highs": today_highs,
        "today_lows": today_lows,
        "tomorrow_highs": [],
        "tomorrow_lows": [],
        "next_high": next_high or (today_highs[0] if today_highs else None),
        "next_low": next_low or (today_lows[0] if today_lows else None),
    }


def build_tide_table(tide_context):
    lines = ["Today's tide times (Survey of India):"]
    if tide_context.get("today_highs"):
        for event in tide_context["today_highs"]:
            lines.append(f"- High: {format_tide_clock(event)}")
    if tide_context.get("today_lows"):
        for event in tide_context["today_lows"]:
            lines.append(f"- Low: {format_tide_clock(event)}")
    if not tide_context.get("today_highs") and not tide_context.get("today_lows"):
        lines.append("- See next tide times above.")

    if tide_context.get("tomorrow_highs") or tide_context.get("tomorrow_lows"):
        lines.append("Tomorrow:")
        for event in tide_context.get("tomorrow_highs", []):
            lines.append(f"- High: {format_tide_clock(event)}")
        for event in tide_context.get("tomorrow_lows", []):
            lines.append(f"- Low: {format_tide_clock(event)}")
    return "\n".join(lines)


def fetch_tide_context(station, now_ist, pressures=None, pressure_start_idx=0):
    soi_summary = _summarize_soi_tides(station, now_ist)
    if soi_summary:
        return soi_summary

    if pressures is not None:
        return _summarize_pressure_tides(pressures, pressure_start_idx, now_ist)

    return {
        "source": "unavailable",
        "tide_clock_line": "Tide timing unavailable — follow local shoreline markers.",
        "tide_summary": "Tide timing unavailable.",
        "today_highs": [],
        "today_lows": [],
        "tomorrow_highs": [],
        "tomorrow_lows": [],
    }
