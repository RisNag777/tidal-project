# Coastal Safety Agents

Two regional WhatsApp / SMS / voice coastal safety apps share common helpers:

| Path | Region | Tide source | LLM |
|------|--------|-------------|-----|
| [`karnataka/`](karnataka/) | Karnataka, India | Open-Meteo `sea_level_height_msl` | Sarvam |
| [`pnw/`](pnw/) | Pacific Northwest, US | NOAA CO-OPS hilo | OpenAI |
| [`coastal_common/`](coastal_common/) | Shared | Open-Meteo wind/waves, risk scoring, clocks, WhatsApp helpers | — |

## Run

```bash
python3 -m venv tidal_env
source tidal_env/bin/activate   # Windows: tidal_env\Scripts\activate
pip install -r requirements.txt
```

`.env` at repo root:

```env
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
SARVAM_API_KEY=...          # Karnataka
OPENAI_API_KEY=...          # PNW
OPENAI_CHAT_MODEL=gpt-4o-mini
```

```bash
# Karnataka (port 5000) — systemd still uses root app.py
python app.py
# or: python karnataka/app.py

# PNW (port 5001)
python pnw/app.py
```

Precompute Karnataka caches: `python broadbase.py`

## Deploy (Karnataka droplet)

Working directory remains `/root/tidal-project`. `ExecStart` still runs `/root/tidal-project/app.py` (thin launcher into `karnataka/`).

See [`karnataka/README.md`](karnataka/README.md) and [`pnw/README.md`](pnw/README.md) for region-specific notes.
