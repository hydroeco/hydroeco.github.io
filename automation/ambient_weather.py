#!/usr/bin/env python3
"""Maintain the Rancho Venada Ambient Weather CSV without unbounded files."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd


HOME = Path.home()
DATA_DIR = HOME / "hydroeco.github.io" / "rancho_venada"
LIVE_FILE = DATA_DIR / "rv_ambient.csv"
CONFIG_FILE = HOME / ".config" / "hydroeco" / "ambient_credentials.json"
TIMEZONE = "America/Los_Angeles"
API_URL = "https://rt.ambientweather.net/v1/devices/{mac}"
API_LIMIT = 288
EXPECTED_INTERVAL = pd.Timedelta(minutes=5)


def load_credentials() -> dict[str, str]:
    with CONFIG_FILE.open() as handle:
        credentials = json.load(handle)
    required = {"MAC", "API_KEY", "APP_KEY"}
    missing = required.difference(credentials)
    if missing:
        raise RuntimeError(f"Missing credential fields: {', '.join(sorted(missing))}")
    return credentials


def localize_index(index: pd.Index) -> pd.DatetimeIndex:
    parsed = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
    if parsed.tz is None:
        try:
            parsed = parsed.tz_localize(
                TIMEZONE, ambiguous="infer", nonexistent="shift_forward"
            )
        except Exception:
            # Older files stored naive local time and removed the duplicate fall-back
            # hour, so that hour cannot always be inferred. Prefer standard time.
            parsed = parsed.tz_localize(
                TIMEZONE, ambiguous=False, nonexistent="shift_forward"
            )
    else:
        parsed = parsed.tz_convert(TIMEZONE)
    return parsed


def load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0, low_memory=False)
    local_index = localize_index(frame.index)
    # The UTC observation time preserves both occurrences of the fall-back hour.
    if "dateutc" in frame:
        utc = pd.to_datetime(pd.to_numeric(frame["dateutc"], errors="coerce"), unit="ms", utc=True)
        utc_index = pd.DatetimeIndex(utc).tz_convert(TIMEZONE)
        frame.index = utc_index.where(utc_index.notna(), local_index)
    else:
        frame.index = local_index
    frame = frame.loc[~frame.index.isna()]
    return frame.loc[~frame.index.duplicated(keep="last")].sort_index()


def atomic_write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame.loc[~frame.index.duplicated(keep="last")].sort_index().copy()
    if output.index.tz is not None:
        output.index = output.index.tz_convert(TIMEZONE).tz_localize(None)
    output.index.name = "date"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        output.to_csv(temporary)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_chunk(end_date_utc: dt.datetime, credentials: dict[str, str]) -> pd.DataFrame:
    query = urlencode(
        {
            "apiKey": credentials["API_KEY"],
            "applicationKey": credentials["APP_KEY"],
            "endDate": end_date_utc.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": API_LIMIT,
        }
    )
    url = f"{API_URL.format(mac=credentials['MAC'])}?{query}"

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urlopen(url, timeout=20) as response:
                records = json.loads(response.read().decode("utf-8"))
            if not records:
                return pd.DataFrame()
            frame = pd.DataFrame(records)
            if "date" not in frame:
                raise RuntimeError("Ambient response did not contain a date field")
            frame.index = pd.to_datetime(frame.pop("date"), utc=True).dt.tz_convert(TIMEZONE)
            frame.index.name = "date"
            return frame.loc[~frame.index.duplicated(keep="last")].sort_index()
        except Exception as error:  # network and malformed responses use the same retry policy
            last_error = error
            print(f"Ambient request attempt {attempt}/3 failed: {type(error).__name__}")
            if attempt < 3:
                time.sleep(2**attempt)
    raise RuntimeError("Ambient Weather request failed after three attempts") from None


def merge_frames(*frames: pd.DataFrame) -> pd.DataFrame:
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return pd.DataFrame()
    combined = pd.concat(populated, sort=False)
    # Prefer the latest non-null field, rather than replacing an entire good row
    # with a later partial response. This never fills across observation times.
    return combined.groupby(level=0, sort=True).last()


def save_partitioned(frame: pd.DataFrame) -> None:
    years = sorted(set(int(year) for year in frame.index.year))
    active_year = years[-1]
    for year in years:
        part = frame.loc[frame.index.year == year]
        destination = LIVE_FILE if year == active_year else DATA_DIR / f"rv_ambient_{year}.csv"
        if destination != LIVE_FILE and destination.exists():
            part = merge_frames(load_frame(destination), part)
        atomic_write(part, destination)
        print(f"Wrote {len(part):,} rows to {destination.name}")


def update() -> None:
    if not LIVE_FILE.exists():
        raise RuntimeError(f"Live data file does not exist: {LIVE_FILE}")
    credentials = load_credentials()
    existing = load_frame(LIVE_FILE)
    if existing.empty:
        raise RuntimeError("Live data file contains no valid rows")

    newest = existing.index.max().tz_convert("UTC")
    request_end = pd.Timestamp.now(tz="UTC")
    additions: list[pd.DataFrame] = []
    print(f"Updating from {newest.isoformat()} to {request_end.isoformat()}")

    for _ in range(64):
        if request_end <= newest:
            break
        chunk = fetch_chunk(request_end.to_pydatetime(), credentials)
        if chunk.empty:
            print("Ambient Weather returned no newer data")
            break
        additions.append(chunk)
        oldest = chunk.index.min().tz_convert("UTC")
        print(f"Fetched {len(chunk):,} rows back to {oldest.isoformat()}")
        if oldest <= newest:
            break
        request_end = oldest - pd.Timedelta(seconds=1)
        time.sleep(1)
    else:
        raise RuntimeError("Update stopped after 64 API pages; manual inspection is required")

    if not additions:
        return
    combined = merge_frames(existing, *additions)
    before = len(existing)
    save_partitioned(combined)
    print(f"Update complete: {len(combined) - before:,} net new rows")


CORE_FIELDS = ["tempf", "humidity", "windspeedmph", "solarradiation", "dailyrainin", "yearlyrainin"]
REPAIR_STATE = HOME / ".local/state/ambient-repair.json"


def repair_days(frame: pd.DataFrame, cutoff: pd.Timestamp) -> list[pd.Timestamp]:
    """Include partial records and every day of a multi-day timestamp gap."""
    recent = frame.loc[frame.index >= cutoff]
    fields = recent.reindex(columns=CORE_FIELDS)
    days = set(recent.index[fields.isna().any(axis=1)].normalize())
    # Also replay wet days to catch revised rain counters, independent of temp.
    days.update(recent.index[fields.dailyrainin.gt(0)].normalize())
    gaps = frame.index.to_series().diff()
    for end in gaps[(gaps > EXPECTED_INTERVAL + pd.Timedelta(seconds=30)) & (gaps.index >= cutoff)].index:
        start = max(end - gaps.loc[end], cutoff)
        days.update(pd.date_range(start.normalize(), end.normalize(), freq="D"))
    return sorted(days)


def fetch_day(day: pd.Timestamp, credentials: dict[str, str]) -> pd.DataFrame:
    """Page until the whole local day is covered, including 25-hour DST days."""
    stop = day + pd.DateOffset(days=1)
    end = stop.tz_convert("UTC") - pd.Timedelta(seconds=1)
    chunks = []
    for _ in range(8):
        chunk = fetch_chunk(end.to_pydatetime(), credentials)
        time.sleep(1)
        if chunk.empty:
            break
        chunks.append(chunk.loc[(chunk.index >= day) & (chunk.index < stop)])
        oldest = chunk.index.min().tz_convert("UTC")
        if oldest <= day.tz_convert("UTC"):
            break
        if oldest >= end:
            raise RuntimeError("Ambient pagination did not advance")
        end = oldest - pd.Timedelta(seconds=1)
    else:
        raise RuntimeError("Ambient day exceeded eight pages")
    return merge_frames(*chunks)


def repair(days: int, max_gaps: int) -> None:
    if days < 0 or max_gaps < 1:
        raise ValueError("days must be non-negative and max-gaps must be positive")
    credentials = load_credentials()
    paths = sorted(DATA_DIR.glob("rv_ambient_[0-9][0-9][0-9][0-9].csv")) + [LIVE_FILE]
    existing = merge_frames(*(load_frame(path) for path in paths))
    cutoff = existing.index.min() if days == 0 else pd.Timestamp.now(tz=TIMEZONE) - pd.Timedelta(days=days)
    candidates = repair_days(existing, cutoff)
    state = json.loads(REPAIR_STATE.read_text()) if REPAIR_STATE.exists() else {}
    # Old unrecoverable gaps must not permanently starve newer gaps of retries.
    candidates.sort(key=lambda day: (state.get(str(day.date()), ""), -day.timestamp()))
    repairs = []
    for day in candidates[:max_gaps]:
        fresh = fetch_day(day, credentials)
        old = existing.reindex(index=fresh.index, columns=CORE_FIELDS)
        values = fresh.reindex(columns=CORE_FIELDS)
        recovered = (old.isna() & values.notna()).sum()
        print(f"Checked {day.date()}: {len(fresh)} API rows, "
              f"{len(fresh.index.difference(existing.index))} new timestamps, "
              f"filled fields {recovered.to_dict()}")
        if not fresh.empty:
            repairs.append(fresh)
        state[str(day.date())] = pd.Timestamp.now(tz="UTC").isoformat()
    if repairs:
        repaired = merge_frames(existing, *repairs)
        for path in paths:
            before = load_frame(path)
            years = set(before.index.year)
            after = repaired.loc[repaired.index.year.isin(years)]
            if not after.equals(before):
                atomic_write(after, path)
        print(f"Repair complete: {len(repaired) - len(existing)} new rows")
    REPAIR_STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPAIR_STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(REPAIR_STATE)
    print(f"Checked {min(len(candidates), max_gaps)} of {len(candidates)} candidate days")


def check() -> None:
    paths = sorted(DATA_DIR.glob("rv_ambient_[0-9][0-9][0-9][0-9].csv")) + [LIVE_FILE]
    previous_end: pd.Timestamp | None = None
    for path in paths:
        frame = load_frame(path)
        if frame.empty:
            raise RuntimeError(f"{path.name} has no valid rows")
        start, end = frame.index.min(), frame.index.max()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        print(
            f"{path.name}: {len(frame):,} rows, {path.stat().st_size:,} bytes, "
            f"{start.isoformat()} -> {end.isoformat()}, sha256 {digest}"
        )
        missing = frame.reindex(columns=CORE_FIELDS).isna().sum().to_dict()
        print(f"  Missing fields: {missing}; timestamp gaps: "
              f"{int((frame.index.to_series().diff() > EXPECTED_INTERVAL * 1.1).sum())}")
        if previous_end is not None and start <= previous_end:
            raise RuntimeError(f"Date ranges overlap at {path.name}")
        previous_end = end


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("update", help="Download and append new observations")
    repair_parser = subparsers.add_parser("repair", help="Re-query incomplete observations, wet days, and timestamp gaps")
    repair_parser.add_argument("--days", type=int, default=14, help="Lookback days; 0 includes all archives")
    repair_parser.add_argument("--max-gaps", type=int, default=12, help="Maximum days to re-query per run")
    subparsers.add_parser("check", help="Validate and summarize local data files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "update":
        update()
    elif args.command == "repair":
        repair(args.days, args.max_gaps)
    else:
        check()


if __name__ == "__main__":
    main()
