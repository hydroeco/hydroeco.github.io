# Ambient Weather data files

`rv_ambient.csv` contains observations for the active calendar year. Completed
years are stored as `rv_ambient_YYYY.csv`. Splitting the data keeps every file
well below GitHub's 100 MiB file limit and prevents the active file from growing
without bound.

The updater automatically archives the active file at the first successful
update of a new calendar year. All timestamps are local Pacific time and the
files retain the same columns as the original combined dataset.

To reconstruct the full history, concatenate the annual files and the active
file, use `dateutc` (UTC milliseconds) as the observation identity, remove duplicate
UTC timestamps, and sort by time. The local `date` column alone is ambiguous
during the repeated daylight-saving hour.

`weather_live.json` is generated and published hourly with privacy-safe current
Ambient readings and a seven-day chart series. `weather_history.json` contains
the daily record and is published only when daily data change. The merged record
prefers Ambient, then historical Dendra, then PRISM precipitation where station
coverage is incomplete.

The recent feed preserves native five-minute observation times. Rain amounts
end at their observation timestamp; rolling windows exclude the opening
boundary. Increments are calculated before slicing a window. Daily rainfall
uses changes in the cumulative rain counter, with daily/storm counter fallbacks
at resets. Midnight gaps are reconciled against the resumed daily counter.
Temperature coverage does not determine whether recorded rainfall is used.

The repair command checks incomplete sensor fields, wet days, and timestamp
gaps, paging through entire local days. Use `repair --days 0 --max-gaps N` to
include archived years. Its private checkpoint rotates retries so an
unrecoverable gap cannot starve later dates. A later partial API response never
erases a previously saved non-null reading at the same UTC time.

Run regressions with `python3 -m unittest discover -s automation -p
"test_ambient_weather.py"`. API credentials and repair state remain on the home
computer outside this repository.
