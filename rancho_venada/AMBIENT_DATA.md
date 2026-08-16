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
