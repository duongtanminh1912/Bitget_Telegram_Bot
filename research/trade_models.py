"""Models of net trade win probability and expected return, with chronological calibration."""
import numpy as np
from lightgbm import LGBMClassifier,LGBMRegressor
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .trade_labels import TRADE_FEATURES

class TradeModel:
    def __init__(self,name,feature_columns=None):
        self.name=name
        self.feature_columns=list(feature_columns or TRADE_FEATURES)
        if name=='logistic':
            self.classifier=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=1000))
            self.regressor=make_pipeline(StandardScaler(),Ridge(alpha=100))
        elif name=='lightgbm':
            settings=dict(n_estimators=120,learning_rate=.03,num_leaves=7,max_depth=3,min_child_samples=150,
                reg_lambda=10,verbosity=-1,n_jobs=2,random_state=42,deterministic=True,force_col_wise=True)
            self.classifier=LGBMClassifier(**settings)
            self.regressor=LGBMRegressor(**settings)
        else: raise ValueError('Unknown trade model')
    def fit(self,training,calibration):
        if training.win.nunique()!=2 or calibration.win.nunique()!=2: raise ValueError('Both outcomes required')
        if training.exit_ms.max()>=calibration.signal_close_ms.min(): raise ValueError('Calibration label overlap')
        cols=getattr(self,'feature_columns',TRADE_FEATURES)
        self.classifier.fit(training[cols],training.win)
        self.regressor.fit(training[cols],training.net_return)
        self.calibrator=LogisticRegression(C=1,max_iter=1000)
        p=self.classifier.predict_proba(calibration[cols])[:,1]
        self.calibrator.fit(self.logit(p),calibration.win)
        self.calibration_prior=float(calibration.win.mean())
        return self
    @staticmethod
    def logit(p):
        p=np.clip(p,1e-6,1-1e-6)
        return np.log(p/(1-p)).reshape(-1,1)
    def predict(self,frame):
        cols=getattr(self,'feature_columns',TRADE_FEATURES)
        p=self.classifier.predict_proba(frame[cols])[:,1]
        win=self.calibrator.predict_proba(self.logit(p))[:,1]
        expected=self.regressor.predict(frame[cols])
        return win,expected

def signals(model,frame):
    p,expected=model.predict(frame)
    result=frame.copy()
    result['p_win']=p
    result['expected_net_return']=expected
    # Fixed before inspecting outcomes; never optimize on the final diagnostic block.
    result=result[(result.p_win>=.55)&(result.expected_net_return>=.0003)]
    return result.sort_values('expected_net_return',ascending=False).drop_duplicates('decision_idx').sort_values('entry_ms')
