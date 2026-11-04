import unittest
from unittest.mock import patch
try:
    import numpy as np
    import pandas as pd
    from research.trade_labels import outcome,TRADE_FEATURES
    from research.trade_backtest import replay,wilson
    from research.trade_models import TradeModel,signals
    HAS_ML=True
except ImportError:
    HAS_ML=False

@unittest.skipUnless(HAS_ML,'ML image required')
class TradeOutcomeTests(unittest.TestCase):
    def path(self):
        return np.array([[60000+i*60000,100,100.1,99.9,100,10,1000] for i in range(59)],dtype=float)
    def test_long_tp_before_later_stop(self):
        p=self.path();p[1,2]=104;p[2,3]=95
        result=outcome(p,100,1,'long',[])
        self.assertEqual(result['reason'],'tp')
        self.assertEqual(result['tp_first'],1)
        self.assertGreater(result['net_return'],0)
    def test_short_tp(self):
        p=self.path();p[1,3]=96
        result=outcome(p,100,1,'short',[])
        self.assertEqual(result['reason'],'tp')
        self.assertGreater(result['net_return'],0)
    def test_both_barriers_in_same_minute_is_loss(self):
        for side in ('long','short'):
            p=self.path();p[1,2:4]=[105,95]
            result=outcome(p,100,1,side,[])
            self.assertEqual(result['reason'],'sl')
            self.assertTrue(result['ambiguous'])
            self.assertLess(result['net_return'],0)
    def test_gap_stop_fills_at_open(self):
        p=self.path();p[1,1:5]=[95,96,94,95]
        result=outcome(p,100,1,'long',[])
        self.assertAlmostEqual(result['exit_fill'],95*(1-.0005))
    def test_approval_drift_rejected(self):
        p=self.path();p[0,1]=101
        self.assertIsNone(outcome(p,100,1,'long',[]))
    def test_flat_price_is_net_loss(self):
        for side in ('long','short'):
            result=outcome(self.path(),100,1,side,[])
            self.assertEqual(result['reason'],'timeout')
            self.assertEqual(result['win'],0)
            self.assertLess(result['net_return'],0)
    def test_funding_has_correct_side_sign(self):
        path=self.path();settlement=120000
        for side,sign in (('long',1),('short',-1)):
            funded=outcome(path,100,1,side,[(settlement,.001)])
            plain=outcome(path,100,1,side,[])
            self.assertAlmostEqual(funded['net_per_unit']-plain['net_per_unit'],-sign*.1)
    def test_funding_at_entry_excluded_and_expiry_included(self):
        result=outcome(self.path(),100,1,'long',[(60000,.001),(3600000,.002)])
        self.assertAlmostEqual(result['funding_per_unit'],.2)
    def test_funding_after_barrier_exit_excluded(self):
        path=self.path();path[0,2]=104
        result=outcome(path,100,1,'long',[(120000,.01)])
        self.assertEqual(result['funding_per_unit'],0)
    def test_double_cost_reduces_net_return(self):
        path=self.path();path[1,2]=104
        self.assertLess(outcome(path,100,1,'long',[],2)['net_return'],outcome(path,100,1,'long',[])['net_return'])
    def test_replay_matches_label_and_charges_funding_once(self):
        from decimal import Decimal,ROUND_DOWN
        from research.data import FIELDS
        for side in ('long','short'):
            path=self.path()
            result=outcome(path,100,1,side,[(120000,.001)])
            full=np.vstack([[0,100,100.1,99.9,100,10,1000],path])
            data=pd.DataFrame(full,columns=FIELDS)
            candidates=pd.DataFrame([dict(result,signal_reference=100,signal_close_ms=0,side_name=side,
                p_win=.6,expected_net_return=.001)])
            funding=pd.DataFrame([{'timestamp':120000,'rate':.001}])
            metric,trades=replay(candidates,data,funding)
            entry=Decimal(str(result['entry_fill']))
            qty=min(Decimal('.5')/Decimal(str(result['risk_per_unit'])),Decimal('100')/(entry*Decimal('1.0006'))).quantize(Decimal('.000001'),rounding=ROUND_DOWN)
            self.assertEqual(metric['trades'],1)
            self.assertAlmostEqual(trades[0]['pnl'],float(qty)*result['net_per_unit'],places=9)
    def test_overlap_is_skipped(self):
        from research.data import FIELDS
        result=outcome(self.path(),100,1,'long',[])
        candidate=dict(result,signal_reference=100,signal_close_ms=0,side_name='long',p_win=.6,expected_net_return=.001)
        full=np.vstack([[0,100,100.1,99.9,100,10,1000],self.path()])
        metrics,_=replay(pd.DataFrame([candidate,candidate]),pd.DataFrame(full,columns=FIELDS),pd.DataFrame(columns=['timestamp','rate']))
        self.assertEqual(metrics['trades'],1)
    def test_wilson_no_trades_is_unknown(self):
        self.assertIsNone(wilson(0,0))
        low,high=wilson(1,1)
        self.assertLess(low,.3)
        self.assertAlmostEqual(high,1)

@unittest.skipUnless(HAS_ML,'ML image required')
class TradePolicyTests(unittest.TestCase):
    def test_policy_requires_probability_and_positive_edge(self):
        from unittest.mock import Mock
        frame=pd.DataFrame(dict(decision_idx=[1,1,2,3],entry_ms=[1,1,2,3],marker=['a','b','c','d']))
        model=Mock()
        model.predict.return_value=(np.array([.6,.7,.54,.8]),np.array([.001,.002,.003,-.001]))
        picked=signals(model,frame)
        self.assertEqual(picked.marker.tolist(),['b'])
    def test_calibration_overlap_is_rejected(self):
        model=TradeModel('logistic')
        train=pd.DataFrame(dict(win=[0,1],exit_ms=[5,10]))
        cal=pd.DataFrame(dict(win=[0,1],signal_close_ms=[10,11]))
        with self.assertRaisesRegex(ValueError,'overlap'): model.fit(train,cal)
    def test_constant_target_rejected(self):
        model=TradeModel('logistic')
        train=pd.DataFrame(dict(win=[0,0],exit_ms=[5,6]))
        cal=pd.DataFrame(dict(win=[0,1],signal_close_ms=[10,11]))
        with self.assertRaisesRegex(ValueError,'Both outcomes'):model.fit(train,cal)

@unittest.skipUnless(HAS_ML,'ML image required')
class ForwardShadowTests(unittest.TestCase):
    def setUp(self):
        import tempfile,json,joblib
        from pathlib import Path
        from research.shadow import Shadow
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        bundle=dict(model=None,features=TRADE_FEATURES,paper_proposals_enabled=False,
            data_through_ms=0,report={'last_ms':0,'parameters':{'horizon_minutes':60}})
        joblib.dump(bundle,root/'model.joblib')
        self.s=Shadow(root,root/'forward.db')
        from unittest.mock import Mock
        self.s.bundle['model']=Mock()
        self.s.bundle['model'].predict.return_value=(np.array([.7,.6]),np.array([.002,.001]))
    def tearDown(self):
        self.s.db.close();self.tmp.cleanup()
    def candles(self):
        return [[i*900000,100+i*.001,101+i*.001,99+i*.001,100.1+i*.001,10,1000] for i in range(200)]
    def test_record_is_prospective_and_idempotent(self):
        now=200*900
        self.assertEqual(self.s.record(self.candles(),now),2)
        self.assertEqual(self.s.record(self.candles(),now+1),0)
        self.assertEqual(self.s.summary()['selected'],1)
        self.assertIsNone(self.s.summary()['selected_win_rate'])
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
    def test_cannot_backdate_after_approval_window(self):
        self.assertEqual(self.s.record(self.candles(),200*900+60),0)
        self.assertEqual(self.s.summary()['forecasts'],0)
    def test_cannot_record_previously_seen_history(self):
        self.s.bundle['report']['last_ms']=200*900000
        self.assertEqual(self.s.record(self.candles(),200*900),0)
    def test_stale_model_rejected(self):
        self.s.bundle['data_through_ms']=-20*86400000
        with self.assertRaisesRegex(ValueError,'Stale model'):self.s.record(self.candles(),200*900)
    def test_pending_forecasts_not_evaluated_early(self):
        self.s.record(self.candles(),200*900)
        with patch('research.shadow.get_json') as network:
            self.assertEqual(self.s.settle(200*900+3599),0)
            network.assert_not_called()
    def test_funding_missing_keeps_result_pending(self):
        self.s.record(self.candles(),200*900)
        with patch('research.shadow.get_json',return_value=[]):
            with self.assertRaisesRegex(ValueError,'funding'):self.s.settle(200*900+3601)
        self.assertEqual(self.s.summary()['resolved'],0)
    def test_live_promotion_flag_rejected(self):
        import joblib
        from pathlib import Path
        from research.shadow import Shadow
        bundle=dict(self.s.bundle,model=None,paper_proposals_enabled=True)
        root=Path(self.tmp.name)
        joblib.dump(bundle,root/'model.joblib')
        with self.assertRaisesRegex(ValueError,'observation-only'):Shadow(root,root/'other.db')
    def test_future_outcomes_are_scored_once(self):
        signal=200*900000
        self.s.record(self.candles(),signal/1000)
        reference=self.candles()[-1][4]
        path=[[signal+60000+i*60000,reference,reference+.01,reference-.01,reference,10,1000] for i in range(59)]
        def api(endpoint,params):
            if endpoint=='history-fund-rate':return [{'fundingTime':signal-3600000,'fundingRate':'0'}]
            return path
        with patch('research.shadow.get_json',side_effect=api):
            self.assertEqual(self.s.settle(signal/1000+3601),2)
        result=self.s.summary()
        self.assertEqual(result['resolved'],2)
        self.assertEqual(result['selected_win_rate'],0)
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM events WHERE kind='result'").fetchone()[0],2)
        with patch('research.shadow.get_json') as api:
            self.assertEqual(self.s.settle(signal/1000+3700),0)
            api.assert_not_called()
    def test_summaries_do_not_mix_model_versions(self):
        self.s.record(self.candles(),200*900)
        self.s.hash='new-version'
        self.assertEqual(self.s.summary()['forecasts'],0)
    def test_event_migration_and_restart_do_not_duplicate(self):
        from pathlib import Path
        from research.shadow import Shadow
        self.s.record(self.candles(),200*900)
        self.s.db.execute('DELETE FROM events');self.s.db.commit()
        root=Path(self.tmp.name)
        for _ in range(2):
            other=Shadow(root,root/'forward.db')
            self.assertEqual(other.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
            other.db.close()
