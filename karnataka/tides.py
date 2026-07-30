"""Open-Meteo sea_level_height_msl tide timing (Karnataka)."""
from coastal_common.tide_clocks import summary_with_clocks


def _fill_gaps(levels):
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


def compute_tide_timing(levels, start_idx=0, now_ist=None, window_hours=24):
    """
    Estimate high/low water from Open-Meteo marine sea_level_height_msl.

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
        "tide_summary": summary_with_clocks(
            now_ist, high_mins, low_mins, len(filled)
        ),
    }
