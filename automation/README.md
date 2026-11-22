# Hydroeco automation

The Raspberry Pi runs one locked Ambient pipeline from cron:

- `ambient_weather.py` downloads Ambient Weather observations, repairs recent
  gaps, and rotates completed years into annual CSV files.
- `build_weather_dashboard.py` merges live Ambient data with historical Dendra
  station data and PRISM precipitation gap fills. It writes a small hourly live
  file and a separate historical file that changes only when daily data change.
- `publish_hydroeco.sh` copies the small live JSON into the
  `daviddralle.github.io` field-site dashboard hourly. Daily mode also publishes
  the historical JSON there and preserves the partitioned Ambient CSV archive
  in this repository.

Dendra polling is paused because the remote station feed is stale. Its local
history remains the preferred backfill between PRISM and Ambient coverage.
`update_weather.py` is retained as a manual diagnostic but is not run by cron.

Credentials are intentionally outside this repository in
`~/.config/hydroeco/ambient_credentials.json` and
`~/.config/hydroeco/dendra_credentials.json`, both with mode `0600`. The
sanitized Dendra client is versioned here and linked into the user's Python
site-packages directory for older local scripts that import it.

Machine-specific cron wrappers live in `~/hydroeco-automation`. Both Ambient
wrappers use the same `flock` lock so data and Git operations cannot overlap.
The public dashboard is
<https://daviddralle.github.io/field-sites/rancho/>.

The weekly repair wrapper replays up to 32 candidate days from the last 30 days,
including incomplete outdoor fields and rain-counter increases. It pages whole
days, allows 75 seconds for historical responses, and shares a request-rate lock
with the hourly updater. This covers the full lookback without skipping its
oldest dates when every day needs repair.

Rain reconstructions are fixed in `rain_corrections.json`. The November 18–19,
2026 clog reconstruction preserves the 1.19 inches recorded before November 18
10:50 PST. Eight screened Ambient stations provide the median cumulative shape,
normalized to that early accumulation. Six other nearby stations were excluded
for absent or implausibly prolonged rain responses. The 800 m PRISM grids ending
November 18, 19 and 20 at 12 UTC sum to 1.74386 inches; the 4 km comparison is
1.77196 inches. These are preliminary release-1 grids, not on-site ground truth.
PRISM's 04:00 PST boundary includes a recorded 0.01-inch Friday tail. Retaining
that tail gives rounded daily targets of 1.40 inches Wednesday and 0.33 Thursday,
a net addition of 0.34 inches. The last repaired five-minute interval ends at
Thursday 10:40, encompassing the reported 10:37 clearing time. Good readings
outside the interval are retained; subsequent cumulative counters carry the
addition until their normal reset.

The updater writes corrected rain fields and retains changed original readings
in `observed_*` columns of the same CSV. It restores those original readings
before merging API refreshes or repairs, then reapplies the fixed reconstruction
once. The dashboard builder reads the corrected fields. Annual partitions use
the same write path. Rainfall interval precision is retained so subdivision does
not change the storm total. The reconstructed rain rate is a five-minute average.
Ambient's manual summary edits do not modify its original API time series.
