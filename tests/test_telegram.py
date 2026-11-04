import os
import unittest
from unittest.mock import patch
from bot.main import Telegram, main
from bot.core import Engine

class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,dict(TELEGRAM_BOT_TOKEN='dummy',TELEGRAM_USER_ID='123',TELEGRAM_CHAT_ID='123',DB_PATH=':memory:'))
        self.env.start(); self.t=Telegram()
    def tearDown(self):
        self.t.engine.db.close(); self.env.stop()
    def test_wrong_user_no_command(self):
        with patch.object(self.t,'command') as command:
            self.t.handle({'message':{'from':{'id':999},'chat':{'id':123},'text':'/von 50'}})
            command.assert_not_called()
    def test_wrong_chat_no_approval(self):
        with patch.object(self.t,'api'), patch.object(self.t.engine,'approve') as approve:
            self.t.handle({'callback_query':{'id':'a','from':{'id':123},'message':{'chat':{'id':999}},'data':'ok:fake'}})
            approve.assert_not_called()
    def test_authorized_command(self):
        with patch.object(self.t,'send'):
            self.t.handle({'message':{'from':{'id':123},'chat':{'id':123},'text':'/von 50'}})
        self.assertEqual(self.t.engine.snapshot()['budget'],'50')
    def test_blank_command(self):
        with patch.object(self.t,'send') as send:
            self.t.command('   ')
            send.assert_called_once_with('Lệnh không hợp lệ. Dùng /help')
    def test_malformed_callback(self):
        for data in ('', 'ok', 'ok:', 'unknown:key'):
            with self.subTest(data=data), patch.object(self.t,'api'), patch('bot.main.ticker') as ticker:
                with self.assertRaises(ValueError):
                    self.t.handle({'callback_query':{'id':'a','from':{'id':123},'message':{'chat':{'id':123}},'data':data}})
                ticker.assert_not_called()
        self.assertIsNone(self.t.engine.snapshot()['position'])
    def test_live_mode_refused(self):
        with patch.dict(os.environ, TRADING_MODE='live'), patch.object(Telegram,'run') as run:
            with self.assertRaises(SystemExit): main()
            with self.assertRaises(SystemExit): Telegram()
            run.assert_not_called()
    def test_offline_telegram_flow(self):
        self.t.engine.clock=lambda:1793667600.0
        with patch.object(self.t,'api',return_value=True) as api, patch('bot.main.ticker',return_value=('100',1793667600.0)):
            self.t.command('/nap 200')
            self.t.command('/von 250')
            self.t.command('/demo long')
            key=next(iter(self.t.engine.snapshot()['signals']))
            self.t.handle({'callback_query':{'id':'a','from':{'id':123},'message':{'chat':{'id':123}},'data':'ok:'+key}})
            self.assertIsNotNone(self.t.engine.snapshot()['position'])
            self.t.command('/pause')
            self.t.engine.tick('102',1793667600.0)
            self.t.command('/status')
            self.assertIsNone(self.t.engine.snapshot()['position'])
            self.assertGreater(float(self.t.engine.snapshot()['cash']),300)
            self.assertTrue(self.t.engine.snapshot()['paused'])
            self.assertTrue(all(call.args[0] in ('sendMessage','answerCallbackQuery') for call in api.call_args_list))
    def test_cashflow_preserves_pnl_and_halt(self):
        with self.t.engine.tx() as s:
            s.update(day='2026-11-03',baseline='100',cash='84',halted=True)
        self.t.engine.clock=lambda:1793667600
        self.t.engine.cashflow(200)
        s=self.t.engine.snapshot()
        self.assertEqual(s['cash'],'284')
        self.assertEqual(s['baseline'],'300')
        self.assertTrue(s['halted'])
        self.t.engine.set_budget(250)
        self.assertEqual(self.t.engine.snapshot()['budget'],'250')

    def forecast(self, enabled=False):
        return dict(model='lightgbm',bar_ms=1793666700000,side='long',atr=1,
            probability=.6,probabilities={'1':.6,'-1':.2,'0':.2},
            paper_proposals_enabled=enabled,decision='paper_candidate' if enabled else 'observe_only')

    def test_observe_only_never_proposes(self):
        from unittest.mock import Mock
        self.t.predictor=Mock()
        self.t.predictor.forecast.return_value=self.forecast()
        with patch.dict(os.environ,MODEL_DIR='unused'), patch.object(self.t,'send') as send, patch('bot.main.ticker') as ticker:
            self.t.model_forecast()
            ticker.assert_not_called()
            self.assertIsNone(send.call_args.args[1])
        self.assertFalse(self.t.engine.snapshot()['signals'])

    def test_model_bar_deduplicated_across_restart(self):
        from unittest.mock import Mock
        self.t.predictor=Mock()
        self.t.predictor.forecast.return_value=self.forecast()
        with patch.dict(os.environ,MODEL_DIR='unused'), patch.object(self.t,'send') as send:
            self.t.model_forecast(automatic=True)
            self.t.model_forecast(automatic=True)
            send.assert_called_once()
        self.assertEqual(self.t.engine.snapshot()['model_last_bar'],1793666700000)

    def test_model_paper_proposal_requires_approval(self):
        from unittest.mock import Mock
        self.t.engine.clock=lambda:1793667600.
        self.t.predictor=Mock()
        self.t.predictor.forecast.return_value=self.forecast(True)
        with patch.dict(os.environ,MODEL_DIR='unused'), patch.object(self.t,'send'), patch('bot.main.time.time',return_value=1793667600.), patch('bot.main.ticker',return_value=('100',1793667600.)):
            self.t.model_forecast()
        state=self.t.engine.snapshot()
        self.assertIsNone(state['position'])
        self.assertEqual(len(state['signals']),1)
        self.assertEqual(next(iter(state['signals'].values()))['exit_at'],1793671200.)

    def test_pause_and_halt_block_model_proposals(self):
        from unittest.mock import Mock
        self.t.predictor=Mock()
        self.t.predictor.forecast.return_value=self.forecast(True)
        for field in ('paused','halted'):
            with self.subTest(field=field):
                with self.t.engine.tx() as state: state[field]=True
                with patch.dict(os.environ,MODEL_DIR='unused'), patch.object(self.t,'send'), patch('bot.main.time.time',return_value=1793667600.), patch('bot.main.ticker') as ticker:
                    self.t.model_forecast()
                    ticker.assert_not_called()
                with self.t.engine.tx() as state: state[field]=False
