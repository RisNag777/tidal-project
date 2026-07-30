# PNW Coastal Safety Agent

WhatsApp / SMS / voice advisories for Pacific Northwest stations (WA / OR). Uses **NOAA CO-OPS** for tide highs/lows, **Open-Meteo** for wind/waves, and **OpenAI** for advisory text + Whisper. Shared helpers live in [`../coastal_common/`](../coastal_common/).

## What it does

- Text a station name (e.g. `Astoria`, `Seattle`, `Cannon`)
- Default reply: conditions + one-liners; detail via `Astoria families | …`
- Voice defaults to Westport Harbor

### Tide / weather caveat

NOAA tide tables are astronomical. Weather setup can push actual water above or below the table — check beach flags and shoreline markers.

## Run

From repo root:

```bash
python pnw/app.py   # port 5001
```

Requires `OPENAI_API_KEY` (and Twilio) in repo-root `.env`.
