#!/bin/bash
set -euo pipefail

repo=/home/daviddralle/hydroeco.github.io
cd "$repo"

mode=${1:-live}
case "$mode" in
  live)
    files=(rancho_venada/weather_live.json)
    message="Update live weather data"
    ;;
  daily)
    files=(
      rancho_venada/rv_ambient.csv \
      rancho_venada/rv_ambient_[0-9][0-9][0-9][0-9].csv \
      rancho_venada/weather_live.json \
      rancho_venada/weather_history.json
    )
    message="Refresh weather data archive"
    ;;
  *)
    echo "Usage: $0 [live|daily]" >&2
    exit 2
    ;;
esac

git add -A -- "${files[@]}"

if git diff --cached --quiet -- "${files[@]}"; then
  echo "No weather changes to publish"
  exit 0
fi

git commit --only -m "$message $(date --iso-8601=minutes)" -- "${files[@]}"
git push origin master
git gc --auto
