from datetime import timedelta

# Chaotic high-water window: roughly 2 hours after peak.
HIGH_WATER_END_MINUTES = 2 * 60


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


def _fill_gaps(levels):
    """Interpolate None holes from nearest neighbors."""
    filled = [
        None if value is None else float(value)
        for value in levels
    ]
    for index, value in enumerate(filled):
        if value is not None:
            continue
        left = next(
            (filled[j] for j in range(index - 1, -1, -1) if filled[j] is not None),
            None,
        )
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
    return filled


def _local_extrema(values):
    """Relative indices of local highs and lows."""
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

    `levels` is an hourly series; `start_idx` is the current hour.

    Note: astronomical tide tables ignore weather setup (low pressure,
    onshore wind, cyclone surge, monsoon runoff). This marine series is
    modeled, not official SOI — still treat clocks as approximate.
    """
    uncertain = {
        "tide_summary": "Tide timing uncertain — use local shoreline markers.",
    }
    if not levels or now_ist is None:
        return uncertain

    filled = _fill_gaps(levels[start_idx:start_idx + window_hours])
    if sum(1 for value in filled if value is not None) < 3:
        return uncertain

    highs, lows = _local_extrema(filled)
    # Falling start ≈ high now; rising start ≈ low now.
    if filled[0] is not None and filled[1] is not None:
        if filled[0] >= filled[1] and 0 not in highs:
            highs = [0] + highs
        if filled[0] <= filled[1] and 0 not in lows:
            lows = [0] + lows

    next_high = _first_at_or_after(highs)
    next_low = _first_at_or_after(lows)
    if next_high is None:
        next_high = filled.index(max(v for v in filled if v is not None))
    if next_low is None:
        next_low = filled.index(min(v for v in filled if v is not None))

    if next_high == next_low:
        return {"tide_summary": "No clear high/low signal in the next day."}

    high_mins = next_high * 60
    low_mins = next_low * 60
    return {
        "tide_summary": _summary_with_clocks(
            now_ist, high_mins, low_mins, len(filled)
        ),
    }
