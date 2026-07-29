from datetime import timedelta


def format_eta(minutes):
    if minutes == 0:
        return "now"
    if minutes < 60:
        return f"in about {minutes} minutes"
    hours, rem = divmod(minutes, 60)
    hour_label = "hour" if hours == 1 else "hours"
    if rem == 0:
        return f"in about {hours} {hour_label}"
    return f"in about {hours} {hour_label} {rem} minutes"


def format_tide_clock(now_ist, minutes):
    """Clock label for an offset from now (pressure-based estimate)."""
    when = now_ist + timedelta(minutes=minutes)
    label = when.strftime("%I:%M %p")
    return label[1:] if label.startswith("0") else label


def compute_tide_timing(pressures, start_idx, now_ist=None, window_hours=12):
    """Estimate high/low water from Open-Meteo surface-pressure trends."""
    window = pressures[start_idx:start_idx + window_hours]
    if len(window) < 3:
        return {
            "tide_summary": "Tide timing uncertain — use local shoreline markers.",
        }

    highest_idx = window.index(max(window))
    lowest_idx = window.index(min(window))
    high_mins = highest_idx * 60
    low_mins = lowest_idx * 60

    if highest_idx == lowest_idx:
        return {
            "tide_summary": "No clear high/low signal in the next 12 hours.",
        }

    # Prefer explicit peak clocks when we have a current timestamp.
    if now_ist is not None:
        high_clock = format_tide_clock(now_ist, high_mins)
        low_clock = format_tide_clock(now_ist, low_mins)
        if highest_idx == 0:
            return {
                "tide_summary": f"Peak High now (~{high_clock}) | Next Low at {low_clock}",
            }
        if lowest_idx == 0:
            return {
                "tide_summary": f"Peak Low now (~{low_clock}) | Next High at {high_clock}",
            }
        if high_mins < low_mins:
            return {
                "tide_summary": f"Peak High at {high_clock} | Next Low at {low_clock}",
            }
        return {
            "tide_summary": f"Peak Low at {low_clock} | Next High at {high_clock}",
        }

    if highest_idx == 0:
        tide_summary = (
            f"High water conditions are likely now. "
            f"Low water expected {format_eta(low_mins)}."
        )
    elif lowest_idx == 0:
        tide_summary = (
            f"Low water conditions are likely now. "
            f"High water expected {format_eta(high_mins)}."
        )
    elif high_mins < low_mins:
        tide_summary = (
            f"High water expected {format_eta(high_mins)}, "
            f"then low water expected {format_eta(low_mins)}."
        )
    else:
        tide_summary = (
            f"Low water expected {format_eta(low_mins)}, "
            f"then high water expected {format_eta(high_mins)}."
        )

    return {"tide_summary": tide_summary}
