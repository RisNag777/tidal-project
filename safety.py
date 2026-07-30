"""Coastal safety advisory pipeline (telemetry, AI, cache)."""
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from actions import apply_action_templates
from risk import (
    RISK_ADVISORY_TITLES,
    RISK_BOAT_SENTENCES,
    compute_risk_level,
    danger_label_for,
    normalize_risk_level,
)
from storage import CACHE_FILE, REGISTRY_FILE, STATIONS_FILE, load_json, save_json
from tides import compute_tide_timing
from weather import (
    apply_monsoon_overlay,
    build_weather_line,
    fetch_marine_bundle,
    in_monsoon_season,
    monsoon_overlay_block,
)

load_dotenv()

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")


def format_ist_time(now_ist):
    time_str = now_ist.strftime("%I:%M %p")
    return time_str[1:] if time_str.startswith("0") else time_str

def build_safety_prompt(station, telemetry, now_ist):
    loc = station["location_name"]
    risk_level = normalize_risk_level(telemetry["risk_level"])
    monsoon_block = monsoon_overlay_block(now_ist)
    monsoon_section = f"\n{monsoon_block}\n" if monsoon_block else "\n"
    monsoon_rule = (
        "- Include the monsoon alert lines exactly as shown; do not invent legal bans or fines.\n"
        "- Do not let the monsoon banner override the boat-risk sentence or invent stormier weather than the telemetry shows.\n"
        if monsoon_block else
        "- Do not invent a monsoon ban if no monsoon alert lines are shown.\n"
    )
    advisory_title = RISK_ADVISORY_TITLES[risk_level]
    danger_label = danger_label_for(station, risk_level)
    boat_sentence = RISK_BOAT_SENTENCES[risk_level]
    conditions_block = (
        f"{telemetry['weather_line']}\n"
        f"Tide: {telemetry['tide_summary']}\n"
        f"{boat_sentence}"
    )
    return f"""Write ONLY the coastal status header and conditions using EXACTLY this structure and line breaks. Do not use markdown.

🌊 Safety Status Update: {loc}
{monsoon_section}
{advisory_title}

Location: {loc}
Current Time: {telemetry['current_time']}

⚠️ {danger_label}

{conditions_block}

Rules:
- Copy the conditions block (weather, Tide, and boat-risk sentence) exactly as shown; do not rephrase numbers or invent stronger weather.
- Stop after the boat-risk sentence. Do not add audience sections, Stay safe, or emergency lines.
- Do not invent exact tide heights in feet or meters.
- Keep the whole reply concise for WhatsApp.
{monsoon_rule}- Keep the header lines exactly as shown, including the advisory title, location name, current time, and danger label.
- Use plain text only."""

# --- Registry logging ---
def update_station_registry(queried_location, target_station):
    registry = load_json(REGISTRY_FILE)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    current_entry = {
        "station_name": target_station["location_name"],
        "latitude": target_station["latitude"],
        "longitude": target_station["longitude"],
    }

    if queried_location not in registry:
        registry[queried_location] = {
            "first_queried_date": today_str,
            "history": [current_entry],
        }
        print(f"📝 Initialized tracking audit record for: {queried_location}")
        save_json(REGISTRY_FILE, registry)
        return

    last_recorded = registry[queried_location]["history"][-1]
    if last_recorded["station_name"] != target_station["location_name"]:
        registry[queried_location]["history"].append(current_entry)
        print(f"🚨 ALERT: Mapping change tracked for {queried_location} -> {target_station['location_name']}")
        save_json(REGISTRY_FILE, registry)

def transcribe_audio_via_sarvam(audio_url):
    """Download a Twilio recording and translate Kannada/Tulu speech to English."""
    response = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    if response.status_code != 200:
        return ""

    filename = "temp_voice.ogg"
    with open(filename, "wb") as handle:
        handle.write(response.content)

    try:
        url = "https://api.sarvam.ai/speech-to-text"
        headers = {"api-subscription-key": SARVAM_API_KEY}
        with open(filename, "rb") as audio_file:
            files = {"file": (filename, audio_file, "audio/ogg")}
            data = {"model": "saaras:v3", "mode": "translate"}
            api_resp = requests.post(url, headers=headers, files=files, data=data)
        if api_resp.status_code == 200:
            return api_resp.json().get("transcript", "")
        return ""
    finally:
        if os.path.exists(filename):
            os.remove(filename)

def match_station_locally(user_text):
    stations = load_json(STATIONS_FILE)
    clean_input = user_text.lower().strip()
    for station in stations:
        core_keyword = station["location_name"].lower().split()[0]
        if core_keyword in clean_input:
            return station
    return None

def process_coastal_safety(station, audience=None):
    cache = load_json(CACHE_FILE)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    loc = station["location_name"]
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    in_monsoon = in_monsoon_season(now_ist)

    params = {
        "latitude": float(station["latitude"]),
        "longitude": float(station["longitude"]),
        "hourly": "surface_pressure,wind_speed_10m,wind_gusts_10m",
        "timezone": "Asia/Kolkata",
        "forecast_days": 2,
    }
    api_response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params=params,
        timeout=20,
    ).json()

    times = api_response["hourly"]["time"]
    pressures = api_response["hourly"]["surface_pressure"]
    wind_speeds = api_response["hourly"]["wind_speed_10m"]
    wind_gusts = api_response["hourly"].get("wind_gusts_10m") or []

    current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(current_hour_str)
    except ValueError:
        idx = 0

    target_pressures = pressures[idx:idx + 12]
    target_winds = wind_speeds[idx:idx + 12]
    current_wind = float(target_winds[0])
    current_gust = None
    if wind_gusts and idx < len(wind_gusts) and wind_gusts[idx] is not None:
        current_gust = float(wind_gusts[idx])
    marine = fetch_marine_bundle(
        station["latitude"], station["longitude"], now_ist
    )
    current_wave = marine["wave_m"]
    risk_level = compute_risk_level(current_wind, current_wave, in_monsoon)
    if not marine["sea_levels"]:
        print("⚠️ sea_level_height_msl unavailable; tide timing uncertain.")
    tide_timing = compute_tide_timing(
        marine["sea_levels"] or [],
        marine["sea_idx"],
        now_ist=now_ist,
    )

    cached = cache.get(loc) or {}
    conditions = cached.get("conditions")
    if (
        cached.get("date") == today_str
        and cached.get("risk_level") == risk_level
        and conditions
    ):
        print(
            f"💰 Cost Avoided! Reusing cached conditions "
            f"(risk={risk_level}, audience={audience or 'summary'})."
        )
        conditions = apply_monsoon_overlay(conditions, now_ist)
        return apply_action_templates(
            conditions, station, risk_level, audience=audience
        )

    telemetry = {
        "current_time": format_ist_time(now_ist),
        "weather_line": build_weather_line(
            float(target_pressures[0]),
            target_pressures,
            current_wind,
            target_winds,
            current_wave,
            gust_kmh=current_gust,
            risk_level=risk_level,
        ),
        "tide_summary": tide_timing["tide_summary"],
        "risk_level": risk_level,
    }

    prompt = build_safety_prompt(station, telemetry, now_ist)
    payload = {
        "model": "sarvam-105b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 320,
        "reasoning_effort": None,
    }
    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": SARVAM_API_KEY,
    }
    ai_response = requests.post(
        "https://api.sarvam.ai/v1/chat/completions",
        headers=headers,
        json=payload,
    )
    ai_response.raise_for_status()
    conditions = ai_response.json()["choices"][0]["message"]["content"]
    conditions = apply_monsoon_overlay(conditions, now_ist)

    cache[loc] = {
        "date": today_str,
        "risk_level": risk_level,
        "conditions": conditions,
    }
    save_json(CACHE_FILE, cache)
    return apply_action_templates(
        conditions, station, risk_level, audience=audience
    )
