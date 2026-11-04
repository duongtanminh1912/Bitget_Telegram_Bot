"""Descriptive audit of the frozen holdout. Never tunes or changes deployed model."""
import json
import hashlib
from pathlib import Path
import joblib
import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, log_loss
from .features import FEATURES, HORIZON, dataset, load
from .train import decisions


def diagnose(data_path='data/BTCUSDT_15m.csv', directory='artifacts'):
    directory=Path(directory)
    report=json.loads((directory/'report.json').read_text())
    if hashlib.sha256(Path(data_path).read_bytes()).hexdigest()!=report['data_sha256']:
        raise ValueError('Data differs from evaluated history')
    frame=dataset(load(data_path))
    cut=int(len(frame)*.8)
    train=frame.iloc[:cut-HORIZON]
    test=frame.iloc[cut:]
    if int(test.timestamp.iloc[0])!=report['holdout_start_ms']:
        raise ValueError('Holdout boundary differs')
    bundle=joblib.load(directory/'evaluated.joblib')
    model=bundle['model']
    if model is None:
        raise ValueError('This diagnostic is for classifier candidates')
    y=test.label.to_numpy()
    predicted=model.predict(test[FEATURES])
    probs=model.predict_proba(test[FEATURES])
    selected=decisions(model,test)
    indices=np.array([i in selected for i in test.index])
    majority=int(train.label.mode().iloc[0])
    prior=np.array([(train.label==k).mean() for k in model.classes_])
    prior_probs=np.tile(prior,(len(test),1))
    truth=(y[:,None]==model.classes_[None,:]).astype(float)
    result=dict(
        purpose='Descriptive audit of already-viewed holdout; no parameter tuning.',
        holdout_samples=len(test), class_counts={str(int(k)):int((y==k).sum()) for k in model.classes_},
        model_accuracy=float(accuracy_score(y,predicted)),
        always_neutral_accuracy=float((y==0).mean()),
        train_majority_class=majority,train_majority_accuracy=float((y==majority).mean()),
        model_log_loss=float(log_loss(y,probs,labels=model.classes_)),
        train_prior_log_loss=float(log_loss(y,prior_probs,labels=model.classes_)),
        multiclass_brier=float(np.mean(np.sum((probs-truth)**2,axis=1))),
        train_prior_brier=float(np.mean(np.sum((prior_probs-truth)**2,axis=1))),
        confusion_matrix=dict(labels=[int(k) for k in model.classes_],rows='actual',columns='predicted',values=confusion_matrix(y,predicted,labels=model.classes_).tolist()),
        argmax_directional_predictions=int((predicted!=0).sum()),
        argmax_directional_label_precision=float((predicted[predicted!=0]==y[predicted!=0]).mean()) if (predicted!=0).any() else None,
        eligible_signals=len(selected),coverage=float(indices.mean()),
        executed_trades=report['holdout']['trades'],
        trade_win_rate=report['holdout']['win_rate'] if report['holdout']['trades'] else None,
        net_return_pct=report['holdout']['return_pct'],
        cv_trades=sum(fold['metrics'][report['candidate']]['trades'] for fold in report['folds']),
        limitations=['Direction label accuracy is not trade win rate: SL/TP can be hit before terminal horizon.',
                    'Zero trades provides no estimate of trade win probability.',
                    'Holdout has already been viewed; subsequent tuning needs new evaluation data.',
                    'Funding, execution latency and intrabar price path are not fully modeled.'])
    (directory/'accuracy_audit.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    lines=['# Kiểm tra độ chính xác giao dịch M15','',
        f"Số mẫu holdout: {len(test)}.",
        f"Accuracy mô hình: {result['model_accuracy']:.2%}; luôn đoán trung tính: {result['always_neutral_accuracy']:.2%}.",
        f"Tín hiệu đạt ngưỡng: {len(selected)}; giao dịch đã mô phỏng: {result['executed_trades']}.",
        '', 'Không thể ước lượng tỷ lệ thắng giao dịch khi không có giao dịch.',
        'Accuracy phân loại và tỷ lệ thắng sau SL/TP, phí, trượt giá là hai đại lượng khác nhau.',
        'Chưa có bằng chứng xác nhận lợi thế giao dịch của phiên bản này.',
        '', 'Chi tiết: accuracy_audit.json. Không đổi model, ngưỡng hoặc trạng thái bot.']
    (directory/'accuracy_audit.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result,indent=2,allow_nan=False))

if __name__=='__main__': diagnose()
