"""Coast-profile action copy and WhatsApp reply assembly."""
from risk import normalize_risk_level, station_site_type

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

# WhatsApp freeform body limit is 1600; stay under with margin.
WHATSAPP_MAX_CHARS = 1500

def audience_header_texts():
    return [header for _, header in AUDIENCE_HEADERS]

def earliest_marker_index(text, markers):
    cut_at = None
    for marker in markers:
        idx = text.find(marker)
        if idx != -1 and (cut_at is None or idx < cut_at):
            cut_at = idx
    return cut_at

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
