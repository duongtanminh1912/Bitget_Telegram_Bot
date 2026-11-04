import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock
try:
    import numpy as np
    import pandas as pd
    import talib
    from research.indicators import last_values,indicator_features,INDICATORS
    from research.feature_sets import columns,inputs
    from research.features import FEATURES
    HAS_INDICATORS=True
except ImportError:HAS_INDICATORS=False

@unittest.skipUnless(HAS_INDICATORS,'TA-Lib image required')
class IndicatorTests(unittest.TestCase):
    def frame(self,n=320):
        t=np.arange(n);c=100+t*.01+np.sin(t/7)
        return pd.DataFrame(dict(timestamp=t*900000,open=c-.01,high=c+.5,low=c-.5,close=c,
            volume=10+t%9,quote_volume=(10+t%9)*c))
    def test_reference_rsi_macd_adx_and_stochastic(self):
        f=self.frame().iloc[-200:];r=last_values(f)
        h,l,c=[f[k].to_numpy(dtype=float) for k in ('high','low','close')]
        self.assertAlmostEqual(r['rsi14'],talib.RSI(c,14)[-1]/100)
        macd,sig,hist=talib.MACD(c,12,26,9)
        self.assertAlmostEqual(r['macd_hist_pct'],hist[-1]/c[-1])
        self.assertAlmostEqual(r['macd_pct'],macd[-1]/c[-1])
        self.assertAlmostEqual(r['adx14'],talib.ADX(h,l,c,14)[-1]/100)
        k,d=talib.STOCH(h,l,c,14,3,0,3,0)
        self.assertAlmostEqual(r['stoch_k'],k[-1]/100)
    def test_bollinger_and_vwap_against_direct_formula(self):
        f=self.frame().iloc[-200:];r=last_values(f);last=f.iloc[-20:]
        mean=last.close.mean();std=last.close.std(ddof=0)
        self.assertAlmostEqual(r['bb_width'],4*std/mean,places=9)
        self.assertAlmostEqual(r['bb_position'],(last.close.iloc[-1]-(mean-2*std))/(4*std),places=9)
        vwap=(((last.high+last.low+last.close)/3)*last.volume).sum()/last.volume.sum()
        self.assertAlmostEqual(r['vwap_gap20'],last.close.iloc[-1]/vwap-1)
    def test_no_future_leakage_and_live_history_equality(self):
        f=self.frame();full=indicator_features(f)
        for end in (200,201,220,299,320):
            live=indicator_features(f.iloc[end-200:end])
            np.testing.assert_allclose(live[INDICATORS].iloc[-1],full[INDICATORS].iloc[end-1],rtol=1e-12,atol=1e-12)
            prefix=indicator_features(f.iloc[:end])
            np.testing.assert_allclose(prefix[INDICATORS].iloc[-1],full[INDICATORS].iloc[end-1],rtol=1e-12,atol=1e-12)
        changed=f.copy();changed.loc[250:,'close']*=1.1
        np.testing.assert_allclose(indicator_features(changed)[INDICATORS].iloc[249],full[INDICATORS].iloc[249])
    def test_warmup_and_constant_price_never_infinite(self):
        f=self.frame();f[['open','high','low','close']]=100.;f.volume=0
        result=indicator_features(f)
        self.assertTrue(result[INDICATORS].iloc[:199].isna().all().all())
        self.assertTrue(np.isfinite(result[INDICATORS].iloc[199:].to_numpy()).all())
        self.assertEqual(result.bb_position.iloc[-1],.5)
        self.assertEqual(result.obv_flow20.iloc[-1],0)
    def test_base_columns_unchanged(self):
        from research.features import features
        f=self.frame()
        np.testing.assert_allclose(features(f)[FEATURES],indicator_features(f)[FEATURES],equal_nan=True)
        self.assertEqual(len(columns('indicators')),42)
    def test_shared_train_live_inputs_and_signs(self):
        from research.feature_sets import side_input
        row=indicator_features(self.frame()).iloc[-1]
        x=inputs(row,'indicators')
        self.assertEqual(set(x.columns),set(columns('indicators')))
        self.assertEqual(x.iloc[0].to_dict(),side_input(row,1,'indicators'))
        self.assertAlmostEqual(x.signed_rsi14.iloc[0],-x.signed_rsi14.iloc[1])
        self.assertAlmostEqual(x.signed_macd_pct.iloc[0],-x.signed_macd_pct.iloc[1])
    def test_indicator_artifact_schema_and_snapshot(self):
        import joblib
        from research.shadow import Shadow
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            bundle=dict(model=None,feature_mode='indicators',features=columns('indicators'),paper_proposals_enabled=False,
                data_through_ms=0,report={'last_ms':0,'parameters':{'horizon_minutes':60}})
            joblib.dump(bundle,root/'model.joblib')
            s=Shadow(root,root/'forward.db')
            try:
                model=Mock();model.predict.return_value=(np.array([.6,.4]),np.array([.001,-.001]));s.bundle['model']=model
                f=self.frame(200)
                self.assertEqual(s.record(f.to_numpy().tolist(),now=200*900),2)
                self.assertEqual(s.db.execute('SELECT COUNT(*) FROM feature_snapshots').fetchone()[0],1)
                import json
                event=json.loads(s.db.execute("SELECT body FROM events WHERE kind='forecast'").fetchone()[0])
                self.assertIn('rsi14',event[0]['indicators'])
                self.assertEqual(list(model.predict.call_args.args[0].columns),columns('indicators'))
            finally:s.db.close()
    def test_legacy_model_schema_still_works(self):
        from research.trade_models import TradeModel
        from research.trade_labels import TRADE_FEATURES
        m=TradeModel('lightgbm')
        del m.feature_columns # pre-V3 joblib snapshots did not have this field
        m.classifier=Mock();m.classifier.predict_proba.return_value=np.array([[.7,.3]])
        m.calibrator=Mock();m.calibrator.predict_proba.return_value=np.array([[.6,.4]])
        m.regressor=Mock();m.regressor.predict.return_value=np.array([.001])
        m.predict(pd.DataFrame([{k:0 for k in TRADE_FEATURES}]))
        self.assertEqual(list(m.classifier.predict_proba.call_args.args[0].columns),TRADE_FEATURES)
