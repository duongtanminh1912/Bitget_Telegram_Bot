import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bot.main import Telegram
from research.forward_view import connect,snapshot,status_text,forecast_text,result_text,preferred

class ForwardTelegramTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'v2').mkdir();(self.root/'v2'/'model.joblib').write_bytes(b'test model bytes')
        (self.root/'v2'/'report.json').write_text(json.dumps({'candidate':'lightgbm'}))
        (self.root/'v3').mkdir();(self.root/'v3'/'model.joblib').write_bytes(b'test model bytes')
        from research.forward_view import model_hash
        self.version=model_hash(self.root)
        self.path=self.root/'forward.db'
        self.db=sqlite3.connect(self.path)
        self.db.executescript('''CREATE TABLE forecasts (model_hash TEXT,signal_ms INTEGER,side TEXT,predicted_at REAL,p_win REAL,expected_return REAL,reference REAL,atr REAL,horizon INTEGER,selected INTEGER,result TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY,kind TEXT,model_hash TEXT,signal_ms INTEGER,side TEXT,body TEXT,created_at REAL);
            CREATE TABLE health (id INTEGER PRIMARY KEY,body TEXT);''')
        self.env=patch.dict(os.environ,dict(TELEGRAM_BOT_TOKEN='dummy',TELEGRAM_USER_ID='123',TELEGRAM_CHAT_ID='123',
            DB_PATH=':memory:',TRADING_MODE='paper',MODEL_DIR=str(self.root),FORWARD_DB=str(self.path),INDICATOR_DB=str(self.path)))
        self.env.start();self.t=Telegram()
    def tearDown(self):
        self.t.engine.db.close();self.env.stop();self.db.close();self.tmp.cleanup()
    def row(self):
        return dict(model_hash=self.version,signal_ms=1793718900000,side='long',predicted_at=1793718907.,
            p_win=.2,expected_return=-.002,reference=77000.,atr=200.,horizon=60,selected=0,result=None)
    def insert(self,row):
        self.db.execute('INSERT INTO forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?)',tuple(row.values()));self.db.commit()
    def event(self,row,eventid=1,kind='forecast'):
        body=[row] if kind=='forecast' else row
        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',(eventid,kind,self.version,row['signal_ms'],row['side'],json.dumps(body),1));self.db.commit()
    def test_empty_is_unknown_not_zero_percent(self):
        view=snapshot(self.path,self.version)
        self.assertIsNone(view['selected']['win_rate'])
        self.assertIn('chưa đủ mẫu',status_text(view))
        self.assertIn('Đang chờ',forecast_text(view['latest']))
    def test_read_only_cannot_mutate(self):
        db=connect(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM forecasts')
        finally:db.close()
    def test_missing_path_does_not_create_database(self):
        path=self.root/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):snapshot(path,self.version)
        self.assertFalse(path.exists())
    def test_rejected_samples_not_counted_as_losses(self):
        row=self.row();row['selected']=1;row['result']=json.dumps({'rejected':'approval_price_drift'});self.insert(row)
        view=snapshot(self.path,self.version)
        self.assertEqual(view['selected']['rejected'],1)
        self.assertEqual(view['selected']['scored'],0)
        self.assertIsNone(view['selected']['win_rate'])
        self.assertIn('Không tính',result_text(row))
    def test_results_separate_controls_and_selected(self):
        a=self.row();a['result']=json.dumps(dict(win=0,net_return=-.002,reason='timeout'));self.insert(a)
        b=self.row();b.update(side='short',selected=1,result=json.dumps(dict(win=1,net_return=.003,reason='tp')));self.insert(b)
        view=snapshot(self.path,self.version)
        self.assertEqual(view['all']['win_rate'],.5)
        self.assertEqual(view['selected']['win_rate'],1)
        self.assertAlmostEqual(view['all']['brier'],(.2**2+.8**2)/2)
    def test_overdue_and_stale_health_visible(self):
        row=self.row();self.insert(row)
        now=row['signal_ms']/1000+4000
        self.db.execute('INSERT INTO health VALUES (1,?)',(json.dumps(dict(at=now-91)),));self.db.commit()
        text=status_text(snapshot(self.path,self.version,now))
        self.assertIn('mất cập nhật',text)
        self.assertIn('quá hạn',text)
    def test_forward_commands_never_open_or_propose(self):
        before=self.t.engine.snapshot()
        with patch.object(self.t,'send') as send,patch.object(self.t.engine,'propose') as propose,patch.object(self.t.engine,'approve') as approve:
            for cmd in ('/forward','/predict2','/results','/model2','/indicators'):self.t.command(cmd)
            self.assertEqual(send.call_count,5);propose.assert_not_called();approve.assert_not_called()
        self.assertEqual(before,self.t.engine.snapshot())
    def test_wrong_user_cannot_read_forward(self):
        with patch.object(self.t,'forward_command') as command:
            self.t.handle({'message':{'from':{'id':999},'chat':{'id':123},'text':'/forward'}})
            command.assert_not_called()
    def test_notification_retry_does_not_lose_cursor(self):
        self.event(self.row())
        with patch.object(self.t,'send',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):self.t.poll_forward()
        self.assertEqual(self.t.engine.snapshot().get('forward_event_cursor',0),0)
        with patch.object(self.t,'send') as send:
            self.t.poll_forward();self.t.poll_forward();send.assert_called_once()
        self.assertEqual(self.t.engine.snapshot()['forward_event_cursor'],1)
    def test_late_settlement_event_not_skipped(self):
        self.insert(self.row())
        self.event(self.row())
        with patch.object(self.t,'send') as send:
            self.t.poll_forward()
            row=self.row();row['result']=json.dumps(dict(win=0,net_return=-.002,reason='timeout'))
            self.event(row,2,'result')
            self.t.poll_forward()
            self.assertEqual(send.call_count,2)
            self.assertIn('KẾT QUẢ',send.call_args.args[0])
    def test_pause_skips_alerts_and_retains_observations(self):
        row=self.row();self.insert(row);self.event(row)
        self.t.engine.pause(True)
        with patch.object(self.t,'send') as send:
            self.t.poll_forward();self.t.engine.pause(False);self.t.poll_forward()
            send.assert_not_called()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0],1)
    def test_one_direction_and_one_x_with_valid_short_levels(self):
        long=self.row();short=dict(long,side='short',expected_return=-.001)
        text=forecast_text([long,short])
        self.assertIn('ƯU TIÊN SHORT',text)
        self.assertNotIn('ƯU TIÊN LONG',text)
        self.assertIn('1x (cố định)',text)
        self.assertIn('SL: 77300.00',text)
        self.assertIn('TP: 76400.00',text)
        self.assertIn('Chưa đạt bộ lọc',text)
    def test_preference_cannot_be_changed_by_realized_outcome(self):
        long=self.row();short=dict(long,side='short',expected_return=-.001)
        self.assertEqual(preferred([long,short])['side'],'short')
        long['result']=json.dumps({'win':1});short['result']=json.dumps({'win':0})
        self.assertEqual(preferred([short,long])['side'],'short')
    def test_eligible_direction_has_priority_over_unqualified_edge(self):
        long=dict(self.row(),selected=1,expected_return=.001,p_win=.6)
        short=dict(self.row(),side='short',expected_return=.005,p_win=.3)
        self.assertEqual(preferred([long,short])['side'],'long')
    def test_preferred_stats_count_one_direction_per_bar(self):
        long=self.row();long['result']=json.dumps(dict(win=1,net_return=.001,reason='timeout'));self.insert(long)
        short=dict(long,side='short',expected_return=-.001,result=json.dumps(dict(win=0,net_return=-.003,reason='sl')));self.insert(short)
        view=snapshot(self.path,self.version)
        self.assertEqual(view['preferred']['count'],1)
        self.assertEqual(view['preferred']['win_rate'],0)
        self.assertEqual(view['all']['win_rate'],.5)
        self.assertEqual(view['recent_results'][0]['side'],'short')
    def test_opposite_result_not_sent_but_cursor_advances(self):
        long=self.row();short=dict(long,side='short',expected_return=-.001)
        self.insert(long);self.insert(short)
        long['result']=json.dumps(dict(win=1,net_return=.001,reason='tp'))
        self.event(long,1,'result')
        with patch.object(self.t,'send') as send:
            self.t.poll_forward();send.assert_not_called()
        self.assertEqual(self.t.engine.snapshot()['forward_event_cursor'],1)
    def test_indicator_snapshot_is_frozen_and_visible(self):
        row=self.row();self.insert(row)
        ta=dict(rsi14=.55,adx14=.23,macd_hist_pct=.0001)
        self.db.execute('CREATE TABLE feature_snapshots (model_hash TEXT,signal_ms INTEGER,body TEXT)')
        self.db.execute('INSERT INTO feature_snapshots VALUES (?,?,?)',(self.version,row['signal_ms'],json.dumps(ta)));self.db.commit()
        view=snapshot(self.path,self.version)
        text=forecast_text(view['latest'])
        self.assertIn('V3 CHỈ BÁO',text)
        self.assertIn('RSI14 55.0',text)
        self.assertIn('ADX14 23.0',text)
        with patch.object(self.t,'send') as send:
            self.t.command('/indicators')
            self.assertIn('chưa tốt hơn V2',send.call_args.args[0])
