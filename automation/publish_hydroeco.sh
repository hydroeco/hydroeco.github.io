#!/bin/bash
set -euo pipefail

source_repo=/home/daviddralle/hydroeco.github.io
site_repo=/home/daviddralle/daviddralle.github.io
source_weather_dir="$source_repo/rancho_venada"
site_weather_dir="$site_repo/field-sites/rancho"

mode=${1:-live}
case "$mode" in
  live)
    site_files=(weather_live.json)
    message="Update live weather data"
    ;;
  daily)
    site_files=(weather_live.json weather_history.json)
    archive_files=(
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

if [[ ! -d "$site_repo/.git" ]]; then
  echo "Missing website checkout: $site_repo" >&2
  exit 1
fi

git -C "$site_repo" pull --ff-only origin master

site_paths=()
for file in "${site_files[@]}"; do
  install -m 0644 "$source_weather_dir/$file" "$site_weather_dir/$file"
  site_paths+=("field-sites/rancho/$file")
done

git -C "$site_repo" add -A -- "${site_paths[@]}"

if git -C "$site_repo" diff --cached --quiet -- "${site_paths[@]}"; then
  echo "No website weather changes to publish"
else
  git -C "$site_repo" commit --only -m "$message $(date --iso-8601=minutes)" -- "${site_paths[@]}"
  git -C "$site_repo" push origin master
fi

if [[ "$mode" == daily ]]; then
  git -C "$source_repo" add -A -- "${archive_files[@]}"
  if git -C "$source_repo" diff --cached --quiet -- "${archive_files[@]}"; then
    echo "No source archive changes to publish"
  else
    git -C "$source_repo" commit --only -m "Refresh weather data archive $(date --iso-8601=minutes)" -- "${archive_files[@]}"
    git -C "$source_repo" push origin master
  fi
fi

git -C "$site_repo" gc --auto
git -C "$source_repo" gc --auto
