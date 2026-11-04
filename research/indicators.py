"""Standard TA-Lib indicators, recomputed on a fixed 200-bar closed window.
The fixed window makes historical and live features numerically identical.
"""
import numpy as np
import pandas as pd
import talib
from .features import features

WINDOW=200
INDICATORS=['rsi14','macd_pct','macd_signal_pct','macd_hist_pct','bb_position','bb_width',
            'adx14','plus_di14','minus_di14','stoch_k','stoch_d','obv_flow20','vwap_gap20','mfi14']
SIGNED=['signed_rsi14','signed_macd_pct','signed_macd_hist_pct','signed_bb_position',
        'signed_di_gap','signed_stoch_k','signed_obv_flow20','signed_vwap_gap20']

def last_values(window):
    if len(window)!=WINDOW:raise ValueError('Indicators require exactly 200 closed candles')
    h,l,c,v=(np.ascontiguousarray(window[k],dtype=np.float64) for k in ('high','low','close','volume'))
    macd,signal,hist=talib.MACD(c,fastperiod=12,slowperiod=26,signalperiod=9)
    upper,middle,lower=talib.BBANDS(c,timeperiod=20,nbdevup=2,nbdevdn=2,matype=0)
    k,d=talib.STOCH(h,l,c,fastk_period=14,slowk_period=3,slowk_matype=0,slowd_period=3,slowd_matype=0)
    obv=talib.OBV(c,v)
    volume=v[-20:].sum()
    vwap=np.sum((h[-20:]+l[-20:]+c[-20:])/3*v[-20:])/volume if volume else c[-1]
    width=upper[-1]-lower[-1]
    return dict(rsi14=talib.RSI(c,timeperiod=14)[-1]/100,
        macd_pct=macd[-1]/c[-1],macd_signal_pct=signal[-1]/c[-1],macd_hist_pct=hist[-1]/c[-1],
        bb_position=(c[-1]-lower[-1])/width if width>1e-10 else .5,
        bb_width=width/middle[-1],adx14=talib.ADX(h,l,c,timeperiod=14)[-1]/100,
        plus_di14=talib.PLUS_DI(h,l,c,timeperiod=14)[-1]/100,
        minus_di14=talib.MINUS_DI(h,l,c,timeperiod=14)[-1]/100,
        stoch_k=k[-1]/100,stoch_d=d[-1]/100,
        obv_flow20=(obv[-1]-obv[-21])/volume if volume else 0,
        vwap_gap20=c[-1]/vwap-1,mfi14=talib.MFI(h,l,c,v,timeperiod=14)[-1]/100)

def indicator_features(frame):
    f=features(frame)
    values=np.full((len(f),len(INDICATORS)),np.nan)
    for i in range(WINDOW-1,len(frame)):
        result=last_values(frame.iloc[i-WINDOW+1:i+1])
        values[i]=[result[k] for k in INDICATORS]
    for i,k in enumerate(INDICATORS):f[k]=values[:,i]
    return f.replace([np.inf,-np.inf],np.nan)
