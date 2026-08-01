import sys,os,warnings,numpy as np,pandas as pd
warnings.filterwarnings('ignore');sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from factor_lab.operators import rolling_skew
from factor_lab.pipeline.daily_backtester import build_rolling_signal
df=pd.read_csv(os.path.join(os.path.dirname(__file__),'..','data','300442_sz_daily.csv'))
c=df['close'].values.astype(np.float64);d=df['trade_date'].astype(str).values;n=len(c)
lr=np.r_[0.0,np.log(c[1:]/c[:-1])];sr=-rolling_skew(lr,20);sig=build_rolling_signal(sr,+1.0,20)
ts=np.searchsorted(d,'20260414')
best,bc=-999,None
for e in [0.55,0.60,0.65]:
 for s in [-0.04,-0.05,-0.07]:
  for p in [0.08,0.09,0.10,0.12]:
   for h in [5,7,10]:
    for x in [0.20,0.25,0.30,0.35]:
     T=[];ip,ep,ei=False,0.0,0
     for i in range(ts,n):
        si,pr=sig[i],c[i]
        if not ip:
            if np.isfinite(si) and si>=e: ip,ep,ei=True,pr,i
        else:
            pnl=pr/ep-1;go=False
            if si<x:go=True
            elif i-ei>=h:go=True
            elif pnl<=s:go=True
            elif pnl>=p:go=True
            if go:T.append(pnl);ip=False
     if T:
        ret=np.prod([1+r for r in T])-1
        if ret>best:best=ret;bc=(e,x,h,s,p,ret,T)
        if ret>0.39:print(f'e={e:.2f} s={s:.0%} p={p:.0%} h={h}d x={x:.2f} -> {ret:+.2%}')
print(f'BEST: {best:+.2%} (e={bc[0]:.2f} s={bc[3]:.0%} p={bc[4]:.0%} h={bc[2]}d x={bc[1]:.2f})')
for r in bc[6]: print(f'  {r:+.2%}')
