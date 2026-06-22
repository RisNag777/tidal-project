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
        print("💰 Cost Avoided! Returning pre-computed safety advisory from cache.")
        return cache[loc]["advisory"]

    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": float(station['latitude']),
        "longitude": float(station['longitude']),
        "hourly": "surface_pressure,wind_speed_10m",
        "timezone": "Asia/Kolkata",
        "forecast_days": 1
    }
    api_response = requests.get(base_url, params=params).json()
    
    times = api_response['hourly']['time']
    pressures = api_response['hourly']['surface_pressure']
    
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
    
    try: idx = times.index(current_hour_str)
    except ValueError: idx = 0

    target_pressures = pressures[idx:idx+12]
    highest_idx = target_pressures.index(max(target_pressures))
    lowest_idx = target_pressures.index(min(target_pressures))
    
    high_tide_eta_mins = highest_idx * 60
    low_tide_eta_mins = lowest_idx * 60
    
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}
    
    prompt = f"""
    Location: {loc}. 
    High water parameter spike occurs in exactly {high_tide_eta_mins} minutes.
    Low water channel drop occurs in exactly {low_tide_eta_mins} minutes.
    Write a brief marine safety advisory for small boats and foragers. Specify exactly how many hours or minutes remain before high tides start or end. Keep it to 2 sentences without markdown.
    """
    
    payload = {
        "model": "sarvam-105b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
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
        twiml_resp.message(f"🌊 *Update for {station['location_name']}*:\n\n{advisory}")
        
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
