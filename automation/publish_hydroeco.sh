#!/bin/bash
set -euo pipefail

repo=/home/daviddralle/hydroeco.github.io
cd "$repo"

git add -A -- \
  rancho_venada/rv_ambient.csv \
  rancho_venada/rv_ambient_[0-9][0-9][0-9][0-9].csv \
  rancho_venada/weather_dashboard.json

if git diff --cached --quiet; then
  echo "No weather changes to publish"
  exit 0
fi

git commit -m "Update weather data $(date --iso-8601=minutes)"
git push origin master
git gc --auto
