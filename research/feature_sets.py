"""Versioned feature schemas shared by training and real-time observation."""
import pandas as pd
from .features import FEATURES,features
from .trade_labels import TRADE_FEATURES


def columns(mode='base'):
    if mode=='base':return list(TRADE_FEATURES)
    if mode=='indicators':
        from .indicators import INDICATORS,SIGNED
        return list(TRADE_FEATURES)+INDICATORS+SIGNED
    raise ValueError('Unknown feature mode')

def frame_features(frame,mode='base'):
    if mode=='base':return features(frame)
    if mode=='indicators':
        from .indicators import indicator_features
        return indicator_features(frame)
    raise ValueError('Unknown feature mode')

def side_input(row,side,mode='base'):
    x={k:float(row[k]) for k in FEATURES};x['side']=side
    for name in ('ret1','ret4','ret16','ema_gap','h1_gap'):x['signed_'+name]=side*x[name]
    if mode=='indicators':
        from .indicators import INDICATORS
        x.update({k:float(row[k]) for k in INDICATORS})
        x.update(signed_rsi14=side*(x['rsi14']-.5),signed_macd_pct=side*x['macd_pct'],
            signed_macd_hist_pct=side*x['macd_hist_pct'],signed_bb_position=side*(x['bb_position']-.5),
            signed_di_gap=side*(x['plus_di14']-x['minus_di14']),signed_stoch_k=side*(x['stoch_k']-.5),
            signed_obv_flow20=side*x['obv_flow20'],signed_vwap_gap20=side*x['vwap_gap20'])
    elif mode!='base':raise ValueError('Unknown feature mode')
    return x

def inputs(row,mode='base'):
    return pd.DataFrame([side_input(row,s,mode) for s in (1,-1)])
