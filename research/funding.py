"""Fetch realized public funding history; never use future rates as features."""
import csv
import json
import math
from pathlib import Path
from .microdata import get_json

def collect(directory='data',days=84):
    directory=Path(directory)
    with (directory/'BTCUSDT_15m.csv').open() as f: times=[int(r['timestamp']) for r in csv.DictReader(f)]
    end=times[-1]+900000
    start=max(times[0],end-days*86400000)
    rates={}
    for page in range(1,101):
        rows=get_json('history-fund-rate',dict(symbol='BTCUSDT',productType='USDT-FUTURES',pageSize=100,pageNo=page))
        if not rows: break
        previous=len(rates)
        for row in rows:
            ts=int(row['fundingTime']); rate=float(row['fundingRate'])
            if not math.isfinite(rate) or abs(rate)>1: raise ValueError('Invalid funding rate')
            if ts in rates and rates[ts]!=rate: raise ValueError('Conflicting funding history')
            rates[ts]=rate
        if len(rates)==previous: raise ValueError('Funding pagination did not progress')
        print('Funding page:',page,'records:',len(rates),flush=True)
        if min(rates)<=start: break
    ts=sorted(rates)
    if not ts or ts[0]>start or end-ts[-1]>8*3600_000 or any(b-a>8*3600_000 for a,b in zip(ts,ts[1:])):
        raise ValueError('Funding does not cover study or gap exceeds 8h; no zero-fill permitted')
    path=directory/'BTCUSDT_funding.csv'
    with path.open('w') as f:
        writer=csv.writer(f); writer.writerow(['timestamp','rate'])
        writer.writerows((t,rates[t]) for t in ts if start-8*3600_000<=t<=end)
    print('Funding saved',len(ts),flush=True)

if __name__=='__main__': collect()
