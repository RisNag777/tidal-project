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
        with open(filepath, 'r') as f: return json.load(f)
    except Exception: return {}

def save_json(filepath, data):
    with open(filepath, 'w') as f: json.dump(data, f, indent=2)

def format_ist_time(now_ist):
    time_str = now_ist.strftime("%I:%M %p")
    if time_str.startswith("0"):
        time_str = time_str[1:]
    return time_str

def describe_trend(values, threshold):
    if len(values) < 2:
        return "steady"
    delta = values[-1] - values[0]
    if delta > threshold:
        return "increasing"
    if delta < -threshold:
        return "decreasing"
    return "steady"

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
    window = pressures[start_idx:start_idx + window_hours]
    if len(window) < 3:
        return {
            "tide_summary": (
                "Tide timing is uncertain due to limited forecast data. "
                "Use local shoreline markers and harbor signals."
            ),
            "high_tide_eta_mins": None,
            "low_tide_eta_mins": None,
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
            "high_tide_eta_mins": high_mins,
            "low_tide_eta_mins": low_mins,
        }

    if highest_idx == 0:
        tide_summary = f"High water conditions are likely now. Low water expected {format_eta(low_mins)}."
    elif lowest_idx == 0:
        tide_summary = f"Low water conditions are likely now. High water expected {format_eta(high_mins)}."
    elif high_mins < low_mins:
        tide_summary = f"High water expected {format_eta(high_mins)}, then low water expected {format_eta(low_mins)}."
    else:
        tide_summary = f"Low water expected {format_eta(low_mins)}, then high water expected {format_eta(high_mins)}."

    return {
        "tide_summary": tide_summary,
        "high_tide_eta_mins": high_mins,
        "low_tide_eta_mins": low_mins,
    }

def build_safety_prompt(station, telemetry):
    loc = station["location_name"]
    return f"""Write a coastal safety advisory using EXACTLY this structure and line breaks. Do not use markdown.

🌊 Safety Status Update: {loc}

Urgent Safety Advisory

Location: {loc}
Current Time: {telemetry['current_time']}

⚠️ {{DANGER_TYPE_IN_CAPS}}

{{2-3 sentences describing current conditions. Use these telemetry facts:
- Pressure trend: {telemetry['pressure_trend']} (current {telemetry['current_pressure']:.1f} hPa)
- Wind trend: {telemetry['wind_trend']} (current {telemetry['current_wind']:.1f} km/h)
- Tide estimate (pressure-based, approximate): {telemetry['tide_summary']}
State whether conditions are safe or risky for small boats. Do not contradict the tide estimate above.}}

For small non-motorized fishing boats:
- {{action bullet 1}}
- {{action bullet 2}}
- {{action bullet 3}}

Stay safe.

Rules:
- Replace {{placeholders}} with real content; do not leave braces in the output.
- Use the tide estimate sentence exactly as written; never report high and low water at the same time.
- Choose danger level from conditions: CAUTION for steady/moderate wind, DANGER only for strong wind or clearly unsafe tide timing.
- Choose a danger type such as ESTUARY/BACKWATER DANGER, HARBOR DANGER, or OPEN COAST DANGER based on the location and conditions.
- Keep the header lines exactly as shown, including the location name and current time.
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
def process_coastal_safety(station):
    cache = load_json(CACHE_FILE)
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    loc = station["location_name"]

    if loc in cache and cache[loc].get("date") == today_str:
        cached_advisory = cache[loc].get("advisory")
        if cached_advisory:
            print("💰 Cost Avoided! Returning pre-computed safety advisory from cache.")
            return cached_advisory

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
    
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
    
    try: idx = times.index(current_hour_str)
    except ValueError: idx = 0

    target_pressures = pressures[idx:idx+12]
    target_winds = wind_speeds[idx:idx+12]
    tide_timing = compute_tide_timing(pressures, idx)
    
    telemetry = {
        "current_time": format_ist_time(now_ist),
        "current_pressure": target_pressures[0],
        "current_wind": target_winds[0],
        "pressure_trend": describe_trend(target_pressures, 0.5),
        "wind_trend": describe_trend(target_winds, 2.0),
        "tide_summary": tide_timing["tide_summary"],
        "high_tide_eta_mins": tide_timing["high_tide_eta_mins"],
        "low_tide_eta_mins": tide_timing["low_tide_eta_mins"],
    }
    
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}
    prompt = build_safety_prompt(station, telemetry)
    
    payload = {
        "model": "sarvam-105b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
        "reasoning_effort": None,
    }
    
    ai_response = requests.post(url, headers=headers, json=payload)
    ai_response.raise_for_status()
    final_advisory = ai_response.json()["choices"][0]["message"]["content"]
    
    cache[loc] = {"date": today_str, "advisory": final_advisory}
    save_json(CACHE_FILE, cache)
    
    return final_advisory

# ==================== INTERFACE WEBHOOK ENDPOINTS ====================

# 1. WHATSAPP & SMS ENHANCED ENDPOINT (Requirements 1 & 7)
@app.route("/webhook/whatsapp", methods=["POST"])
@app.route("/webhook/sms", methods=["POST"])
def incoming_message_handler():
    twiml_resp = MessagingResponse()
    try:
        incoming_text = request.values.get("Body", "").strip()
        num_media = int(request.values.get("NumMedia", 0))
        media_url = request.values.get("MediaUrl0", "") # Twilio indexes media components starting at 0
        
        user_query = incoming_text
        if num_media > 0 and media_url: 
            print("🎙️ Processing incoming audio note from Twilio pipeline...")
            user_query = transcribe_audio_via_sarvam(media_url)
            print(f"📝 Sarvam Audio Transcription: '{user_query}'")
            
        station = match_station_locally(user_query)
        if not station:
            twiml_resp.message("⚓ *Karnataka Coastal Safety Agent*\n\nPlease state your location to check safety windows (e.g., Malpe, Karwar).")
            return str(twiml_resp)
            
        update_station_registry(user_query, station)
        advisory = process_coastal_safety(station)
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
    default_station = {"location_name": "Malpe Fishing Harbor", "latitude": 13.3486, "longitude": 74.6961}
    update_station_registry("Voice Phone Call Inbound Connection", default_station)
    
    advisory_script = process_coastal_safety(default_station)
    
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
