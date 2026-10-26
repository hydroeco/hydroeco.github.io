"""Rain derived from recorded counters; never interpolate outdoor sensor readings."""
from __future__ import annotations
import pandas as pd


def rain_increments(frame: pd.DataFrame) -> pd.Series:
    """Amounts ending at each observation, including rain across midnight.

    The water-year counter avoids daily-reset losses and rounding drift. Daily
    and storm counters are fallbacks for a water-year reset or an absent field.
    A missing counter stays missing until an actual later reading accounts for
    the interval. The first reading's daily accumulation has no earlier baseline.
    """
    values = frame.reindex(columns=["yearlyrainin", "dailyrainin", "eventrainin"]).apply(pd.to_numeric, errors="coerce")
    values = values.where(values >= 0)
    year = values.yearlyrainin
    annual_delta = year - year.ffill().shift()
    daily = values.dailyrainin
    day = pd.Series(frame.index.normalize(), index=frame.index)
    daily_delta = daily - daily.groupby(day).ffill().shift()
    new_day = day.ne(day.shift())
    daily_delta = daily_delta.where(~new_day, daily)
    event = values.eventrainin
    event_delta = event - event.ffill().shift()
    fallback = event_delta.where(event_delta >= 0).combine_first(daily_delta.where(daily_delta >= 0))
    # Both short counters can reset at the same instant as the annual counter.
    reset = annual_delta.lt(0)
    fallback = fallback.where(~(reset & fallback.isna()), 0.0)
    # If only the annual field was absent, short counters may already have
    # accounted for part of its next increment. Do not count that part twice.
    groups = year.notna().cumsum()
    accounted = fallback.where(year.isna(), 0).fillna(0).groupby(groups).cumsum().shift(fill_value=0)
    annual_delta = annual_delta - accounted.where(year.notna() & ~reset, 0)
    result = annual_delta.where(annual_delta >= -0.00001).clip(lower=0).combine_first(fallback)
    result.loc[values.isna().all(axis=1)] = float("nan")
    if len(result):
        result.iloc[0] = daily.iloc[0]
    return result.round(5).rename("rain_increment_in")


def daily_rain(frame: pd.DataFrame) -> pd.Series:
    """Allocate recorded increments to calendar days, respecting midnight gaps.

    An observation at midnight closes the preceding day. For an outage across
    one midnight, the resumed daily counter gives the new day's portion and
    the remaining annual-counter increase belongs to the preceding day.
    Multi-day wet outages cannot be dated exactly from counters alone; retain
    their total on the recovery date, without inventing an hourly distribution.
    """
    increments = rain_increments(frame)
    allocation = increments.copy()
    allocation.index = allocation.index - pd.Timedelta(nanoseconds=1)
    totals = allocation.resample("D").sum(min_count=1)
    times = frame.index.to_series()
    previous = times.shift()
    crossed = (times.dt.date.ne(previous.dt.date) & previous.notna()) & ((times - previous) > pd.Timedelta(minutes=6))
    for stamp in times[crossed]:
        before = previous.loc[stamp]
        total = increments.loc[stamp]
        if pd.isna(total):
            continue
        days = pd.date_range(before.normalize(), stamp.normalize(), freq="D")
        if total == 0:
            # An unchanged cumulative counter establishes zero across this gap.
            totals.loc[days] = totals.reindex(days).fillna(0)
        elif len(days) == 2:
            current = frame.loc[stamp, "dailyrainin"]
            if pd.notna(current) and 0 <= current <= total + 0.011:
                prior = max(0.0, total - current)
                destination = (stamp - pd.Timedelta(nanoseconds=1)).normalize()
                if destination != before.normalize():
                    totals.loc[destination] -= prior
                    totals.loc[before.normalize()] = totals.get(before.normalize(), 0.0) + prior
    return totals.reindex(pd.date_range(frame.index.min().normalize(), frame.index.max().normalize(), freq="D")).round(5)
