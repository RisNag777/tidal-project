"""JSON file paths and helpers for stations, cache, and registry."""
import json

STATIONS_FILE = "stations.json"
CACHE_FILE = "cache.json"
REGISTRY_FILE = "station_registry.json"


def load_json(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
