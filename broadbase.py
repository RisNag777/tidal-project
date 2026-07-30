from datetime import datetime
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from karnataka.safety import process_coastal_safety
from karnataka.storage import STATIONS_FILE, load_json


def run_broadbase_telemetry_refresh():
    interval_hours = 4
    try:
        with open("config.txt", "r", encoding="utf-8") as config_file:
            for line in config_file:
                if "INTERVAL_HOURS" in line:
                    interval_hours = int(line.split("=", 1)[1].strip())
    except Exception:
        print("⚠️ Config file unreadable. Defaulting to 4-hour cycle window.")

    print(
        f"🕒 Commencing broadbase telemetry check. "
        f"System profile interval parameter: {interval_hours} hours."
    )
    stations = load_json(STATIONS_FILE)

    for station in stations:
        print(f"🔄 Processing and pre-computing safety metrics for: {station['location_name']}")
        process_coastal_safety(station)

    print(
        f"✅ Pre-compute complete at {datetime.now().strftime('%H:%M:%S')}. "
        "System cached until next execution window."
    )


if __name__ == "__main__":
    run_broadbase_telemetry_refresh()
