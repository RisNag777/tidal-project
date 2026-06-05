import json
import requests
from datetime import datetime
from app import load_json, STATIONS_FILE, process_coastal_safety

def run_broadbase_telemetry_refresh():
    # Read the execution window from our separate parameters config file
    interval_hours = 4 # Hard fallback parameter 
    try:
        with open("config.txt", "r") as config_file:
            for line in config_file:
                if "INTERVAL_HOURS" in line:
                    interval_hours = int(line.split("=")[1].strip())
    except Exception:
        print("⚠️ Config file unreadable. Defaulting to 4-hour cycle window.")

    print(f"🕒 Commencing broadbase telemetry check. System profile interval parameter: {interval_hours} hours.")
    stations = load_json(STATIONS_FILE)
    
    for station in stations:
        print(f"🔄 Processing and pre-computing safety metrics for: {station['location_name']}")
        # Calling process_coastal_safety automatically updates cache.json entries
        process_coastal_safety(station)
        
    print(f"✅ Pre-compute complete at {datetime.now().strftime('%H:%M:%S')}. System cached until next execution window.")

if __name__ == "__main__":
    run_broadbase_telemetry_refresh()
