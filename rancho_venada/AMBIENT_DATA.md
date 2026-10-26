# Ambient Weather data files

`rv_ambient.csv` contains observations for the active calendar year. Completed
years are stored as `rv_ambient_YYYY.csv`. Splitting the data keeps every file
well below GitHub's 100 MiB file limit and prevents the active file from growing
without bound.

The updater automatically archives the active file at the first successful
update of a new calendar year. All timestamps are local Pacific time and the
files retain the weather measurements from the original combined dataset.
Station passkeys, device identifiers, and location metadata are excluded from
public CSV output.

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

## October 26, 2026 archive audit

Re-queried 654 wet or incomplete dates spanning December 31, 2022 through
October 26, 2026. Recovered 59 observations: the first 23 records of the archive
and 12 records each from the repeated daylight-saving hours on November 5,
2023, November 3, 2024, and November 2, 2025. No previously populated observation
fields were erased. Existing missing outdoor fields were also missing in the
replayed Ambient responses; saved rain-counter values matched the replay.

Corrected rainfall accounting adds a net 0.783 inches to the previously
published historical series. Key daily corrections are February 4, 2024
(1.85 to 2.37 inches), February 5, 2024 (0.047 to 0.29 inches), and April 5, 2024
(0.67 to 0.23 inches). Complete Ambient water-year totals now reconcile to the
retained station counters: WY2024 22.54, WY2025 16.76, WY2026 22.82 inches.
The recent October 2026 storm remains 0.36 inches. Private backups and detailed
per-date replay results are retained on the ingestion computer.
