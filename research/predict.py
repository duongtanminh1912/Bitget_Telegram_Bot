"""Forecast from trusted local artifacts; never place orders here."""
import hashlib
import json
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from .data import STEP, FIELDS, fetch_page, normalize
from .features import FEATURES, features
from .train import decisions

class Predictor:
    def __init__(self, directory):
        directory=Path(directory)
        self.report=json.loads((directory/'report.json').read_text())
        self.bundle=joblib.load(directory/'model.joblib') # trusted, locally trained files only
        digest=hashlib.sha256((directory/'report.json').read_bytes()).hexdigest()
        if self.bundle['report_sha256'] != digest or self.bundle['features'] != FEATURES:
            raise ValueError('Model/report mismatch')

    def forecast(self, now=None):
        now=time.time() if now is None else now
        if not 0 <= now*1000-self.bundle['data_through_ms'] <= 14*86400*1000:
            raise ValueError('Model older than 14 days; retrain before forecasting')
        rows=normalize(fetch_page(int(now*1000),recent=True,attempts=1,timeout=8),int(now*1000))
        if len(rows)<150 or any(b[0]-a[0]!=STEP for a,b in zip(rows,rows[1:])):
            raise ValueError('Missing recent M15 candles')
        expected=int(now*1000)//STEP*STEP-STEP
        if rows[-1][0]!=expected:
            raise ValueError('Latest closed M15 candle unavailable')
        frame=features(pd.DataFrame(rows,columns=FIELDS))
        last=frame.iloc[[-1]]
        if last[FEATURES].isna().any().any():
            raise ValueError('Feature warmup incomplete')
        model=self.bundle['model']
        selected=decisions(model,last)
        side=next(iter(selected.values()))[0] if selected else 'flat'
        probability=None
        probabilities=None
        if model is not None:
            p=model.predict_proba(last[FEATURES])[0]
            probabilities={str(int(k)):float(v) for k,v in zip(model.classes_,p)}
            probability=float(max(p))
        return dict(model=self.bundle['name'],bar_ms=int(rows[-1][0]),side=side,
            close=float(last.close.iloc[0]),atr=float(last.atr.iloc[0]),probability=probability,
            probabilities=probabilities,paper_proposals_enabled=self.bundle['paper_proposals_enabled'],
            decision=self.report['decision'])

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('--artifacts',default='artifacts')
    args=p.parse_args(); print(json.dumps(Predictor(args.artifacts).forecast(),indent=2))
