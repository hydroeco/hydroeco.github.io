import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import ambient_weather as a
import build_weather_dashboard as b
from ambient_rain import daily_rain, rain_increments


def frame(times, yearly, daily, event=None):
    index = pd.DatetimeIndex(times)
    if index.tz is None:
        index = index.tz_localize(a.TIMEZONE)
    return pd.DataFrame({'yearlyrainin':yearly, 'dailyrainin':daily,
        'eventrainin':event if event is not None else yearly,
        'tempf':60., 'humidity':50., 'windspdmph_avg10m':1.,
        'windspeedmph':1., 'windgustmph':2., 'solarradiation':10., 'uv':1.},index=index)


class WeatherRegressionTests(unittest.TestCase):
    def test_partial_response_never_erases_good_observation(self):
        old=frame(['2026-10-20 12:00'],[1],[.1]); new=old.copy()
        new.loc[:,['tempf','dailyrainin']]=float('nan');new['humidity']=55.
        merged=a.merge_frames(old,new)
        self.assertEqual(merged.tempf.iloc[0],60)
        self.assertEqual(merged.dailyrainin.iloc[0],.1)
        self.assertEqual(merged.humidity.iloc[0],55)

    def test_new_fractional_rain_is_not_cast_to_old_integer_dry_column(self):
        old=frame(['2026-10-20 12:00'],[0],[0])
        new=frame(['2026-10-20 12:05'],[.01],[.01])
        result=a.align_partition(a.merge_frames(old,new),old)
        self.assertEqual(result.dailyrainin.iloc[-1],.01)
        self.assertEqual(result.yearlyrainin.iloc[-1],.01)

    def test_daily_reset_does_not_lose_midnight_rain(self):
        f=frame(['2026-04-26 23:55','2026-04-27 00:00','2026-04-27 00:05'],[22.70,22.72,22.73],[.29,0,.01])
        self.assertEqual(rain_increments(f).tolist(),[.29,.02,.01])
        self.assertAlmostEqual(daily_rain(f).iloc[0],.31)

    def test_delayed_daily_reset_does_not_double_count_yesterday(self):
        f=frame(['2024-04-04 23:55','2024-04-05 00:00','2024-04-05 00:05','2024-04-05 23:55'],[21.36,21.36,21.36,21.59],[.67,.67,0,.23])
        self.assertAlmostEqual(daily_rain(f).iloc[-1],.23)

    def test_rain_during_cross_midnight_outage_is_reconciled(self):
        f=frame(['2024-02-04 19:40','2024-02-05 01:07','2024-02-05 23:55'],[13.52,14.15,14.33],[1.85,.11,.29])
        self.assertEqual(daily_rain(f).tolist(),[2.37,.29])

    def test_water_year_reset_uses_storm_increment(self):
        f=frame(['2026-09-30 23:55','2026-10-01 00:00','2026-10-01 00:05'],[22.8,0,.01],[.1,0,.01],[.1,.12,.13])
        self.assertEqual(rain_increments(f).tolist(),[.1,.02,.01])

    def test_missing_counters_are_not_zero_filled(self):
        f=frame(['2026-10-20 12:00','2026-10-20 12:05','2026-10-20 12:10'],[1,None,1.04],[.1,None,.14],[.1,None,.14])
        increments=rain_increments(f)
        self.assertTrue(pd.isna(increments.iloc[1]))
        self.assertEqual(increments.iloc[2],.04)

    def test_returning_year_counter_does_not_recount_daily_fallback(self):
        f=frame(['2026-10-20 12:00','2026-10-20 12:05','2026-10-20 12:10'],[1,None,1.04],[.1,.12,.14],[.1,.12,.14])
        self.assertEqual(rain_increments(f).tolist(),[.1,.02,.02])

    def test_first_window_point_does_not_count_earlier_daily_rain(self):
        idx=pd.date_range('2026-10-19 12:00',periods=7*288+2,freq='5min',tz=a.TIMEZONE)
        f=frame(idx,[1]*len(idx),[.5]*len(idx))
        self.assertEqual(sum(p['rain_in'] or 0 for p in b.recent_series(f)),0)

    def test_temperature_dropout_does_not_discard_precipitation(self):
        idx=pd.date_range('2026-10-20',periods=288,freq='5min',tz=a.TIMEZONE)
        f=frame(idx,[1+i*.001 for i in range(288)],[i*.001 for i in range(288)])
        f['tempf']=float('nan')
        dendra=pd.DataFrame({'RanchoVenadaWs_Rainfall':[0.], 'RanchoVenadaWs_Air_Temp_Avg':[20.], 'RanchoVenadaWs_Relative_Humidity_Max':[50.], 'RanchoVenadaWs_Wind_Speed_Avg':[1.]},index=pd.to_datetime(['2026-10-19']))
        records,_=b.merged_history(f,dendra,pd.Series([0.],index=pd.to_datetime(['2026-10-19'])))
        self.assertEqual(records[-1]['source'],'ambient')
        self.assertEqual(records[-1]['precip_in'],.287)
        self.assertIsNone(records[-1]['temp_mean_f'])

    def test_retained_cumulative_rain_is_not_replaced_due_to_low_sample_count(self):
        f=frame(['2024-02-05 01:07','2024-02-05 23:55','2024-02-06 00:00'],[14.15,14.33,14.33],[.11,.29,0])
        idx=pd.date_range('2024-02-05',periods=288,freq='5min')
        dendra=pd.DataFrame({'RanchoVenadaWs_Rainfall':.047*25.4/288, 'RanchoVenadaWs_Air_Temp_Avg':20., 'RanchoVenadaWs_Relative_Humidity_Max':50., 'RanchoVenadaWs_Wind_Speed_Avg':1.},index=idx)
        records,_=b.merged_history(f,dendra,pd.Series([0.],index=pd.to_datetime(['2024-02-05'])))
        self.assertEqual(records[0]['precip_in'],.29)
        self.assertEqual(records[0]['source'],'ambient')

    def test_latest_rain_is_kept_when_latest_temperature_is_missing(self):
        f=frame(['2026-10-20 12:00','2026-10-20 12:05'],[1,1.1],[0,.1])
        f.loc[f.index[-1],'tempf']=float('nan')
        latest=b.latest_conditions(f)
        self.assertEqual(latest['timestamp'],f.index[-1].isoformat())
        self.assertEqual(latest['rain_today_in'],.1)
        self.assertIsNone(latest['temp_f'])

    def test_repair_checks_rain_retained_only_in_annual_counter(self):
        f=frame(['2026-04-23 08:35','2026-04-23 08:40'],[22.40,22.41],[0,0])
        self.assertEqual(a.repair_days(f,f.index[0]),[f.index[0].normalize()])

    def test_candidates_include_partial_fields_and_all_gap_days(self):
        f=frame(['2026-10-20 00:00','2026-10-20 00:05','2026-10-23 00:00'],[0,0,0],[0,0,0])
        f.loc[f.index[0],'tempf']=float('nan')
        days=a.repair_days(f,f.index[0])
        self.assertEqual([str(d.date()) for d in days],['2026-10-20','2026-10-21','2026-10-22','2026-10-23'])

    def test_dry_counter_bridges_multi_day_outage_without_inventing_rain(self):
        f=frame(['2025-07-31 12:00','2025-08-09 12:00'],[10,10],[0,0])
        self.assertEqual(daily_rain(f).tolist(),[0.]*10)

    def test_station_credentials_and_location_metadata_are_not_written_to_archive(self):
        f=frame(['2026-10-20 12:00'],[1],[.1])
        f['passkey']='test-private-value';f['loc']='test-private-location'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.csv';a.atomic_write(f,path);read=a.load_frame(path)
        self.assertNotIn('passkey',read.columns)
        self.assertNotIn('loc',read.columns)
        self.assertEqual(read.dailyrainin.iloc[0],.1)

    def test_utc_time_preserves_both_fall_back_hours_in_csv(self):
        idx=pd.date_range('2025-11-02 08:00',periods=25,freq='5min',tz='UTC').tz_convert(a.TIMEZONE)
        f=frame(idx,[1]*len(idx),[0]*len(idx)); f['dateutc']=[int(t.timestamp()*1000) for t in idx]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.csv';a.atomic_write(f,path);read=a.load_frame(path)
        self.assertEqual(list(read.index),list(idx))

    def test_fetch_day_pages_through_25_hour_day(self):
        day=pd.Timestamp('2025-11-02',tz=a.TIMEZONE)
        idx=pd.date_range(day,day+pd.DateOffset(days=1),freq='5min',inclusive='left')
        f=frame(idx,[1]*len(idx),[0]*len(idx))
        self.assertEqual(len(f),300)
        with patch.object(a,'fetch_chunk',side_effect=[f.iloc[-288:],f.iloc[:12]]),patch.object(a.time,'sleep'):
            result=a.fetch_day(day,{})
        self.assertEqual(len(result),300)

if __name__=='__main__':unittest.main()
