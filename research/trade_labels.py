"""Executable M1 trade outcomes for each M15 decision, with explicit costs."""
import numpy as np
import pandas as pd
from .features import FEATURES, features
from .microdata import MINUTE, validate

FEE=.0006
SLIP=.0005
DELAY_MINUTES=1
HOLD_MINUTES=60
EXTRA=['side','signed_ret1','signed_ret4','signed_ret16','signed_ema_gap','signed_h1_gap']
TRADE_FEATURES=FEATURES+EXTRA

def outcome(path, reference, atr, side, funding, multiplier=1):
    """SL first when same minute touches both. One minute approval delay included."""
    if len(path)==0: raise ValueError('Empty execution path')
    direction=1 if side=='long' else -1
    stop_distance=max(1.5*atr,.003*reference)
    stop=reference-direction*stop_distance
    target=reference+direction*2*stop_distance
    entry_ref=float(path[0,1])
    entry=entry_ref*(1+direction*SLIP*multiplier)
    if abs(entry_ref/reference-1)>.001 or not (stop<entry<target if direction==1 else target<entry<stop):
        return None # matches paper price-drift rejection at approval
    exit_ref=float(path[-1,4]); exit_ms=int(path[-1,0])+MINUTE
    reason='timeout'; ambiguous=False
    for row in path:
        ts,o,h,l,c,*_=row
        # Existing position at open can gap through a barrier.
        if direction==1:
            gap=o<=stop or o>=target; sl=l<=stop; tp=h>=target
        else:
            gap=o>=stop or o<=target; sl=h>=stop; tp=l<=target
        if gap:
            exit_ref=float(o); exit_ms=int(ts); reason='sl' if (o<=stop if direction==1 else o>=stop) else 'tp'; break
        if sl or tp:
            ambiguous=bool(sl and tp)
            exit_ref=stop if sl else target
            exit_ms=int(ts)+MINUTE
            reason='sl' if sl else 'tp'; break
    fill=exit_ref*(1-direction*SLIP*multiplier)
    # Charge at settlement in (entry, exit], using previous minute close as mark proxy.
    fund=0.
    entry_ms=int(path[0,0])
    for ts,rate in funding:
        if entry_ms < ts < exit_ms or (ts==exit_ms and reason=='timeout'):
            i=max(0,min(len(path)-1,int((ts-entry_ms)//MINUTE)-1))
            fund+=direction*rate*float(path[i,4])*multiplier
    net_unit=(fill-entry)*direction-(entry+fill)*FEE*multiplier-fund
    reserve=abs(entry-stop)+(entry+stop)*(FEE+SLIP)*multiplier
    return dict(entry_ms=entry_ms,exit_ms=exit_ms,entry_reference=entry_ref,entry_fill=entry,
        exit_fill=fill,stop=stop,target=target,risk_per_unit=reserve,net_per_unit=net_unit,
        net_return=net_unit/entry_ref,win=int(net_unit>0),tp_first=int(reason=='tp'),
        reason=reason,ambiguous=ambiguous,funding_per_unit=fund,
        entry_fee_per_unit=entry*FEE*multiplier)

def build(m15,m1,funding,multiplier=1,horizon_minutes=60,feature_mode='base'):
    from .feature_sets import frame_features,side_input,columns
    raw=m1.to_numpy(dtype=float)
    start=int(raw[0,0]); end=int(raw[-1,0])+MINUTE
    if np.any(np.diff(raw[:,0])!=MINUTE): raise ValueError('M1 gap')
    # Verify M1 aggregation against M15, not just their timestamps.
    grouped=m1.assign(bucket=(m1.timestamp//900000)*900000).groupby('bucket').agg(
        open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),count=('close','count'))
    anchor=m15.set_index('timestamp')
    full=grouped[grouped['count']==15]
    common=full.index.intersection(anchor.index)
    if len(common)!=len(full) or not np.allclose(full.loc[common,['open','high','low','close']],anchor.loc[common,['open','high','low','close']],rtol=1e-9,atol=1e-6):
        raise ValueError('M1/M15 OHLC mismatch')
    cols=columns(feature_mode)
    f=frame_features(m15,feature_mode)
    f=f.dropna(subset=[k for k in cols if k in f.columns])
    rows=[]
    fund=funding[['timestamp','rate']].to_numpy()
    if len(fund)==0 or fund[0,0]>start or end-fund[-1,0]>8*3600000 or np.any(np.diff(fund[:,0])>8*3600000):
        raise ValueError('Funding coverage incomplete')
    for idx,row in f.iterrows():
        signal_close=int(row.timestamp)+900000
        entry_ms=signal_close+DELAY_MINUTES*MINUTE
        exit_end=signal_close+horizon_minutes*MINUTE
        if signal_close<start or exit_end>end: continue
        a=(entry_ms-start)//MINUTE; b=(exit_end-start)//MINUTE
        path=raw[a:b]
        relevant=fund[(fund[:,0]>entry_ms)&(fund[:,0]<=exit_end)]
        for side in ('long','short'):
            trade=outcome(path,float(row.close),float(row.atr),side,relevant,multiplier)
            if trade is None: continue
            sign=1 if side=='long' else -1
            x=side_input(row,sign,feature_mode)
            rows.append(dict(x,decision_idx=int(idx),signal_close_ms=signal_close,exit_limit_ms=exit_end,signal_reference=float(row.close),side_name=side,atr=float(row.atr),**trade))
    return pd.DataFrame(rows)
