from datetime import timedelta

# Approximate half-cycle between high and low on the Indian west coast.
SEMI_DIURNAL_MINUTES = 6 * 60 + 12


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
    """Approximate clock label (~ half-hour), not a false precision timestamp."""
    when = now_ist + timedelta(minutes=minutes)
    # Round to nearest 30 minutes so pressure-bucket math does not look exact.
    total_mins = when.hour * 60 + when.minute
    rounded = int(round(total_mins / 30.0) * 30)
    if rounded >= 24 * 60:
        when = when.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        when = when.replace(
            hour=rounded // 60, minute=rounded % 60, second=0, microsecond=0
        )
    label = when.strftime("%I:%M %p")
    if label.startswith("0"):
        label = label[1:]
    return f"~{label}"


def _companion_minutes(peak_mins, window_hours):
    """Next opposite tide ~6h12 after a peak, capped to the forecast window."""
    companion = peak_mins + SEMI_DIURNAL_MINUTES
    max_mins = (window_hours - 1) * 60
    if companion > max_mins:
        return None
    return companion


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
        if highest_idx == 0:
            companion = _companion_minutes(0, window_hours)
            if companion is not None:
                low_clock = format_tide_clock(now_ist, companion)
            else:
                low_clock = format_tide_clock(now_ist, low_mins)
            return {
                "tide_summary": f"Peak High now ({high_clock}) | Next Low {low_clock}",
            }
        if lowest_idx == 0:
            companion = _companion_minutes(0, window_hours)
            if companion is not None:
                high_clock = format_tide_clock(now_ist, companion)
            else:
                high_clock = format_tide_clock(now_ist, high_mins)
            low_clock = format_tide_clock(now_ist, 0)
            return {
                "tide_summary": f"Peak Low now ({low_clock}) | Next High {high_clock}",
            }
        if high_mins < low_mins:
            companion = _companion_minutes(high_mins, window_hours)
            low_clock = format_tide_clock(
                now_ist, companion if companion is not None else low_mins
            )
            return {
                "tide_summary": f"Peak High {high_clock} | Next Low {low_clock}",
            }
        companion = _companion_minutes(low_mins, window_hours)
        high_clock = format_tide_clock(
            now_ist, companion if companion is not None else high_mins
        )
        low_clock = format_tide_clock(now_ist, low_mins)
        return {
            "tide_summary": f"Peak Low {low_clock} | Next High {high_clock}",
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
