import os
import json
import requests
import traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse
from tides import compute_tide_timing

load_dotenv()
app = Flask(__name__)

# Core Credentials (Twilio $ billing, Sarvam AI INR billing)
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")

STATIONS_FILE = "stations.json"
CACHE_FILE = "cache.json"
REGISTRY_FILE = "station_registry.json"

# --- HELPER DATA FUNCTIONS ---
def load_json(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)

def format_ist_time(now_ist):
    time_str = now_ist.strftime("%I:%M %p")
    return time_str[1:] if time_str.startswith("0") else time_str

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
        "⛔ MONSOON SEASON ALERT (May 16 – Sep 25)\n"
        "Arabian Sea conditions are often dangerous. Treat all water access as high risk.\n"
        "Follow local district orders and red-flag warnings."
    )

def apply_monsoon_overlay(advisory, now_ist):
    """Insert the monsoon banner after the advisory header when in season."""
    block = monsoon_overlay_block(now_ist)
    if not block or "MONSOON SEASON ALERT" in advisory:
        return advisory

    lines = advisory.split("\n", 1)
    header = lines[0]
    rest = lines[1].lstrip("\n") if len(lines) > 1 else ""
    if rest:
        return f"{header}\n\n{block}\n\n{rest}"
    return f"{header}\n\n{block}"

# Audience actions by site_type and live risk_level (low / elevated / high)
ACTION_TEMPLATES = {
    "harbor": {
        "low": {
            "recreational": [
                "Swim only in marked zones and watch children near the waterline.",
                "Stay clear of working boats and slipways.",
                "Leave the water if red flags go up or patrols advise.",
            ],
            "operators": [
                "Run recreational launches only in calm, marked waters.",
                "Brief passengers on life jackets before departure.",
                "Pause operations if wind or swell picks up.",
            ],
            "fishermen": [
                "Check harbor mouth conditions before leaving the basin.",
                "Carry life jackets and keep VHF or phone contact.",
                "Return early if wind or swell builds.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay behind shoreline barricades when red flags are shown.",
                "Avoid swimming near the river mouth or breakwater.",
                "Keep children on upper dry walkways away from surge.",
            ],
            "operators": [
                "Limit recreational launches; prefer sheltered water only.",
                "Keep jet skis and rental craft close to shore.",
                "Do not operate near the breakwater in building swell.",
            ],
            "fishermen": [
                "Favor short trips inside or just outside the harbor.",
                "Avoid the river mouth if swell is building.",
                "Secure gear before peak tide and rising wind.",
            ],
        },
        "high": {
            "recreational": [
                "Stay behind shoreline barricades and red-flag markers.",
                "Do not enter the water for swimming, wading, or photos.",
                "Keep children on upper dry walkways away from breaking waves.",
            ],
            "operators": [
                "Suspend recreational water sports and beach boat launches.",
                "Keep jet skis, banana boats, and rental craft grounded.",
                "Do not bring equipment near the shore during peak high tide.",
            ],
            "fishermen": [
                "Remain docked inside the protected harbor.",
                "Do not launch from shore during peak high tide.",
                "Avoid the river mouth and breakwater until water eases.",
            ],
        },
    },
    "backwater": {
        "low": {
            "recreational": [
                "Stay on marked paths and watch for soft mud at the edges.",
                "Supervise children near channel banks.",
                "Follow local patrol instructions if posted.",
            ],
            "operators": [
                "Run ferries and joyrides only in sheltered channels.",
                "Brief passengers before boarding.",
                "Delay trips if rain squalls or strong current appear.",
            ],
            "fishermen": [
                "Work sheltered channels; watch current at bends.",
                "Keep life jackets aboard small craft.",
                "Avoid the sea mouth if swell is visible outside.",
            ],
        },
        "elevated": {
            "recreational": [
                "Avoid sandbars and channel edges during rising water.",
                "Stay off mud flats that can flood on the incoming tide.",
                "Follow local patrol instructions and red-flag warnings.",
            ],
            "operators": [
                "Reduce ferry or joyride runs in narrow channels.",
                "Keep rental craft in the most sheltered stretches.",
                "Keep passengers away from the sea mouth.",
            ],
            "fishermen": [
                "Avoid crossing the backwater mouth in building current.",
                "Keep small boats ready to tie up in sheltered channels.",
                "Watch for strong currents where the backwater meets the sea.",
            ],
        },
        "high": {
            "recreational": [
                "Avoid sandbars and channel edges during rising water.",
                "Stay off mud flats that can flood quickly on incoming tide.",
                "Follow local patrol instructions and red-flag warnings.",
            ],
            "operators": [
                "Suspend ferry or joyride operations in narrow channels.",
                "Ground all rental craft until water levels ease.",
                "Keep passengers away from estuary entry points.",
            ],
            "fishermen": [
                "Do not cross the backwater mouth during peak high tide.",
                "Keep small boats tied inside sheltered channels.",
                "Watch for strong currents where the backwater meets the sea.",
            ],
        },
    },
    "estuary": {
        "low": {
            "recreational": [
                "Use designated walkways along the estuary banks.",
                "Do not wade into unmarked channels.",
                "Supervise children near the waterline.",
            ],
            "operators": [
                "Run small-craft tours only in calm, inland stretches.",
                "Brief passengers and check life jackets.",
                "Turn back if current or wind strengthens.",
            ],
            "fishermen": [
                "Work inland channels first; check the mouth before crossing.",
                "Secure nets if the tide is rising quickly.",
                "Carry life jackets on every trip.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay away from estuary banks during higher water.",
                "Do not wade into channels or sand spits.",
                "Use designated walkways only.",
            ],
            "operators": [
                "Limit small craft tours; avoid the river mouth.",
                "Keep passenger boats in sheltered inland water.",
                "Monitor district advisories before extending trips.",
            ],
            "fishermen": [
                "Avoid the estuary mouth if current is strong.",
                "Secure nets and canoes in sheltered inland channels.",
                "Watch for rip currents where river flow meets the sea.",
            ],
        },
        "high": {
            "recreational": [
                "Stay away from estuary banks during high water.",
                "Do not wade into channels or sand spits.",
                "Use designated walkways only.",
            ],
            "operators": [
                "Suspend small craft tours through the estuary.",
                "Keep all passenger boats away from the river mouth.",
                "Monitor district advisories before resuming service.",
            ],
            "fishermen": [
                "Do not attempt to cross the estuary mouth at peak tide.",
                "Secure nets and canoes in sheltered inland channels.",
                "Watch for rip currents where river flow meets the sea.",
            ],
        },
    },
    "port": {
        "low": {
            "recreational": [
                "Stay off restricted quay and breakwater areas.",
                "Do not swim near shipping channels or dock walls.",
                "Observe port security and safety signage.",
            ],
            "operators": [
                "Run passenger craft only inside protected basins when seas are calm.",
                "Brief crews on traffic separation and life jackets.",
                "Follow harbor master instructions.",
            ],
            "fishermen": [
                "Check wind and swell before leaving the basin.",
                "Keep trips short and stay near protected waters if unsure.",
                "Secure gear before peak tide.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay off port breakwaters and restricted quay areas.",
                "Do not swim near shipping channels or dock walls.",
                "Observe port security and safety signage.",
            ],
            "operators": [
                "Limit non-essential port transits for small passenger craft.",
                "Prefer protected basins over open approaches.",
                "Follow harbor master instructions.",
            ],
            "fishermen": [
                "Stay close to protected harbor waters in small craft.",
                "Postpone open-coast legs if swell is building.",
                "Secure gear before peak high water.",
            ],
        },
        "high": {
            "recreational": [
                "Stay off port breakwaters and restricted quay areas.",
                "Do not swim near shipping channels or dock walls.",
                "Observe port security and safety signage.",
            ],
            "operators": [
                "Delay non-essential port transits for small passenger craft.",
                "Keep commercial launches inside protected basins.",
                "Follow harbor master instructions.",
            ],
            "fishermen": [
                "Remain alongside port docks until tide and wind ease.",
                "Do not leave protected harbor waters in small craft.",
                "Secure gear before peak high water.",
            ],
        },
    },
}

AUDIENCE_HEADERS = (
    ("recreational", "🏊 Families, kids & swimmers:"),
    ("operators", "🏄 Water sports operators:"),
    ("fishermen", "🎣 Small boats & fishermen:"),
)

LEGACY_ACTION_MARKERS = (
    "For small non-motorized fishing boats:",
)

# Site labels soften/harden with live risk (monsoon banner stays separate)
SITE_DANGER_LABELS = {
    "harbor": {
        "low": "HARBOR NOTICE",
        "elevated": "HARBOR / RIVER-MOUTH CAUTION",
        "high": "HARBOR / RIVER-MOUTH WARNING",
    },
    "backwater": {
        "low": "BACKWATER NOTICE",
        "elevated": "BACKWATER CAUTION",
        "high": "BACKWATER DANGER",
    },
    "estuary": {
        "low": "ESTUARY NOTICE",
        "elevated": "ESTUARY CAUTION",
        "high": "ESTUARY DANGER",
    },
    "port": {
        "low": "PORT NOTICE",
        "elevated": "PORT CAUTION",
        "high": "PORT WARNING",
    },
}

RISK_ADVISORY_TITLES = {
    "low": "Safety Advisory",
    "elevated": "Caution Advisory",
    "high": "Urgent Safety Advisory",
}

RISK_BOAT_SENTENCES = {
    "low": "Conditions are manageable for experienced small craft.",
    "elevated": "Conditions call for extra caution for small boats.",
    "high": "Conditions are risky for small boats.",
}

RISK_RANK = {"low": 0, "elevated": 1, "high": 2}
RISK_LEVELS = ("low", "elevated", "high")

# Small-craft thresholds (Open-Meteo wind km/h, significant wave height m)
WIND_ELEVATED_KMH = 20.0
WIND_HIGH_KMH = 35.0
WAVE_ELEVATED_M = 1.0
WAVE_HIGH_M = 1.75

def audience_header_texts():
    return [header for _, header in AUDIENCE_HEADERS]

def earliest_marker_index(text, markers):
    cut_at = None
    for marker in markers:
        idx = text.find(marker)
        if idx != -1 and (cut_at is None or idx < cut_at):
            cut_at = idx
    return cut_at

def station_site_type(station):
    return station.get("site_type", "harbor")

def normalize_risk_level(risk_level):
    if risk_level in RISK_RANK:
        return risk_level
    return "elevated"

def wind_risk_level(wind_kmh):
    if wind_kmh is None:
        return "low"
    if wind_kmh >= WIND_HIGH_KMH:
        return "high"
    if wind_kmh >= WIND_ELEVATED_KMH:
        return "elevated"
    return "low"

def wave_risk_level(wave_m):
    if wave_m is None:
        return None
    if wave_m >= WAVE_HIGH_M:
        return "high"
    if wave_m >= WAVE_ELEVATED_M:
        return "elevated"
    return "low"

def compute_risk_level(wind_kmh, wave_m, in_monsoon):
    """Score live risk from wind + waves. Monsoon only fills in when wave data is missing."""
    scores = [RISK_RANK[wind_risk_level(wind_kmh)]]
    wave_level = wave_risk_level(wave_m)
    if wave_level is not None:
        scores.append(RISK_RANK[wave_level])
    elif in_monsoon:
        # No marine reading: seasonal seas warrant at least elevated caution
        scores.append(RISK_RANK["elevated"])
    return RISK_LEVELS[max(scores)]

def danger_label_for(station, risk_level):
    site_type = station_site_type(station)
    labels = SITE_DANGER_LABELS.get(site_type, SITE_DANGER_LABELS["harbor"])
    return labels.get(normalize_risk_level(risk_level), labels["elevated"])

def fetch_wave_height_m(latitude, longitude, now_ist):
    """Current significant wave height (m) from Open-Meteo marine; None if unavailable."""
    try:
        response = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": float(latitude),
                "longitude": float(longitude),
                "hourly": "wave_height",
                "timezone": "Asia/Kolkata",
                "forecast_days": 2,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        times = payload["hourly"]["time"]
        heights = payload["hourly"]["wave_height"]
        current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
        try:
            idx = times.index(current_hour_str)
        except ValueError:
            idx = 0
        height = heights[idx]
        if height is None:
            return None
        return float(height)
    except Exception as exc:
        print(f"⚠️ Marine wave fetch failed: {exc}")
        return None

def actions_for(station, audience, risk_level):
    site_type = station_site_type(station)
    by_site = ACTION_TEMPLATES.get(site_type, ACTION_TEMPLATES["harbor"])
    by_risk = by_site.get(normalize_risk_level(risk_level), by_site["elevated"])
    return by_risk[audience]

def build_action_sections(station, risk_level):
    lines = []
    for audience, header in AUDIENCE_HEADERS:
        lines.append(header)
        for bullet in actions_for(station, audience, risk_level):
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(lines).rstrip()

def apply_action_templates(advisory, station, risk_level):
    """Replace free-form action bullets with site-type + risk templates."""
    sections = build_action_sections(station, risk_level)
    cut_at = earliest_marker_index(
        advisory, audience_header_texts() + list(LEGACY_ACTION_MARKERS)
    )
    closing = "Stay safe."

    stay_idx = advisory.rfind("Stay safe.")
    if cut_at is not None and stay_idx != -1 and cut_at < stay_idx:
        return advisory[:cut_at].rstrip() + "\n\n" + sections + "\n\n" + closing
    if stay_idx != -1:
        return advisory[:stay_idx].rstrip() + "\n\n" + sections + "\n\n" + closing
    return advisory.rstrip() + "\n\n" + sections + "\n\n" + closing

def describe_trend(values, threshold):
    if len(values) < 2:
        return "steady"
    delta = values[-1] - values[0]
    if delta > threshold:
        return "increasing"
    if delta < -threshold:
        return "decreasing"
    return "steady"

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
    action_sections = build_action_sections(station, risk_level)
    wave_fact = (
        f"- Wave height: {telemetry['current_wave']:.1f} m"
        if telemetry.get("current_wave") is not None
        else "- Wave height: unavailable"
    )
    return f"""Write a coastal safety advisory using EXACTLY this structure and line breaks. Do not use markdown.

🌊 Safety Status Update: {loc}
{monsoon_section}
{advisory_title}

Location: {loc}
Current Time: {telemetry['current_time']}

⚠️ {danger_label}

{{2-3 sentences describing current conditions. Use these telemetry facts:
- Pressure trend: {telemetry['pressure_trend']} (current {telemetry['current_pressure']:.1f} hPa)
- Wind trend: {telemetry['wind_trend']} (current {telemetry['current_wind']:.1f} km/h)
{wave_fact}
- Tide estimate (pressure-based, approximate): {telemetry['tide_summary']}
End the conditions paragraph with this exact boat-risk sentence: {boat_sentence}
Match the tone of the telemetry; do not invent stronger wind, waves, or urgency than the facts show.}}

{action_sections}

Stay safe.

Rules:
- Replace {{placeholders}} with real content; do not leave braces in the output.
- Use the tide estimate sentence exactly as written; never report high and low water at the same time.
- Do not invent exact tide heights in feet or meters.
- Use the boat-risk sentence exactly as written; do not replace it with a different safe/risky judgment.
- Copy the audience action sections exactly as shown; do not invent, remove, or rewrite bullets.
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

def process_coastal_safety(station):
    cache = load_json(CACHE_FILE)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    loc = station["location_name"]
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    in_monsoon = in_monsoon_season(now_ist)

    params = {
        "latitude": float(station["latitude"]),
        "longitude": float(station["longitude"]),
        "hourly": "surface_pressure,wind_speed_10m",
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

    current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(current_hour_str)
    except ValueError:
        idx = 0

    target_pressures = pressures[idx:idx + 12]
    target_winds = wind_speeds[idx:idx + 12]
    current_wind = float(target_winds[0])
    current_wave = fetch_wave_height_m(
        station["latitude"], station["longitude"], now_ist
    )
    risk_level = compute_risk_level(current_wind, current_wave, in_monsoon)
    tide_timing = compute_tide_timing(pressures, idx)

    cached = cache.get(loc) or {}
    cached_advisory = cached.get("advisory") or cached.get("full_advisory")
    if (
        cached.get("date") == today_str
        and cached.get("risk_level") == risk_level
        and cached_advisory
    ):
        print(
            f"💰 Cost Avoided! Returning cached advisory "
            f"(risk={risk_level})."
        )
        advisory = apply_monsoon_overlay(cached_advisory, now_ist)
        return apply_action_templates(advisory, station, risk_level)

    telemetry = {
        "current_time": format_ist_time(now_ist),
        "current_pressure": target_pressures[0],
        "current_wind": current_wind,
        "current_wave": current_wave,
        "pressure_trend": describe_trend(target_pressures, 0.5),
        "wind_trend": describe_trend(target_winds, 2.0),
        "tide_summary": tide_timing["tide_summary"],
        "risk_level": risk_level,
    }

    prompt = build_safety_prompt(station, telemetry, now_ist)
    payload = {
        "model": "sarvam-105b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
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
    base_advisory = ai_response.json()["choices"][0]["message"]["content"]
    base_advisory = apply_monsoon_overlay(base_advisory, now_ist)
    advisory = apply_action_templates(base_advisory, station, risk_level)

    cache[loc] = {
        "date": today_str,
        "risk_level": risk_level,
        "advisory": advisory,
    }
    save_json(CACHE_FILE, cache)
    return advisory
# ==================== Webhooks ====================

@app.route("/webhook/whatsapp", methods=["POST"])
@app.route("/webhook/sms", methods=["POST"])
def incoming_message_handler():
    twiml_resp = MessagingResponse()
    try:
        incoming_text = request.values.get("Body", "").strip()
        num_media = int(request.values.get("NumMedia", 0))
        media_url = request.values.get("MediaUrl0", "")

        user_query = incoming_text
        if num_media > 0 and media_url:
            print("🎙️ Processing incoming audio note from Twilio pipeline...")
            user_query = transcribe_audio_via_sarvam(media_url)
            print(f"📝 Sarvam Audio Transcription: '{user_query}'")

        station = match_station_locally(user_query)
        if not station:
            twiml_resp.message(
                "⚓ *Karnataka Coastal Safety Agent*\n\n"
                "Please state your location to check safety windows (e.g., Malpe, Karwar)."
            )
            return str(twiml_resp)

        update_station_registry(user_query, station)
        advisory = process_coastal_safety(station)
        twiml_resp.message(advisory)

    except Exception:
        traceback.print_exc()
        twiml_resp.message(
            "⚠️ Safety database is syncing. Please check local shoreline water indicators."
        )

    return str(twiml_resp)

@app.route("/webhook/voice", methods=["POST"])
def voice_ivr_handler():
    twiml_voice = VoiceResponse()

    default_station = {
        "location_name": "Malpe Fishing Harbor",
        "latitude": 13.3486,
        "longitude": 74.6961,
        "site_type": "harbor",
    }
    update_station_registry("Voice Phone Call Inbound Connection", default_station)

    advisory_script = process_coastal_safety(default_station)
    location = default_station["location_name"]

    twiml_voice.say(
        f"Welcome to Karnataka Coastal Safety System. Here is your current update for {location}.",
        voice="alice",
        language="en-IN",
    )
    twiml_voice.say(advisory_script, voice="alice", language="en-IN")
    twiml_voice.say(
        "Please cross-check beach marker lines before entering the water. Stay safe. Goodbye.",
        voice="alice",
        language="en-IN",
    )
    twiml_voice.hangup()

    return Response(str(twiml_voice), mimetype="text/xml")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
