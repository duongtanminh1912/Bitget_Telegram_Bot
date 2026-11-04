"""Causal features, with H1 bars available only after their closing time."""
import numpy as np
import pandas as pd
from .data import STEP, normalize

HORIZON = 4
FEATURES = ['ret1','ret4','ret16','ret96','atr_pct','range_pct','body_pct',
            'volume_ratio','volatility','ema_gap','ema_slope','h1_gap','hour_sin','hour_cos']

def load(path):
    frame=pd.read_csv(path)
    rows=normalize(frame.values.tolist(),2**63-1)
    if len(rows)!=len(frame) or len(rows)<1000:
        raise ValueError('Need >= 1000 unique candles')
    frame=pd.DataFrame(rows,columns=frame.columns)
    if not frame.timestamp.diff().dropna().eq(STEP).all():
        raise ValueError('History contains gaps')
    return frame

def features(frame):
    f=frame.copy()
    c=f.close
    for lag in (1,4,16,96): f[f'ret{lag}']=c.pct_change(lag)
    tr=pd.concat([f.high-f.low,(f.high-c.shift()).abs(),(f.low-c.shift()).abs()],axis=1).max(axis=1)
    f['atr']=tr.rolling(14,min_periods=14).mean()
    f['atr_pct']=f.atr/c
    f['range_pct']=(f.high-f.low)/c
    f['body_pct']=(c-f.open)/f.open
    f['volume_ratio']=f.volume/f.volume.rolling(20).mean().replace(0,np.nan)
    f['volatility']=f.ret1.rolling(20).std()
    # Finite windows make historical and live (last 200 bars) features identical.
    def ema(span):
        weights=(1-2/(span+1))**np.arange(95,-1,-1)
        weights=weights/weights.sum()
        return c.rolling(96).apply(lambda values:np.dot(values,weights),raw=True)
    fast=ema(12)
    slow=ema(48)
    f['ema_gap']=fast/slow-1
    f['ema_slope']=slow/slow.shift(4)-1
    close_times=pd.to_datetime(f.timestamp+STEP,unit='ms',utc=True)
    hourly=pd.Series(c.to_numpy(),index=close_times).resample('1h',closed='right',label='right').agg(['last','count'])
    hourly=hourly[hourly['count']==4]['last']
    hgap=hourly/hourly.rolling(24,min_periods=24).mean()-1
    f['h1_gap']=hgap.reindex(pd.DatetimeIndex(close_times),method='ffill').to_numpy()
    hour=close_times.dt.hour+close_times.dt.minute/60
    f['hour_sin']=np.sin(hour*2*np.pi/24)
    f['hour_cos']=np.cos(hour*2*np.pi/24)
    return f.replace([np.inf,-np.inf],np.nan)

def dataset(frame):
    f=features(frame)
    # Decision after close t; executable entry at open t+1; exit close t+4.
    f['future_return']=f.close.shift(-HORIZON)/f.open.shift(-1)-1
    band=np.maximum(.0027,.5*f.atr_pct)
    f['label']=np.where(f.future_return>band,1,np.where(f.future_return < -band,-1,0))
    return f.dropna(subset=FEATURES+['future_return']).copy()
