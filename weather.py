"""Open-Meteo fetches, monsoon overlay, and public weather phrasing."""
import requests

from risk import WAVE_ELEVATED_M, WAVE_HIGH_M, WIND_ELEVATED_KMH

# Karnataka coastal monsoon safety window (district-style seasonal ban period)
MONSOON_START = (5, 16)   # May 16
MONSOON_END = (9, 25)     # September 25

def in_monsoon_season(now_ist):
    month_day = (now_ist.month, now_ist.day)
    return MONSOON_START <= month_day <= MONSOON_END

def monsoon_overlay_block(now_ist):
    if not in_monsoon_season(now_ist):
        return ""
    return (
        "⛔ MONSOON (May 16–Sep 25): Treat water access as high risk. "
        "Follow district orders and red flags."
    )

def apply_monsoon_overlay(advisory, now_ist):
    """Insert the monsoon banner after the advisory header when in season."""
    block = monsoon_overlay_block(now_ist)
    if not block or "MONSOON" in advisory:
        return advisory

    lines = advisory.split("\n", 1)
    header = lines[0]
    rest = lines[1].lstrip("\n") if len(lines) > 1 else ""
    if rest:
        return f"{header}\n\n{block}\n\n{rest}"
    return f"{header}\n\n{block}"

def fetch_marine_bundle(latitude, longitude, now_ist):
    """
    Open-Meteo marine: current wave height + hourly sea_level_height_msl.
    Returns {"wave_m": float|None, "sea_levels": list|None, "sea_idx": int}.
    """
    empty = {"wave_m": None, "sea_levels": None, "sea_idx": 0}
    try:
        response = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": float(latitude),
                "longitude": float(longitude),
                "hourly": "wave_height,sea_level_height_msl",
                "timezone": "Asia/Kolkata",
                "forecast_days": 3,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        times = payload["hourly"]["time"]
        heights = payload["hourly"]["wave_height"]
        sea_levels = payload["hourly"].get("sea_level_height_msl")
        current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
        try:
            idx = times.index(current_hour_str)
        except ValueError:
            idx = 0
        wave_m = None
        if idx < len(heights) and heights[idx] is not None:
            wave_m = float(heights[idx])
        if not sea_levels:
            return {"wave_m": wave_m, "sea_levels": None, "sea_idx": idx}
        return {
            "wave_m": wave_m,
            "sea_levels": sea_levels,
            "sea_idx": idx,
        }
    except Exception as exc:
        print(f"⚠️ Marine fetch failed: {exc}")
        return empty

def impact_trend_label(values, soft_threshold, strong_threshold, rising_word, falling_word):
    """Layperson trend label: Rising / Rising fast / Falling / Falling fast / Steady."""
    if len(values) < 2:
        return "Steady"
    delta = values[-1] - values[0]
    if delta >= strong_threshold:
        return f"{rising_word} fast"
    if delta > soft_threshold:
        return rising_word
    if delta <= -strong_threshold:
        return f"{falling_word} fast"
    if delta < -soft_threshold:
        return falling_word
    return "Steady"

def wind_impact_label(wind_kmh, winds_window, gust_kmh=None):
    """Plain-language wind for the public — no km/h or 'gusts N' jargon."""
    mean = float(wind_kmh or 0)
    gust = float(gust_kmh) if gust_kmh is not None else None
    gusty = (
        gust is not None
        and gust >= mean + 5
        and gust >= WIND_ELEVATED_KMH
    )

    # Light mean + punchy gusts: the burst is the hazard, not a fake trend.
    if mean < WIND_ELEVATED_KMH and gusty:
        return "sudden strong wind bursts"

    if mean < 5:
        return "light"
    if mean < WIND_ELEVATED_KMH:
        return "gentle"

    trend = impact_trend_label(winds_window, 2.0, 8.0, "Rising", "Easing")
    if gusty:
        if "Rising" in trend:
            return "strong, building, with sudden bursts"
        if "Easing" in trend:
            return "still strong with sudden bursts"
        return "strong with sudden bursts"
    if trend == "Rising fast":
        return "strong and building fast"
    if trend == "Rising":
        return "strong and building"
    if trend == "Easing fast":
        return "strong but easing"
    if trend == "Easing":
        return "strong but easing"
    return "strong"

def weather_condition_label(pressures_window, wave_m=None, risk_level=None):
    """Public weather phrase — no hPa / meteorologist jargon."""
    pressure_trend = impact_trend_label(
        pressures_window, 0.5, 2.0, "Rising", "Falling"
    )
    rough_sea = wave_m is not None and wave_m >= WAVE_HIGH_M
    choppy_sea = wave_m is not None and wave_m >= WAVE_ELEVATED_M

    if pressure_trend == "Falling fast" or (
        pressure_trend == "Falling" and rough_sea
    ):
        return "Storm conditions developing"
    if pressure_trend == "Falling" or rough_sea:
        return "Rough conditions building"
    if choppy_sea or risk_level == "elevated":
        return "Caution — seas unsettled"
    if "Rising" in pressure_trend:
        return "Conditions easing"
    return "Conditions relatively calm"

def sea_condition_label(wave_m):
    if wave_m is None:
        return None
    if wave_m >= WAVE_HIGH_M:
        return "rough"
    if wave_m >= WAVE_ELEVATED_M:
        return "choppy"
    return "moderate"

def build_weather_line(
    pressure, pressures_window, wind, winds_window, wave_m, gust_kmh=None, risk_level=None
):
    # pressure arg kept for call-site compatibility; not shown to the public.
    _ = pressure
    parts = [
        f"Weather: {weather_condition_label(pressures_window, wave_m, risk_level)}",
        f"Wind: {wind_impact_label(wind, winds_window, gust_kmh=gust_kmh)}",
    ]
    sea = sea_condition_label(wave_m)
    if sea:
        parts.append(f"Sea: {sea}")
    return " | ".join(parts)
