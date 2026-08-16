# Hydroeco automation

The Raspberry Pi runs two locked pipelines from cron:

- `ambient_weather.py` downloads Ambient Weather observations, repairs recent
  gaps, and rotates completed years into annual CSV files.
- `update_weather.py` downloads Dendra station observations and rebuilds the
  Rancho Venada dashboard images and HTML.
- `publish_hydroeco.sh` stages only known generated weather files, commits when
  content changed, pushes `master`, and performs lightweight Git maintenance.

Credentials are intentionally outside this repository in
`~/.config/hydroeco/ambient_credentials.json` and
`~/.config/hydroeco/dendra_credentials.json`, both with mode `0600`. The
sanitized Dendra client is versioned here and linked into the user's Python
site-packages directory for older local scripts that import it.

Machine-specific cron wrappers live in `~/hydroeco-automation`. Both wrappers
use the same `flock` lock so the data and Git operations cannot overlap.
