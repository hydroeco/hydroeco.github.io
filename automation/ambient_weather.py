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
    frame.index = localize_index(frame.index)
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
            "endDate": end_date_utc.strftime("%Y-%m-%dT%H:%M"),
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
    raise RuntimeError("Ambient Weather request failed after three attempts") from last_error


def merge_frames(*frames: pd.DataFrame) -> pd.DataFrame:
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return pd.DataFrame()
    combined = pd.concat(populated, sort=False)
    return combined.loc[~combined.index.duplicated(keep="last")].sort_index()


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


def repair(days: int, max_gaps: int) -> None:
    credentials = load_credentials()
    existing = load_frame(LIVE_FILE)
    cutoff = pd.Timestamp.now(tz=TIMEZONE) - pd.Timedelta(days=days)
    recent = existing.loc[existing.index >= cutoff]
    gaps = recent.index.to_series().diff()
    gap_ends = list(gaps[gaps > EXPECTED_INTERVAL * 4].index[:max_gaps])
    if not gap_ends:
        print(f"No gaps over 20 minutes in the last {days} days")
        return

    repairs: list[pd.DataFrame] = []
    for gap_end in gap_ends:
        previous = existing.index[existing.index.get_loc(gap_end) - 1]
        print(f"Checking gap {previous.isoformat()} to {gap_end.isoformat()}")
        chunk = fetch_chunk(gap_end.tz_convert("UTC").to_pydatetime(), credentials)
        if chunk.empty:
            continue
        valid = chunk.loc[(chunk.index > previous) & (chunk.index < gap_end)]
        if not valid.empty:
            repairs.append(valid)
            print(f"Recovered {len(valid):,} rows")
        time.sleep(1)

    if repairs:
        repaired = merge_frames(existing, *repairs)
        atomic_write(repaired, LIVE_FILE)
        print(f"Repair complete: {len(repaired) - len(existing):,} rows recovered")
    else:
        print("No recoverable rows were returned")


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
        if previous_end is not None and start <= previous_end:
            raise RuntimeError(f"Date ranges overlap at {path.name}")
        previous_end = end


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("update", help="Download and append new observations")
    repair_parser = subparsers.add_parser("repair", help="Repair recent data gaps")
    repair_parser.add_argument("--days", type=int, default=14)
    repair_parser.add_argument("--max-gaps", type=int, default=12)
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
