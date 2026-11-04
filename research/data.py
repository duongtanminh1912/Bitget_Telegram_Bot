"""Collect closed BTCUSDT USDT futures candles using public Bitget REST."""
import argparse
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

STEP = 900_000
FIELDS = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'quote_volume']

def normalize(rows, now_ms):
    candles = {}
    for row in rows:
        ts = int(row[0])
        values = list(map(float, row[1:7]))
        if ts % STEP or len(values) != 6 or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid candle')
        o, h, l, c, v, q = values
        if min(o, h, l, c) <= 0 or min(v, q) < 0 or not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('Invalid OHLCV')
        if ts + STEP <= now_ms:
            candle = [ts] + values
            if ts in candles and candles[ts] != candle:
                raise ValueError('Conflicting duplicate candle')
            candles[ts] = candle
    return [candles[k] for k in sorted(candles)]

def fetch_page(end_ms, recent=False, attempts=5, timeout=25,limit=200):
    query = urllib.parse.urlencode(dict(symbol='BTCUSDT', productType='USDT-FUTURES',
                                       granularity='15m', endTime=int(end_ms), limit=limit))
    endpoint = 'candles' if recent else 'history-candles'
    url = 'https://api.bitget.com/api/v2/mix/market/' + endpoint + '?' + query
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'PaperBot-Research/0.2'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                result = json.load(r)
            if result.get('code') != '00000':
                raise ValueError('Bitget: ' + str(result.get('code')))
            return result['data']
        except Exception:
            if attempt == attempts-1:
                raise
            time.sleep(2 ** attempt)

def save(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    tmp.replace(path)

def collect(path, days=365):
    if days <= 0:
        raise ValueError('days must be positive')
    now = int(time.time()*1000)
    start = (now // STEP - days*96) * STEP
    rows = []
    if Path(path).exists():
        with open(path) as f:
            rows = normalize(([r[k] for k in FIELDS] for r in csv.DictReader(f)), now)
    cursor = now
    # Always page backwards: cached pages avoid rewriting history but do not mask gaps.
    while cursor > start:
        page = normalize(fetch_page(cursor), now)
        if not page:
            break
        oldest = page[0][0]
        if oldest >= cursor:
            raise ValueError('Pagination did not progress')
        rows = normalize(rows + page, now)
        save(path, rows)
        # Bitget endTime is exclusive; subtracting 1ms can skip a whole bar
        # after the exchange rounds to the M15 boundary.
        cursor = oldest
        print('Candles:',len(rows),'earliest:',oldest,flush=True)
        time.sleep(.12)
    rows = [r for r in rows if r[0] >= start]
    save(path, rows)
    gaps = sum(b[0]-a[0] != STEP for a,b in zip(rows, rows[1:]))
    complete = bool(rows) and rows[0][0] == start and rows[-1][0] == now//STEP*STEP-STEP and not gaps
    manifest = dict(symbol='BTCUSDT',product_type='USDT-FUTURES',interval='15m',
                    requested_days=days, retrieved_at_ms=now, count=len(rows), gaps=gaps,
                    complete=complete, first_ms=rows[0][0] if rows else None,
                    last_ms=rows[-1][0] if rows else None)
    Path(str(path)+'.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest),flush=True)
    if not complete:
        raise ValueError('Incomplete history; do not train on silently truncated data')

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--days',type=int,default=365)
    p.add_argument('--output',default='data/BTCUSDT_15m.csv')
    args=p.parse_args()
    collect(args.output,args.days)
