# Hydroeco automation

The Raspberry Pi runs two locked pipelines from cron:

- `ambient_weather.py` downloads Ambient Weather observations, repairs recent
  gaps, and rotates completed years into annual CSV files.
- `update_weather.py` downloads Dendra station observations and rebuilds the
  Rancho Venada dashboard images and HTML.
- `publish_hydroeco.sh` stages only known generated weather files, commits when
  content changed, pushes `master`, and performs lightweight Git maintenance.

Ambient Weather credentials are intentionally outside this repository at
`~/.config/hydroeco/ambient_credentials.json` with mode `0600`.

Machine-specific cron wrappers live in `~/hydroeco-automation`. Both wrappers
use the same `flock` lock so the data and Git operations cannot overlap.
