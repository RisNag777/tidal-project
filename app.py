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

# Coast profiles (Gemini A/B/C). site_type still drives danger labels.
# Bullets: verb first + numeric boundary + outcome.
ACTION_TEMPLATES = {
    # A — shared commercial / high-activity hubs (Malpe-class)
    "A": {
        "low": {
            "recreational": [
                "Swim only inside marked zones within 50 m of the lifeguard line. Outside that strip, working boats create propeller hazard.",
                "Keep children within arm's reach inside the swim zone. Fast craft wake can knock toddlers off their feet.",
                "Stay clear of slipways within 30 m of launching craft. Propellers and hull swing can cause crush injuries.",
            ],
            "operators": [
                "Keep jet skis and banana boats outside the swim zone by at least 50 m. Overlap with families creates collision risk.",
                "Hold tourist boats within the marked lane past the jetty. Cutting inside that lane risks propeller strikes on waders.",
                "Pause launches if patrols raise red flags within 100 m of the beach. Continuing ops then risks fine and injury claims.",
            ],
            "fishermen": [
                "Exit through the marked harbor channel within 100 m of the jetty tip. Cutting across swim water risks collision with rentals.",
                "Carry life jackets and keep phone or VHF contact within 30 minutes of departure. Delay reporting slows rescue.",
                "Return inside the basin if wind builds above comfort. Open approaches amplify swell against the breakwater.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay behind barricades and red flags within 50 m of the waterline. Shorebreak can slam you into fencing.",
                "Avoid the river mouth and breakwater within 100 m. Overlapping boat traffic and surge create knockdown risk.",
                "Keep children on upper walkways at least 30 m from surge. Fast craft wake and shorebreak can sweep them seaward.",
            ],
            "operators": [
                "Limit launches to sheltered water within 100 m of the basin entrance. Building swell outside that line flips small craft.",
                "Keep rental craft outside family zones by at least 50 m. Propeller hazard rises when crowds compress near the jetty.",
                "Avoid operating within 100 m of the breakwater in rising swell. Reflected waves can throw riders into rock or concrete.",
            ],
            "fishermen": [
                "Favor trips inside or within 200 m of the harbor mouth. Beyond that, commercial traffic and swell stack risk.",
                "Avoid the river mouth within 150 m if swell is building. Cross-currents can pin small craft against the jetty.",
                "Secure gear before peak tide within 1 hour of high water. Loose nets and crates become deck hazards in surge.",
            ],
        },
        "high": {
            "recreational": [
                "Stay behind barricades and red flags within 50 m of the waterline. Breaking waves can cause spinal and head injuries on concrete.",
                "Avoid all water entry within 100 m of the shoreline. Shorebreak and boat traffic make swimming a fatal risk.",
                "Keep children on upper dry walkways at least 30 m from surge. Sudden wash-up can pull them under fencing.",
            ],
            "operators": [
                "Suspend all recreational launches within 200 m of the beach. Continuing ops risks passenger injury and enforcement action.",
                "Ground jet skis, banana boats, and rentals at least 50 m inland of the high-water mark. Equipment near shore becomes projectile hazard.",
                "Keep commercial craft inside the protected basin within the jetty line. Open approaches are propeller and broach zones.",
            ],
            "fishermen": [
                "Remain docked inside the protected harbor within the breakwater. Leaving now risks capsize at the mouth.",
                "Avoid shore launches within 100 m of the beach. Undercurrents and shorebreak can flip non-motorized craft.",
                "Stay clear of the river mouth and breakwater within 200 m. Peak tide surge there can pin hulls against concrete.",
            ],
        },
    },
    # B — rocky terrain, cliffs, heavy rips (Kapu / Someshwara-class; ready for new stations)
    "B": {
        "low": {
            "recreational": [
                "Stay on marked paths at least 10 m back from cliff edges. Wet rock causes falls onto shorebreak.",
                "Keep within 50 m of the lifeguard or lighthouse approach when walking the foreshore. Hidden rips run along rock ridges.",
                "Avoid selfie spots within 5 m of drop-offs. Sudden shorebreak can knock you onto rocks and cause spinal injury.",
            ],
            "operators": [
                "Hold guided walks on marked routes within 20 m of signed paths. Shortcuts across wet rock cause slip injuries.",
                "Keep rental gear off rock shelves within 30 m of surge. Equipment becomes a slide hazard when wet.",
                "Abort tours if red flags rise within 100 m of the viewing point. Continuing then exposes guests to cliff fall risk.",
            ],
            "fishermen": [
                "Cast only from signed shore points at least 15 m from cliff faces. Rock spray zones knock anglers into surge.",
                "Wear non-slip footwear within 20 m of wet rock. Algae film causes falls into shorebreak.",
                "Exit if a rip pulls within 50 m of your stance. Fighting the current toward rocks risks drowning.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay at least 20 m back from cliff edges and rock ridges. Spray-slick surfaces cause fatal falls.",
                "Avoid rock pools within 30 m of open shorebreak. Sudden sets can pin you against basalt.",
                "Keep children within arm's reach on the upper path, at least 50 m from the waterline. Rips along ridges sweep fast.",
            ],
            "operators": [
                "Limit groups to marked overlooks at least 25 m from drop-offs. Crowd pressure near edges causes falls.",
                "Ground water toys at least 50 m inland of rock shelves. Surf can throw gear and bystanders onto stone.",
                "Avoid launching within 100 m of rock points. Reflected swell flips small craft onto reefs.",
            ],
            "fishermen": [
                "Avoid casting within 30 m of rock points in rising swell. Shorebreak can sweep you off the ledge.",
                "Keep boats at least 100 m off rock ridges. Hidden reefs and rips cause grounding and capsize.",
                "Secure gear before peak sets within 1 hour of high water. Loose tackle becomes a trip hazard on wet rock.",
            ],
        },
        "high": {
            "recreational": [
                "Stay at least 50 m back from cliffs and rock ridges. Shorebreak and spray make edges unsurvivable if you fall.",
                "Avoid all rock and water entry within 100 m of the shoreline. Rips along formations pull swimmers into caves and reefs.",
                "Keep to upper paths near the lighthouse or signed ridge line only. Selfie ledges are spinal-injury zones in this surf.",
            ],
            "operators": [
                "Suspend all cliff and rock tours within 100 m of the foreshore. Fall and surge risk exceeds guide control.",
                "Ground all craft and gear at least 100 m inland. Equipment near rock shelves becomes projectile hazard.",
                "Hold guests behind signed barriers only. Crossing within 50 m of drop-offs risks fatal falls.",
            ],
            "fishermen": [
                "Remain off rock ledges and point launches within 100 m of surge. One set can throw you onto basalt.",
                "Keep vessels at least 200 m off rock ridges. Reefs and rips here cause rapid grounding.",
                "Shelter in harbor or inland berths only. Open rocky approaches are capsize zones at this energy.",
            ],
        },
    },
    # C — estuaries / river-sea mouths / surf confluences
    "C": {
        "low": {
            "recreational": [
                "Keep children within arm's reach inside marked bank paths. Soft mud within 10 m of the edge hides drop-offs.",
                "Stay at least 20 m back from unmarked channel edges. Tidal cuts deepen fast and trap waders.",
                "Avoid sandbars within 50 m of the active mouth. Bars shift and create sudden holes underfoot.",
            ],
            "operators": [
                "Run tours only on inland stretches at least 200 m from the sea mouth. Mouth currents flip small passenger craft.",
                "Hold passengers inside the boat within 5 m of boarding points. Slippery mangrove roots cause fall injuries.",
                "Abort if current visibly accelerates within 100 m of the confluence. Continuing then risks broach on bars.",
            ],
            "fishermen": [
                "Work sheltered channels at least 150 m inland of the mouth. Confluence rips foul traditional shore nets.",
                "Carry life jackets within reach on every trip. Cold shock after a fall into the mouth slows self-rescue.",
                "Check the bar within 50 m before crossing. Unseen cuts can ground and roll small craft.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay at least 30 m back from estuary banks at higher water. Undercut edges collapse without warning.",
                "Avoid wading within 50 m of channels or sand spits. Drop-offs and tidal jets sweep children seaward.",
                "Keep to designated walkways only, at least 20 m from the mangrove edge when surge is up. Soft banks give way.",
            ],
            "operators": [
                "Limit tours to sheltered inland water at least 300 m from the mouth. Bars and opposing currents broach hulls.",
                "Keep passenger boats off the confluence within 200 m. Rapid tidal jets cause capsizes.",
                "Delay new trips if district flags rise within the estuary zone. Operating then risks passenger injury.",
            ],
            "fishermen": [
                "Avoid the mouth within 200 m in strong current. Outflow against swell pins nets and canoes.",
                "Secure nets and canoes in inland channels at least 150 m from the sea. Mouth surge shreds shore sets.",
                "Watch for rips within 100 m of where river meets sea. Crossing that line risks sweep-out.",
            ],
        },
        "high": {
            "recreational": [
                "Stay at least 50 m back from estuary banks. High water undercuts paths and drops walkers into current.",
                "Avoid all wading within 100 m of channels or sand spits. Violent bar shifts create drown-out holes.",
                "Keep to designated walkways only, at least 30 m from the mangrove or tree line. Soft edges fail in surge.",
            ],
            "operators": [
                "Suspend all estuary tours within 500 m of the mouth. Sandbar and tidal jet risk exceeds small-craft limits.",
                "Keep passenger boats inland at least 300 m from the confluence. Mouth crossings are capsize zones.",
                "Hold service until district advisories clear. Restarting early risks passenger and hull loss.",
            ],
            "fishermen": [
                "Avoid the estuary mouth within 300 m at peak tide. Opposing current and swell can roll small craft.",
                "Secure nets and canoes in inland channels at least 200 m from the sea. Shore casting at the mouth is a sweep-out trap.",
                "Stay off sandbars within 150 m of the confluence. Bars collapse and create fatal drop-offs underfoot.",
            ],
        },
    },
}

# Fallback when coast_profile is missing
SITE_TYPE_TO_COAST_PROFILE = {
    "harbor": "A",
    "port": "A",
    "backwater": "C",
    "estuary": "C",
}

LANDMARK_OUTCOMES = {
    "A": "Outside that strip, jet skis and tourist boats create propeller and collision risk.",
    "B": "Outside that strip, rock faces and rip currents create fall and sweep-out risk.",
    "C": "Outside that strip, estuary currents and shifting sandbars create drop-off and sweep-out risk.",
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

def station_coast_profile(station):
    """Return A/B/C coast profile; fall back from site_type when unset."""
    raw = str(station.get("coast_profile") or "").strip().upper()
    if raw in ACTION_TEMPLATES:
        return raw
    return SITE_TYPE_TO_COAST_PROFILE.get(station_site_type(station), "A")

def format_landmark_list(landmarks):
    landmarks = [str(item).strip() for item in landmarks if str(item).strip()]
    if not landmarks:
        return ""
    if len(landmarks) == 1:
        return landmarks[0]
    if len(landmarks) == 2:
        return f"{landmarks[0]} and {landmarks[1]}"
    return ", ".join(landmarks[:-1]) + f", and {landmarks[-1]}"

def landmark_zoning_line(station):
    """Optional recreational bullet: numeric stay-near landmarks + profile outcome."""
    landmarks = station.get("landmarks") or []
    if not isinstance(landmarks, list) or not landmarks:
        return None
    zone = format_landmark_list(landmarks)
    if not zone:
        return None
    profile = station_coast_profile(station)
    outcome = LANDMARK_OUTCOMES.get(profile, LANDMARK_OUTCOMES["A"])
    return f"Keep within 50 m of the {zone}. {outcome}"

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
    profile = station_coast_profile(station)
    by_profile = ACTION_TEMPLATES.get(profile, ACTION_TEMPLATES["A"])
    by_risk = by_profile.get(normalize_risk_level(risk_level), by_profile["elevated"])
    bullets = list(by_risk[audience])
    if audience == "recreational":
        zoning = landmark_zoning_line(station)
        if zoning:
            bullets.insert(0, zoning)
    return bullets

def build_action_sections(station, risk_level):
    lines = []
    for audience, header in AUDIENCE_HEADERS:
        lines.append(header)
        for bullet in actions_for(station, audience, risk_level):
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(lines).rstrip()

def apply_action_templates(advisory, station, risk_level):
    """Replace free-form action bullets with coast-profile + risk templates."""
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
                "Please state your location to check safety windows (e.g., Malpe, Karwar)."
            )
            return Response(str(twiml_resp), mimetype="text/xml")

        update_station_registry(user_query, station)
        advisory = process_coastal_safety(station)
        # WhatsApp freeform body limit is 1600 characters.
        if len(advisory) > 1500:
            print(f"⚠️ Advisory length {len(advisory)} may exceed WhatsApp limit")
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
