from datetime import datetime

from app import STATIONS_FILE, load_json, process_coastal_safety


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
