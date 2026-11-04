"""Single-position, risk-sized OHLC simulation through the paper Engine."""
import math
import numpy as np
from bot.core import Engine, number
from .features import HORIZON

def simulate(candles, decisions, start, end, cost_multiplier=1):
    now=[float(candles.iloc[start].timestamp)/1000]
    e=Engine(':memory:',lambda:now[0])
    with e.tx() as s:
        s['fee']=str(.0006*cost_multiplier)
        s['slip']=str(.0005*cost_multiplier)
    entry_bar=None
    curve=[100.]
    trades=[]
    last_cash=100.
    last_event=0
    for i in range(start,end):
        row=candles.iloc[i]
        now[0]=float(row.timestamp)/1000
        had_position=bool(e.snapshot()['position'])
        e.tick(str(row.open),now[0]) # gaps fill at actual opening price
        s=e.snapshot()
        decision=decisions.get(i-1)
        if not had_position and not s['position'] and decision and not s['halted']:
            side,atr=decision
            p=float(row.open)
            distance=max(1.5*atr,.003*p)
            direction=1 if side=='long' else -1
            try:
                key,_=e.propose(side,str(p),str(p-direction*distance),str(p+direction*2*distance))
                e.approve(key,str(p),now[0])
                entry_bar=i
            except (ValueError,ArithmeticError):
                pass
        s=e.snapshot()
        p=s['position']
        if p:
            stop,target=float(p['stop']),float(p['target'])
            # If both touched in one candle, stop first. Never assume profitable ordering.
            stop_hit=row.low<=stop if p['side']=='long' else row.high>=stop
            target_hit=row.high>=target if p['side']=='long' else row.low<=target
            if stop_hit: e.tick(str(stop),now[0])
            elif target_hit: e.tick(str(target),now[0])
        e.tick(str(row.close),now[0])
        if e.snapshot()['position'] and (i>=entry_bar+HORIZON-1 or i==end-1):
            with e.tx() as state: e.close(state,str(row.close),'horizon')
        s=e.snapshot()
        cash=float(s['cash'])
        # Read realized close events (cash also changes on entry due to fees).
        events=e.db.execute("SELECT rowid FROM audit WHERE event='paper_close' AND rowid>?",(last_event,)).fetchall()
        for event in events:
            # Include opening fee by measuring change against preceding flat cash.
            trades.append(cash-last_cash)
            last_cash=cash
            last_event=event[0]
        curve.append(float(e.equity(s)))
    values=np.asarray(curve)
    drawdown=1-values/np.maximum.accumulate(values)
    wins=sum(x for x in trades if x>0)
    losses=-sum(x for x in trades if x<0)
    result=dict(return_pct=(values[-1]/100-1)*100,max_drawdown_pct=float(drawdown.max()*100),
                trades=len(trades),win_rate=sum(x>0 for x in trades)/len(trades) if trades else 0,
                profit_factor=wins/losses if losses else None,final_equity=float(values[-1]),
                cost_multiplier=cost_multiplier)
    e.db.close()
    return result
