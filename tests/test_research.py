import unittest
from unittest.mock import patch
from research.data import normalize, STEP, collect

class CandleTests(unittest.TestCase):
    def test_only_closed_sorted_deduplicated(self):
        a=[0,100,102,99,101,10,1000]
        b=[STEP,101,103,100,102,12,1200]
        self.assertEqual([r[0] for r in normalize([b,a,a],STEP)],[0])
    def test_invalid_and_conflicting(self):
        for row in ([1,100,102,99,101,1,1],[0,100,99,98,101,1,1],[0,100,102,99,101,-1,1],
                    [0,100,102,99,float('nan'),1,1]):
            with self.assertRaises(ValueError): normalize([row],STEP)
        with self.assertRaises(ValueError):
            normalize([[0,100,102,99,101,1,1],[0,100,102,99,100,1,1]],STEP)
    def test_pagination_exclusive_boundary(self):
        import tempfile
        from pathlib import Path
        # Each fake page is exclusive of endTime, just like Bitget.
        def page(end):
            return [[t,100,101,99,100,1,100] for t in range(max(0,(int(end)//STEP-20)*STEP),int(end)//STEP*STEP,STEP)]
        with tempfile.TemporaryDirectory() as tmp, patch('research.data.time.time',return_value=100*STEP/1000), patch('research.data.time.sleep'), patch('research.data.fetch_page',side_effect=page), patch('builtins.print'):
            path=Path(tmp)/'test.csv'
            collect(path,1)
            import json
            meta=json.loads(Path(str(path)+'.json').read_text())
            self.assertTrue(meta['complete'])
            self.assertEqual(meta['count'],96)

try:
    import numpy as np
    import pandas as pd
    from research.features import features, dataset, FEATURES, HORIZON
    from research.backtest import simulate
    HAS_ML=True
except ImportError:
    HAS_ML=False

@unittest.skipUnless(HAS_ML,'ML dependencies only installed in research image')
class ResearchTests(unittest.TestCase):
    def candles(self,n=300):
        c=100+np.arange(n)*.01+np.sin(np.arange(n)/5)*.1
        return pd.DataFrame(dict(timestamp=np.arange(n)*STEP,open=c,high=c+.2,low=c-.2,close=c+.01,
                                 volume=10+np.arange(n)%7,quote_volume=1000))
    def test_features_do_not_see_future(self):
        raw=self.candles()
        full=features(raw)
        for end in (150,151,152,153,199,200):
            prefix=features(raw.iloc[:end])
            np.testing.assert_allclose(prefix[FEATURES].iloc[-1],full[FEATURES].iloc[end-1],equal_nan=True)
        changed=raw.copy(); changed.loc[201:,'close']*=2
        np.testing.assert_allclose(features(changed)[FEATURES].iloc[200],full[FEATURES].iloc[200],equal_nan=True)
        np.testing.assert_allclose(features(raw.iloc[-200:])[FEATURES].iloc[-1],full[FEATURES].iloc[-1],equal_nan=True)
    def test_labels_start_at_next_open_and_drop_unresolved(self):
        raw=self.candles()
        d=dataset(raw)
        self.assertEqual(d.index[-1],len(raw)-HORIZON-1)
        i=d.index[0]
        self.assertAlmostEqual(d.loc[i,'future_return'],raw.close.iloc[i+4]/raw.open.iloc[i+1]-1)
    def test_both_barriers_stop_first(self):
        raw=self.candles(10)
        raw.loc[1,['open','high','low','close']]=[100,105,95,100]
        r=simulate(raw,{0:('long',.2)},1,6)
        self.assertEqual(r['trades'],1)
        self.assertLess(r['final_equity'],100)
    def test_next_open_execution_and_costs(self):
        raw=self.candles(10)
        raw.loc[:,['open','high','low','close']]=[110,110,110,110]
        r=simulate(raw,{0:('long',1)},1,6)
        expensive=simulate(raw,{0:('long',1)},1,6,2)
        self.assertEqual(r['trades'],1)
        self.assertLess(r['final_equity'],100)
        self.assertGreater(r['final_equity'],99.5)
        self.assertLess(expensive['final_equity'],r['final_equity'])
    def test_no_signals_no_cost(self):
        r=simulate(self.candles(10),{},1,9)
        self.assertEqual(r['final_equity'],100)
        self.assertEqual(r['max_drawdown_pct'],0)
    def test_purged_splits(self):
        from sklearn.model_selection import TimeSeriesSplit
        for train,val in TimeSeriesSplit(n_splits=3,gap=HORIZON).split(np.arange(1000)):
            self.assertLess(train[-1]+HORIZON,val[0])
