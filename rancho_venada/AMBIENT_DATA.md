# Ambient Weather data files

`rv_ambient.csv` contains observations for the active calendar year. Completed
years are stored as `rv_ambient_YYYY.csv`. Splitting the data keeps every file
well below GitHub's 100 MiB file limit and prevents the active file from growing
without bound.

The updater automatically archives the active file at the first successful
update of a new calendar year. All timestamps are local Pacific time and the
files retain the same columns as the original combined dataset.

To reconstruct the full history, concatenate the annual files and the active
file, parse the `date` column, remove duplicate timestamps, and sort by date.

`weather_live.json` is generated and published hourly with privacy-safe current
Ambient readings and a seven-day chart series. `weather_history.json` contains
the daily record and is published only when daily data change. The merged record
prefers Ambient, then historical Dendra, then PRISM precipitation where station
coverage is incomplete.
