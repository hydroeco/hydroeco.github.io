# Hydroeco automation

The Raspberry Pi runs one locked Ambient pipeline from cron:

- `ambient_weather.py` downloads Ambient Weather observations, repairs recent
  gaps, and rotates completed years into annual CSV files.
- `build_weather_dashboard.py` merges live Ambient data with historical Dendra
  station data and PRISM precipitation gap fills, then writes the compact JSON
  used by the Rancho Venada weather dashboard.
- `publish_hydroeco.sh` stages only known generated weather files, commits when
  content changed, pushes `master`, and performs lightweight Git maintenance.

Dendra polling is paused because the remote station feed is stale. Its local
history remains the preferred backfill between PRISM and Ambient coverage.
`update_weather.py` is retained as a manual diagnostic but is not run by cron.

Credentials are intentionally outside this repository in
`~/.config/hydroeco/ambient_credentials.json` and
`~/.config/hydroeco/dendra_credentials.json`, both with mode `0600`. The
sanitized Dendra client is versioned here and linked into the user's Python
site-packages directory for older local scripts that import it.

Machine-specific cron wrappers live in `~/hydroeco-automation`. Both Ambient wrappers
use the same `flock` lock so the data and Git operations cannot overlap.
