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
        "⛔ MONSOON (May 16–Sep 25): Treat water access as high risk. "
        "Follow district orders and red flags."
    )

def apply_monsoon_overlay(advisory, now_ist):
    """Insert the monsoon banner after the advisory header when in season."""
    block = monsoon_overlay_block(now_ist)
    if not block or "MONSOON" in advisory:
        return advisory

    lines = advisory.split("\n", 1)
    header = lines[0]
    rest = lines[1].lstrip("\n") if len(lines) > 1 else ""
    if rest:
        return f"{header}\n\n{block}\n\n{rest}"
    return f"{header}\n\n{block}"

# Coast profiles (Gemini A/B/C). site_type still drives danger labels.
# Bullets: verb first + numeric boundary + outcome. Keep short for WhatsApp.
ACTION_TEMPLATES = {
    # A — shared commercial / high-activity hubs (Malpe-class)
    "A": {
        "low": {
            "recreational": [
                "Swim only within 50 m of the lifeguard line — boats outside create propeller hazard.",
                "Keep kids within arm's reach in the swim zone — boat wash can knock them down.",
            ],
            "operators": [
                "Keep jet skis and banana boats at least 50 m outside the swim zone — collision risk with families.",
                "Pause boat rides if red flags rise within 100 m — continuing risks injury and fines.",
            ],
            "fishermen": [
                "Leave through the marked harbor channel within 100 m of the jetty — cutting across swimmers risks collision.",
                "Return inside the harbor if wind builds — open water outside the walls gets rough fast.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay behind red flags within 50 m of the waterline — shorebreak can slam you into fencing.",
                "Keep kids on upper walkways at least 30 m from surge — boat wash and shorebreak sweep seaward.",
            ],
            "operators": [
                "Limit boat rides to within 100 m of the harbor entrance — swell outside flips small craft.",
                "Keep boats and ride equipment at least 50 m from family beach zones — propeller hazard near the jetty.",
            ],
            "fishermen": [
                "Stay within 200 m of the harbor opening — traffic and swell stack beyond.",
                "Stay at least 150 m from where the river meets the sea in building swell — currents pin boats to the jetty.",
            ],
        },
        "high": {
            "recreational": [
                "🚨 TOTAL WATER BAN. No water entry within 100 m of shore — shorebreak and boats make swimming fatal.",
                "If on the beach, stay behind red flags at least 50 m from the waterline — breaking waves cause head/spinal injury.",
            ],
            "operators": [
                "Stop all boat rides and jet ski trips within 200 m of the beach — injury and fine risk.",
                "Keep all boats and ride equipment at least 50 m inland from the wet sand — gear near water becomes dangerous in surge.",
            ],
            "fishermen": [
                "Keep boats tied inside the protected harbor walls — leaving now risks capsize at the harbor opening.",
                "Stay at least 200 m from where the river meets the sea and from harbor wall ends — surge can smash boats into concrete.",
            ],
        },
    },
    # B — rocky terrain, cliffs, heavy rips (Kapu / Someshwara-class; ready for new stations)
    "B": {
        "low": {
            "recreational": [
                "Stay at least 10 m back from cliff edges — wet rock causes falls onto shorebreak.",
                "Avoid selfie spots within 5 m of drop-offs — shorebreak can cause spinal injury.",
            ],
            "operators": [
                "Keep tours on marked routes within 20 m of signed paths — wet rock shortcuts cause slips.",
                "Stop tours if red flags rise within 100 m — continuing exposes guests to cliff falls.",
            ],
            "fishermen": [
                "Cast at least 15 m from cliff faces — spray zones knock anglers into surge.",
                "Exit if a rip pulls within 50 m — fighting toward rocks risks drowning.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay at least 20 m from cliffs and rock ridges — spray-slick edges cause fatal falls.",
                "Keep kids within arm's reach at least 50 m from water — rips along ridges sweep fast.",
            ],
            "operators": [
                "Limit groups to overlooks at least 25 m from drop-offs — crowd pressure causes falls.",
                "Avoid boat rides within 100 m of rock points — rebound swell flips craft onto reefs.",
            ],
            "fishermen": [
                "Avoid casting within 30 m of rock points in rising swell — shorebreak sweeps ledges.",
                "Keep boats at least 100 m off rock ridges — reefs and rips cause grounding/capsize.",
            ],
        },
        "high": {
            "recreational": [
                "🚨 TOTAL WATER BAN. No rock or water entry within 100 m of shore — rips pull into caves and reefs.",
                "If on shore, stay at least 50 m from cliffs and ridges — falls onto shorebreak are unsurvivable.",
            ],
            "operators": [
                "Stop cliff and rock tours within 100 m of the shore — fall/surge exceeds guide control.",
                "Hold guests behind barriers only — within 50 m of drop-offs risks fatal falls.",
            ],
            "fishermen": [
                "Stay off rock ledges within 100 m of surge — one set can throw you onto basalt.",
                "Keep boats at least 200 m off rock ridges — reefs/rips cause rapid grounding.",
            ],
        },
    },
    # C — estuaries / river-sea mouths / surf confluences
    "C": {
        "low": {
            "recreational": [
                "Keep kids within arm's reach on bank paths — mud within 10 m hides drop-offs.",
                "Stay at least 20 m from unmarked channel edges — tidal cuts trap waders.",
            ],
            "operators": [
                "Run boat rides at least 200 m inland of where the river meets the sea — mouth currents flip small craft.",
                "Stop trips if current accelerates within 100 m of where the river meets the sea — boats can broach on sandbars.",
            ],
            "fishermen": [
                "Work channels at least 150 m inland of where the river meets the sea — strong rips foul shore nets.",
                "Check the sandbar within 50 m before crossing — unseen cuts ground and roll craft.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay at least 30 m from estuary banks at higher water — undercut edges collapse.",
                "No wading within 50 m of channels/sand spits — tidal jets sweep kids seaward.",
            ],
            "operators": [
                "Limit boat rides to at least 300 m inland of where the river meets the sea — bars and opposing currents broach hulls.",
                "Keep boats at least 200 m from where the river meets the sea — rapid jets cause capsizes.",
            ],
            "fishermen": [
                "Stay at least 200 m from where the river meets the sea in strong current — outflow pins nets and canoes.",
                "Secure gear at least 150 m inland of the sea — mouth surge shreds shore nets.",
            ],
        },
        "high": {
            "recreational": [
                "🚨 TOTAL WATER BAN. No wading within 100 m of channels/sand spits — bar shifts create drown-out holes.",
                "If on shore, stay at least 50 m from estuary banks — high water drops walkers into current.",
            ],
            "operators": [
                "Stop all boat rides within 500 m of where the river meets the sea — sandbar and tidal jet exceed small-boat limits.",
                "Keep boats at least 300 m inland of where the river meets the sea — crossing the mouth is a capsize zone.",
            ],
            "fishermen": [
                "Stay at least 300 m from where the river meets the sea at peak tide — current vs swell can roll craft.",
                "Stay off sandbars within 150 m of where the river meets the sea — bars collapse into drop-offs.",
            ],
        },
    },
}

# One-line summary per audience (default WhatsApp reply). Full bullets on demand.
ACTION_ONE_LINERS = {
    "A": {
        "low": {
            "recreational": "Swim only in marked zones; keep kids close.",
            "operators": "Keep jet ski and banana rides clear of the swim zone.",
            "fishermen": "Use the marked harbor channel; return inside if wind builds.",
        },
        "elevated": {
            "recreational": "Stay behind red flags; keep kids on upper walkways.",
            "operators": "Limit boat rides near the harbor entrance; keep clear of family beach zones.",
            "fishermen": "Stay near the harbor opening; avoid where the river meets the sea in building swell.",
        },
        "high": {
            "recreational": "Total water ban — no swimming; stay behind red flags on land.",
            "operators": "Stop all boat rides and jet ski trips; keep equipment inland.",
            "fishermen": "Keep boats tied inside the harbor walls; avoid the river–sea junction.",
        },
    },
    "B": {
        "low": {
            "recreational": "Stay back from cliff edges and selfie drop-offs.",
            "operators": "Keep tours on marked paths; stop if red flags rise.",
            "fishermen": "Cast away from cliff faces; exit if a rip pulls you.",
        },
        "elevated": {
            "recreational": "Stay well back from cliffs; keep kids far from the water.",
            "operators": "Limit overlook groups; avoid boat rides near rock points.",
            "fishermen": "Avoid casting from rock points; keep boats off the ridges.",
        },
        "high": {
            "recreational": "Total water ban — stay far from cliffs and rocks.",
            "operators": "Stop cliff and rock tours; hold guests behind barriers.",
            "fishermen": "Stay off rock ledges; keep boats well clear of ridges.",
        },
    },
    "C": {
        "low": {
            "recreational": "Keep kids on bank paths; stay back from channel edges.",
            "operators": "Run boat rides inland of where the river meets the sea.",
            "fishermen": "Work inland channels; check the sandbar before crossing.",
        },
        "elevated": {
            "recreational": "Stay back from banks; no wading near channels or sand spits.",
            "operators": "Keep boat rides well inland of where the river meets the sea.",
            "fishermen": "Avoid where the river meets the sea in strong current.",
        },
        "high": {
            "recreational": "Total water ban — no wading near channels or sand spits.",
            "operators": "Stop boat rides near where the river meets the sea.",
            "fishermen": "Stay far from where the river meets the sea at peak tide.",
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
    "A": "propeller/collision risk beyond",
    "B": "rock/rip risk beyond",
    "C": "current/sandbar risk beyond",
}

AUDIENCE_HEADERS = (
    ("recreational", "🏊 Families, kids & swimmers:"),
    ("operators", "🏄 Water sports operators:"),
    ("fishermen", "🎣 Small boats & fishermen:"),
)

# Keywords for "Malpe families" / "Karwar fishermen" detail requests.
AUDIENCE_ALIASES = {
    "recreational": (
        "families", "family", "kids", "kid", "swimmers", "swimmer",
        "swim", "beach", "recreational",
    ),
    "operators": (
        "operators", "operator", "rides", "ride", "jetski", "jet-ski",
        "jet ski", "banana", "watersports", "water sports", "tourism",
    ),
    "fishermen": (
        "fishermen", "fisherman", "fishing", "boats", "boat",
        "harbor", "harbour", "net", "nets",
    ),
}

LEGACY_ACTION_MARKERS = (
    "For small non-motorized fishing boats:",
    "For more detail, reply:",
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
    "low": "Manageable for experienced small craft.",
    "elevated": "Extra caution for small boats.",
    "high": "Risky for small boats.",
}

RISK_RANK = {"low": 0, "elevated": 1, "high": 2}
RISK_LEVELS = ("low", "elevated", "high")

# WhatsApp freeform body limit is 1600; stay under with margin.
WHATSAPP_MAX_CHARS = 1500

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

def landmark_zoning_line(station, risk_level):
    """Optional recreational bullet: landmark zoning that matches swim vs total ban."""
    landmarks = station.get("landmarks") or []
    if not isinstance(landmarks, list) or not landmarks:
        return None
    risk_level = normalize_risk_level(risk_level)
    labels = [str(item).strip() for item in landmarks if str(item).strip()]
    if not labels:
        return None

    if risk_level == "high":
        hazard = next(
            (
                item
                for item in labels
                if "jetty" in item.lower() or "breakwater" in item.lower()
            ),
            None,
        )
        walkway = next(
            (
                item
                for item in labels
                if "walkway" in item.lower() or "sea walk" in item.lower()
            ),
            None,
        )
        if hazard and walkway:
            return (
                f"Stay off and clear of the {hazard}—surges can sweep pedestrians "
                f"off structures. Stay on the land-side of the {walkway} behind barriers."
            )
        if hazard:
            return (
                f"Stay off and clear of the {hazard}—surges can sweep pedestrians "
                f"off structures. Stay behind barriers on solid ground only."
            )
        zone = format_landmark_list(labels[:2])
        return (
            f"If on shore, stay behind barriers on the land-side of the {zone} — "
            f"do not enter the water or climb wet structures."
        )

    zone = format_landmark_list(labels[:2])
    profile = station_coast_profile(station)
    outcome = LANDMARK_OUTCOMES.get(profile, LANDMARK_OUTCOMES["A"])
    return f"Stay within 50 m of the {zone} — {outcome}."

def emergency_footer(station):
    line = (station.get("emergency_line") or "").strip()
    if line:
        return line
    return "📞 Emergency: Dial 112"

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

def fetch_marine_bundle(latitude, longitude, now_ist):
    """
    Open-Meteo marine: current wave height + hourly sea_level_height_msl.
    Returns {"wave_m": float|None, "sea_levels": list|None, "sea_idx": int}.
    """
    empty = {"wave_m": None, "sea_levels": None, "sea_idx": 0}
    try:
        response = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": float(latitude),
                "longitude": float(longitude),
                "hourly": "wave_height,sea_level_height_msl",
                "timezone": "Asia/Kolkata",
                "forecast_days": 3,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        times = payload["hourly"]["time"]
        heights = payload["hourly"]["wave_height"]
        sea_levels = payload["hourly"].get("sea_level_height_msl")
        current_hour_str = now_ist.strftime("%Y-%m-%dT%H:00")
        try:
            idx = times.index(current_hour_str)
        except ValueError:
            idx = 0
        wave_m = None
        if idx < len(heights) and heights[idx] is not None:
            wave_m = float(heights[idx])
        if not sea_levels:
            return {"wave_m": wave_m, "sea_levels": None, "sea_idx": idx}
        return {
            "wave_m": wave_m,
            "sea_levels": sea_levels,
            "sea_idx": idx,
        }
    except Exception as exc:
        print(f"⚠️ Marine fetch failed: {exc}")
        return empty

def actions_for(station, audience, risk_level):
    profile = station_coast_profile(station)
    by_profile = ACTION_TEMPLATES.get(profile, ACTION_TEMPLATES["A"])
    by_risk = by_profile.get(normalize_risk_level(risk_level), by_profile["elevated"])
    bullets = list(by_risk[audience])
    if audience == "recreational":
        zoning = landmark_zoning_line(station, risk_level)
        if zoning:
            # After water-ban line when present; otherwise lead with zoning.
            if bullets and "TOTAL WATER BAN" in bullets[0]:
                bullets.insert(1, zoning)
            else:
                bullets.insert(0, zoning)
    return bullets

def one_liner_for(station, audience, risk_level):
    profile = station_coast_profile(station)
    by_profile = ACTION_ONE_LINERS.get(profile, ACTION_ONE_LINERS["A"])
    by_risk = by_profile.get(normalize_risk_level(risk_level), by_profile["elevated"])
    return by_risk[audience]

def build_one_liner_sections(station, risk_level):
    lines = []
    for audience, header in AUDIENCE_HEADERS:
        lines.append(f"{header} {one_liner_for(station, audience, risk_level)}")
    lines.append("")
    place = station["location_name"].split()[0]
    lines.append(
        "For more detail, reply: "
        f"{place} families | {place} operators | {place} fishermen"
    )
    return "\n".join(lines)

def build_detail_section(station, risk_level, audience):
    header = dict(AUDIENCE_HEADERS)[audience]
    lines = [header]
    for bullet in actions_for(station, audience, risk_level):
        lines.append(f"- {bullet}")
    return "\n".join(lines)

def build_action_sections(station, risk_level, audience=None):
    """Full multi-audience detail (used in prompts / legacy) or one audience."""
    if audience:
        return build_detail_section(station, risk_level, audience)
    lines = []
    for key, header in AUDIENCE_HEADERS:
        lines.append(header)
        for bullet in actions_for(station, key, risk_level):
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(lines).rstrip()

def apply_action_templates(advisory, station, risk_level, audience=None):
    """Attach summary one-liners or one category's detailed bullets."""
    if audience:
        sections = build_detail_section(station, risk_level, audience)
    else:
        sections = build_one_liner_sections(station, risk_level)
    cut_at = earliest_marker_index(
        advisory, audience_header_texts() + list(LEGACY_ACTION_MARKERS)
    )
    closing = "Stay safe.\n\n" + emergency_footer(station)

    stay_idx = advisory.rfind("Stay safe.")
    if cut_at is not None and stay_idx != -1 and cut_at < stay_idx:
        return advisory[:cut_at].rstrip() + "\n\n" + sections + "\n\n" + closing
    if stay_idx != -1:
        return advisory[:stay_idx].rstrip() + "\n\n" + sections + "\n\n" + closing
    return advisory.rstrip() + "\n\n" + sections + "\n\n" + closing

def parse_audience(user_text):
    """Return audience key if the message asks for a category detail."""
    clean = " ".join((user_text or "").lower().split())
    if not clean:
        return None
    # Prefer longer aliases first (e.g. "water sports" before "water").
    candidates = []
    for audience, aliases in AUDIENCE_ALIASES.items():
        for alias in aliases:
            candidates.append((len(alias), alias, audience))
    candidates.sort(reverse=True)
    for _length, alias, audience in candidates:
        if alias in clean:
            return audience
    return None

def truncate_for_whatsapp(text, limit=WHATSAPP_MAX_CHARS):
    """Hard-cap outbound WhatsApp body so Twilio does not silently drop it."""
    if len(text) <= limit:
        return text
    suffix = "\n\n…(shortened) Stay safe."
    keep = limit - len(suffix)
    trimmed = text[:keep].rsplit("\n", 1)[0].rstrip()
    print(f"⚠️ Truncated advisory from {len(text)} to ≤{limit} chars for WhatsApp")
    return trimmed + suffix

def describe_trend(values, threshold):
    if len(values) < 2:
        return "steady"
    delta = values[-1] - values[0]
    if delta > threshold:
        return "increasing"
    if delta < -threshold:
        return "decreasing"
    return "steady"

def impact_trend_label(values, soft_threshold, strong_threshold, rising_word, falling_word):
    """Layperson trend label: Rising / Rising fast / Falling / Falling fast / Steady."""
    if len(values) < 2:
        return "Steady"
    delta = values[-1] - values[0]
    if delta >= strong_threshold:
        return f"{rising_word} fast"
    if delta > soft_threshold:
        return rising_word
    if delta <= -strong_threshold:
        return f"{falling_word} fast"
    if delta < -soft_threshold:
        return falling_word
    return "Steady"

def wind_impact_label(wind_kmh, winds_window, gust_kmh=None):
    """Plain-language wind for the public — no km/h or 'gusts N' jargon."""
    mean = float(wind_kmh or 0)
    gust = float(gust_kmh) if gust_kmh is not None else None
    gusty = (
        gust is not None
        and gust >= mean + 5
        and gust >= WIND_ELEVATED_KMH
    )

    # Light mean + punchy gusts: the burst is the hazard, not a fake trend.
    if mean < WIND_ELEVATED_KMH and gusty:
        return "sudden strong wind bursts"

    if mean < 5:
        return "light"
    if mean < WIND_ELEVATED_KMH:
        return "gentle"

    trend = impact_trend_label(winds_window, 2.0, 8.0, "Rising", "Easing")
    if gusty:
        if "Rising" in trend:
            return "strong, building, with sudden bursts"
        if "Easing" in trend:
            return "still strong with sudden bursts"
        return "strong with sudden bursts"
    if trend == "Rising fast":
        return "strong and building fast"
    if trend == "Rising":
        return "strong and building"
    if trend == "Easing fast":
        return "strong but easing"
    if trend == "Easing":
        return "strong but easing"
    return "strong"

def weather_condition_label(pressures_window, wave_m=None, risk_level=None):
    """Public weather phrase — no hPa / meteorologist jargon."""
    pressure_trend = impact_trend_label(
        pressures_window, 0.5, 2.0, "Rising", "Falling"
    )
    rough_sea = wave_m is not None and wave_m >= WAVE_HIGH_M
    choppy_sea = wave_m is not None and wave_m >= WAVE_ELEVATED_M

    if pressure_trend == "Falling fast" or (
        pressure_trend == "Falling" and rough_sea
    ):
        return "Storm conditions developing"
    if pressure_trend == "Falling" or rough_sea:
        return "Rough conditions building"
    if choppy_sea or risk_level == "elevated":
        return "Caution — seas unsettled"
    if "Rising" in pressure_trend:
        return "Conditions easing"
    return "Conditions relatively calm"

def sea_condition_label(wave_m):
    if wave_m is None:
        return None
    if wave_m >= WAVE_HIGH_M:
        return "rough"
    if wave_m >= WAVE_ELEVATED_M:
        return "choppy"
    return "moderate"

def build_weather_line(
    pressure, pressures_window, wind, winds_window, wave_m, gust_kmh=None, risk_level=None
):
    # pressure arg kept for call-site compatibility; not shown to the public.
    _ = pressure
    parts = [
        f"Weather: {weather_condition_label(pressures_window, wave_m, risk_level)}",
        f"Wind: {wind_impact_label(wind, winds_window, gust_kmh=gust_kmh)}",
    ]
    sea = sea_condition_label(wave_m)
    if sea:
        parts.append(f"Sea: {sea}")
    return " | ".join(parts)

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
    if marine["sea_levels"]:
        tide_timing = compute_tide_timing(
            marine["sea_levels"], marine["sea_idx"], now_ist=now_ist
        )
    else:
        print("⚠️ sea_level_height_msl unavailable; tide timing uncertain.")
        tide_timing = {
            "tide_summary": "Tide timing uncertain — use local shoreline markers.",
            "source": "unavailable",
        }

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
        "current_pressure": target_pressures[0],
        "current_wind": current_wind,
        "current_wave": current_wave,
        "pressure_trend": describe_trend(target_pressures, 0.5),
        "wind_trend": describe_trend(target_winds, 2.0),
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
