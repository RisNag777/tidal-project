"""Coast-profile action copy and WhatsApp reply assembly (PNW)."""
from coastal_common.actions_kit import (
    apply_action_templates as _apply_action_templates,
    format_landmark_list,
    parse_audience as _parse_audience,
    truncate_for_whatsapp,
)
from coastal_common.risk import normalize_risk_level, station_site_type

# A harbor/port, B rocky/open beach with stacks, C estuary/bar
ACTION_TEMPLATES = {
    "A": {
        "low": {
            "recreational": [
                "Swim only in marked zones — boat traffic and cold water raise risk outside the swim area.",
                "Keep kids within arm's reach near the water — boat wake and cold shock can knock them down.",
            ],
            "operators": [
                "Keep rentals and rides clear of swim zones and ferry lanes — collision risk with families.",
                "Pause trips if small-craft advisories or red flags go up — continuing risks injury and fines.",
            ],
            "fishermen": [
                "Use marked channels and jetty openings — cutting across traffic risks collision.",
                "Return inside the harbor if wind builds — bars and entrances get rough fast.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay behind flags and well back from the surge line — sneaker waves slam hard here.",
                "Keep kids on upper walkways away from wet docks — boat wash and surge sweep seaward.",
            ],
            "operators": [
                "Limit boat rides to sheltered water near the harbor — swell outside flips small craft.",
                "Keep gear off wet docks and jetty ends — propeller and surge hazard near families.",
            ],
            "fishermen": [
                "Stay near the harbor opening — bar and entrance seas stack beyond.",
                "Avoid the river–ocean junction in building swell — currents pin boats to jetties.",
            ],
        },
        "high": {
            "recreational": [
                "🚨 TOTAL WATER BAN. No water entry — cold water, surge, and boats make swimming fatal.",
                "If on the beach or pier, stay behind barriers well back from the waterline.",
            ],
            "operators": [
                "Stop all boat rides and rentals near the beach and bar — injury and fine risk.",
                "Keep equipment inland of the wet sand — gear near water becomes dangerous in surge.",
            ],
            "fishermen": [
                "Keep boats tied inside protected harbor walls — leaving now risks capsize at the entrance.",
                "Stay clear of jetty ends and the bar — surge can smash boats into rock and concrete.",
            ],
        },
    },
    "B": {
        "low": {
            "recreational": [
                "Stay back from wet rocks and selfie drop-offs — sneaker waves and slips cause serious injury.",
                "Watch kids near tide pools — cold water and sudden waves pull people off rocks.",
            ],
            "operators": [
                "Keep tours on marked paths — wet rock shortcuts cause falls.",
                "Stop tours if high-surf or red-flag warnings rise — cliff and rock exposure exceeds guide control.",
            ],
            "fishermen": [
                "Cast away from cliff faces and sea stacks — spray zones knock anglers into surge.",
                "Exit if a rip pulls you — fighting toward rocks risks drowning.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay well back from cliffs, stacks, and log lines — sneaker waves and driftwood kill.",
                "Keep kids far from the water — rips along rocky points sweep fast.",
            ],
            "operators": [
                "Limit overlook groups — crowd pressure near drop-offs causes falls.",
                "Avoid boat rides near rock points — rebound swell flips craft onto reefs.",
            ],
            "fishermen": [
                "Avoid casting from rock points in rising swell — shorebreak sweeps ledges.",
                "Keep boats well off rock ridges — reefs and rips cause grounding.",
            ],
        },
        "high": {
            "recreational": [
                "🚨 TOTAL WATER BAN. Stay far from cliffs, stacks, and the wet sand — sneaker waves are unsurvivable.",
                "If on shore, stay behind barriers on solid ground only.",
            ],
            "operators": [
                "Stop cliff and rock tours — fall and surge exceed guide control.",
                "Hold guests behind barriers only — near drop-offs risks fatal falls.",
            ],
            "fishermen": [
                "Stay off rock ledges — one set can throw you onto basalt.",
                "Keep boats well clear of ridges and stacks — reefs cause rapid grounding.",
            ],
        },
    },
    "C": {
        "low": {
            "recreational": [
                "Keep kids on bank paths — mud and undercut edges hide drop-offs.",
                "Stay back from unmarked channel edges — tidal cuts trap waders.",
            ],
            "operators": [
                "Run boat rides inland of the river mouth — bar currents flip small craft.",
                "Stop trips if current accelerates near the mouth — boats can broach on sandbars.",
            ],
            "fishermen": [
                "Work inland channels — strong rips foul nets near the mouth.",
                "Check the bar and sandbars before crossing — unseen cuts ground and roll craft.",
            ],
        },
        "elevated": {
            "recreational": [
                "Stay back from estuary banks at higher water — undercut edges collapse.",
                "No wading near channels or sand spits — tidal jets sweep kids seaward.",
            ],
            "operators": [
                "Keep boat rides well inland of the river–ocean junction — bars and opposing currents broach hulls.",
                "Keep boats clear of the bar entrance — rapid jets cause capsizes.",
            ],
            "fishermen": [
                "Avoid the river–ocean junction in strong current — outflow pins nets and canoes.",
                "Secure gear inland of the mouth — bar surge shreds shore nets.",
            ],
        },
        "high": {
            "recreational": [
                "🚨 TOTAL WATER BAN. No wading near channels or sand spits — bar shifts create drown-out holes.",
                "If on shore, stay far from estuary banks — high water drops walkers into current.",
            ],
            "operators": [
                "Stop boat rides near the river–ocean junction — sandbar and tidal jet exceed small-boat limits.",
                "Keep boats far inland of the mouth — crossing the bar is a capsize zone.",
            ],
            "fishermen": [
                "Stay far from the river–ocean junction at peak tide — current vs swell can roll craft.",
                "Stay off sandbars near the mouth — bars collapse into drop-offs.",
            ],
        },
    },
}

ACTION_ONE_LINERS = {
    "A": {
        "low": {
            "recreational": "Swim only in marked zones; keep kids close in cold water.",
            "operators": "Keep rides clear of swim zones and ferry lanes.",
            "fishermen": "Use marked channels; return inside if wind builds.",
        },
        "elevated": {
            "recreational": "Stay behind flags; keep kids off wet docks and piers.",
            "operators": "Limit trips to sheltered harbor water.",
            "fishermen": "Stay near the harbor opening; avoid the bar in building swell.",
        },
        "high": {
            "recreational": "Total water ban — stay behind barriers on land.",
            "operators": "Stop all boat rides and rentals; keep gear inland.",
            "fishermen": "Keep boats tied inside; clear of jetty ends and the bar.",
        },
    },
    "B": {
        "low": {
            "recreational": "Stay back from wet rocks, stacks, and selfie drop-offs.",
            "operators": "Keep tours on marked paths; stop if high-surf flags rise.",
            "fishermen": "Cast away from cliff faces; exit if a rip pulls you.",
        },
        "elevated": {
            "recreational": "Stay well back from cliffs and log lines; watch for sneaker waves.",
            "operators": "Limit overlook groups; avoid rock-point boat rides.",
            "fishermen": "Avoid rock points; keep boats off the ridges.",
        },
        "high": {
            "recreational": "Total water ban — stay far from cliffs, stacks, and wet sand.",
            "operators": "Stop cliff and rock tours; hold guests behind barriers.",
            "fishermen": "Stay off rock ledges; keep boats well clear of ridges.",
        },
    },
    "C": {
        "low": {
            "recreational": "Keep kids on bank paths; stay back from channel edges.",
            "operators": "Run boat rides inland of the river mouth.",
            "fishermen": "Work inland channels; check the bar before crossing.",
        },
        "elevated": {
            "recreational": "Stay back from banks; no wading near channels or sand spits.",
            "operators": "Keep boat rides well inland of the river–ocean junction.",
            "fishermen": "Avoid the river–ocean junction in strong current.",
        },
        "high": {
            "recreational": "Total water ban — no wading near channels or sand spits.",
            "operators": "Stop boat rides near the river–ocean junction.",
            "fishermen": "Stay far from the river–ocean junction at peak tide.",
        },
    },
}

SITE_TYPE_TO_COAST_PROFILE = {
    "harbor": "A",
    "port": "A",
    "beach": "B",
    "rocky": "B",
    "estuary": "C",
}

LANDMARK_OUTCOMES = {
    "A": "boat/collision risk beyond",
    "B": "sneaker-wave/rock risk beyond",
    "C": "current/sandbar risk beyond",
}

AUDIENCE_HEADERS = (
    ("recreational", "🏊 Families, kids & swimmers:"),
    ("operators", "🏄 Water sports operators:"),
    ("fishermen", "🎣 Small boats & fishermen:"),
)

AUDIENCE_ALIASES = {
    "recreational": (
        "families", "family", "kids", "kid", "swimmers", "swimmer",
        "swim", "beach", "recreational",
    ),
    "operators": (
        "operators", "operator", "rides", "ride", "jetski", "jet-ski",
        "jet ski", "charter", "watersports", "water sports", "tourism",
    ),
    "fishermen": (
        "fishermen", "fisherman", "fishing", "boats", "boat",
        "harbor", "harbour", "net", "nets",
    ),
}

LEGACY_ACTION_MARKERS = (
    "For more detail, reply:",
)


def audience_header_texts():
    return [header for _, header in AUDIENCE_HEADERS]


def station_coast_profile(station):
    raw = str(station.get("coast_profile") or "").strip().upper()
    if raw in ACTION_TEMPLATES:
        return raw
    return SITE_TYPE_TO_COAST_PROFILE.get(station_site_type(station), "A")


def landmark_zoning_line(station, risk_level):
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
                if "jetty" in item.lower() or "pier" in item.lower() or "rock" in item.lower()
            ),
            None,
        )
        if hazard:
            return (
                f"Stay off and clear of the {hazard} — surges and sneaker waves "
                f"can sweep pedestrians off structures. Stay behind barriers on solid ground."
            )
        zone = format_landmark_list(labels[:2])
        return (
            f"If on shore, stay behind barriers on the land-side of the {zone} — "
            f"do not enter the water or climb wet structures."
        )

    zone = format_landmark_list(labels[:2])
    profile = station_coast_profile(station)
    outcome = LANDMARK_OUTCOMES.get(profile, LANDMARK_OUTCOMES["A"])
    return f"Stay near the {zone} — {outcome}."


def emergency_footer(station):
    line = (station.get("emergency_line") or "").strip()
    if line:
        return line
    return "📞 Emergency: Dial 911"


def actions_for(station, audience, risk_level):
    profile = station_coast_profile(station)
    by_profile = ACTION_TEMPLATES.get(profile, ACTION_TEMPLATES["A"])
    by_risk = by_profile.get(normalize_risk_level(risk_level), by_profile["elevated"])
    bullets = list(by_risk[audience])
    if audience == "recreational":
        zoning = landmark_zoning_line(station, risk_level)
        if zoning:
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
    if audience:
        sections = build_detail_section(station, risk_level, audience)
    else:
        sections = build_one_liner_sections(station, risk_level)
    return _apply_action_templates(
        advisory,
        sections,
        emergency_footer(station),
        audience_header_texts() + list(LEGACY_ACTION_MARKERS),
    )


def parse_audience(user_text):
    return _parse_audience(user_text, AUDIENCE_ALIASES)
