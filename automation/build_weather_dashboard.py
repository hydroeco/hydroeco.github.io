#!/usr/bin/env python3
"""Build compact, privacy-safe dashboard data from Rancho Venada weather sources."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import tempfile

import pandas as pd


REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "rancho_venada"
LIVE_OUTPUT = DATA_DIR / "weather_live.json"
HISTORY_OUTPUT = DATA_DIR / "weather_history.json"
TIMEZONE = "America/Los_Angeles"
AMBIENT_MIN_DAILY_SAMPLES = 200
DENDRA_MIN_DAILY_SAMPLES = 200

AMBIENT_COLUMNS = [
    "date",
    "tempf",
    "humidity",
    "winddir",
    "windspdmph_avg10m",
    "windspeedmph",
    "windgustmph",
    "maxdailygust",
    "dailyrainin",
    "eventrainin",
    "baromrelin",
    "solarradiation",
    "uv",
    "feelsLike",
    "dewPoint",
    "soilhum3",
    "pm25",
]

DENDRA_COLUMNS = [
    "RanchoVenadaWs_Rainfall",
    "RanchoVenadaWs_Air_Temp_Avg",
    "RanchoVenadaWs_Barometric_Pressure",
    "RanchoVenadaWs_Relative_Humidity_Max",
    "RanchoVenadaWs_Solar_Radiation_Avg",
    "RanchoVenadaWs_Wind_Speed_Avg",
    "RanchoVenadaWs_Wind_Direction",
]


def number(value: object, digits: int = 2) -> float | None:
    if value is None or pd.isna(value):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return round(result, digits)


def numeric(frame: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def load_ambient() -> pd.DataFrame:
    archives = sorted(DATA_DIR.glob("rv_ambient_[0-9][0-9][0-9][0-9].csv"))
    paths = archives + [DATA_DIR / "rv_ambient.csv"]
    frames = []
    for path in paths:
        available = pd.read_csv(path, nrows=0).columns
        usecols = [column for column in AMBIENT_COLUMNS if column in available]
        frame = pd.read_csv(path, usecols=usecols, parse_dates=["date"], low_memory=False)
        frame = frame.set_index("date")
        frames.append(frame)
    ambient = pd.concat(frames, sort=False)
    ambient = ambient.loc[~ambient.index.duplicated(keep="last")].sort_index()
    numeric(ambient, [column for column in AMBIENT_COLUMNS if column != "date"])
    return ambient


def load_dendra() -> pd.DataFrame:
    frame = pd.read_csv(
        DATA_DIR / "rvws.csv",
        index_col=0,
        usecols=lambda column: column == "Unnamed: 0" or column in DENDRA_COLUMNS,
        parse_dates=True,
        low_memory=False,
    )
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.loc[~frame.index.isna()].sort_index()
    numeric(frame, DENDRA_COLUMNS)
    # A single 7,999 mm logger sentinel caused the old dashboard's impossible total.
    rain = "RanchoVenadaWs_Rainfall"
    frame[rain] = frame[rain].where(frame[rain].between(0, 100))
    return frame


def load_prism() -> pd.Series:
    frame = pd.read_csv(DATA_DIR / "prism.csv", index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    return pd.to_numeric(frame["ppt"], errors="coerce").sort_index()


def aggregate_ambient(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.resample("D")
    daily = pd.DataFrame(
        {
            "count": grouped["tempf"].count(),
            "rain_in": grouped["dailyrainin"].max(),
            "temp_min_f": grouped["tempf"].min(),
            "temp_max_f": grouped["tempf"].max(),
            "temp_mean_f": grouped["tempf"].mean(),
            "humidity_pct": grouped["humidity"].mean(),
            "wind_mph": grouped["windspdmph_avg10m"].mean(),
        }
    )
    return daily


def aggregate_dendra(frame: pd.DataFrame) -> pd.DataFrame:
    rain = "RanchoVenadaWs_Rainfall"
    temp = "RanchoVenadaWs_Air_Temp_Avg"
    humidity = "RanchoVenadaWs_Relative_Humidity_Max"
    wind = "RanchoVenadaWs_Wind_Speed_Avg"
    grouped = frame.resample("D")
    temp_c = frame[temp]
    daily = pd.DataFrame(
        {
            "count": grouped[temp].count(),
            "rain_count": grouped[rain].count(),
            "rain_in": grouped[rain].sum(min_count=1) / 25.4,
            "temp_min_f": grouped[temp].min() * 9 / 5 + 32,
            "temp_max_f": grouped[temp].max() * 9 / 5 + 32,
            "temp_mean_f": temp_c.resample("D").mean() * 9 / 5 + 32,
            "humidity_pct": grouped[humidity].mean(),
            "wind_mph": grouped[wind].mean() * 2.23694,
        }
    )
    return daily


def recent_series(ambient: pd.DataFrame) -> list[dict[str, object]]:
    recent = ambient.loc[ambient.index >= ambient.index.max() - pd.Timedelta(days=7)].copy()
    rain = recent["dailyrainin"].clip(lower=0)
    increment = rain.groupby(recent.index.normalize()).diff()
    first = ~recent.index.normalize().duplicated()
    increment.loc[first] = rain.loc[first]
    increment = increment.where(increment.between(0, 5), 0)
    recent["rain_increment_in"] = increment

    sampled = recent.resample("15min").agg(
        {
            "tempf": "mean",
            "humidity": "mean",
            "windspdmph_avg10m": "mean",
            "windgustmph": "max",
            "rain_increment_in": "sum",
        }
    )
    sampled = sampled.dropna(how="all")
    records = []
    for timestamp, row in sampled.iterrows():
        aware = timestamp.tz_localize(TIMEZONE, ambiguous=False, nonexistent="shift_forward")
        records.append(
            {
                "t": aware.isoformat(),
                "temp_f": number(row["tempf"], 1),
                "humidity_pct": number(row["humidity"], 0),
                "wind_mph": number(row["windspdmph_avg10m"], 1),
                "gust_mph": number(row["windgustmph"], 1),
                "rain_in": number(row["rain_increment_in"], 3),
            }
        )
    return records


def merged_history(
    ambient: pd.DataFrame, dendra: pd.DataFrame, prism: pd.Series
) -> tuple[list[dict[str, object]], dict[str, int]]:
    ambient_daily = aggregate_ambient(ambient)
    dendra_daily = aggregate_dendra(dendra)
    dates = pd.date_range(prism.index.min().normalize(), ambient.index.max().normalize(), freq="D")
    prism_daily = prism.reindex(dates)
    current_date = ambient.index.max().normalize()
    counts = {"ambient": 0, "dendra": 0, "prism": 0, "partial": 0, "missing": 0}
    records = []

    for date in dates:
        ambient_row = ambient_daily.loc[date] if date in ambient_daily.index else None
        dendra_row = dendra_daily.loc[date] if date in dendra_daily.index else None
        prism_mm = prism_daily.loc[date]

        ambient_good = ambient_row is not None and (
            ambient_row["count"] >= AMBIENT_MIN_DAILY_SAMPLES or date == current_date
        )
        dendra_good = dendra_row is not None and dendra_row["rain_count"] >= DENDRA_MIN_DAILY_SAMPLES

        if ambient_good:
            source, precip = "ambient", ambient_row["rain_in"]
        elif dendra_good:
            source, precip = "dendra", dendra_row["rain_in"]
        elif not pd.isna(prism_mm):
            source, precip = "prism", prism_mm / 25.4
        elif ambient_row is not None and ambient_row["count"] > 0:
            source, precip = "ambient-partial", ambient_row["rain_in"]
        elif dendra_row is not None and dendra_row["rain_count"] > 0:
            source, precip = "dendra-partial", dendra_row["rain_in"]
        else:
            source, precip = "missing", None

        if source in counts:
            counts[source] += 1
        elif source.endswith("partial"):
            counts["partial"] += 1

        if ambient_good:
            weather = ambient_row
            weather_source = "ambient"
        elif dendra_row is not None and dendra_row["count"] >= DENDRA_MIN_DAILY_SAMPLES:
            weather = dendra_row
            weather_source = "dendra"
        elif ambient_row is not None and ambient_row["count"] > 0:
            weather = ambient_row
            weather_source = "ambient-partial"
        elif dendra_row is not None and dendra_row["count"] > 0:
            weather = dendra_row
            weather_source = "dendra-partial"
        else:
            weather = None
            weather_source = None

        records.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "source": source,
                "weather_source": weather_source,
                "precip_in": number(precip, 3),
                "temp_min_f": number(weather["temp_min_f"], 1) if weather is not None else None,
                "temp_max_f": number(weather["temp_max_f"], 1) if weather is not None else None,
                "temp_mean_f": number(weather["temp_mean_f"], 1) if weather is not None else None,
                "humidity_pct": number(weather["humidity_pct"], 0) if weather is not None else None,
                "wind_mph": number(weather["wind_mph"], 1) if weather is not None else None,
            }
        )
    return records, counts


def latest_conditions(ambient: pd.DataFrame) -> dict[str, object]:
    latest = ambient.dropna(subset=["tempf"]).iloc[-1]
    timestamp = ambient.dropna(subset=["tempf"]).index[-1]
    aware = timestamp.tz_localize(TIMEZONE, ambiguous=False, nonexistent="shift_forward")
    return {
        "timestamp": aware.isoformat(),
        "temp_f": number(latest.get("tempf"), 1),
        "feels_like_f": number(latest.get("feelsLike"), 1),
        "dew_point_f": number(latest.get("dewPoint"), 1),
        "humidity_pct": number(latest.get("humidity"), 0),
        "wind_mph": number(latest.get("windspdmph_avg10m"), 1),
        "gust_mph": number(latest.get("windgustmph"), 1),
        "wind_direction_deg": number(latest.get("winddir_avg10m", latest.get("winddir")), 0),
        "pressure_inhg": number(latest.get("baromrelin"), 2),
        "solar_wm2": number(latest.get("solarradiation"), 0),
        "uv_index": number(latest.get("uv"), 1),
        "rain_today_in": number(latest.get("dailyrainin"), 2),
        "rain_event_in": number(latest.get("eventrainin"), 2),
        "soil_moisture_pct": number(latest.get("soilhum3"), 0),
        "pm25_ugm3": number(latest.get("pm25"), 1),
    }


def build() -> tuple[dict[str, object], dict[str, object]]:
    ambient = load_ambient()
    dendra = load_dendra()
    prism = load_prism()
    live = recent_series(ambient)
    history, source_counts = merged_history(ambient, dendra, prism)

    now = dt.datetime.now(dt.timezone.utc).astimezone()
    current = latest_conditions(ambient)
    active_date = current["timestamp"][:10]
    active_day = next((record for record in history if record["date"] == active_date), None)
    historical_days = [record for record in history if record["date"] < active_date]

    live_payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "station": {
            "name": "Rancho Venada",
            "timezone": TIMEZONE,
            "elevation_note": "Sierra Nevada foothills",
        },
        "current": current,
        "live_7d": live,
        "active_day": active_day,
        "coverage": {
            "selected_days": source_counts,
            "ambient": {
                "start": ambient.index.min().strftime("%Y-%m-%d"),
                "end": ambient.index.max().strftime("%Y-%m-%d"),
                "observations": int(len(ambient)),
                "status": "live",
            },
            "dendra": {
                "start": dendra.index.min().strftime("%Y-%m-%d"),
                "end": dendra.index.max().strftime("%Y-%m-%d"),
                "observations": int(len(dendra)),
                "status": "historical",
            },
            "prism": {
                "start": prism.index.min().strftime("%Y-%m-%d"),
                "end": prism.index.max().strftime("%Y-%m-%d"),
                "observations": int(prism.count()),
                "status": "historical precipitation",
            },
        },
        "method": {
            "precipitation_priority": ["Ambient", "Dendra", "PRISM"],
            "notes": [
                "Ambient supplies current five-minute station observations.",
                "Dendra backfills earlier station days; one 7,999 mm logger sentinel is rejected.",
                "PRISM fills precipitation-only days when station coverage is incomplete.",
                "Daily station records require at least 200 observations, except the active day.",
                "Cumulative water-year precipitation omits days marked missing; water years begin October 1.",
            ],
        },
    }
    history_payload = {"daily_history": historical_days}
    return live_payload, history_payload


def write_atomic(payload: dict[str, object], output: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w") as handle:
            json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    live_result, history_result = build()
    write_atomic(live_result, LIVE_OUTPUT)
    write_atomic(history_result, HISTORY_OUTPUT)
    print(
        f"Wrote {LIVE_OUTPUT.name} with {len(live_result['live_7d']):,} recent points; "
        f"{HISTORY_OUTPUT.name} with {len(history_result['daily_history']):,} historical days"
    )
