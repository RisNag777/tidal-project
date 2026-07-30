"""Karnataka-region file paths."""
from pathlib import Path

from coastal_common.storage import load_json, region_data_paths, save_json

_PATHS = region_data_paths(Path(__file__).resolve().parent)
STATIONS_FILE = _PATHS["stations"]
CACHE_FILE = _PATHS["cache"]
REGISTRY_FILE = _PATHS["registry"]

__all__ = [
    "STATIONS_FILE",
    "CACHE_FILE",
    "REGISTRY_FILE",
    "load_json",
    "save_json",
]
