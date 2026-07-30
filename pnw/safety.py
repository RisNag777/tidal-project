"""PNW coastal safety advisory pipeline (telemetry, OpenAI, cache)."""
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from coastal_common.bootstrap import ensure_repo_root_on_path
from coastal_common.openmeteo import current_hour_index, fetch_forecast_hourly, fetch_wave_height_m

ensure_repo_root_on_path(__file__)

from pnw.actions import apply_action_templates
from pnw.risk import (
    RISK_ADVISORY_TITLES,
    RISK_BOAT_SENTENCES,
    compute_risk_level,
    danger_label_for,
    normalize_risk_level,
)
from pnw.storage import CACHE_FILE, REGISTRY_FILE, STATIONS_FILE, load_json, save_json
from pnw.tides import tide_timing_for_station
from pnw.weather import (
    TIMEZONE,
    apply_storm_overlay,
    build_weather_line,
    in_storm_season,
    storm_overlay_block,
)

load_dotenv()

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")

PACIFIC = ZoneInfo(TIMEZONE)


def format_pt_time(now_pt):
    time_str = now_pt.strftime("%I:%M %p")
    return time_str[1:] if time_str.startswith("0") else time_str


def build_safety_prompt(station, telemetry, now_pt):
    loc = station["location_name"]
    risk_level = normalize_risk_level(telemetry["risk_level"])
    storm_block = storm_overlay_block(now_pt)
    storm_section = f"\n{storm_block}\n" if storm_block else "\n"
    storm_rule = (
        "- Include the winter storm-season alert lines exactly as shown; do not invent legal bans.\n"
        "- Do not let the storm banner override the boat-risk sentence or invent stormier weather than the telemetry shows.\n"
        if storm_block else
        "- Do not invent a winter storm-season ban if no storm alert lines are shown.\n"
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
{storm_section}
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
{storm_rule}- Keep the header lines exactly as shown, including the advisory title, location name, current time, and danger label.
- Use plain text only."""


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
        print(
            f"🚨 ALERT: Mapping change tracked for {queried_location} "
            f"-> {target_station['location_name']}"
        )
        save_json(REGISTRY_FILE, registry)


def transcribe_audio_via_openai(audio_url):
    if not OPENAI_API_KEY:
        print("⚠️ OPENAI_API_KEY missing; cannot transcribe audio.")
        return ""

    response = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    if response.status_code != 200:
        return ""

    filename = str(Path(__file__).resolve().parent / "temp_voice.ogg")
    with open(filename, "wb") as handle:
        handle.write(response.content)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(filename, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return (result.text or "").strip()
    except Exception as exc:
        print(f"⚠️ OpenAI Whisper failed: {exc}")
        return ""
    finally:
        if os.path.exists(filename):
            os.remove(filename)


def match_station_locally(user_text):
    stations = load_json(STATIONS_FILE)
    if not isinstance(stations, list):
        return None
    clean_input = user_text.lower().strip()
    for station in stations:
        core_keyword = station["location_name"].lower().split()[0]
        if core_keyword in clean_input:
            return station
    return None


def _generate_conditions_openai(prompt):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    completion = client.chat.completions.create(
        model=OPENAI_CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=320,
    )
    return completion.choices[0].message.content


def process_coastal_safety(station, audience=None):
    cache = load_json(CACHE_FILE)
    now_pt = datetime.now(PACIFIC)
    today_str = now_pt.strftime("%Y-%m-%d")
    loc = station["location_name"]
    stormy = in_storm_season(now_pt)

    hourly = fetch_forecast_hourly(
        station["latitude"], station["longitude"], TIMEZONE, forecast_days=2
    )
    times = hourly["time"]
    pressures = hourly["surface_pressure"]
    wind_speeds = hourly["wind_speed_10m"]
    wind_gusts = hourly.get("wind_gusts_10m") or []

    idx = current_hour_index(times, now_pt)
    target_pressures = pressures[idx:idx + 12]
    target_winds = wind_speeds[idx:idx + 12]
    current_wind = float(target_winds[0])
    current_gust = None
    if wind_gusts and idx < len(wind_gusts) and wind_gusts[idx] is not None:
        current_gust = float(wind_gusts[idx])

    current_wave = fetch_wave_height_m(
        station["latitude"], station["longitude"], now_pt, TIMEZONE
    )
    risk_level = compute_risk_level(
        current_wind, current_wave, seasonal_elevated=stormy
    )
    tide_timing = tide_timing_for_station(station, now_pt)

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
        conditions = apply_storm_overlay(conditions, now_pt)
        return apply_action_templates(
            conditions, station, risk_level, audience=audience
        )

    telemetry = {
        "current_time": format_pt_time(now_pt),
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

    prompt = build_safety_prompt(station, telemetry, now_pt)
    conditions = _generate_conditions_openai(prompt)
    conditions = apply_storm_overlay(conditions, now_pt)

    cache[loc] = {
        "date": today_str,
        "risk_level": risk_level,
        "conditions": conditions,
    }
    save_json(CACHE_FILE, cache)
    return apply_action_templates(
        conditions, station, risk_level, audience=audience
    )
