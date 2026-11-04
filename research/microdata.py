"""Download public M1 candles matching the frozen M15 study. Cached, resumable pages."""
import concurrent.futures
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path
from .data import FIELDS, save

MINUTE=60000

def get_json(endpoint,params):
    url='https://api.bitget.com/api/v2/mix/market/'+endpoint+'?'+urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url,timeout=25) as r:
                result=json.load(r)
            if result.get('code')!='00000': raise ValueError('Bitget response '+str(result.get('code')))
            return result['data']
        except Exception:
            if attempt==4: raise
            time.sleep(2**attempt)

def validate(rows,start,end):
    result={}
    for row in rows:
        t=int(row[0]); values=list(map(float,row[1:7]))
        if len(values)!=6 or t%MINUTE or not all(math.isfinite(v) for v in values): raise ValueError('Invalid M1 row')
        o,h,l,c,v,q=values
        if min(o,h,l,c)<=0 or min(v,q)<0 or not l<=min(o,c)<=max(o,c)<=h: raise ValueError('Invalid M1 OHLC')
        if start<=t<end:
            if t in result and result[t]!=[t]+values: raise ValueError('Conflicting M1 duplicate')
            result[t]=[t]+values
    rows=[result[t] for t in sorted(result)]
    if len(rows)!=(end-start)//MINUTE or any(r[0]!=start+i*MINUTE for i,r in enumerate(rows)):
        raise ValueError('Incomplete M1 data')
    return rows

def collect(directory='data', days=84):
    directory=Path(directory)
    with (directory/'BTCUSDT_15m.csv').open() as f:
        anchors=[int(r['timestamp']) for r in csv.DictReader(f)]
    if days<=0: raise ValueError('days must be positive')
    end=anchors[-1]+900000
    start=max(anchors[0],end-days*86400000)
    cache=directory/'m1_pages'; cache.mkdir(exist_ok=True)
    ends=list(range(end,start,-200*MINUTE))
    def page(stop):
        path=cache/(str(stop)+'.json')
        begin=max(start,stop-200*MINUTE)
        if path.exists(): rows=json.loads(path.read_text())
        else:
            rows=get_json('history-candles',dict(symbol='BTCUSDT',productType='USDT-FUTURES',granularity='1m',endTime=stop,limit=200))
            # Validate each page before marking it cached.
            rows=validate(rows,begin,stop)
            tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(rows)); tmp.replace(path)
            time.sleep(.3)
        return validate(rows,begin,stop)
    pages=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(page,stop):stop for stop in ends}
        for i,future in enumerate(concurrent.futures.as_completed(futures),1):
            pages.extend(future.result())
            if i%50==0 or i==len(ends): print('M1 pages:',i,'/',len(ends),flush=True)
    rows=validate(pages,start,end)
    save(directory/'BTCUSDT_1m.csv',rows)
    meta=dict(count=len(rows),start_ms=start,end_exclusive_ms=end,interval='1m',complete=True)
    (directory/'BTCUSDT_1m.csv.json').write_text(json.dumps(meta,indent=2))
    print(json.dumps(meta),flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--days',type=int,default=84)
    collect(days=parser.parse_args().days)
