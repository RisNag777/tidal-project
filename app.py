"""Flask webhooks for WhatsApp / SMS / voice coastal safety advisories."""
import traceback

from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse

from actions import parse_audience, truncate_for_whatsapp
from safety import (
    match_station_locally,
    process_coastal_safety,
    transcribe_audio_via_sarvam,
    update_station_registry,
)

load_dotenv()
app = Flask(__name__)


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
            print("🎙️ Processing incoming audio note from Twilio pipeline...")
            user_query = transcribe_audio_via_sarvam(media_url)
            print(f"📝 Sarvam Audio Transcription: '{user_query}'")

        station = match_station_locally(user_query)
        if not station:
            twiml_resp.message(
                "⚓ *Karnataka Coastal Safety Agent*\n\n"
                "Please state your location (e.g., Malpe, Karwar).\n"
                "For category detail: Malpe families | Malpe operators | Malpe fishermen"
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
            "⚠️ Safety database is syncing. Please check local shoreline water indicators."
        )

    return Response(str(twiml_resp), mimetype="text/xml")


@app.route("/webhook/voice", methods=["POST"])
def voice_ivr_handler():
    twiml_voice = VoiceResponse()

    default_station = {
        "location_name": "Malpe Fishing Harbor",
        "latitude": 13.3486,
        "longitude": 74.6961,
        "site_type": "harbor",
        "coast_profile": "A",
        "landmarks": ["concrete jetty", "public Sea Walkway", "lifeguard watchtower"],
        "emergency_line": "📞 Malpe Harbor / Coastal Security: Dial 112",
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
