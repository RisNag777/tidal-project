"""Karnataka site danger labels (shared scoring lives in coastal_common.risk)."""
from coastal_common.risk import (
    RISK_ADVISORY_TITLES,
    RISK_BOAT_SENTENCES,
    RISK_LEVELS,
    RISK_RANK,
    WAVE_ELEVATED_M,
    WAVE_HIGH_M,
    WIND_ELEVATED_KMH,
    WIND_HIGH_KMH,
    compute_risk_level,
    danger_label_for as _danger_label_for,
    normalize_risk_level,
    station_site_type,
    wave_risk_level,
    wind_risk_level,
)

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


def danger_label_for(station, risk_level):
    return _danger_label_for(station, risk_level, SITE_DANGER_LABELS, default_site="harbor")
