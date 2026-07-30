"""Flask webhooks for PNW WhatsApp / SMS / voice coastal safety advisories."""
import traceback

from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse

from coastal_common.bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path(__file__)

from pnw.actions import parse_audience, truncate_for_whatsapp
from pnw.safety import (
    match_station_locally,
    process_coastal_safety,
    transcribe_audio_via_openai,
    update_station_registry,
)
from pnw.storage import STATIONS_FILE, load_json

load_dotenv()
app = Flask(__name__)


def _default_voice_station():
    stations = load_json(STATIONS_FILE)
    if isinstance(stations, list):
        for station in stations:
            if station.get("location_name", "").startswith("Westport"):
                return station
        if stations:
            return stations[0]
    return {
        "location_name": "Westport Harbor",
        "state": "WA",
        "latitude": 46.8900,
        "longitude": -124.1100,
        "site_type": "harbor",
        "coast_profile": "A",
        "noaa_station_id": "9441102",
        "landmarks": ["marina docks", "jetty entrance", "public pier"],
        "emergency_line": "📞 Emergency: Dial 911 | USCG Station Grays Harbor",
    }


@app.route("/webhook/whatsapp", methods=["POST"])
@app.route("/webhook/sms", methods=["POST"])
def incoming_message_handler():
    twiml_resp = MessagingResponse()
    try:
        incoming_text = request.values.get("Body", "").strip()
        num_media = int(request.values.get("NumMedia", 0))
        media_url = request.values.get("MediaUrl0", "")
        print(
            f"📩 WhatsApp/SMS Body={incoming_text!r} "
            f"NumMedia={num_media}"
        )

        user_query = incoming_text
        if num_media > 0 and media_url:
            print("🎙️ Processing incoming audio note via OpenAI Whisper...")
            user_query = transcribe_audio_via_openai(media_url)
            print(f"📝 Whisper transcription: '{user_query}'")

        station = match_station_locally(user_query)
        if not station:
            twiml_resp.message(
                "⚓ *PNW Coastal Safety Agent*\n\n"
                "Please state your location (e.g., Astoria, Seattle, Cannon).\n"
                "For category detail: Astoria families | Astoria operators | Astoria fishermen"
            )
            return Response(str(twiml_resp), mimetype="text/xml")

        audience = parse_audience(user_query)
        update_station_registry(user_query, station)
        advisory = process_coastal_safety(station, audience=audience)
        advisory = truncate_for_whatsapp(advisory)
        twiml_resp.message(advisory)

    except Exception:
        traceback.print_exc()
        twiml_resp.message(
            "⚠️ Safety data is syncing. Please check local beach flags and NOAA forecasts."
        )

    return Response(str(twiml_resp), mimetype="text/xml")


@app.route("/webhook/voice", methods=["POST"])
def voice_ivr_handler():
    twiml_voice = VoiceResponse()
    default_station = _default_voice_station()
    update_station_registry("Voice Phone Call Inbound Connection", default_station)

    advisory_script = process_coastal_safety(default_station)
    location = default_station["location_name"]

    twiml_voice.say(
        f"Welcome to the Pacific Northwest Coastal Safety System. "
        f"Here is your current update for {location}.",
        voice="alice",
        language="en-US",
    )
    twiml_voice.say(advisory_script, voice="alice", language="en-US")
    twiml_voice.say(
        "Please check beach flags and local shoreline markers before entering the water. "
        "Stay safe. Goodbye.",
        voice="alice",
        language="en-US",
    )
    twiml_voice.hangup()

    return Response(str(twiml_voice), mimetype="text/xml")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
