"""Shared public weather phrasing (no hPa / km/h jargon)."""
from coastal_common.risk import WAVE_ELEVATED_M, WAVE_HIGH_M, WIND_ELEVATED_KMH


def impact_trend_label(values, soft_threshold, strong_threshold, rising_word, falling_word):
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
    mean = float(wind_kmh or 0)
    gust = float(gust_kmh) if gust_kmh is not None else None
    gusty = (
        gust is not None
        and gust >= mean + 5
        and gust >= WIND_ELEVATED_KMH
    )

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
    _ = pressure
    parts = [
        f"Weather: {weather_condition_label(pressures_window, wave_m, risk_level)}",
        f"Wind: {wind_impact_label(wind, winds_window, gust_kmh=gust_kmh)}",
    ]
    sea = sea_condition_label(wave_m)
    if sea:
        parts.append(f"Sea: {sea}")
    return " | ".join(parts)
