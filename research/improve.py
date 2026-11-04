"""V2: trade-aligned outcomes, M1 execution, funding, chronological calibration.
All historical results are exploratory because previous research viewed this period.
"""
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss,log_loss
from sklearn.model_selection import TimeSeriesSplit
from .features import load
from .trade_labels import build,TRADE_FEATURES
from .trade_models import TradeModel,signals
from .trade_backtest import replay


def fit(name,rows,bar_indices,feature_columns=None):
    split=int(len(bar_indices)*.8)
    boundary=bar_indices[split]
    training=rows[(rows.decision_idx.isin(bar_indices[:split])) & (rows.exit_ms < rows[rows.decision_idx>=boundary].signal_close_ms.min())]
    calibration=rows[rows.decision_idx.isin(bar_indices[split:])]
    return TradeModel(name,feature_columns).fit(training,calibration)

def evaluate(model,part,m1,funding):
    p,expected=model.predict(part)
    picked=signals(model,part)
    result,trades=replay(picked,m1,funding)
    result.update(brier=float(brier_score_loss(part.win,p)),log_loss=float(log_loss(part.win,p,labels=[0,1])),
        examples=len(part),signal_count=len(picked),actual_win_base_rate=float(part.win.mean()),
        calibration_prior_brier=float(brier_score_loss(part.win,np.full(len(part),model.calibration_prior))),
        predicted_win_probability_min=float(p.min()),predicted_win_probability_max=float(p.max()))
    return result,trades

def run(horizon=60):
    if horizon not in (60,240):raise ValueError('Only predeclared 60 and 240 minute studies')
    output=Path('artifacts/v2' if horizon==60 else 'artifacts/v2_240');output.mkdir(parents=True,exist_ok=True)
    m15=load('data/BTCUSDT_15m.csv')
    m1=pd.read_csv('data/BTCUSDT_1m.csv')
    funding=pd.read_csv('data/BTCUSDT_funding.csv').sort_values('timestamp')
    rows=build(m15,m1,funding,horizon_minutes=horizon)
    rows.to_csv(output/'trade_labels.csv',index=False)
    if len(rows)<4000:raise ValueError('Too few executable outcomes')
    bars=np.array(sorted(rows.decision_idx.unique()))
    report=dict(version=2,purpose='Exploratory historical research; fresh forward evidence required',
        all_historical_periods_previously_viewed=True,paper_proposals_enabled=False,decision='observe_only',
        count_m1=len(m1),count_trade_examples=len(rows),first_ms=int(m1.timestamp.min()),
        last_ms=int(m1.timestamp.max()),label='Net trade win after SL/TP/timeout, fees, slippage and funding',
        parameters=dict(stop_atr=1.5,minimum_stop_pct=.003,target_multiple=2,horizon_minutes=60,
            approval_delay_minutes=1,price_drift_limit=.001,p_win_threshold=.55,expected_return_threshold=.0003),
        execution=dict(same_minute_both_barriers='SL first',funding='actual rate; previous M1 close as mark proxy',
            portfolio='paper Engine; 0.5% risk, 1x cap, daily halt 15%',
            drawdown='M1 close equity',funding_at_exact_entry='excluded',
            note='M1 still cannot resolve path within one minute or actual funding mark price'),
        hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ('data/BTCUSDT_15m.csv','data/BTCUSDT_1m.csv','data/BTCUSDT_funding.csv')},
        folds=[])
    names=('logistic','lightgbm')
    # Select using first two validation windows; reserve last window for diagnostics.
    report['parameters']['horizon_minutes']=horizon
    splits=list(TimeSeriesSplit(n_splits=3,gap=horizon//15).split(bars))
    score={name:[] for name in names}
    for i,(tr,va) in enumerate(splits[:2],1):
        training=rows[rows.decision_idx.isin(bars[tr])]
        part=rows[rows.decision_idx.isin(bars[va])]
        training=training[training.exit_ms<part.signal_close_ms.min()]
        metrics={}
        for name in names:
            eligible_bars=np.array(sorted(training.decision_idx.unique()))
            model=fit(name,training,eligible_bars)
            metrics[name],trades=evaluate(model,part,m1,funding)
            score[name].append(metrics[name]['return_pct'])
        report['folds'].append(dict(fold=i,train_end_ms=int(training.signal_close_ms.max()),
            evaluation_start_ms=int(part.signal_close_ms.min()),metrics=metrics))
        print('V2 fold',i,json.dumps(metrics),flush=True)
    selected=max(names,key=lambda name:(np.mean(score[name]),-np.mean([f['metrics'][name]['brier'] for f in report['folds']])))
    report['selection_rule']='CV mean net return; ties broken by CV Brier, never final diagnostics.'
    report['candidate']=selected
    report['cv_mean_return_pct']={k:float(np.mean(v)) for k,v in score.items()}
    tr,va=splits[-1]
    training=rows[rows.decision_idx.isin(bars[tr])]
    diagnostic=rows[rows.decision_idx.isin(bars[va])]
    training=training[training.exit_ms<diagnostic.signal_close_ms.min()]
    model=fit(selected,training,np.array(sorted(training.decision_idx.unique())))
    report['historical_diagnostic'],trades=evaluate(model,diagnostic,m1,funding)
    report['diagnostic_start_ms']=int(diagnostic.signal_close_ms.min())
    pd.DataFrame(trades).to_csv(output/'diagnostic_trades.csv',index=False)
    # Same policy on double-cost labels, no retraining or reselecting.
    doubled=build(m15,m1,funding,multiplier=2,horizon_minutes=horizon)
    stress=doubled[doubled.decision_idx.isin(bars[va])]
    # Predictors only consume pre-trade features; altered cost cannot alter prediction.
    report['double_cost'],_=replay(signals(model,stress),m1,funding,2)
    report['can_claim_improved_trade_accuracy']=False
    report['reason']='Historical results are exploratory; use prospective shadow trades before promotion.'
    report['candidate_acceptable_historically']=(report['historical_diagnostic']['trades']>=30
        and report['historical_diagnostic']['return_pct']>0 and report['double_cost']['return_pct']>0
        and all(x>0 for x in score[selected]))
    baseline=model.classifier # retain full evaluated model, including calibration
    joblib.dump(model,output/'evaluated.joblib')
    production=fit(selected,rows,bars)
    joblib.dump(dict(model=production,features=TRADE_FEATURES,report=report,
        data_through_ms=int(m15.timestamp.max()),paper_proposals_enabled=False),output/'model.joblib')
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    lines=['# V2 — Đánh giá giao dịch M15','',
        'Nhãn lời/lỗ sau SL/TP, timeout, phí, trượt giá và funding; mô phỏng bằng M1.',
        'Có độ trễ duyệt 1 phút, giới hạn lệch giá 0.1%; xác suất được hiệu chỉnh trên đoạn thời gian riêng.',
        f"Ứng viên: {selected}. M1: {len(m1):,} nến; ví dụ giao dịch có thể thực hiện: {len(rows):,}.",
        '', '**Toàn bộ kết quả lịch sử là thăm dò; chưa có kiểm chứng tương lai. Không bật lệnh mô hình.**',
        '', '## Hai cửa sổ chọn ứng viên','', '| Mô hình | Lợi nhuận trung bình (%) |','|---|---:|']
    lines += [f'| {k} | {np.mean(v):.3f} |' for k,v in score.items()]
    lines += ['', '## Đoạn chẩn đoán cuối','', '```json',json.dumps(report['historical_diagnostic'],indent=2),'```',
        '', '## Chi phí gấp đôi','', '```json',json.dumps(report['double_cost'],indent=2),'```',
        '', 'Tỷ lệ thắng không đủ để kết luận có lợi nhuận; đọc cùng PnL sau chi phí và drawdown.',
        'Khoảng Wilson chỉ mô tả số lệnh quan sát, chưa điều chỉnh phụ thuộc giữa lệnh theo thời gian.',
        'M1 vẫn không biết đường đi trong một phút. Funding dùng giá close M1 làm đại diện mark price.',
        'V1 và V2 dùng giai đoạn/nhãn khác nhau: không thể lấy chênh lệch accuracy làm mức cải thiện trực tiếp.']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--horizon',type=int,default=60,choices=[60,240])
    run(parser.parse_args().horizon)
