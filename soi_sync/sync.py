import calendar
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from soi_sync.parser import parse_port_pdf

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "soi_sync_state.json"
TIDES_FILE = DATA_DIR / "soi_tides.json"
STATIONS_FILE = PROJECT_ROOT / "stations.json"
SOI_BASE_URL = "https://surveyofindia.gov.in/documents"

# SOI renames some ports across years (e.g. MANGLORE vs MANGALORE).
PORT_FILENAME_ALIASES = {
    "KARWAR": ("KARWAR",),
    "MANGLORE": ("MANGLORE", "MANGALORE"),
    "MANGALORE": ("MANGALORE", "MANGLORE"),
    "GANGRA": ("GANGRA",),
}


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def month_key(year, month):
    return f"{year:04d}-{month:02d}"


def build_download_urls(year, month):
    month_name = calendar.month_name[month]
    lower_name = month_name.lower()
    return [
        f"{SOI_BASE_URL}/Tidal-{month_name}-{year}.zip",
        f"{SOI_BASE_URL}/tidal-data-{lower_name}-{year}.zip",
        f"{SOI_BASE_URL}/tidal-{lower_name}-{year}.zip",
        f"{SOI_BASE_URL}/Tidal-{lower_name}-{year}.zip",
    ]


def required_ports_from_stations():
    stations = load_json(STATIONS_FILE)
    ports = set()
    if isinstance(stations, list):
        for station in stations:
            port = station.get("soi_pdf_port")
            if port:
                ports.add(port.upper())
    return sorted(ports)


def find_port_pdf(zip_file, port_code):
    candidates = PORT_FILENAME_ALIASES.get(
        port_code.upper(), (port_code.upper(),)
    )
    for candidate in candidates:
        target = f"/{candidate}.pdf".upper()
        for name in zip_file.namelist():
            if name.upper().endswith(target):
                return name
    return None


def download_month_zip(year, month):
    verify_ssl = os.environ.get("SOI_SSL_VERIFY", "false").lower() == "true"
    errors = []
    for url in build_download_urls(year, month):
        try:
            response = requests.get(url, timeout=120, verify=verify_ssl)
            if response.status_code != 200:
                errors.append(f"{url} -> HTTP {response.status_code}")
                continue
            if response.content[:2] != b"PK":
                errors.append(f"{url} -> not a zip file")
                continue
            return response.content, url
        except Exception as exc:
            errors.append(f"{url} -> {exc}")
    raise RuntimeError("SOI tidal zip not available yet. " + " | ".join(errors))


def parse_required_ports(zip_bytes, year, month, port_codes):
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    ports = {}
    missing = []

    for port_code in port_codes:
        pdf_name = find_port_pdf(archive, port_code)
        if not pdf_name:
            missing.append(port_code)
            continue
        events = parse_port_pdf(archive.read(pdf_name), year, month)
        ports[port_code] = {
            "port_name": port_code,
            "pdf_name": pdf_name,
            "events": events,
        }

    if missing:
        raise RuntimeError(f"Missing SOI PDFs for ports: {', '.join(missing)}")

    return ports


def sync_soi_tides(now_ist=None, force=False, month_override=None):
    now_ist = now_ist or datetime.now(IST)
    if month_override:
        year, month = map(int, month_override.split("-"))
    else:
        year = now_ist.year
        month = now_ist.month
    target = month_key(year, month)
    state = load_json(STATE_FILE)

    if not force and state.get("completed_month") == target:
        print(f"SOI tides already synced for {target}.")
        return True

    port_codes = required_ports_from_stations()
    zip_bytes, source_url = download_month_zip(year, month)
    ports = parse_required_ports(zip_bytes, year, month, port_codes)

    payload = {
        "source": "survey_of_india",
        "month": target,
        "source_url": source_url,
        "synced_at": now_ist.isoformat(),
        "ports": ports,
    }
    save_json(TIDES_FILE, payload)

    state.update(
        {
            "target_month": target,
            "completed_month": target,
            "last_attempt_at": now_ist.isoformat(),
            "last_error": None,
            "source_url": source_url,
        }
    )
    save_json(STATE_FILE, state)
    print(f"SOI tides synced for {target} from {source_url}")
    return True


def main():
    import sys

    force = "--force" in sys.argv
    month_override = None
    for arg in sys.argv:
        if arg.startswith("--month="):
            month_override = arg.split("=", 1)[1]

    try:
        sync_soi_tides(force=force, month_override=month_override)
    except Exception as exc:
        now_ist = datetime.now(IST)
        state = load_json(STATE_FILE)
        state.update(
            {
                "target_month": month_override or month_key(now_ist.year, now_ist.month),
                "last_attempt_at": now_ist.isoformat(),
                "last_error": str(exc),
            }
        )
        save_json(STATE_FILE, state)
        print(f"SOI sync failed: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
