import unittest
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np
from rain_corrections import apply_corrections, restore_observations
from ambient_weather import atomic_write, load_frame, merge_frames
from ambient_rain import daily_rain

class RainCorrectionTests(unittest.TestCase):
    def sample(self):
        idx=pd.date_range('2026-11-18', '2026-11-23', freq='5min', tz='America/Los_Angeles')
        # Fixed raw year counter values from the documented source baseline.
        t=pd.DatetimeIndex(['2026-11-18 00:00','2026-11-18 10:50','2026-11-19 00:00','2026-11-19 10:40','2026-11-20 00:00','2026-11-20 02:00','2026-11-23 00:00']).tz_localize('America/Los_Angeles')
        year=np.interp(idx.asi8,t.asi8,[1.47,2.66,2.77,2.86,2.86,2.87,2.87])
        f=pd.DataFrame({'yearlyrainin':year,'monthlyrainin':year-.37,'weeklyrainin':year-1.04,'eventrainin':year-1.47,'dailyrainin':0.,'hourlyrainin':0.,'tempf':50.},index=idx)
        f.loc[idx>='2026-11-22','weeklyrainin']=0
        f.loc[idx>='2026-11-20 05:25','eventrainin']=0
        return f

    def test_idempotent_and_raw_roundtrip(self):
        raw=self.sample();first=apply_corrections(raw)
        pd.testing.assert_frame_equal(first,apply_corrections(first))
        pd.testing.assert_frame_equal(raw,restore_observations(first))
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'rv_ambient.csv';atomic_write(first,p)
            pd.testing.assert_frame_equal(raw,load_frame(p),check_names=False,check_freq=False,atol=1e-8)

    def test_refresh_preserves_correction_without_double_counting(self):
        raw=self.sample();corrected=apply_corrections(raw)
        refreshed=merge_frames(restore_observations(corrected),raw.iloc[-288:])
        pd.testing.assert_frame_equal(corrected,apply_corrections(refreshed),check_freq=False)
        self.assertAlmostEqual(corrected.yearlyrainin.iloc[-1]-raw.yearlyrainin.iloc[-1],.34)

    def test_counter_resets_and_other_measurements(self):
        raw=self.sample();c=apply_corrections(raw)
        pd.testing.assert_series_equal(c.tempf,raw.tempf)
        self.assertEqual(c.loc['2026-11-22 00:00','weeklyrainin'],0)
        self.assertEqual(c.loc['2026-11-20 05:25','eventrainin'],0)
        self.assertEqual(c.loc['2026-11-19 00:00','dailyrainin'],0)
        self.assertAlmostEqual(c.loc['2026-11-19 10:40','dailyrainin'],.33)
        pd.testing.assert_frame_equal(c.loc[:'2026-11-18 10:50',raw.columns],raw.loc[:'2026-11-18 10:50'])

if __name__=='__main__':unittest.main()
