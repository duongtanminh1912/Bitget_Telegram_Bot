"""Prospective observational forecasts. No Telegram, exchange keys, orders or paper wallet access."""
import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
import joblib
import pandas as pd
from .data import FIELDS,STEP,fetch_page,normalize
from .features import FEATURES,features
from .trade_labels import TRADE_FEATURES,outcome
from .microdata import MINUTE,get_json,validate


def inputs(row):
    from .feature_sets import inputs as versioned_inputs
    return versioned_inputs(row)

class Shadow:
    def __init__(self,artifact='artifacts/v2',db='data/shadow/forward.db'):
        model_path=Path(artifact)/'model.joblib'
        self.hash=hashlib.sha256(model_path.read_bytes()).hexdigest()
        self.bundle=joblib.load(model_path)
        from .feature_sets import columns
        self.feature_mode=self.bundle.get('feature_mode','base')
        if self.bundle['paper_proposals_enabled'] or self.bundle['features']!=columns(self.feature_mode):
            raise ValueError('Shadow accepts observation-only trade models')
        Path(db).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(db)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS forecasts (model_hash TEXT, signal_ms INTEGER, side TEXT, predicted_at REAL, p_win REAL, expected_return REAL, reference REAL, atr REAL, horizon INTEGER, selected INTEGER, result TEXT, PRIMARY KEY(model_hash,signal_ms,side))')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, model_hash TEXT, signal_ms INTEGER, side TEXT, body TEXT, created_at REAL, UNIQUE(kind,model_hash,signal_ms,side))')
        self.db.execute('CREATE TABLE IF NOT EXISTS health (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS feature_snapshots (model_hash TEXT,signal_ms INTEGER,body TEXT,PRIMARY KEY(model_hash,signal_ms))')
        # Populate notifications for predictions already recorded before this schema upgrade.
        for version,signal in self.db.execute('SELECT DISTINCT model_hash,signal_ms FROM forecasts').fetchall():
            self.forecast_event(version,signal)
        for row in self.db.execute('SELECT * FROM forecasts WHERE result IS NOT NULL').fetchall():
            self.event('result',row['model_hash'],row['signal_ms'],row['side'],dict(row))
        self.db.commit()
        self.record_status='starting'
    def event(self,kind,version,signal,side,body):
        self.db.execute('INSERT OR IGNORE INTO events (kind,model_hash,signal_ms,side,body,created_at) VALUES (?,?,?,?,?,?)',
            (kind,version,signal,side,json.dumps(body,allow_nan=False),time.time()))
    def forecast_event(self,version,signal):
        rows=[dict(r) for r in self.db.execute('SELECT * FROM forecasts WHERE model_hash=? AND signal_ms=? ORDER BY side',(version,signal))]
        extra=self.db.execute('SELECT body FROM feature_snapshots WHERE model_hash=? AND signal_ms=?',(version,signal)).fetchone()
        if extra:
            for r in rows:r['indicators']=json.loads(extra[0])
        self.event('forecast',version,signal,'pair',rows)
    def heartbeat(self,record_error=None,settle_error=None):
        body=dict(at=time.time(),model_hash=self.hash,record_status=self.record_status,
            record_error=record_error,settle_error=settle_error)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO health VALUES (1,?)',(json.dumps(body),))
    def record(self,rows,now=None):
        now=time.time() if now is None else now
        now_ms=int(now*1000)
        if not 0 <= now_ms-self.bundle['data_through_ms'] <=14*86400000:
            raise ValueError('Stale model')
        candles=normalize(rows,now_ms)
        minimum=200 if self.feature_mode=='indicators' else 150
        if len(candles)<minimum or any(b[0]-a[0]!=STEP for a,b in zip(candles,candles[1:])):
            raise ValueError('Incomplete forecast candles')
        signal=candles[-1][0]+STEP
        # Never backdate a prediction into the already-observed study or approval window.
        if signal<=self.bundle['report']['last_ms']+MINUTE:
            self.record_status='previously_observed_history'
            return 0
        if not 0<=now_ms-signal<MINUTE:
            self.record_status='waiting_next_close'
            return 0
        if candles[-1][0]!=(now_ms//STEP-1)*STEP:raise ValueError('Stale M15 candle')
        from .feature_sets import frame_features,inputs as versioned_inputs
        f=frame_features(pd.DataFrame(candles,columns=FIELDS),self.feature_mode).iloc[-1]
        x=versioned_inputs(f,self.feature_mode)
        if x[self.bundle['features']].isna().any().any():raise ValueError('Incomplete features')
        probs,expected=self.bundle['model'].predict(x)
        # At most one selected direction; both observations are scored as controls.
        chosen=None
        eligible=[i for i in range(2) if probs[i]>=.55 and expected[i]>=.0003]
        if eligible:chosen=max(eligible,key=lambda i:expected[i])
        before=self.db.total_changes
        for i,side in enumerate(('long','short')):
            self.db.execute('INSERT OR IGNORE INTO forecasts VALUES (?,?,?,?,?,?,?,?,?,?,NULL)',
                (self.hash,signal,side,now,float(probs[i]),float(expected[i]),float(f.close),float(f.atr),
                 self.bundle['report']['parameters']['horizon_minutes'],int(i==chosen)))
        inserted=self.db.total_changes-before
        if inserted and self.feature_mode=='indicators':
            from .indicators import INDICATORS
            self.db.execute('INSERT OR IGNORE INTO feature_snapshots VALUES (?,?,?)',
                (self.hash,signal,json.dumps({k:float(f[k]) for k in INDICATORS},allow_nan=False)))
        if inserted:self.forecast_event(self.hash,signal)
        self.db.commit()
        self.record_status='recorded' if inserted else 'already_recorded'
        return inserted
    def settle(self,now=None):
        now=time.time() if now is None else now
        pending=self.db.execute('SELECT model_hash,signal_ms,side,reference,atr,horizon FROM forecasts WHERE result IS NULL AND signal_ms+horizon*60000<=?',(int(now*1000),)).fetchall()
        if not pending:return 0
        funds=get_json('history-fund-rate',dict(symbol='BTCUSDT',productType='USDT-FUTURES',pageSize=100,pageNo=1))
        funding=sorted((int(r['fundingTime']),float(r['fundingRate'])) for r in funds)
        count=0
        for model,signal,side,reference,atr,horizon in pending:
            start=signal+MINUTE;end=signal+horizon*MINUTE
            if not funding or funding[0][0]>start or end-funding[-1][0]>8*3600000:
                raise ValueError('Incomplete forward funding coverage')
            cursor=end;rows=[]
            while cursor>start:
                page=get_json('history-candles',dict(symbol='BTCUSDT',productType='USDT-FUTURES',granularity='1m',endTime=cursor,limit=200))
                if not page:raise ValueError('Missing forward M1 candles')
                oldest=min(int(r[0]) for r in page)
                if oldest>=cursor:raise ValueError('Forward pagination did not progress')
                rows.extend(page);cursor=oldest
            path=validate(rows,start,end)
            import numpy as np
            result=outcome(np.array(path,dtype=float),reference,atr,side,funding)
            if result is None:result={'rejected':'approval_price_drift'}
            self.db.execute('UPDATE forecasts SET result=? WHERE model_hash=? AND signal_ms=? AND side=? AND result IS NULL',
                (json.dumps(result,allow_nan=False),model,signal,side))
            row=self.db.execute('SELECT * FROM forecasts WHERE model_hash=? AND signal_ms=? AND side=?',(model,signal,side)).fetchone()
            self.event('result',model,signal,side,dict(row))
            self.db.commit();count+=1
        return count
    def summary(self):
        rows=self.db.execute('SELECT selected,result FROM forecasts WHERE model_hash=?',(self.hash,)).fetchall()
        resolved=[json.loads(r) for _,r in rows if r]
        executed=[r for r in resolved if 'win' in r]
        picked=[json.loads(r) for selected,r in rows if selected and r and 'win' in json.loads(r)]
        return dict(model_hash=self.hash,forecasts=len(rows),resolved=len(resolved),selected=sum(s for s,_ in rows),
            selected_resolved=len(picked),selected_win_rate=sum(r['win'] for r in picked)/len(picked) if picked else None,
            control_resolved=len(executed),note='Overlapping hypothetical outcomes, not a portfolio or real trades')

def main():
    p=argparse.ArgumentParser();p.add_argument('--artifacts',default='artifacts/v2');p.add_argument('--db',default='data/shadow/forward.db');p.add_argument('--once',action='store_true')
    args=p.parse_args();s=Shadow(args.artifacts,args.db)
    while True:
        record_error=settle_error=None
        try:
            s.record(fetch_page(int(time.time()*1000),recent=True,attempts=1,timeout=8,limit=300 if s.feature_mode=='indicators' else 200))
        except Exception as e:
            record_error=type(e).__name__
            print('Shadow record unavailable:',record_error,flush=True)
        try:
            s.settle()
        except Exception as e:
            settle_error=type(e).__name__
            print('Shadow settlement unavailable:',settle_error,flush=True)
        s.heartbeat(record_error,settle_error)
        print(json.dumps(s.summary()),flush=True)
        if args.once:break
        time.sleep(15)

if __name__=='__main__':main()
