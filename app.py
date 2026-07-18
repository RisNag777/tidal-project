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
from tides import build_tide_table, fetch_tide_context

load_dotenv()
app = Flask(__name__)

# Core Credentials (Twilio $ billing, Sarvam AI INR billing)
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")

STATIONS_FILE = "stations.json"
CACHE_FILE = "cache.json"
REGISTRY_FILE = "station_registry.json"
USER_SESSIONS_FILE = "user_sessions.json"

DETAILS_KEYWORDS = (
    "more details",
    "full advisory",
    "full update",
    "more info",
    "details please",
    "expand",
)

# --- HELPER DATA FUNCTIONS ---
def load_json(filepath):
    try:
        with open(filepath, 'r') as f: return json.load(f)
    except Exception: return {}

def save_json(filepath, data):
    with open(filepath, 'w') as f: json.dump(data, f, indent=2)

def format_ist_time(now_ist):
    time_str = now_ist.strftime("%I:%M %p")
    if time_str.startswith("0"):
        time_str = time_str[1:]
    return time_str

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

# Audience-specific actions keyed by station site_type
ACTION_TEMPLATES = {
    "harbor": {
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
    "backwater": {
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
    "estuary": {
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
    "port": {
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
}

AUDIENCE_HEADERS = (
    ("recreational", "🏊 Families, kids & swimmers:"),
    ("operators", "🏄 Water sports operators:"),
    ("fishermen", "🎣 Small boats & fishermen:"),
)

SITE_DANGER_LABELS = {
    "harbor": "HARBOR / RIVER-MOUTH CAUTION",
    "backwater": "BACKWATER DANGER",
    "estuary": "ESTUARY DANGER",
    "port": "PORT CAUTION",
}

def station_site_type(station):
    return station.get("site_type", "harbor")

def actions_for(station, audience):
    site_type = station_site_type(station)
    templates = ACTION_TEMPLATES.get(site_type, ACTION_TEMPLATES["harbor"])
    return templates[audience]

def wants_full_advisory(user_text):
    text = user_text.lower().strip()
    if text in {"details", "detail", "full", "more"}:
        return True
    if any(keyword in text for keyword in DETAILS_KEYWORDS):
        return True
    tokens = text.split()
    return any(token in {"details", "detail", "full"} for token in tokens)

def build_action_sections(station, detail_level="short"):
    headers = AUDIENCE_HEADERS if detail_level == "full" else (
        ("fishermen", "🎣 Small boats & fishermen:"),
    )
    lines = []
    for audience, header in headers:
        lines.append(header)
        for bullet in actions_for(station, audience):
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(lines).rstrip()

def apply_action_templates(advisory, station, detail_level="short"):
    """Replace free-form action bullets with site-type templates."""
    sections = build_action_sections(station, detail_level=detail_level)
    markers = [header for _, header in AUDIENCE_HEADERS] + [
        "For small non-motorized fishing boats:",
        "Reply DETAILS for full advisory.",
    ]
    cut_at = None
    for marker in markers:
        idx = advisory.find(marker)
        if idx != -1 and (cut_at is None or idx < cut_at):
            cut_at = idx

    if detail_level == "short":
        closing = "Reply DETAILS for full advisory.\n\nStay safe."
    else:
        closing = "Stay safe."

    stay_idx = advisory.rfind("Stay safe.")
    if cut_at is not None and stay_idx != -1 and cut_at < stay_idx:
        return advisory[:cut_at].rstrip() + "\n\n" + sections + "\n\n" + closing
    if stay_idx != -1:
        return advisory[:stay_idx].rstrip() + "\n\n" + sections + "\n\n" + closing
    return advisory.rstrip() + "\n\n" + sections + "\n\n" + closing

def save_last_station(sender, station):
    if not sender:
        return
    sessions = load_json(USER_SESSIONS_FILE)
    sessions[sender] = {
        "location_name": station["location_name"],
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "site_type": station.get("site_type", "harbor"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_json(USER_SESSIONS_FILE, sessions)

def get_last_station(sender):
    if not sender:
        return None
    sessions = load_json(USER_SESSIONS_FILE)
    return sessions.get(sender)

def describe_trend(values, threshold):
    if len(values) < 2:
        return "steady"
    delta = values[-1] - values[0]
    if delta > threshold:
        return "increasing"
    if delta < -threshold:
        return "decreasing"
    return "steady"

TIDE_TABLE_MARKER = "Today's tide times (Survey of India):"

def strip_tide_table(advisory):
    """Remove any previously inserted SOI tide table so append stays idempotent."""
    start = advisory.find(TIDE_TABLE_MARKER)
    if start == -1:
        return advisory

    rest = advisory[start:]
    end_markers = [header for _, header in AUDIENCE_HEADERS] + [
        "For small non-motorized fishing boats:",
        "Reply DETAILS for full advisory.",
        "Stay safe.",
    ]
    end_rel = None
    for marker in end_markers:
        idx = rest.find(marker)
        if idx != -1 and (end_rel is None or idx < end_rel):
            end_rel = idx

    prefix = advisory[:start].rstrip()
    if end_rel is None:
        return prefix
    return prefix + "\n\n" + rest[end_rel:].lstrip()

def append_tide_table(advisory, tide_context, detail_level):
    if detail_level != "full" or tide_context.get("source") != "survey_of_india":
        return advisory

    advisory = strip_tide_table(advisory)
    table = build_tide_table(tide_context)
    markers = [header for _, header in AUDIENCE_HEADERS] + [
        "For small non-motorized fishing boats:",
        "🎣 Small boats & fishermen:",
        "Reply DETAILS for full advisory.",
    ]
    cut_at = None
    for marker in markers:
        idx = advisory.find(marker)
        if idx != -1 and (cut_at is None or idx < cut_at):
            cut_at = idx

    if cut_at is not None:
        return advisory[:cut_at].rstrip() + "\n\n" + table + "\n\n" + advisory[cut_at:].lstrip()
    return advisory.rstrip() + "\n\n" + table

def build_safety_prompt(station, telemetry, now_ist):
    loc = station["location_name"]
    monsoon_block = monsoon_overlay_block(now_ist)
    monsoon_section = f"\n{monsoon_block}\n" if monsoon_block else "\n"
    monsoon_rule = (
        "- Include the monsoon alert lines exactly as shown; do not invent legal bans or fines.\n"
        if monsoon_block else
        "- Do not invent a monsoon ban if no monsoon alert lines are shown.\n"
    )
    tide_source = telemetry.get("tide_source", "unavailable")
    if tide_source == "survey_of_india":
        tide_fact = f"- Official tide times (Survey of India): {telemetry['tide_summary']}"
        tide_instruction = (
            "Use the tide times exactly as written; do not invent clock times or heights."
        )
        tide_rules = (
            "- Use the Survey of India tide sentence exactly as written; never report high and low water at the same time.\n"
            "- Do not describe tides as \"pressure-based\" when official SOI times are provided.\n"
        )
    else:
        tide_fact = f"- Approximate tide timing (estimate only, no official heights yet): {telemetry['tide_summary']}"
        tide_instruction = (
            "Treat tide timing as approximate. Do not invent tide heights in feet or meters."
        )
        tide_rules = (
            "- Do not invent tide heights; SOI tables for this month are not loaded yet.\n"
            "- Never invent matching high and low water at the same time.\n"
        )
    # Prompt uses the short fishermen section; full audiences are applied in code.
    action_sections = build_action_sections(station, detail_level="short")
    return f"""Write a coastal safety advisory using EXACTLY this structure and line breaks. Do not use markdown.

🌊 Safety Status Update: {loc}
{monsoon_section}
Urgent Safety Advisory

Location: {loc}
Current Time: {telemetry['current_time']}

⚠️ {danger_label}

{{2-3 sentences describing current conditions. Use these telemetry facts:
- Pressure trend: {telemetry['pressure_trend']} (current {telemetry['current_pressure']:.1f} hPa)
- Wind trend: {telemetry['wind_trend']} (current {telemetry['current_wind']:.1f} km/h)
{tide_fact}
State whether conditions are safe or risky for small boats. {tide_instruction}}}

{action_sections}

Stay safe.

Rules:
- Replace {{placeholders}} with real content; do not leave braces in the output.
{tide_rules}- Copy the audience action sections exactly as shown; do not invent, remove, or rewrite bullets.
{monsoon_rule}- Prefer elevated caution during monsoon season or strong wind.
- Keep the header lines exactly as shown, including the location name, current time, and danger label.
- Use plain text only."""

# --- REGISTRY LOGGING ENGINE (Requirement 5) ---
def update_station_registry(queried_location, target_station):
    registry = load_json(REGISTRY_FILE)
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    current_entry = {
        "station_name": target_station["location_name"],
        "latitude": target_station["latitude"],
        "longitude": target_station["longitude"]
    }
    
    if queried_location not in registry:
        registry[queried_location] = {
            "first_queried_date": today_str,
            "history": [current_entry]
        }
        print(f"📝 Initialized tracking audit record for: {queried_location}")
        save_json(REGISTRY_FILE, registry)
    else:
        last_recorded = registry[queried_location]["history"][-1]
        if last_recorded["station_name"] != target_station["location_name"]:
            registry[queried_location]["history"].append(current_entry)
            print(f"🚨 ALERT: Mapping change tracked for {queried_location} -> {target_station['location_name']}")
            save_json(REGISTRY_FILE, registry)

# --- SARVAM INDIC AUDIO TRANSLATION ---
def transcribe_audio_via_sarvam(audio_url):
    """Downloads Twilio's recording and transcribes Kannada/Tulu straight to English."""
    # Twilio recordings require basic auth to download securely
    response = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    if response.status_code != 200:
        return ""
        
    filename = "temp_voice.ogg"
    with open(filename, "wb") as f: 
        f.write(response.content)

    url = "https://api.sarvam.ai/speech-to-text"
    headers = {"api-subscription-key": SARVAM_API_KEY}
    files = {"file": (filename, open(filename, "rb"), "audio/ogg")}
    data = {"model": "saaras:v3", "mode": "translate"}
    
    api_resp = requests.post(url, headers=headers, files=files, data=data)
    os.remove(filename)
    
    if api_resp.status_code == 200:
        return api_resp.json().get("transcript", "")
    return ""

# --- ZERO-COST LOCATION MATCHING (Requirement 2 Optimization) ---
def match_station_locally(user_text):
    stations = load_json(STATIONS_FILE)
    clean_input = user_text.lower().strip()
    
    for station in stations:
        core_keyword = station["location_name"].lower().split()[0]
        if core_keyword in clean_input:
            return station
    return None

# --- TELEMETRY ENGINE & TIME FORECASTING (Requirement 6) ---
def process_coastal_safety(station, detail_level="short"):
    cache = load_json(CACHE_FILE)
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    loc = station["location_name"]
    cache_key = "full_advisory" if detail_level == "full" else "short_advisory"
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))

    if loc in cache and cache[loc].get("date") == today_str:
        cached_advisory = cache[loc].get(cache_key) or cache[loc].get("advisory")
        if cached_advisory:
            print("💰 Cost Avoided! Returning pre-computed safety advisory from cache.")
            advisory = apply_monsoon_overlay(cached_advisory, now_ist)
            result = apply_action_templates(advisory, station, detail_level=detail_level)
            if detail_level == "full":
                tide_context = fetch_tide_context(station, now_ist)
                result = append_tide_table(result, tide_context, detail_level="full")
            return result

    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": float(station['latitude']),
        "longitude": float(station['longitude']),
        "hourly": "surface_pressure,wind_speed_10m",
        "timezone": "Asia/Kolkata",
        "forecast_days": 2
    }
    api_response = requests.get(base_url, params=params).json()
    
    times = api_response['hourly']['time']
    pressures = api_response['hourly']['surface_pressure']
    wind_speeds = api_response['hourly']['wind_speed_10m']
    
    current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
    
    try: idx = times.index(current_hour_str)
    except ValueError: idx = 0

    target_pressures = pressures[idx:idx+12]
    target_winds = wind_speeds[idx:idx+12]
    tide_context = fetch_tide_context(station, now_ist, pressures, idx)

    telemetry = {
        "current_time": format_ist_time(now_ist),
        "current_pressure": target_pressures[0],
        "current_wind": target_winds[0],
        "pressure_trend": describe_trend(target_pressures, 0.5),
        "wind_trend": describe_trend(target_winds, 2.0),
        "tide_summary": tide_context["tide_summary"],
        "tide_source": tide_context.get("source", "unavailable"),
    }
    
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}
    prompt = build_safety_prompt(station, telemetry, now_ist)
    
    payload = {
        "model": "sarvam-105b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
        "reasoning_effort": None,
    }
    
    ai_response = requests.post(url, headers=headers, json=payload)
    ai_response.raise_for_status()
    base_advisory = ai_response.json()["choices"][0]["message"]["content"]
    base_advisory = apply_monsoon_overlay(base_advisory, now_ist)

    short_advisory = apply_action_templates(base_advisory, station, detail_level="short")
    # Cache full without the tide table; append a fresh table on every full response.
    full_advisory = apply_action_templates(base_advisory, station, detail_level="full")
    
    cache[loc] = {
        "date": today_str,
        "short_advisory": short_advisory,
        "full_advisory": full_advisory,
    }
    save_json(CACHE_FILE, cache)
    
    if detail_level == "full":
        return append_tide_table(full_advisory, tide_context, detail_level="full")
    return short_advisory

# ==================== INTERFACE WEBHOOK ENDPOINTS ====================

# 1. WHATSAPP & SMS ENHANCED ENDPOINT (Requirements 1 & 7)
@app.route("/webhook/whatsapp", methods=["POST"])
@app.route("/webhook/sms", methods=["POST"])
def incoming_message_handler():
    twiml_resp = MessagingResponse()
    try:
        incoming_text = request.values.get("Body", "").strip()
        sender = request.values.get("From", "")
        num_media = int(request.values.get("NumMedia", 0))
        media_url = request.values.get("MediaUrl0", "") # Twilio indexes media components starting at 0
        
        user_query = incoming_text
        if num_media > 0 and media_url: 
            print("🎙️ Processing incoming audio note from Twilio pipeline...")
            user_query = transcribe_audio_via_sarvam(media_url)
            print(f"📝 Sarvam Audio Transcription: '{user_query}'")

        wants_full = wants_full_advisory(user_query)
        station = match_station_locally(user_query)
        if not station and wants_full:
            station = get_last_station(sender)

        if not station:
            if wants_full:
                twiml_resp.message(
                    "⚓ Please send your location first (e.g., Malpe, Karwar), then reply DETAILS for the full advisory."
                )
            else:
                twiml_resp.message("⚓ *Karnataka Coastal Safety Agent*\n\nPlease state your location to check safety windows (e.g., Malpe, Karwar).")
            return str(twiml_resp)
            
        update_station_registry(user_query, station)
        save_last_station(sender, station)
        detail_level = "full" if wants_full else "short"
        advisory = process_coastal_safety(station, detail_level=detail_level)
        twiml_resp.message(advisory)
        
    except Exception:
        traceback.print_exc()
        twiml_resp.message("⚠️ Safety database is syncing. Please check local shoreline water indicators.")
        
    return str(twiml_resp)

# 2. INTERACTIVE VOICE CALLS (IVR) ENDPOINT (Requirement 7)
@app.route("/webhook/voice", methods=["POST"])
def voice_ivr_handler():
    """Outputs compliant TwiML XML instructions to orchestrate interactive telephone calls."""
    twiml_voice = VoiceResponse()
    
    # Auto-default to main hub to handle incoming voice calls immediately
    default_station = {
        "location_name": "Malpe Fishing Harbor",
        "latitude": 13.3486,
        "longitude": 74.6961,
        "site_type": "harbor",
    }
    update_station_registry("Voice Phone Call Inbound Connection", default_station)
    
    advisory_script = process_coastal_safety(default_station, detail_level="short")
    
    # Twilio Text-To-Speech engine speaks this out loud over the call line
    twiml_voice.say(f"Welcome to Karnataka Coastal Safety System. Here is your current update for {default_station['location_name']}.", voice='alice', language='en-IN')
    twiml_voice.say(advisory_script, voice='alice', language='en-IN')
    twiml_voice.say("Please cross-check beach marker lines before entering the water. Stay safe. Goodbye.", voice='alice', language='en-IN')
    twiml_voice.hangup()
    
    return Response(str(twiml_voice), mimetype="text/xml")

if __name__ == "__main__":
    # Running directly on production Port 80
    # port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=5000, debug=False)
