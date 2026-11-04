"""Read-only forward-test views and Telegram text. No ML or order functions."""
import hashlib
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def stamp(ms):
    return datetime.fromtimestamp(ms/1000,ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%d/%m %H:%M')

def connect(path):
    # mode=ro prevents accidentally creating a new empty ledger on a wrong path.
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)

def model_hash(directory,subdir='v2'):
    return hashlib.sha256((Path(directory)/subdir/'model.joblib').read_bytes()).hexdigest()

def preferred(rows):
    """Choose only from frozen pre-outcome scores. Never inspect realized results."""
    if not rows:return None
    eligible=[r for r in rows if r['selected']]
    return max(eligible or rows,key=lambda r:(r['expected_return'],r['p_win'],r['side']))

def snapshot(path,version,now=None):
    now=time.time() if now is None else now
    db=connect(path)
    try:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT rowid,* FROM forecasts WHERE model_hash=? ORDER BY signal_ms,side',(version,))]
        try:
            technical={r[0]:json.loads(r[1]) for r in db.execute('SELECT signal_ms,body FROM feature_snapshots WHERE model_hash=?',(version,))}
            for r in rows:
                if r['signal_ms'] in technical:r['indicators']=technical[r['signal_ms']]
        except sqlite3.OperationalError:pass
        try:
            healthrow=db.execute("SELECT body FROM health WHERE id=1").fetchone()
            health=json.loads(healthrow[0]) if healthrow else None
        except sqlite3.OperationalError:health=None
        try:max_event=db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
        except sqlite3.OperationalError:max_event=0
    finally:db.close()
    latest=[r for r in rows if r['signal_ms']==rows[-1]['signal_ms']] if rows else []
    pairs={}
    for r in rows:pairs.setdefault(r['signal_ms'],[]).append(r)
    choices=[preferred(pair) for pair in pairs.values()]
    def group(candidates):
        resolved=[(r,json.loads(r['result'])) for r in candidates if r['result']]
        usable=[(r,out) for r,out in resolved if 'win' in out]
        wins=sum(out['win'] for _,out in usable)
        return dict(count=len(candidates),resolved=len(resolved),scored=len(usable),wins=wins,
            rejected=sum('rejected' in out for _,out in resolved),
            win_rate=wins/len(usable) if usable else None,
            mean_net_return=sum(out['net_return'] for _,out in usable)/len(usable) if usable else None,
            brier=sum((r['p_win']-out['win'])**2 for r,out in usable)/len(usable) if usable else None)
    return dict(version=version,health=health,health_stale=not health or now-health['at']>90,
        health_mismatch=bool(health and health.get('model_hash',version)!=version),
        latest=latest,recent_results=[r for r in choices if r['result']][-4:],
        all=group(rows),selected=group([r for r in rows if r['selected']]),preferred=group(choices),max_event_id=max_event,
        overdue=sum(not r['result'] and now*1000>r['signal_ms']+r['horizon']*60000+120000 for r in rows))

def events(path,version,after=0,limit=6):
    db=connect(path)
    try:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM events WHERE id>? AND model_hash=? ORDER BY id LIMIT ?',
                    (after,version,limit))]
    finally:db.close()

def preferred_at(path,version,signal_ms):
    db=connect(path)
    try:
        db.row_factory=sqlite3.Row
        return preferred([dict(r) for r in db.execute('SELECT * FROM forecasts WHERE model_hash=? AND signal_ms=?',(version,signal_ms))])
    finally:db.close()

def forecast_text(rows):
    if not rows:return 'QUAN SÁT M15\nĐang chờ nến M15 đóng tiếp theo. Chưa có dự báo được ghi trước diễn biến giá.'
    r=preferred(rows)
    direction=1 if r['side']=='long' else -1
    distance=max(1.5*r['atr'],.003*r['reference'])
    stop=r['reference']-direction*distance;target=r['reference']+direction*2*distance
    lines=[f"BTCUSDT · M15 · ƯU TIÊN {r['side'].upper()}",
        f"Nến tín hiệu: {stamp(r['signal_ms'])} (giờ Việt Nam)",
        f"Giá tham chiếu: {r['reference']:.2f}",
        'Đòn bẩy giả lập: 1x (cố định)',f"SL: {stop:.2f}",f"TP: {target:.2f}",
        f"Kết thúc chậm nhất: {stamp(r['signal_ms']+r['horizon']*60000)}",
        f"P(lời ròng) ước lượng: {r['p_win']:.1%}",
        f"Lợi suất ròng dự kiến: {r['expected_return']:.3%}",
        'Đạt bộ lọc nghiên cứu.' if r['selected'] else 'Chưa đạt bộ lọc; hướng ưu tiên chỉ để kiểm chứng.',
        'CHỈ QUAN SÁT — không đặt lệnh. Giá tham chiếu thuộc nến tín hiệu, không phải giá vào hiện tại.']
    if r.get('indicators'):
        ta=r['indicators']
        lines.insert(1,'V3 CHỈ BÁO · thử nghiệm song song, chưa thay mô hình mặc định')
        lines.insert(-1,f"RSI14 {ta['rsi14']*100:.1f} | ADX14 {ta['adx14']*100:.1f} | MACD hist {ta['macd_hist_pct']:.4%}")
    return '\n'.join(lines)

def result_text(row):
    out=json.loads(row['result']) if isinstance(row['result'],str) else row['result']
    text=f"V2 · KẾT QUẢ {row['side'].upper()}\nTín hiệu: {stamp(row['signal_ms'])}\n"
    if 'rejected' in out:
        return text+'Loại mẫu: giá lúc vào giả định lệch quá 0,1%. Không tính vào tỷ lệ thắng.'
    reason={'tp':'chạm TP','sl':'chạm SL','timeout':'hết thời hạn'}.get(out['reason'],out['reason'])
    text+=f"{'LỜI' if out['win'] else 'KHÔNG LỜI'} sau chi phí: {out['net_return']:.3%}\nKết thúc: {reason}\n"
    text+=('Tín hiệu đạt bộ lọc nghiên cứu.' if row['selected'] else 'Hướng ưu tiên để kiểm chứng; chưa đạt bộ lọc.')
    return text+'\nKết quả giả định trên giá thị trường; không có giao dịch trên sàn.'

def status_text(view):
    health=view['health']
    status='chưa có heartbeat' if not health else ('mất cập nhật >90 giây' if view['health_stale'] else 'đang chạy')
    if view.get('health_mismatch'):status='đang dùng model khác — cần restart dịch vụ V2'
    lines=['V2 · FORWARD TEST',f"Dịch vụ: {status}",f"Phiên bản: {view['version'][:10]}"]
    if health and (health.get('record_error') or health.get('settle_error')):
        lines.append('Có lỗi dữ liệu/kết nối; chỉ chấm khi dữ liệu đầy đủ.')
    for key,title in (('preferred','Hướng ưu tiên (một hướng mỗi nến)'),('selected','Tín hiệu đạt bộ lọc'),('all','Toàn bộ long/short đối chứng')):
        g=view[key];rate='chưa đủ mẫu' if g['win_rate'] is None else f"{g['win_rate']:.1%} ({g['wins']}/{g['scored']})"
        lines += [title+':',f"Đã ghi {g['count']} | Đã chấm {g['scored']} | Bị loại {g['rejected']}",f"Tỷ lệ có lời ròng: {rate}"]
        if g['mean_net_return'] is not None:lines.append(f"Lợi suất ròng TB mỗi mẫu: {g['mean_net_return']:.3%}")
    if view['overdue']:lines.append(f"Mẫu quá hạn chưa chấm: {view['overdue']}")
    lines.append('Đây không phải PnL danh mục hay tỷ lệ dự đoán hướng. Các mẫu có thể chồng lấn; chưa kết luận từ vài mẫu.')
    return '\n'.join(lines)
