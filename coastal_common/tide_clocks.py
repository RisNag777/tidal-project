"""Shared tide clock formatting helpers."""
from datetime import timedelta

HIGH_WATER_END_MINUTES = 2 * 60


def format_tide_clock_at(when):
    """Approximate clock label (~ half-hour) for an absolute datetime."""
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


def format_tide_clock(now, minutes):
    """Approximate clock label (~ half-hour) for now + minutes."""
    return format_tide_clock_at(now + timedelta(minutes=minutes))


def high_until_minutes(high_mins, low_mins, window_hours):
    """End of high water: ~2h after peak, not past midpoint toward low."""
    end = high_mins + HIGH_WATER_END_MINUTES
    if low_mins is not None and low_mins > high_mins:
        midpoint = high_mins + (low_mins - high_mins) // 2
        end = min(end, midpoint)
    max_mins = max((window_hours - 1) * 60, 0)
    return min(end, max_mins)


def summary_with_clocks(now, high_mins, low_mins, window_hours):
    high_clock = format_tide_clock(now, high_mins)
    low_clock = format_tide_clock(now, low_mins)
    until_clock = format_tide_clock(
        now, high_until_minutes(high_mins, low_mins, window_hours)
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


def high_until_clock(high_when, low_when):
    end = high_when + timedelta(minutes=HIGH_WATER_END_MINUTES)
    if low_when is not None and low_when > high_when:
        midpoint = high_when + (low_when - high_when) / 2
        if midpoint < end:
            end = midpoint
    return format_tide_clock_at(end)
