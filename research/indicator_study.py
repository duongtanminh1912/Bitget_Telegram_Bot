"""Matched, fixed-parameter indicator ablation; historical results remain exploratory."""
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss,log_loss
from sklearn.model_selection import TimeSeriesSplit
from .features import load
from .trade_labels import build
from .feature_sets import columns,frame_features,side_input
from .improve import fit
from .trade_backtest import replay


def choices(model,part,qualified_only=False):
    p,edge=model.predict(part)
    scored=part.copy();scored['p_win']=p;scored['expected_net_return']=edge
    scored['eligible']=(scored.p_win>=.55)&(scored.expected_net_return>=.0003)
    if qualified_only:scored=scored[scored.eligible]
    return scored.sort_values(['eligible','expected_net_return','p_win','side_name'],ascending=False).drop_duplicates('decision_idx').sort_values('entry_ms')

def assess(model,part,m1,funding):
    p,edge=model.predict(part)
    primary,trades=replay(choices(model,part),m1,funding)
    gated,_=replay(choices(model,part,True),m1,funding)
    return dict(brier=float(brier_score_loss(part.win,p)),log_loss=float(log_loss(part.win,p,labels=[0,1])),
        base_rate=float(part.win.mean()),examples=len(part),preferred=primary,qualified=gated),trades

def run():
    output=Path('artifacts/v3');output.mkdir(parents=True,exist_ok=True)
    m15=load('data/BTCUSDT_15m.csv');m1=pd.read_csv('data/BTCUSDT_1m.csv')
    funding=pd.read_csv('data/BTCUSDT_funding.csv').sort_values('timestamp')
    base=build(m15,m1,funding)
    enhanced=frame_features(m15,'indicators')
    rows=[]
    # Reuse identical labels/execution outcomes; change only pre-decision features.
    for r in base.itertuples():
        f=enhanced.loc[r.decision_idx]
        x=side_input(f,1 if r.side_name=='long' else -1,'indicators')
        if not all(np.isfinite(v) for v in x.values()):raise ValueError('Incomplete indicator history')
        rows.append(dict(r._asdict(),**{k:v for k,v in x.items() if k not in base.columns}))
    augmented=pd.DataFrame(rows).drop(columns=['Index'])
    if len(augmented)!=len(base):raise ValueError('Ablation examples must match')
    bars=np.array(sorted(base.decision_idx.unique()))
    splits=list(TimeSeriesSplit(n_splits=3,gap=4).split(bars))
    report=dict(version=3,feature_mode='indicators',candidate='lightgbm',decision='observe_only',
        paper_proposals_enabled=False,first_ms=int(m1.timestamp.min()),last_ms=int(m1.timestamp.max()),
        all_historical_periods_previously_viewed=True,
        features=columns('indicators'),base_features=columns('base'),
        indicators=['RSI14','MACD12/26/9','Bollinger20/2','ADX14 and DI','Stochastic14/3/3','OBV flow20','rolling VWAP20','MFI14'],
        parameters=dict(horizon_minutes=60,p_win_threshold=.55,expected_return_threshold=.0003,
            stop_atr=1.5,minimum_stop_pct=.003,target_multiple=2,approval_delay_minutes=1,price_drift_limit=.001),
        indicator_window=200,indicator_library='TA-Lib 0.6.8',
        hashes={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['data/BTCUSDT_15m.csv','data/BTCUSDT_1m.csv','data/BTCUSDT_funding.csv']},
        comparison='Same examples, labels, model parameters, chronological splits, calibration and execution costs; only features change.',
        folds=[])
    data={'base':base,'indicators':augmented}
    for fold,(tr,va) in enumerate(splits,1):
        metrics={}
        for mode,frame in data.items():
            training=frame[frame.decision_idx.isin(bars[tr])]
            part=frame[frame.decision_idx.isin(bars[va])]
            training=training[training.exit_ms<part.signal_close_ms.min()]
            model=fit('lightgbm',training,np.array(sorted(training.decision_idx.unique())),columns(mode))
            metrics[mode],trades=assess(model,part,m1,funding)
            pd.DataFrame(trades).to_csv(output/f'fold_{fold}_{mode}_trades.csv',index=False)
            if fold==3 and mode=='indicators':joblib.dump(model,output/'evaluated.joblib')
        report['folds'].append(dict(fold=fold,phase='development' if fold<3 else 'historical_diagnostic',
            evaluation_start_ms=int(part.signal_close_ms.min()),metrics=metrics))
        print('Indicator fold',fold,json.dumps(metrics),flush=True)
    report['cv']={mode:dict(brier=float(np.mean([f['metrics'][mode]['brier'] for f in report['folds'][:2]])),
        mean_return_pct=float(np.mean([f['metrics'][mode]['preferred']['return_pct'] for f in report['folds'][:2]])),
        mean_win_rate=float(np.mean([f['metrics'][mode]['preferred']['win_rate'] or 0 for f in report['folds'][:2]]))) for mode in data}
    report['historical_diagnostic']=report['folds'][-1]['metrics']['indicators']
    report['historical_brier_improved']=report['historical_diagnostic']['brier']<report['folds'][-1]['metrics']['base']['brier']
    report['can_claim_improved_trade_accuracy']=False
    report['reason']='Indicator challenger requires prospective matched evaluation; no automatic trading or leverage increase.'
    production=fit('lightgbm',augmented,bars,columns('indicators'))
    joblib.dump(dict(model=production,features=columns('indicators'),feature_mode='indicators',
        report=report,data_through_ms=int(m15.timestamp.max()),paper_proposals_enabled=False),output/'model.joblib')
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    lines=['# V3 — Chỉ báo kỹ thuật và so sánh cùng điều kiện','',
        'Thêm RSI, MACD, Bollinger Bands, ADX/DI, Stochastic, OBV, VWAP20 và MFI.',
        'Các chỉ báo vẫn là biến đổi của giá/khối lượng; không tạo thông tin bên ngoài thị trường.',
        'TA-Lib chuẩn, tính lại trên 200 nến đóng cho mỗi thời điểm để online/offline khớp nhau.',
        '', 'So sánh giữ nguyên nhãn, mẫu, tham số LightGBM, calibration, thời gian và chi phí.',
        '**Toàn bộ số liệu lịch sử là thăm dò. Chưa kết luận cải thiện tỷ lệ thắng tương lai.**',
        '', '| Bộ đặc trưng | CV Brier (thấp hơn tốt hơn) | CV lợi nhuận trung bình hướng ưu tiên (%) |', '|---|---:|---:|']
    for mode,m in report['cv'].items():lines.append(f"| {mode} | {m['brier']:.6f} | {m['mean_return_pct']:.3f} |")
    lines += ['', '## Đoạn chẩn đoán cuối', '', '```json',json.dumps(report['folds'][-1]['metrics'],indent=2),'```',
        '', 'Đòn bẩy vẫn 1x, không mở giao dịch. Giữ worker V2 song song để đối chiếu dự báo mới.',
        'Kết quả hướng ưu tiên dùng danh mục 1 vị thế trong replay. Mẫu forward chồng lấn được báo riêng, không cộng thành PnL danh mục.']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report['cv']),flush=True)

if __name__=='__main__':run()
