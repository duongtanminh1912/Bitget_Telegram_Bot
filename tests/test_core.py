import os
import tempfile
import unittest
from bot.core import Engine, number

class RiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=os.path.join(self.tmp.name,'state.db')
        self.now=1793667600.0
        self.e=Engine(self.path,lambda:self.now)
        self.e.tick('100',self.now)
    def tearDown(self):
        self.e.db.close(); self.tmp.cleanup()
    def signal(self):
        return self.e.propose('long','100','99','102')[0]
    def test_risk_budget(self):
        _,s=self.e.propose('long','100','99','102')
        self.assertLessEqual(number(s['loss']),number('0.5'))
    def test_duplicate_approval(self):
        k=self.signal(); self.e.approve(k,100,self.now)
        with self.assertRaises(ValueError): self.e.approve(k,100,self.now)
    def test_expiry(self):
        k=self.signal(); self.now+=61
        with self.assertRaises(ValueError): self.e.approve(k,100,self.now)
    def test_stale_price(self):
        k=self.signal()
        with self.assertRaises(ValueError): self.e.approve(k,100,self.now-11)
    def test_price_drift(self):
        k=self.signal()
        with self.assertRaises(ValueError): self.e.approve(k,101,self.now)
    def test_approval_rejects_out_of_order_price(self):
        k=self.signal()
        with self.assertRaisesRegex(ValueError, 'đảo thứ tự'):
            self.e.approve(k,100,self.now-1)
        self.assertIsNone(self.e.snapshot()['position'])
    def test_future_price(self):
        k=self.signal()
        with self.assertRaises(ValueError): self.e.approve(k,100,self.now+1)
        with self.assertRaises(ValueError): self.e.tick(100,self.now+1)
    def test_stop(self):
        self.e.approve(self.signal(),100,self.now)
        self.e.tick(98,self.now)
        self.assertIsNone(self.e.snapshot()['position'])
        self.assertLess(number(self.e.snapshot()['cash']),100)
    def test_daily_lock_restart_budget_cannot_reset(self):
        with self.e.tx() as s: s['cash']='84'
        self.e.tick(100,self.now)
        self.e.set_budget(50)
        other=Engine(self.path,lambda:self.now)
        self.assertTrue(other.snapshot()['halted'])
        with self.assertRaises(ValueError): other.propose('long',100,99,102)
        other.db.close()
    def test_new_day(self):
        with self.e.tx() as s: s['cash']='84'
        self.e.tick(100,self.now)
        self.now+=86400; self.e.tick(100,self.now)
        self.assertFalse(self.e.snapshot()['halted'])
        self.assertEqual(self.e.snapshot()['baseline'],'84')
    def test_pause_does_not_disable_stop(self):
        self.e.approve(self.signal(),100,self.now)
        self.e.pause(True); self.e.tick(98,self.now)
        self.assertIsNone(self.e.snapshot()['position'])
    def test_invalid_numbers(self):
        for x in ('NaN','Infinity','-1','0','101'):
            with self.assertRaises(ValueError): self.e.set_budget(x)
    def test_no_budget_change_with_position(self):
        self.e.approve(self.signal(),100,self.now)
        with self.assertRaises(ValueError): self.e.set_budget(50)
    def test_short_target(self):
        k,_=self.e.propose('short',100,101,98)
        self.e.approve(k,100,self.now); self.e.tick(97,self.now)
        self.assertIsNone(self.e.snapshot()['position'])
        self.assertGreater(number(self.e.snapshot()['cash']),100)
    def test_model_horizon_survives_restart_and_pause(self):
        k,_=self.e.propose('long',100,99,102,exit_at=self.now+3600,source='test')
        self.e.approve(k,100,self.now)
        self.e.pause(True)
        other=Engine(self.path,lambda:self.now)
        self.now+=3600
        other.tick(100,self.now)
        self.assertIsNone(other.snapshot()['position'])
        self.assertIn('horizon',other.db.execute("SELECT body FROM audit WHERE event='paper_close'").fetchone()[0])
        other.db.close()
    def test_invalid_model_horizon(self):
        for expiry in (self.now,self.now-1,self.now+3601,float('nan')):
            with self.assertRaises(ValueError):
                self.e.propose('long',100,99,102,exit_at=expiry)

if __name__=='__main__': unittest.main()
