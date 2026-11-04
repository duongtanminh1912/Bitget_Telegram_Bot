"""Deterministic paper engine. No authenticated exchange endpoints exist here."""
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

D = Decimal

def number(value):
    n = D(str(value))
    if not n.is_finite():
        raise ValueError('Số phải hữu hạn')
    return n

class Engine:
    def __init__(self, path='paper.db', clock=time.time):
        self.clock = clock
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS audit (at REAL, event TEXT, body TEXT)')
        initial = dict(cash='100', budget='100', baseline='100', day='', halted=False,
                       paused=False, position=None, signals={}, offset=0, last_tick=0,
                       risk='0.005', daily='0.15', fee='0.0006', slip='0.0005')
        self.db.execute('INSERT OR IGNORE INTO state VALUES (1, ?)', (json.dumps(initial),))

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            s = json.loads(self.db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
            yield s
            self.db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(s),))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def audit(self, event, body):
        self.db.execute('INSERT INTO audit VALUES (?, ?, ?)', (self.clock(), event, json.dumps(body)))

    def snapshot(self):
        with self.tx() as s:
            return json.loads(json.dumps(s))

    def equity(self, s, price=None):
        eq = number(s['cash'])
        p = s['position']
        if p:
            mark = number(price if price is not None else p['mark'])
            eq += (mark-number(p['entry'])) * number(p['qty']) * (1 if p['side']=='long' else -1)
        return eq

    def roll_day(self, s):
        day = datetime.fromtimestamp(self.clock(), ZoneInfo('Asia/Ho_Chi_Minh')).date().isoformat()
        if s['day'] != day:
            s.update(day=day, baseline=str(self.equity(s)), halted=False)
            s['signals'] = {}

    def set_budget(self, amount):
        amount = number(amount)
        with self.tx() as s:
            self.roll_day(s)
            if s['position']:
                raise ValueError('Đóng vị thế trước khi đổi vốn')
            if not 0 < amount <= number(s['cash']):
                raise ValueError('Ngân sách phải > 0 và không vượt số dư mô phỏng')
            # Budget changes never reset daily baseline or halt.
            s['budget'] = str(amount)
            s['signals'] = {}
            self.audit('budget', str(amount))

    def cashflow(self, amount):
        """Paper-only deposit/withdrawal. Cashflows do not alter daily trading PnL."""
        amount = number(amount)
        with self.tx() as s:
            self.roll_day(s)
            if s['position'] or amount == 0:
                raise ValueError('Đóng vị thế trước khi nạp/rút mô phỏng')
            cash = number(s['cash'])+amount
            baseline = number(s['baseline'])+amount
            if cash <= 0 or baseline <= 0:
                raise ValueError('Số dư sau nạp/rút phải dương')
            # Adjust denominator for daily threshold but preserve existing halt and absolute PnL.
            s['cash'], s['baseline'] = str(cash), str(baseline)
            s['budget'] = str(min(number(s['budget']), cash))
            s['signals'] = {}
            self.audit('paper_cashflow', str(amount))

    def pause(self, value):
        with self.tx() as s:
            s['paused'] = value
            if value:
                s['signals'] = {}

    def size(self, s, entry, stop):
        risk = min(number(s['budget']), self.equity(s)) * number(s['risk'])
        # Round-trip fee + slippage reserve. Linear USDT simulation, 1x cap.
        cost = abs(entry-stop) + (entry+stop)*(number(s['fee'])+number(s['slip']))
        qty = min(risk/cost, min(number(s['budget']), number(s['cash'])) / (entry*(1+number(s['fee']))))
        qty = qty.quantize(D('0.000001'), rounding=ROUND_DOWN)
        if qty <= 0:
            raise ValueError('Vốn quá nhỏ')
        return qty, qty*cost

    def propose(self, side, entry, stop, target, exit_at=None, source=None):
        entry, stop, target = map(number, (entry, stop, target))
        if side not in ('long','short') or min(entry,stop,target)<=0:
            raise ValueError('Tín hiệu không hợp lệ')
        if not (stop<entry<target if side=='long' else target<entry<stop):
            raise ValueError('Sai thứ tự SL / entry / TP')
        if exit_at is not None and not self.clock() < exit_at <= self.clock()+3600:
            raise ValueError('Thời hạn giữ lệnh không hợp lệ')
        import secrets
        with self.tx() as s:
            self.roll_day(s)
            if s['halted'] or s['paused'] or s['position']:
                raise ValueError('Bot đang dừng hoặc đã có vị thế')
            qty, loss = self.size(s, entry, stop)
            key = secrets.token_hex(6)
            signal = dict(side=side, entry=str(entry), stop=str(stop), target=str(target),
                          expires=self.clock()+60, qty=str(qty), loss=str(loss))
            if exit_at is not None:
                signal.update(exit_at=exit_at, source=source)
            s['signals'] = {key:signal}
            self.audit('proposal', signal)
            return key, signal

    def approve(self, key, price, timestamp):
        price = number(price)
        if price <= 0 or not 0 <= self.clock()-timestamp <= 10:
            raise ValueError('Giá cũ hoặc không hợp lệ')
        with self.tx() as s:
            if timestamp < s['last_tick']:
                raise ValueError('Dữ liệu đảo thứ tự')
            self.roll_day(s)
            sig = s['signals'].get(key)
            if not sig or self.clock()>=sig['expires']:
                raise ValueError('Tín hiệu hết hạn hoặc đã xử lý')
            if sig.get('exit_at') is not None and self.clock()>=sig['exit_at']:
                raise ValueError('Đã hết thời hạn giữ lệnh')
            if s['paused'] or s['halted'] or s['position']:
                raise ValueError('Không được mở vị thế')
            if abs(price/number(sig['entry'])-1)>D('0.001'):
                raise ValueError('Giá lệch quá 0,1%')
            direction = 1 if sig['side']=='long' else -1
            entry = price*(1+direction*number(s['slip']))
            stop, target = number(sig['stop']), number(sig['target'])
            if not (stop<entry<target if direction==1 else target<entry<stop):
                raise ValueError('Giá đã ra ngoài SL/TP')
            qty, loss = self.size(s,entry,stop)
            remaining = self.equity(s)-number(s['baseline'])*(1-number(s['daily']))
            if loss > remaining:
                raise ValueError('Không đủ ngân sách lỗ còn lại trong ngày')
            s['cash'] = str(number(s['cash'])-entry*qty*number(s['fee']))
            s['position'] = dict(side=sig['side'], entry=str(entry), mark=str(price),
                                 qty=str(qty), stop=sig['stop'], target=sig['target'])
            if sig.get('exit_at') is not None:
                s['position'].update(exit_at=sig['exit_at'],source=sig.get('source'))
            s['signals'] = {}
            s['last_tick'] = timestamp
            self.audit('paper_open', s['position'])
            return s['position']

    def close(self, s, price, reason):
        p = s['position']
        if not p:
            return
        direction = 1 if p['side']=='long' else -1
        fill = number(price)*(1-direction*number(s['slip']))
        qty = number(p['qty'])
        pnl = (fill-number(p['entry']))*qty*direction-fill*qty*number(s['fee'])
        s['cash'] = str(number(s['cash'])+pnl)
        s['position'] = None
        self.audit('paper_close', dict(reason=reason, pnl=str(pnl), fill=str(fill)))

    def tick(self, price, timestamp):
        price = number(price)
        if price <= 0 or not 0 <= self.clock()-timestamp <= 10:
            raise ValueError('Dữ liệu thị trường cũ')
        with self.tx() as s:
            if timestamp < s['last_tick']:
                raise ValueError('Dữ liệu đảo thứ tự')
            if s['position']:
                s['position']['mark'] = str(price)
            self.roll_day(s)
            s['last_tick'] = timestamp
            threshold = number(s['baseline'])*(1-number(s['daily']))
            if self.equity(s) <= threshold:
                s['halted'] = True
                s['signals'] = {}
                self.close(s, price, 'daily_limit')
            p = s['position']
            if p:
                hit = (price<=number(p['stop']) or price>=number(p['target'])) if p['side']=='long' else (price>=number(p['stop']) or price<=number(p['target']))
                if hit:
                    self.close(s,price,'stop_or_target')
            p=s['position']
            if p and p.get('exit_at') is not None and self.clock()>=p['exit_at']:
                self.close(s,price,'horizon')
            # Closing costs can themselves cross the daily threshold.
            if self.equity(s) <= threshold:
                s['halted'] = True
                s['signals'] = {}

    def reject(self, key):
        with self.tx() as s:
            s['signals'].pop(key, None)

    def offset(self, value=None):
        with self.tx() as s:
            if value is not None:
                s['offset'] = value
            return s['offset']
