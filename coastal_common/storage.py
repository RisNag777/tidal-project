"""JSON load/save and per-region file paths."""
import json
from pathlib import Path


def load_json(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def region_data_paths(region_dir):
    """Return stations/cache/registry paths under a region package directory."""
    root = Path(region_dir).resolve()
    return {
        "stations": str(root / "stations.json"),
        "cache": str(root / "cache.json"),
        "registry": str(root / "station_registry.json"),
    }
