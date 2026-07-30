"""PNW site danger labels (shared scoring in coastal_common.risk)."""
from coastal_common.risk import (
    RISK_ADVISORY_TITLES,
    RISK_BOAT_SENTENCES,
    compute_risk_level,
    danger_label_for as _danger_label_for,
    normalize_risk_level,
    station_site_type,
)

SITE_DANGER_LABELS = {
    "harbor": {
        "low": "HARBOR NOTICE",
        "elevated": "HARBOR / BAR CAUTION",
        "high": "HARBOR / BAR WARNING",
    },
    "beach": {
        "low": "BEACH NOTICE",
        "elevated": "BEACH CAUTION",
        "high": "BEACH DANGER",
    },
    "rocky": {
        "low": "ROCKY COAST NOTICE",
        "elevated": "ROCKY COAST CAUTION",
        "high": "ROCKY COAST DANGER",
    },
    "estuary": {
        "low": "ESTUARY / RIVER NOTICE",
        "elevated": "ESTUARY / RIVER CAUTION",
        "high": "ESTUARY / RIVER DANGER",
    },
    "port": {
        "low": "PORT NOTICE",
        "elevated": "PORT CAUTION",
        "high": "PORT WARNING",
    },
}


def danger_label_for(station, risk_level):
    return _danger_label_for(station, risk_level, SITE_DANGER_LABELS, default_site="harbor")
