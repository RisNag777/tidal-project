"""Wind/wave risk scoring and advisory labels."""

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

# Small-craft thresholds (Open-Meteo wind km/h, significant wave height m)
WIND_ELEVATED_KMH = 20.0
WIND_HIGH_KMH = 35.0
WAVE_ELEVATED_M = 1.0
WAVE_HIGH_M = 1.75

def station_site_type(station):
    return station.get("site_type", "harbor")

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
