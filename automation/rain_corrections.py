"""Apply fixed, reviewed rain reconstructions while retaining station readings."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

CONFIG = Path(__file__).with_name('rain_corrections.json')
PREFIX = 'observed_'
RAIN_FIELDS = ('yearlyrainin', 'monthlyrainin', 'weeklyrainin', 'eventrainin',
               'dailyrainin', 'hourlyrainin')


def restore_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Return raw input before API merging, so refreshes cannot compound a fill."""
    result = frame.copy()
    for column in RAIN_FIELDS:
        backup = PREFIX + column
        if backup in result:
            result[column] = result[backup].combine_first(result[column])
            result = result.drop(columns=[backup])
    return result


def apply_corrections(frame: pd.DataFrame) -> pd.DataFrame:
    result = restore_observations(frame)
    if result.empty or not CONFIG.exists():
        return result
    index = result.index
    for correction in json.loads(CONFIG.read_text()):
        start, end = pd.Timestamp(correction['start']), pd.Timestamp(correction['end'])
        if index.max() <= start or index.min() >= pd.Timestamp(correction['expires']['yearlyrainin']):
            continue
        knots = pd.DataFrame(correction['knots'])
        times = pd.DatetimeIndex(pd.to_datetime(knots.timestamp, utc=True))
        delta = np.interp(index.asi8, times.asi8, knots.delta_in, left=0)
        raw = result.copy()
        for column, expiration in correction['expires'].items():
            if column not in result:
                continue
            mask = (index > start) & (index < pd.Timestamp(expiration))
            result.loc[mask, column] = raw.loc[mask, column] + delta[mask]
        # Reconstruct daily counters from corrected annual counters, avoiding
        # asynchronous rounding of the station's different rain counters.
        for day, baseline in correction['daily_year_baselines'].items():
            midnight = pd.Timestamp(day, tz=correction['timezone'])
            mask = (index > start) & (index >= midnight) & (index < midnight + pd.DateOffset(days=1))
            result.loc[mask, 'dailyrainin'] = result.loc[mask, 'yearlyrainin'] - baseline
        # The reconstructed rate is the average over each five-minute interval.
        # Interpolate cumulative rain for observations at a non-grid timestamp.
        cumulative = knots.rain_in.cumsum().to_numpy()
        after = np.interp(index.asi8, times.asi8, cumulative, left=0)
        before = np.interp((index-pd.Timedelta(minutes=5)).asi8, times.asi8, cumulative, left=0)
        mask = (index > start) & (index <= end)
        if 'hourlyrainin' in result:
            result.loc[mask, 'hourlyrainin'] = (after[mask]-before[mask])*12
        for column in RAIN_FIELDS:
            if column not in result:
                continue
            changed = result[column].ne(raw[column]) & raw[column].notna()
            if changed.any():
                backup = PREFIX + column
                if backup not in result:
                    result[backup] = np.nan
                result.loc[changed, backup] = raw.loc[changed, column]
                result.loc[changed, column] = result.loc[changed, column].round(8)
    return result
