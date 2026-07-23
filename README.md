# Karnataka Coastal Safety Agent

WhatsApp / SMS / voice coastal safety advisories for Karnataka stations. The Flask app runs on a DigitalOcean droplet under **systemd**, pulls weather from Open-Meteo, estimates tide timing from surface-pressure trends, and builds advisories with Sarvam AI.

## What it does

- Users text a station name (e.g. `Malpe`, `Karwar`) over WhatsApp/SMS
- Replies with a full advisory covering families, operators, and fishermen
- Tide timing is estimated from Open-Meteo pressure trends (approximate, not official tide tables)
- Voice calls default to Malpe Fishing Harbor

## Droplet layout

| Path | Purpose |
|------|---------|
| `/root/tidal-project` | App checkout |
| `/root/tidal-project/tidal_env` | Python virtualenv |
| `/root/tidal-project/.env` | Twilio + Sarvam secrets |
| `/etc/systemd/system/tidal.service` | Systemd unit |

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
# Clear stale advisories so format changes take effect
rm -f cache.json
sudo systemctl restart tidal
```

## Logs

```bash
# Live app logs
journalctl -u tidal -f

# Last 100 lines
journalctl -u tidal -n 100 --no-pager
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
- `station_registry.json` — query audit trail

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

Configured in `stations.json` (Karwar, Kumta, Honnavar, Gangolli, Malpe, Mangaluru Bengre). Each station has a `site_type` used for audience-specific action templates.
