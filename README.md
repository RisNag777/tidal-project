# Coastal Safety Agents

One Flask service (`app.py`, port 5000) routes WhatsApp / SMS / voice by **station name** to Karnataka or PNW pipelines. Shared helpers live in `coastal_common/`.

| Path | Region | Tide source | LLM / STT |
|------|--------|-------------|-----------|
| [`karnataka/`](karnataka/) | Karnataka, India | Open-Meteo `sea_level_height_msl` | Sarvam |
| [`pnw/`](pnw/) | Pacific Northwest, US | NOAA CO-OPS hilo | OpenAI |
| [`coastal_common/`](coastal_common/) | Shared | Open-Meteo wind/waves, risk scoring, clocks, WhatsApp helpers | — |

## Run

```bash
python3 -m venv tidal_env
source tidal_env/bin/activate   # Windows: tidal_env\Scripts\activate
pip install -r requirements.txt
```

`.env` at repo root (both region keys needed for full coverage):

```env
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
SARVAM_API_KEY=...          # Karnataka advisories + Kannada/Tulu voice notes
OPENAI_API_KEY=...          # PNW advisories + Whisper fallback
OPENAI_CHAT_MODEL=gpt-4o-mini
```

```bash
# Production entrypoint (systemd): routes Malpe/Karwar/... vs Astoria/Seattle/...
python app.py

# Optional standalone region apps (local testing)
python karnataka/app.py   # port 5000, Karnataka only
python pnw/app.py         # port 5001, PNW only
```

Precompute Karnataka caches: `python broadbase.py`

## Deploy (droplet)

Working directory: `/root/tidal-project`. One systemd unit runs `/root/tidal-project/app.py` on port **5000**. Twilio webhooks point at that host; station name selects the region.

See [`karnataka/README.md`](karnataka/README.md) and [`pnw/README.md`](pnw/README.md) for region-specific notes.
