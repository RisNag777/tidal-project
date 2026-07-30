"""Open-Meteo forecast and marine wave helpers."""
import requests


def fetch_forecast_hourly(latitude, longitude, timezone, forecast_days=2):
    """Return hourly surface_pressure, wind_speed_10m, wind_gusts_10m, time."""
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": float(latitude),
            "longitude": float(longitude),
            "hourly": "surface_pressure,wind_speed_10m,wind_gusts_10m",
            "timezone": timezone,
            "forecast_days": forecast_days,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["hourly"]


def fetch_wave_height_m(latitude, longitude, now_local, timezone):
    """Current significant wave height (m); None if unavailable."""
    try:
        response = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": float(latitude),
                "longitude": float(longitude),
                "hourly": "wave_height",
                "timezone": timezone,
                "forecast_days": 2,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        times = payload["hourly"]["time"]
        heights = payload["hourly"]["wave_height"]
        current_hour_str = now_local.strftime("%Y-%m-%dT%H:00")
        try:
            idx = times.index(current_hour_str)
        except ValueError:
            idx = 0
        if idx < len(heights) and heights[idx] is not None:
            return float(heights[idx])
        return None
    except Exception as exc:
        print(f"⚠️ Marine wave fetch failed: {exc}")
        return None


def fetch_marine_sea_levels(latitude, longitude, now_local, timezone, forecast_days=3):
    """
    Wave height + sea_level_height_msl series.
    Returns {"wave_m", "sea_levels", "sea_idx"}.
    """
    empty = {"wave_m": None, "sea_levels": None, "sea_idx": 0}
    try:
        response = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": float(latitude),
                "longitude": float(longitude),
                "hourly": "wave_height,sea_level_height_msl",
                "timezone": timezone,
                "forecast_days": forecast_days,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        times = payload["hourly"]["time"]
        heights = payload["hourly"]["wave_height"]
        sea_levels = payload["hourly"].get("sea_level_height_msl")
        current_hour_str = now_local.strftime("%Y-%m-%dT%H:00")
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


def current_hour_index(times, now_local):
    current_hour_str = now_local.strftime("%Y-%m-%dT%H:00")
    try:
        return times.index(current_hour_str)
    except ValueError:
        return 0
