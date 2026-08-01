"""精准微调"""
import sys,os,warnings,numpy as np,pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from factor_lab.operators import rolling_skew
from factor_lab.pipeline.daily_backtester import build_rolling_signal

df=pd.read_csv(os.path.join(os.path.dirname(__file__),'..','data','300442_sz_daily.csv'))
c=df['close'].values.astype(np.float64);d=df['trade_date'].astype(str).values
lr=np.r_[0.0,np.log(c[1:]/c[:-1])];sr=-rolling_skew(lr,20);sig=build_rolling_signal(sr,+1.0,20)
ts=np.searchsorted(d,'20260414')

def run(e,x,h,s,p):
    trades=[];in_pos,ep,ei=False,0.0,0
    for i in range(ts,len(c)):
        si,pr=sig[i],c[i]
        if not in_pos:
            if np.isfinite(si) and si>=e: in_pos,ep,ei=True,pr,i
        else:
            pnl=pr/ep-1;go=False
            if si<x:go=True
            elif i-ei>=h:go=True
            elif pnl<=s:go=True
            elif pnl>=p:go=True
            if go:trades.append((d[ei],d[i],ep,pr,i-ei,pnl));in_pos=False
    rets=[t[5] for t in trades]
    return np.prod([1+r for r in rets])-1 if rets else 0, trades

configs=[
(0.60,0.25,7,-0.05,0.10,'s=-5%'),
(0.60,0.25,7,-0.04,0.10,'s=-4%'),
(0.60,0.25,10,-0.07,0.10,'h=10d'),
(0.60,0.20,7,-0.07,0.10,'x=0.20'),
(0.60,0.25,7,-0.07,0.09,'p=9%'),
(0.60,0.25,7,-0.07,0.11,'p=11%'),
(0.65,0.25,7,-0.07,0.10,'e=0.65'),
(0.60,0.25,7,-0.06,0.10,'s=-6%'),
(0.55,0.25,7,-0.07,0.10,'e=0.55'),
(0.60,0.30,7,-0.07,0.12,'p=12%'),
]
best_ret,best_cfg=-999,None
for e,x,h,s,p,label in configs:
    ret,tr=run(e,x,h,s,p)
    if ret>best_ret:best_ret,best_cfg=ret,(e,x,h,s,p,label)
    print(f'{label}: {ret:+.2%} ({len(tr)}t)')
    for t in tr:print(f'  {t[0]}->{t[1]} {t[2]:.2f}->{t[3]:.2f} {t[4]}d {t[5]:+.2%}')

print(f'\nBEST: {best_ret:+.2%} {best_cfg[4]} entry={best_cfg[0]:.2f} exit={best_cfg[1]:.2f} hold={best_cfg[2]}d stop={best_cfg[3]:.0%} profit={best_cfg[4]:.0%}')
