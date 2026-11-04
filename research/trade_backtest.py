"""Replay selected signals through paper Engine, using M1 SL/TP and actual funding."""
import json
import math
import numpy as np
from decimal import Decimal
from bot.core import Engine,number
from .microdata import MINUTE

def wilson(wins,total):
    if total==0:return None
    z=1.96;p=wins/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den
    radius=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [max(0,center-radius),min(1,center+radius)]

def replay(candidates,m1,funding,multiplier=1):
    raw=m1.to_numpy(dtype=float); start=int(raw[0,0])
    rates={int(row.timestamp):float(row.rate) for row in funding.itertuples()}
    now=[start/1000]
    e=Engine(':memory:',lambda:now[0])
    with e.tx() as s:s.update(fee=str(.0006*multiplier),slip=str(.0005*multiplier))
    last_exit=-1; trades=[]; curve=[100.]; times=[start]; rejects=0
    for row in candidates.itertuples():
        if row.entry_ms<=last_exit:continue
        cash_before=float(e.snapshot()['cash'])
        now[0]=row.entry_ms/1000
        k=(int(row.entry_ms)-start)//MINUTE
        reference=Decimal(str(row.entry_reference))
        # Label entry_reference is executable price; proposed reference remains signal close.
        proposal=Decimal(str(row.signal_reference))
        e.tick(str(raw[k,1]),now[0])
        try:
            key,_=e.propose(row.side_name,proposal,str(row.stop),str(row.target))
            e.approve(key,str(raw[k,1]),now[0])
        except (ValueError,ArithmeticError):
            rejects+=1;continue
        charged=set()
        while e.snapshot()['position']:
            bar=raw[k]; ts,o,h,l,c,*_=bar;now[0]=ts/1000
            if int(ts) in rates and ts>row.entry_ms and int(ts) not in charged:
                with e.tx() as s:
                    s['position']['mark']=str(o)
                    e.roll_day(s)
                    p=s['position'];direction=1 if p['side']=='long' else -1
                    fee=number(p['qty'])*number(raw[k-1,4])*number(rates[int(ts)])*direction*multiplier
                    s['cash']=str(number(s['cash'])-fee)
                    e.audit('paper_funding',str(fee))
                charged.add(int(ts))
            e.tick(str(o),now[0])
            s=e.snapshot();p=s['position']
            if p:
                direction=1 if p['side']=='long' else -1
                stop=number(p['stop']);target=number(p['target'])
                threshold=number(s['baseline'])*(1-number(s['daily']))
                daily=number(p['entry'])+(threshold-number(s['cash']))/number(p['qty'])*direction
                barrier=max(stop,daily) if direction==1 else min(stop,daily)
                adverse=number(l)<=barrier if direction==1 else number(h)>=barrier
                profit=number(h)>=target if direction==1 else number(l)<=target
                if adverse:
                    if barrier==daily:
                        with e.tx() as state:
                            e.close(state,str(barrier),'daily_limit');state['halted']=True;state['signals']={}
                    else:e.tick(str(stop),now[0])
                elif profit:e.tick(str(target),now[0])
            now[0]=(ts+MINUTE)/1000
            # Funding at a boundary belongs to the existing position before an expiry close.
            boundary=int(ts)+MINUTE
            if boundary in rates and boundary not in charged and e.snapshot()['position']:
                with e.tx() as s:
                    s['position']['mark']=str(c);e.roll_day(s)
                    p=s['position'];d=1 if p['side']=='long' else -1
                    fee=number(p['qty'])*number(c)*number(rates[boundary])*d*multiplier
                    s['cash']=str(number(s['cash'])-fee)
                    e.audit('paper_funding',str(fee))
                charged.add(boundary)
            e.tick(str(c),now[0])
            deadline=getattr(row,'exit_limit_ms',row.signal_close_ms+3600000)
            if boundary>=deadline and e.snapshot()['position']:
                with e.tx() as s:e.close(s,str(c),'horizon')
                e.tick(str(c),now[0])
            snap=e.snapshot();curve.append(float(e.equity(snap)));times.append(boundary)
            if not snap['position']:
                last_exit=boundary
                close=json.loads(e.db.execute("SELECT body FROM audit WHERE event='paper_close' ORDER BY rowid DESC LIMIT 1").fetchone()[0])
                trades.append(dict(entry_ms=int(row.entry_ms),exit_ms=boundary,side=row.side_name,
                    pnl=float(snap['cash'])-cash_before,reason=close['reason'],p_win=float(row.p_win),
                    expected_net_return=float(row.expected_net_return)))
                break
            k+=1
    e.db.close()
    values=np.array(curve);dd=1-values/np.maximum.accumulate(values)
    winners=[t['pnl'] for t in trades if t['pnl']>0];losers=[t['pnl'] for t in trades if t['pnl']<0]
    result=dict(trades=len(trades),wins=len(winners),win_rate=len(winners)/len(trades) if trades else None,
        win_rate_wilson_95=wilson(len(winners),len(trades)),return_pct=(values[-1]/100-1)*100,
        profit_factor=sum(winners)/-sum(losers) if losers else None,
        max_drawdown_pct=float(dd.max()*100),final_equity=float(values[-1]),
        avg_trade_pnl=float(np.mean([t['pnl'] for t in trades])) if trades else None,
        rejected=rejects,cost_multiplier=multiplier)
    return result,trades
