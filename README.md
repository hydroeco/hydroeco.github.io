# HydroEco weather data

This repository maintains the Rancho Venada weather-processing code and source
archive. The public dashboard is published at
<https://daviddralle.github.io/field-sites/rancho/>.

## Current contents

- `rancho_venada/wx_dash.html`: compatibility redirect for the former dashboard
  URL.
- `rancho_venada/weather_live.json`: current conditions and seven-day series,
  updated hourly.
- `rancho_venada/weather_history.json`: merged daily historical record.
- `rancho_venada/rv_ambient*.csv`: partitioned Ambient Weather observations.
- `rancho_venada/rvws.csv`: historical Dendra station observations.
- `rancho_venada/prism.csv`: PRISM precipitation gap-fill data.
- `automation/`: credential-free download, merge, and publishing scripts.

Ambient and Dendra credentials are stored outside the repository. Dendra
polling is currently paused; its historical observations remain part of the
merged daily record.
