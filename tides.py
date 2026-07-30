from datetime import timedelta

# Chaotic high-water window: roughly 2 hours after peak.
HIGH_WATER_END_MINUTES = 2 * 60


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


def _clean_levels(levels):
    cleaned = []
    for value in levels:
        if value is None:
            cleaned.append(None)
        else:
            cleaned.append(float(value))
    return cleaned


def _local_extrema(values):
    """Return relative indices of local highs and lows (ignore None gaps)."""
    highs = []
    lows = []
    for index in range(1, len(values) - 1):
        prev_val, cur_val, next_val = values[index - 1], values[index], values[index + 1]
        if None in (prev_val, cur_val, next_val):
            continue
        if cur_val >= prev_val and cur_val >= next_val:
            highs.append(index)
        if cur_val <= prev_val and cur_val <= next_val:
            lows.append(index)
    return highs, lows


def _first_at_or_after(indices, minimum=0):
    for index in indices:
        if index >= minimum:
            return index
    return None


def _high_until_minutes(high_mins, low_mins, window_hours):
    """End of high water: ~2h after peak, not past the midpoint toward low."""
    end = high_mins + HIGH_WATER_END_MINUTES
    if low_mins is not None and low_mins > high_mins:
        midpoint = high_mins + (low_mins - high_mins) // 2
        end = min(end, midpoint)
    max_mins = max((window_hours - 1) * 60, 0)
    return min(end, max_mins)


def _summary_with_clocks(now_ist, high_mins, low_mins, window_hours):
    high_clock = format_tide_clock(now_ist, high_mins)
    low_clock = format_tide_clock(now_ist, low_mins)
    until_clock = format_tide_clock(
        now_ist, _high_until_minutes(high_mins, low_mins, window_hours)
    )
    if high_mins == 0:
        return (
            f"Peak High now ({high_clock}), high until {until_clock} "
            f"| Next Low {low_clock}"
        )
    if low_mins == 0:
        return (
            f"Peak Low now ({low_clock}) | Next High {high_clock}, "
            f"high until {until_clock}"
        )
    if high_mins < low_mins:
        return (
            f"Peak High {high_clock}, high until {until_clock} "
            f"| Next Low {low_clock}"
        )
    return (
        f"Peak Low {low_clock} | Next High {high_clock}, "
        f"high until {until_clock}"
    )


def compute_tide_timing(levels, start_idx=0, now_ist=None, window_hours=24):
    """
    Estimate high/low water from Open-Meteo marine sea_level_height_msl.

    `levels` should be an hourly series; `start_idx` is the current hour.
    Falls back gracefully if the series is too short or flat.
    """
    series = _clean_levels(levels[start_idx:start_idx + window_hours])
    usable = [value for value in series if value is not None]
    if len(usable) < 3:
        return {
            "tide_summary": "Tide timing uncertain — use local shoreline markers.",
            "source": "unavailable",
        }

    # Fill tiny gaps with neighbors so extrema detection stays stable.
    filled = list(series)
    for index, value in enumerate(filled):
        if value is not None:
            continue
        left = next((filled[j] for j in range(index - 1, -1, -1) if filled[j] is not None), None)
        right = next(
            (filled[j] for j in range(index + 1, len(filled)) if filled[j] is not None),
            None,
        )
        if left is not None and right is not None:
            filled[index] = (left + right) / 2.0
        elif left is not None:
            filled[index] = left
        elif right is not None:
            filled[index] = right

    highs, lows = _local_extrema(filled)
    # Treat a falling start as high-now / rising start as low-now when useful.
    if filled[0] is not None and filled[1] is not None:
        if filled[0] >= filled[1] and 0 not in highs:
            highs = [0] + highs
        if filled[0] <= filled[1] and 0 not in lows:
            lows = [0] + lows

    next_high = _first_at_or_after(highs, 0)
    next_low = _first_at_or_after(lows, 0)

    if next_high is None and next_low is None:
        # Last resort: window max/min (legacy pressure-style fallback).
        next_high = filled.index(max(filled))
        next_low = filled.index(min(filled))

    if next_high is None:
        next_high = filled.index(max(filled))
    if next_low is None:
        next_low = filled.index(min(filled))

    if next_high == next_low:
        return {
            "tide_summary": "No clear high/low signal in the next day.",
            "source": "sea_level",
        }

    high_mins = next_high * 60
    low_mins = next_low * 60

    if now_ist is not None:
        return {
            "tide_summary": _summary_with_clocks(
                now_ist, high_mins, low_mins, len(filled)
            ),
            "source": "sea_level",
            "high_mins": high_mins,
            "low_mins": low_mins,
        }

    if next_high == 0:
        tide_summary = (
            f"High water conditions are likely now. "
            f"Low water expected {format_eta(low_mins)}."
        )
    elif next_low == 0:
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

    return {
        "tide_summary": tide_summary,
        "source": "sea_level",
        "high_mins": high_mins,
        "low_mins": low_mins,
    }
