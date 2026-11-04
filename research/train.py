"""Fixed-parameter model comparison; purged walk-forward, untouched final holdout."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, log_loss
from .features import FEATURES, HORIZON, dataset, load
from .backtest import simulate

THRESHOLD=.55

def models():
    return dict(logistic=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=1000)),
                lightgbm=LGBMClassifier(n_estimators=150,learning_rate=.03,num_leaves=15,max_depth=4,
                    min_child_samples=150,reg_lambda=5,verbosity=-1,random_state=42,n_jobs=2,deterministic=True,force_col_wise=True))

def decisions(model,frame):
    result={}
    if model is None:
        for idx,row in frame.iterrows():
            if abs(row.ema_gap)>.001 and row.ema_gap*row.h1_gap>0:
                result[int(idx)]=('long' if row.ema_gap>0 else 'short',float(row.atr))
        return result
    probs=model.predict_proba(frame[FEATURES])
    for (idx,row),prob in zip(frame.iterrows(),probs):
        top=int(np.argmax(prob)); label=int(model.classes_[top])
        if label and prob[top]>=THRESHOLD:
            result[int(idx)]=('long' if label==1 else 'short',float(row.atr))
    return result

def evaluate(model,part,candles):
    d=decisions(model,part)
    result=simulate(candles,d,int(part.index[0])+1,int(part.index[-1])+HORIZON+1)
    if model is not None:
        result['accuracy']=float(accuracy_score(part.label,model.predict(part[FEATURES])))
        result['log_loss']=float(log_loss(part.label,model.predict_proba(part[FEATURES]),labels=model.classes_))
    return result

def train(path,output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    candles=load(path)
    frame=dataset(candles)
    cut=int(len(frame)*.8)
    dev=frame.iloc[:cut-HORIZON]
    holdout=frame.iloc[cut:]
    if len(dev)<5000 or len(holdout)<1000:
        raise ValueError('Insufficient data for meaningful comparison')
    report=dict(created_at=datetime.now(timezone.utc).isoformat(),symbol='BTCUSDT',interval='15m',
        data_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),rows=len(candles),
        first_ms=int(candles.timestamp.iloc[0]),last_ms=int(candles.timestamp.iloc[-1]),
        horizon=HORIZON,threshold=THRESHOLD,features=FEATURES,
        assumptions={'fee_per_side':.0006,'slippage_per_side':.0005,'funding_included':False,
            'stop':'max(1.5 ATR14, 0.3% entry)','target':'2 times stop distance',
            'entry':'next candle open','exit':'SL/TP or close of 4th candle','intrabar':'stop first if both touched',
            'risk_per_trade':.005,'notional_cap':'1x','initial_cash':100,
            'daily_loss_limit':.15,'timezone':'Asia/Ho_Chi_Minh','probabilities_calibrated':False},
        folds=[],holdout_start_ms=int(holdout.timestamp.iloc[0]))
    scores={name:[] for name in ('ema','logistic','lightgbm')}
    for fold,(tr,va) in enumerate(TimeSeriesSplit(n_splits=3,gap=HORIZON).split(dev),1):
        training,validation=dev.iloc[tr],dev.iloc[va]
        assert training.index[-1]+HORIZON<validation.index[0]
        fitted=models()
        metrics={}
        for name in scores:
            model=None if name=='ema' else fitted[name].fit(training[FEATURES],training.label)
            metrics[name]=evaluate(model,validation,candles)
            scores[name].append(metrics[name]['return_pct'])
        report['folds'].append(dict(fold=fold,train_end_ms=int(training.timestamp.iloc[-1]),
            validation_start_ms=int(validation.timestamp.iloc[0]),metrics=metrics))
        print('Fold',fold,json.dumps(metrics),flush=True)
    # No tuning or winner selection on final holdout. Cash is an explicit alternative.
    means={name:float(np.mean(v)) for name,v in scores.items()}
    selected=max(means,key=means.get)
    report['cv_mean_return_pct']=means
    report['candidate']=selected
    fitted=models()
    model=None if selected=='ema' else fitted[selected].fit(dev[FEATURES],dev.label)
    report['holdout']=evaluate(model,holdout,candles)
    report['holdout_double_cost']=simulate(candles,decisions(model,holdout),
        int(holdout.index[0])+1,int(holdout.index[-1])+HORIZON+1,2)
    stable=sum(r>0 for r in scores[selected])>=2
    # Conservative paper proposal gate; failure still permits observational forecasts.
    eligible=(means[selected]>0 and stable and report['holdout']['return_pct']>0
        and report['holdout_double_cost']['return_pct']>0 and report['holdout']['trades']>=30
        and report['holdout']['max_drawdown_pct']<10)
    report['paper_proposals_enabled']=bool(eligible)
    report['decision']='paper_candidate' if eligible else 'observe_only'
    report['selection_note']='Candidate fixed by CV; holdout is used once as acceptance test, not to reselect.'
    # Retain evaluated snapshot, then fit deployment snapshot on all resolved labels.
    joblib.dump(dict(model=model,name=selected,features=FEATURES,threshold=THRESHOLD),output/'evaluated.joblib')
    production=None if selected=='ema' else models()[selected].fit(frame[FEATURES],frame.label)
    bundle=dict(model=production,name=selected,features=FEATURES,threshold=THRESHOLD,
        trained_through_ms=int(frame.timestamp.iloc[-1]),data_through_ms=int(candles.timestamp.iloc[-1]),
        paper_proposals_enabled=bool(eligible),report_sha256=None)
    encoded=json.dumps(report,indent=2,allow_nan=False)
    (output/'report.json').write_text(encoded)
    bundle['report_sha256']=hashlib.sha256(encoded.encode()).hexdigest()
    joblib.dump(bundle,output/'model.joblib')
    lines=['# BTCUSDT M15 — nghiên cứu paper', '',f"Ứng viên chọn bằng walk-forward: **{selected}**.",
        f"Trạng thái: **{report['decision']}**.",'','| Mô hình | Lợi nhuận trung bình mỗi fold (%) |', '|---|---:|']
    lines += [f'| {k} | {v:.3f} |' for k,v in means.items()]
    lines += ['', 'Holdout cuối (không dùng chọn mô hình):', '', '```json',json.dumps(report['holdout'],indent=2),'```',
        '', 'Chi phí gấp đôi:', '```json',json.dumps(report['holdout_double_cost'],indent=2),'```','',
        'Kết quả là mô phỏng OHLC, chưa tính funding và độ trễ duyệt Telegram. Không chứng minh lợi nhuận tương lai.',
        'Ngưỡng xác suất 0.55 là cố định và chưa hiệu chỉnh; không diễn giải thành tỷ lệ thắng thực tế.',
        'Model triển khai được fit lại trên tất cả nhãn đã biết; số liệu holdout thuộc snapshot evaluated.joblib.']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    print(encoded,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--data',default='data/BTCUSDT_15m.csv'); p.add_argument('--output',default='artifacts')
    args=p.parse_args(); train(args.data,args.output)
