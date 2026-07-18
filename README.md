# Karnataka Coastal Safety Agent

WhatsApp / SMS / voice coastal safety advisories for Karnataka stations. The Flask app runs on a DigitalOcean droplet under **systemd**, pulls weather from Open-Meteo, builds advisories with Sarvam AI, and prefers official **Survey of India (SOI)** tide tables when the current month is synced.

## What it does

- Users text a station name (e.g. `Malpe`, `Karwar`) over WhatsApp/SMS
- Default reply is a **short** advisory (fishermen actions); reply `DETAILS` for the full multi-audience update
- Tide clock times come from SOI when `data/soi_tides.json` matches the current month; otherwise pressure-based fallback
- Voice calls default to Malpe Fishing Harbor

## Droplet layout

| Path | Purpose |
|------|---------|
| `/root/tidal-project` | App checkout |
| `/root/tidal-project/tidal_env` | Python virtualenv |
| `/root/tidal-project/.env` | Twilio + Sarvam secrets |
| `/etc/systemd/system/tidal.service` | Systemd unit |
| `/etc/cron.d/soi-tide` | Daily SOI tide sync (optional) |

SSH (from your laptop, with your host alias):

```bash
ssh digitalocean-app
```

## First-time setup on the droplet

```bash
cd /root
git clone <your-repo-url> tidal-project
cd tidal-project

python3 -m venv tidal_env
source tidal_env/bin/activate
pip install -r requirements.txt
```

Create `/root/tidal-project/.env`:

```env
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
SARVAM_API_KEY=...
```

Install and enable the systemd service:

```bash
sudo cp deploy/tidal.service /etc/systemd/system/tidal.service
sudo systemctl daemon-reload
sudo systemctl enable tidal
sudo systemctl start tidal
```

Optional — daily SOI tide sync (06:00 IST / 00:30 UTC):

```bash
mkdir -p /root/tidal-project/logs /root/tidal-project/data
sudo cp deploy/soi-tide.cron /etc/cron.d/soi-tide
sudo chmod 644 /etc/cron.d/soi-tide
```

Run an initial SOI sync (retries until the current month’s zip is published):

```bash
cd /root/tidal-project
source tidal_env/bin/activate
python -m soi_sync --force
```

Backfill a specific month if needed:

```bash
python -m soi_sync --force --month=2026-06
```

## Start / stop / restart the service

```bash
sudo systemctl start tidal
sudo systemctl stop tidal
sudo systemctl restart tidal
sudo systemctl status tidal
```

After a code deploy:

```bash
cd /root/tidal-project
git pull
source tidal_env/bin/activate
pip install -r requirements.txt
# Clear stale advisories so format/tide changes take effect
rm -f cache.json
sudo systemctl restart tidal
```

## Logs

```bash
# Live app logs
journalctl -u tidal -f

# Last 100 lines
journalctl -u tidal -n 100 --no-pager

# SOI sync log (if cron is installed)
tail -f /root/tidal-project/logs/soi_sync.log
```

## Webhooks

Point Twilio webhooks at your droplet (public IP or domain), port **5000** unless you put nginx in front:

| Channel | Method | Path |
|---------|--------|------|
| WhatsApp | POST | `/webhook/whatsapp` |
| SMS | POST | `/webhook/sms` |
| Voice | POST | `/webhook/voice` |

Example: `http://YOUR_DROPLET_IP:5000/webhook/whatsapp`

Ensure the droplet firewall / DigitalOcean cloud firewall allows inbound TCP **5000** (or 80/443 if you terminate TLS elsewhere).

## Runtime files (not in git)

These are created on the server and ignored by git:

- `cache.json` — daily advisory cache
- `user_sessions.json` — last station per WhatsApp/SMS sender (for `DETAILS`)
- `station_registry.json` — query audit trail
- `data/soi_tides.json` — parsed SOI tide events for the synced month
- `data/soi_sync_state.json` — last sync attempt / success

## Local development (optional)

```bash
python -m venv tidal_env
# Windows
.\tidal_env\Scripts\activate
# Linux/macOS
source tidal_env/bin/activate

pip install -r requirements.txt
# Create .env with the same keys as production
python app.py
```

App listens on `0.0.0.0:5000` by default.

## Stations

Configured in `stations.json` (Karwar, Kumta, Honnavar, Gangolli, Malpe, Mangaluru Bengre). Each station has a `site_type` and `soi_pdf_port` mapping to the nearest SOI tide PDF (`KARWAR`, `MANGLORE`, or `GANGRA`).
