# Karnataka Coastal Safety Agent

WhatsApp / SMS / voice advisories for Karnataka stations. Uses Open-Meteo (weather + `sea_level_height_msl` tides) and Sarvam AI. Shared helpers live in [`../coastal_common/`](../coastal_common/).

## Run

From repo root:

```bash
python app.py                 # port 5000 (systemd entry)
# or
python karnataka/app.py
```

Stations: [`stations.json`](stations.json). Cache/registry write next to this package.

### Tide / weather caveat

Pure astronomical tide tables cannot account for weather anomalies. Our marine model series is still an estimate — cross-check shoreline markers and red flags.
