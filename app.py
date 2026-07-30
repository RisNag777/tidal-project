"""Unified coastal safety webhooks — routes by station name to Karnataka or PNW."""
import traceback
from pathlib import Path
import sys

from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from karnataka import actions as k_actions
from karnataka import safety as k_safety
from karnataka.storage import STATIONS_FILE as K_STATIONS_FILE
from karnataka.storage import load_json as k_load_json
from pnw import actions as p_actions
from pnw import safety as p_safety

load_dotenv()
app = Flask(__name__)

HELP_MESSAGE = (
    "⚓ *Coastal Safety Agent*\n\n"
    "Please state your location (e.g., Malpe, Karwar, Astoria, Seattle).\n"
    "For category detail: Malpe families | Astoria operators | Seattle fishermen"
)

REGIONS = {
    "karnataka": {
        "actions": k_actions,
        "safety": k_safety,
        "error": (
            "⚠️ Safety database is syncing. "
            "Please check local shoreline water indicators."
        ),
    },
    "pnw": {
        "actions": p_actions,
        "safety": p_safety,
        "error": (
            "⚠️ Safety data is syncing. "
            "Please check local beach flags and NOAA forecasts."
        ),
    },
}


def _station_keyword(station):
    return station["location_name"].lower().split()[0]


def resolve_region(user_query):
    """Return (region_key, station) or (None, None). Prefer longer keyword on ties."""
    k_station = k_safety.match_station_locally(user_query)
    p_station = p_safety.match_station_locally(user_query)
    if k_station and p_station:
        if len(_station_keyword(p_station)) > len(_station_keyword(k_station)):
            return "pnw", p_station
        return "karnataka", k_station
    if k_station:
        return "karnataka", k_station
    if p_station:
        return "pnw", p_station
    return None, None


def _default_voice_station():
    stations = k_load_json(K_STATIONS_FILE)
    if isinstance(stations, list):
        for station in stations:
            if station.get("location_name", "").startswith("Malpe"):
                return station
        if stations:
            return stations[0]
    return {
        "location_name": "Malpe Fishing Harbor",
        "latitude": 13.3486,
        "longitude": 74.6961,
        "site_type": "harbor",
        "coast_profile": "A",
        "landmarks": ["concrete jetty", "public Sea Walkway", "lifeguard watchtower"],
        "emergency_line": "📞 Malpe Harbor / Coastal Security: Dial 112",
    }


def _resolve_user_query(incoming_text, num_media, media_url):
    """Build query text; for voice notes try Sarvam then Whisper until a station matches."""
    user_query = (incoming_text or "").strip()
    region, station = resolve_region(user_query)
    if station:
        return user_query, region, station

    if num_media <= 0 or not media_url:
        return user_query, None, None

    print("🎙️ Processing incoming audio note...")
    sarvam_text = k_safety.transcribe_audio_via_sarvam(media_url) or ""
    print(f"📝 Sarvam transcription: {sarvam_text!r}")
    region, station = resolve_region(sarvam_text)
    if station:
        return sarvam_text, region, station

    whisper_text = p_safety.transcribe_audio_via_openai(media_url) or ""
    print(f"📝 Whisper transcription: {whisper_text!r}")
    region, station = resolve_region(whisper_text)
    if station:
        return whisper_text, region, station

    # Prefer whichever transcription produced text for the help path.
    fallback = whisper_text.strip() or sarvam_text.strip() or user_query
    return fallback, None, None


@app.route("/webhook/whatsapp", methods=["POST"])
@app.route("/webhook/sms", methods=["POST"])
def incoming_message_handler():
    twiml_resp = MessagingResponse()
    region = None
    try:
        incoming_text = request.values.get("Body", "").strip()
        num_media = int(request.values.get("NumMedia", 0))
        media_url = request.values.get("MediaUrl0", "")
        print(
            f"📩 WhatsApp/SMS Body={incoming_text!r} "
            f"NumMedia={num_media}"
        )

        user_query, region, station = _resolve_user_query(
            incoming_text, num_media, media_url
        )
        if not station:
            twiml_resp.message(HELP_MESSAGE)
            return Response(str(twiml_resp), mimetype="text/xml")

        bundle = REGIONS[region]
        audience = bundle["actions"].parse_audience(user_query)
        bundle["safety"].update_station_registry(user_query, station)
        advisory = bundle["safety"].process_coastal_safety(
            station, audience=audience
        )
        advisory = bundle["actions"].truncate_for_whatsapp(advisory)
        print(f"🧭 Routed to {region}: {station['location_name']}")
        twiml_resp.message(advisory)

    except Exception:
        traceback.print_exc()
        err = REGIONS.get(region, REGIONS["karnataka"])["error"]
        twiml_resp.message(err)

    return Response(str(twiml_resp), mimetype="text/xml")


@app.route("/webhook/voice", methods=["POST"])
def voice_ivr_handler():
    twiml_voice = VoiceResponse()
    default_station = _default_voice_station()
    k_safety.update_station_registry(
        "Voice Phone Call Inbound Connection", default_station
    )

    advisory_script = k_safety.process_coastal_safety(default_station)
    location = default_station["location_name"]

    twiml_voice.say(
        f"Welcome to Karnataka Coastal Safety System. "
        f"Here is your current update for {location}.",
        voice="alice",
        language="en-IN",
    )
    twiml_voice.say(advisory_script, voice="alice", language="en-IN")
    twiml_voice.say(
        "Please cross-check beach marker lines before entering the water. "
        "Stay safe. Goodbye.",
        voice="alice",
        language="en-IN",
    )
    twiml_voice.hangup()

    return Response(str(twiml_voice), mimetype="text/xml")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
