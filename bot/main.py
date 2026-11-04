"""Telegram polling + public Bitget prices. Paper orders only."""
import json
import os
import time
import urllib.request
from decimal import Decimal
from .core import Engine


def request(url, body=None, timeout=15):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json', 'User-Agent':'PaperBot/0.1'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ticker():
    data = request('https://api.bitget.com/api/v2/mix/market/ticker?symbol=BTCUSDT&productType=USDT-FUTURES')
    if data.get('code') != '00000':
        raise ValueError('Bitget từ chối dữ liệu')
    row = data['data'][0]
    return row['lastPr'], int(row['ts'])/1000


class Telegram:
    def __init__(self):
        if os.getenv('TRADING_MODE', 'paper') != 'paper':
            raise SystemExit('Live mode chưa được triển khai; từ chối khởi động.')
        self.token = os.environ['TELEGRAM_BOT_TOKEN']
        self.user = int(os.environ['TELEGRAM_USER_ID'])
        self.chat = int(os.environ['TELEGRAM_CHAT_ID'])
        self.engine = Engine(os.getenv('DB_PATH','paper.db'))
        self.predictor = None
        self.next_model_check = 0
        self.next_forward_check = 0

    def forward_command(self,cmd):
        if not os.getenv('FORWARD_DB') or not os.getenv('MODEL_DIR'):
            self.send('Chưa cấu hình forward test V2. Không có lệnh nào được gửi lên sàn.')
            return
        try:
            from research.forward_view import snapshot,model_hash,status_text,forecast_text,result_text
            indicator_mode=cmd=='/indicators'
            if indicator_mode and not os.getenv('INDICATOR_DB'):
                self.send('Chưa cấu hình thử nghiệm chỉ báo. Mô hình mặc định giữ nguyên.')
                return
            version=model_hash(os.environ['MODEL_DIR'],'v3' if indicator_mode else 'v2')
            view=snapshot(os.environ['INDICATOR_DB'] if indicator_mode else os.environ['FORWARD_DB'],version)
            if indicator_mode:
                self.send('V3 thử nghiệm: RSI, MACD, Bollinger Bands, ADX/DI, Stochastic, OBV, VWAP20, MFI.\n'
                    'So sánh lịch sử chưa tốt hơn V2; chỉ quan sát song song.\n'+forecast_text(view['latest']))
            elif cmd=='/predict2':
                self.send(forecast_text(view['latest']))
            elif cmd=='/results':
                rows=view['recent_results']
                self.send('\n\n'.join(result_text(r) for r in rows) if rows else
                    'V2: chưa có kết quả hoàn tất. Mỗi dự báo được chấm sau thời hạn 1 giờ; mẫu thiếu dữ liệu sẽ chờ bổ sung.')
            elif cmd=='/model2':
                from pathlib import Path
                report=json.loads((Path(os.environ['MODEL_DIR'])/'v2'/'report.json').read_text())
                self.send(f"V2 · {report['candidate']} | Chỉ quan sát\n"
                    'Dự đoán khả năng lời ròng sau SL/TP, phí, slippage, funding và độ trễ 1 phút.\n'
                    'Kết quả lịch sử chỉ là thăm dò, chưa chứng minh lợi thế giao dịch.\n'
                    '/predict2: dự báo đã ghi\n/forward: thống kê tương lai\n/results: kết quả mới nhất\nKhông đặt lệnh.')
            else:
                self.send(status_text(view))
        except (OSError,ValueError,KeyError) as e:
            self.send('V2 chưa đọc được dữ liệu quan sát. Thử lại /forward sau ít phút; không có lệnh nào được tạo.')
        except Exception:
            self.send('V2 tạm chưa sẵn sàng. Không có lệnh nào được tạo.')

    def poll_forward(self):
        if not os.getenv('FORWARD_DB') or not os.getenv('MODEL_DIR'):
            return
        from research.forward_view import snapshot,model_hash,events,forecast_text,result_text,preferred_at
        version=model_hash(os.environ['MODEL_DIR'])
        state=self.engine.snapshot()
        if state['paused']:
            view=snapshot(os.environ['FORWARD_DB'],version)
            with self.engine.tx() as s:s['forward_event_cursor']=view['max_event_id']
            return
        cursor=state.get('forward_event_cursor',0)
        for event in events(os.environ['FORWARD_DB'],version,cursor):
            body=json.loads(event['body'])
            if event['kind']=='result':
                choice=preferred_at(os.environ['FORWARD_DB'],version,event['signal_ms'])
                if not choice or choice['side']!=body['side']:
                    with self.engine.tx() as s:s['forward_event_cursor']=event['id']
                    continue
            text=forecast_text(body) if event['kind']=='forecast' else result_text(body)
            self.send(text)
            # A failed send leaves the event pending. Delivery is at least once.
            with self.engine.tx() as s:s['forward_event_cursor']=event['id']

    def model_forecast(self, automatic=False):
        if not os.getenv('MODEL_DIR'):
            if not automatic:
                self.send('Chưa cấu hình mô hình M15. Bot vẫn ở PAPER.')
            return
        if self.predictor is None:
            from research.predict import Predictor
            self.predictor = Predictor(os.environ['MODEL_DIR'])
        forecast=self.predictor.forecast()
        with self.engine.tx() as state:
            if automatic and state.get('model_last_bar') == forecast['bar_ms']:
                return
            state['model_last_bar']=forecast['bar_ms']
            self.engine.audit('model_forecast',forecast)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        closed=datetime.fromtimestamp((forecast['bar_ms']+900000)/1000,ZoneInfo('Asia/Ho_Chi_Minh'))
        side=forecast['side']
        text=(f"M15 PAPER | {forecast['model']}\nNến đóng: {closed:%d/%m %H:%M}\n"
              f"Hướng trong 1 giờ: {side}\nTrạng thái: {forecast['decision']}\n")
        if forecast['probabilities'] is not None:
            probs=forecast['probabilities']
            text+=f"Điểm mô hình: tăng {probs.get('1',0):.1%}, giảm {probs.get('-1',0):.1%}, trung tính {probs.get('0',0):.1%}\nChưa hiệu chỉnh xác suất; không phải tỷ lệ thắng.\n"
        buttons=None
        state=self.engine.snapshot()
        can_propose=(forecast['paper_proposals_enabled'] and side in ('long','short')
            and not state['paused'] and not state['halted'] and not state['position']
            and not any(time.time()<sig['expires'] for sig in state['signals'].values())
            and 0 <= time.time()-(forecast['bar_ms']+900000)/1000 <= 60)
        if can_propose:
            price,ts=ticker()
            self.engine.tick(price,ts)
            price=Decimal(price)
            distance=max(Decimal(str(forecast['atr']))*Decimal('1.5'),price*Decimal('.003'))
            direction=1 if side=='long' else -1
            key,sig=self.engine.propose(side,price,price-direction*distance,price+direction*2*distance,
                exit_at=(forecast['bar_ms']+5*900000)/1000,source=forecast['model'])
            text+=f"Entry: {price}\nSL: {sig['stop']} | TP: {sig['target']}\nQty: {sig['qty']}\nDuyệt PAPER trong 60 giây; tối đa 1 giờ từ lúc nến tín hiệu đóng."
            buttons=[[{'text':'Duyệt mô phỏng','callback_data':'ok:'+key},{'text':'Bỏ qua','callback_data':'no:'+key}]]
        else:
            text+='Chỉ quan sát; không tạo lệnh từ dự báo này.'
        self.send(text,buttons)

    def model_status(self):
        if not os.getenv('MODEL_DIR'):
            self.send('Chưa cấu hình mô hình M15. PAPER ONLY.')
            return
        from pathlib import Path
        report=json.loads((Path(os.environ['MODEL_DIR'])/'report.json').read_text())
        h=report['holdout']
        self.send(f"M15 PAPER | Ứng viên: {report['candidate']}\nTrạng thái: {report['decision']}\n"
                  f"Holdout: {h['return_pct']:.2f}% | Drawdown: {h['max_drawdown_pct']:.2f}% | Lệnh: {h['trades']}\n"
                  'Backtest OHLC sau phí/slippage giả định, chưa tính funding/độ trễ duyệt. /predict để xem dự báo. /pause dừng tín hiệu mới.')

    def api(self, method, **body):
        result = request('https://api.telegram.org/bot'+self.token+'/'+method,body,35)
        if not result.get('ok'):
            raise ValueError('Telegram API từ chối yêu cầu')
        return result['result']

    def send(self, text, buttons=None):
        body = dict(chat_id=self.chat,text=text)
        if buttons:
            body['reply_markup']={'inline_keyboard':buttons}
        self.api('sendMessage',**body)

    def command(self, text):
        args = text.split()
        if not args:
            self.send('Lệnh không hợp lệ. Dùng /help')
            return
        cmd = args[0].split('@')[0]
        if cmd in ('/forward','/predict2','/results','/model2','/indicators'):
            self.forward_command(cmd)
        elif cmd == '/predict':
            self.model_forecast()
        elif cmd == '/model':
            self.model_status()
        elif cmd in ('/start','/help'):
            self.send('PAPER / QUAN SÁT — Không đặt lệnh thật.\n/forward — thống kê forward test V2\n/predict2 — dự báo V2 đã ghi\n/results — kết quả V2 mới nhất\n/model2 — mô hình giao dịch V2\n/indicators — thử nghiệm chỉ báo V3\n/von 50\n/nap 200 — nạp giả lập\n/rut 20 — rút giả lập\n/status\n/pnl\n/model — nghiên cứu V1\n/predict — dự báo V1\n/pause — ngừng thông báo; V2 tiếp tục ghi dữ liệu\n/resume\n/demo long — tạo tín hiệu KIỂM THỬ paper thủ công\n/demo short\nSố dư mô phỏng ban đầu: 100 USDT.')
        elif cmd == '/von' and len(args)==2:
            self.engine.set_budget(args[1]); self.send('Đã đổi ngân sách mô phỏng: '+args[1]+' USDT')
        elif cmd in ('/nap','/rut') and len(args)==2:
            amount = Decimal(args[1])
            if not amount.is_finite() or amount<=0:
                raise ValueError('Số tiền phải dương')
            self.engine.cashflow(amount if cmd=='/nap' else -amount)
            self.send('Đã ghi nhận nạp/rút MÔ PHỎNG. Dùng /von để chọn ngân sách mới.')
        elif cmd in ('/status','/pnl'):
            s = self.engine.snapshot()
            eq = self.engine.equity(s)
            self.send(f"PAPER | Equity: {eq:.4f} USDT\nNgân sách: {s['budget']}\nPnL ngày (theo giá gần nhất): {eq-Decimal(s['baseline']):.4f}\nNgày: {s['day']}\nPaused: {s['paused']} | Halted: {s['halted']}\nVị thế: {s['position']}\nGiá cập nhật: {s['last_tick']}\nPhí/slippage là giả định, chưa tính funding.")
        elif cmd in ('/pause','/resume'):
            self.engine.pause(cmd=='/pause'); self.send('Đã cập nhật pause; không gỡ khóa lỗ ngày.')
        elif cmd=='/demo' and len(args)==2:
            price, ts = ticker()
            self.engine.tick(price,ts)
            p = Decimal(price)
            side=args[1]
            stop = p*Decimal('0.99' if side=='long' else '1.01')
            target = p*Decimal('1.02' if side=='long' else '0.98')
            key,sig = self.engine.propose(side,p,stop,target)
            self.send(f"TÍN HIỆU KIỂM THỬ — PAPER, không phải khuyến nghị\nBTCUSDT {side}\nEntry tham chiếu: {p}\nSL: {stop}\nTP: {target}\nQty dự kiến: {sig['qty']}\nNgân sách lỗ gồm dự phòng chi phí: {sig['loss']} USDT\nHết hạn sau 60 giây. Khối lượng tính lại khi duyệt.",[[{'text':'Duyệt mô phỏng','callback_data':'ok:'+key},{'text':'Bỏ qua','callback_data':'no:'+key}]])
        else:
            self.send('Lệnh không hợp lệ. Dùng /help')

    def handle(self, update):
        q = update.get('callback_query')
        if q:
            if q.get('from',{}).get('id')!=self.user or q.get('message',{}).get('chat',{}).get('id')!=self.chat:
                self.api('answerCallbackQuery',callback_query_id=q['id'],text='Không được phép'); return
            self.api('answerCallbackQuery',callback_query_id=q['id'],text='Đang kiểm tra')
            action, separator, key = q.get('data','').partition(':')
            if not separator or not key or action not in ('ok', 'no'):
                raise ValueError('Nút bấm không hợp lệ')
            if action=='ok':
                price,ts = ticker()
                self.engine.tick(price,ts)
                self.engine.approve(key,price,ts)
                self.send('Đã mở vị thế MÔ PHỎNG. Không gửi lệnh lên sàn.')
            elif action=='no':
                self.engine.reject(key); self.send('Đã bỏ qua')
        else:
            m=update.get('message',{})
            if m.get('from',{}).get('id')==self.user and m.get('chat',{}).get('id')==self.chat and m.get('text'):
                self.command(m['text'])

    def run(self):
        self.send('Bot PAPER khởi động. /help để xem lệnh. Không có chức năng đặt lệnh thật.')
        while True:
            try:
                before = self.engine.snapshot()
                try:
                    p,ts=ticker(); self.engine.tick(p,ts)
                    after=self.engine.snapshot()
                    if before['position'] and not after['position']:
                        self.send('Vị thế PAPER đã đóng do SL/TP, hết thời gian giữ lệnh hoặc ngưỡng lỗ ngày. /status')
                    if not before['halted'] and after['halted']:
                        self.send('Đã chạm giới hạn lỗ ngày — khóa lệnh mới.')
                except Exception:
                    # No new entries without a fresh successful quote. Do not log token-bearing URLs.
                    print('Market data unavailable; paper protection cannot update.',flush=True)
                if os.getenv('FORWARD_DB') and time.time() >= self.next_forward_check:
                    self.next_forward_check=time.time()+15
                    try:
                        self.poll_forward()
                    except Exception:
                        print('Forward notification unavailable; pending events retained.',flush=True)
                if os.getenv('MODEL_DIR') and not os.getenv('FORWARD_DB') and time.time() >= self.next_model_check:
                    self.next_model_check=time.time()+30
                    try:
                        # Skip network work when this closed bar was already evaluated.
                        bar=(int(time.time())//900-1)*900000
                        state=self.engine.snapshot()
                        if state.get('model_last_bar') != bar and not state['paused']:
                            self.model_forecast(automatic=True)
                    except Exception:
                        print('M15 forecast unavailable; no model proposal created.',flush=True)
                updates=self.api('getUpdates',offset=self.engine.offset(),timeout=2,allowed_updates=['message','callback_query'])
                for update in updates:
                    try:
                        self.handle(update)
                    except (ValueError, ArithmeticError, KeyError):
                        self.send('Không thực hiện được: tín hiệu/giá/cấu hình không hợp lệ hoặc bot đang khóa. /status')
                    self.engine.offset(update['update_id']+1)
            except Exception:
                print('Transport error; retrying without exposing credentials.',flush=True)
                time.sleep(3)


def main():
    if os.getenv('TRADING_MODE','paper') != 'paper':
        raise SystemExit('Live mode chưa được triển khai; từ chối khởi động.')
    Telegram().run()

if __name__=='__main__':
    main()
