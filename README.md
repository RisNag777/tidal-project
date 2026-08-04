# Coastal Safety Agents

One Flask service (`app.py`, port 5000) routes WhatsApp / SMS / voice by **station name** to Karnataka or PNW pipelines. Shared helpers live in `coastal_common/`.

| Path | Region | Tide source | LLM / STT |
|------|--------|-------------|-----------|
| [`karnataka/`](karnataka/) | Karnataka, India | Open-Meteo `sea_level_height_msl` | Sarvam |
| [`pnw/`](pnw/) | Pacific Northwest, US | NOAA CO-OPS hilo | OpenAI |
| [`coastal_common/`](coastal_common/) | Shared | Open-Meteo wind/waves, risk scoring, clocks, WhatsApp helpers | — |

## Setup (new collaborators)

### 1. Get the code and push access

1. Ask the repo owner to add you as a collaborator (GitHub → Settings → Collaborators), **or** fork the repo if you will open PRs from a fork.
2. Clone:

```bash
git clone <repo-url> tidal-project
cd tidal-project
```

3. Confirm you can push (collaborators on the same repo):

```bash
git checkout -b your-feature-branch
# after commits:
git push -u origin your-feature-branch
```

If you forked, push to your fork and open a pull request against this repo’s `main`.

### 2. Python environment

Requires **Python 3.10+** (3.12 is fine).

```bash
python3 -m venv tidal_env
source tidal_env/bin/activate          # Windows: tidal_env\Scripts\activate
pip install -r requirements.txt
```

### 3. Environment variables

Create a `.env` file at the **repo root** (never commit it; it is gitignored):

```env
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
SARVAM_API_KEY=...          # Karnataka advisories + Kannada/Tulu voice notes
OPENAI_API_KEY=...          # PNW advisories + Whisper fallback
OPENAI_CHAT_MODEL=gpt-4o-mini
```

Ask the owner for shared Twilio / API keys, or use your own keys for local testing.

- **Karnataka-only** local work: Twilio + `SARVAM_API_KEY`
- **PNW-only** local work: Twilio + `OPENAI_API_KEY`
- **Full unified router** (`python app.py`): both region keys

Open-Meteo and NOAA tide calls need no API keys.

### 4. Run locally

```bash
# Unified router (same as production / systemd) — port 5000
python app.py

# Optional: one region only
python karnataka/app.py   # port 5000
python pnw/app.py         # port 5001
```

Precompute Karnataka advisory caches (optional): `python broadbase.py`

### 5. Test without Twilio

Quick smoke check that routing and station match work:

```bash
python -c "from app import resolve_region; print(resolve_region('Malpe')); print(resolve_region('Astoria'))"
```

You should see Karnataka → Malpe and PNW → Astoria. Generating a full advisory hits live weather/tide APIs and the region LLM (needs the matching API key).

### 6. Test WhatsApp / SMS / voice webhooks

1. Start `python app.py` (port 5000).
2. Expose the port with a tunnel (e.g. [ngrok](https://ngrok.com/): `ngrok http 5000`).
3. In Twilio, point WhatsApp / SMS / voice webhooks at:
   - `https://<your-tunnel>/webhook/whatsapp`
   - `https://<your-tunnel>/webhook/sms`
   - `https://<your-tunnel>/webhook/voice`
4. Text a station name (e.g. `Malpe`, `Astoria`). Voice calls still default to Malpe.

## Deploy (droplet)

Working directory: `/root/tidal-project`. One systemd unit ([`deploy/tidal.service`](deploy/tidal.service)) runs `/root/tidal-project/app.py` on port **5000**. Twilio production webhooks point at that host; station name selects the region.

After pulling code on the droplet:

```bash
cd /root/tidal-project
git pull
source tidal_env/bin/activate
pip install -r requirements.txt
# optional: clear stale advisories if reply format changed
rm -f karnataka/cache.json pnw/cache.json cache.json
sudo cp deploy/tidal.service /etc/systemd/system/tidal.service
sudo systemctl daemon-reload
sudo systemctl restart tidal
```

See [`karnataka/README.md`](karnataka/README.md) and [`pnw/README.md`](pnw/README.md) for region-specific notes.
