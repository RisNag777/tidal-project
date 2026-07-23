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


def compute_tide_timing(pressures, start_idx, window_hours=12):
    """Estimate high/low water from Open-Meteo surface-pressure trends."""
    window = pressures[start_idx:start_idx + window_hours]
    if len(window) < 3:
        return {
            "tide_summary": (
                "Tide timing is uncertain due to limited forecast data. "
                "Use local shoreline markers and harbor signals."
            ),
        }

    highest_idx = window.index(max(window))
    lowest_idx = window.index(min(window))
    high_mins = highest_idx * 60
    low_mins = lowest_idx * 60

    if highest_idx == lowest_idx:
        return {
            "tide_summary": (
                "No clear high or low water signal in the next 12 hours. "
                "Pressure appears steady; rely on local tide knowledge."
            ),
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
