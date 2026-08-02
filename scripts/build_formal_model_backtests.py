from __future__ import annotations

# ruff: noqa
import argparse
import json, math, hashlib
from pathlib import Path
import pandas as pd
import numpy as np

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, default=Path('artifacts/formal-source'))
parser.add_argument('--output-dir', type=Path, default=Path('data/research/formal_backtests'))
args=parser.parse_args()
ROOT=args.source_root.resolve()
OUT=args.output_dir.resolve()
OUT.mkdir(parents=True, exist_ok=True)

def clean(v):
    if isinstance(v, dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v, list): return [clean(x) for x in v]
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating, float)):
        x=float(v)
        return x if math.isfinite(x) else None
    if pd.isna(v): return None
    return v

def write(name,payload):
    p=OUT/name
    txt=json.dumps(clean(payload),ensure_ascii=False,separators=(',',':'),sort_keys=True)+'\n'
    p.write_text(txt,encoding='utf-8')
    return {'path':name,'sha256':hashlib.sha256(txt.encode()).hexdigest(),'bytes':len(txt.encode())}

# US x1.1
usroot=ROOT/'us/evidence/us_x1_1_complete_backtest_notebook'
manifest=json.load(open(usroot/'audit_manifest.json'))
periods=pd.read_csv(usroot/'period_returns.csv')
hold=pd.read_csv(usroot/'holdings.csv')
trades=pd.read_csv(usroot/'trade_ledger.csv')
attr=pd.read_csv(usroot/'security_attribution.csv')
windows=pd.read_csv(usroot/'window_attribution.csv')
regime=pd.read_csv(usroot/'regime_attribution.csv')
repro=pd.read_csv(usroot/'reproduction_summary.csv')
report=[{'date':'2024-01-01','account':1.0,'bench_qqq':1.0,'turnover':0.0,'period_return':0.0,'benchmark_return':0.0,'trace_frequency':'non_overlapping_10_session'}]
for _,r in periods.iterrows():
    report.append({
      'date':str(r.rebalance_date), 'account':float(r.strategy_equity), 'bench_qqq':float(r.qqq_equity),
      'turnover':float(r.turnover), 'period_return':float(r.net_return), 'gross_return':float(r.gross_return),
      'benchmark_return':float(r.qqq_return),'excess_return':float(r.excess_return),'transaction_cost':float(r.transaction_cost),
      'drawdown':float(r.strategy_drawdown),'window':str(r.window),'holding_end_date':str(r.holding_end_date),
      'trace_frequency':'non_overlapping_10_session'
    })
positions=[{
 'date':str(r.rebalance_date),'instrument':str(r.instrument),'weight':float(r.target_weight),
 'price':float(r.entry_close),'rank':int(r['rank']),'score':float(r.score),'window':str(r.window),
 'holding_end_date':str(r.holding_end_date),'forward_return':float(r.forward_return),'action':str(r.action)
} for _,r in hold.iterrows()]
trade_rows=[{
 'date':str(r.rebalance_date),'holding_end_date':str(r.holding_end_date),'instrument':str(r.instrument),'action':str(r.action),
 'previous_weight':float(r.previous_weight),'target_weight':float(r.target_weight),'weight_delta':float(r.weight_delta),
 'transaction_cost':float(r.allocated_transaction_cost),'rank':None if pd.isna(r['rank']) else int(r['rank']),
 'score':None if pd.isna(r.score) else float(r.score),'window':str(r.window),'period_index':int(r.period_index)
} for _,r in trades.iterrows()]
attribution=[{'instrument':str(r.instrument),'name':str(r.instrument),'value':float(r.net_contribution),
 'gross_contribution':float(r.gross_contribution),'transaction_cost':float(r.total_trading_cost),
 'periods_held':int(r.periods_held),'windows_held':int(r.windows_held),'win_rate':float(r.win_rate),'average_rank':float(r.average_rank)
} for _,r in attr.iterrows()]
us={
 'schema_version':'1.0.0','record_type':'formal_model_backtest','backtest_id':'us_x1_1-formal-30751593667',
 'model_id':'us_x1_1','display_name':'US x1.1','market':'us','benchmark':'QQQ','publication_status':'accepted_formal_baseline',
 'generated_at':'2026-08-02T14:13:24Z','evidence_cutoff':'2025-12-31','research_only':True,'trade_ready':False,
 'trace_frequency':'non_overlapping_10_session','date_range':{'start':'2024-01-02','end':'2025-12-31'},
 'metrics':{
   'Total Return':manifest['aggregate_result']['exact_ledger_compounded_strategy_return'],
   'Benchmark Return':manifest['aggregate_result']['exact_ledger_compounded_benchmark_return'],
   'Compounded Relative Excess Return':manifest['aggregate_result']['exact_ledger_compounded_relative_excess_return'],
   'Max Drawdown':manifest['aggregate_result']['worst_window_drawdown'],
   'Turnover':manifest['aggregate_result']['total_turnover'],
   'Transaction Cost':manifest['aggregate_result']['total_transaction_cost'],
 },
 'portfolio_contract':manifest['portfolio_contract'],'report':report,'positions':positions,'trades':trade_rows,'attribution':attribution,
 'window_summary':windows.to_dict('records'),'regime_summary':regime.to_dict('records'),
 'evidence':{
  'workflow_run_id':30751593667,'artifact_id':8834620874,'artifact_digest':'sha256:3fa7adfc034252b0cd36217dd041670975a070be6b27683a987db32ce95bc809',
  'artifact_expires_at':'2026-10-31T14:12:38Z','source_provider_artifact_id':8831837784,'source_reproduction_artifact_id':8831960659,
  'notebook_path':'notebooks/models/us_x1_1_complete_backtest.ipynb','all_identity_checks_passed':True,'all_reproduction_checks_passed':True,
  'row_counts':manifest['row_counts'],'exports_sha256':manifest['exports_sha256'],
 },
 'evidence_completeness':{
  'status':'complete','performance_trace':'retained_exact_period_trace','holdings':'retained_exact','trades':'retained_exact',
  'attribution':'retained_exact','daily_score_ledger':'retained_in_hash_bound_workflow_artifact','missing':[]
 },
 'reproduction_summary':repro.to_dict('records'),
 'interpretation_notes':['Formal baseline only; no exploratory candidates are published.','2026H1 is excluded from this accepted backtest package.']
}
us_meta=write('us_x1_1.json',us)

# v4.2
vroot=ROOT/'v42/evidence/qqqi_qqq_tqqq_vxn_bridge_v4_2'
daily=pd.read_csv(vroot/'daily_rotation_vxn_bridge_v4_2_50_50.csv')
tr=pd.read_csv(vroot/'trades_rotation_vxn_bridge_v4_2_50_50.csv')
metrics_df=pd.read_csv(vroot/'strategy_metrics.csv')
summary=json.load(open(vroot/'summary.json'))
diag=json.load(open(vroot/'diagnostics.json'))
row=metrics_df.loc[metrics_df.strategy=='rotation_vxn_bridge_v4_2_50_50'].iloc[0]
report=[{'date':'2024-01-29','account':1.0,'bench_qqq':1.0,'turnover':0.0,'period_return':0.0,'trace_frequency':'daily_open_to_open'}]
qqq_equity=1.0
for _,r in daily.iterrows():
    qret=float(r.QQQ_next_open_return) if pd.notna(r.QQQ_next_open_return) else 0.0
    qqq_equity*=1+qret
    report.append({'date':str(r.date),'account':float(r.equity),'bench_qqq':qqq_equity,'bench':qret,
      'turnover':float(r.turnover_units),'period_return':float(r.net_return),'gross_return':float(r.gross_return),
      'transaction_cost':float(r.transaction_cost),'position_state':int(r.position_state),'position_label':str(r.position_label),
      'decision_state':int(r.decision_state),'decision_reason':str(r.decision_reason),'executed_reason':str(r.executed_reason),
      'weight_QQQI':float(r.weight_QQQI),'weight_QQQ':float(r.weight_QQQ),'weight_TQQQ':float(r.weight_TQQQ),
      'trace_frequency':'daily_open_to_open'})
positions=[]
for _,r in daily.iterrows():
    for sym,w,p in [('QQQI',r.weight_QQQI,r.QQQI_open),('QQQ',r.weight_QQQ,r.QQQ_open),('TQQQ',r.weight_TQQQ,r.TQQQ_open)]:
        if float(w)>0:
            positions.append({'date':str(r.date),'instrument':sym,'weight':float(w),'price':float(p),
              'position_state':int(r.position_state),'position_label':str(r.position_label),'executed_reason':str(r.executed_reason)})
trade_rows=[]
prev={'QQQI':0.0,'QQQ':0.0,'TQQQ':0.0}
for _,r in tr.iterrows():
    cur={'QQQI':float(r.weight_QQQI),'QQQ':float(r.weight_QQQ),'TQQQ':float(r.weight_TQQQ)}
    for sym in cur:
        delta=cur[sym]-prev[sym]
        if abs(delta)>1e-12:
            action='BUY' if prev[sym]==0 and cur[sym]>0 else 'SELL' if prev[sym]>0 and cur[sym]==0 else 'INCREASE' if delta>0 else 'DECREASE'
            trade_rows.append({'date':str(r.date),'instrument':sym,'action':action,'previous_weight':prev[sym],'target_weight':cur[sym],
              'weight_delta':delta,'transaction_cost':float(r.transaction_cost)*abs(delta)/max(float(r.turnover_units),1e-12),
              'reason':str(r.executed_reason),'position_state':int(r.position_state),'position_label':str(r.position_label),
              'vix_close':float(r.vix_close),'vix_regime':str(r.vix_regime),'vxn_close':float(r.vxn_close),'vxn_regime':str(r.vxn_regime)})
    prev=cur
contrib={s:0.0 for s in ['QQQI','QQQ','TQQQ']}
prev={'QQQI':0.0,'QQQ':0.0,'TQQQ':0.0}
for _,r in daily.iterrows():
    cur={'QQQI':float(r.weight_QQQI),'QQQ':float(r.weight_QQQ),'TQQQ':float(r.weight_TQQQ)}
    rets={'QQQI':float(r.QQQI_next_open_return),'QQQ':float(r.QQQ_next_open_return),'TQQQ':float(r.TQQQ_next_open_return)}
    for s in contrib: contrib[s]+=cur[s]*rets[s]
    changes={s:abs(cur[s]-prev[s]) for s in cur}; denom=sum(changes.values())
    if denom>0:
        for s in contrib: contrib[s]-=float(r.transaction_cost)*changes[s]/denom
    prev=cur
attribution=[{'instrument':s,'name':s,'value':v,'semantics':'arithmetic daily contribution less allocated transition cost'} for s,v in contrib.items()]
v42={
 'schema_version':'1.0.0','record_type':'formal_model_backtest','backtest_id':'qqqi_qqq_tqqq_v4_2-formal-8820398584',
 'model_id':'qqqi_qqq_tqqq_v4_2','display_name':'QQQ Rotation v4.2','market':'us','benchmark':'QQQ','publication_status':'accepted_formal_baseline',
 'generated_at':'2026-08-01T15:34:47Z','evidence_cutoff':'2026-07-31','research_only':True,'trade_ready':False,
 'trace_frequency':'daily_open_to_open','date_range':{'start':str(row.start_date),'end':str(row.end_date)},
 'metrics':{'Total Return':float(row.total_return),'CAGR':float(row.cagr),'Annualized Volatility':float(row.annual_volatility),
  'Sharpe Ratio':float(row.sharpe),'Sortino Ratio':float(row.sortino),'Max Drawdown':float(row.max_drawdown),'Calmar Ratio':float(row.calmar),
  'Turnover':float(row.turnover_units),'Transaction Cost':float(row.transaction_cost_paid),'Benchmark Return':float(metrics_df.loc[metrics_df.strategy=='buy_hold_QQQ','total_return'].iloc[0])},
 'portfolio_contract':{'symbols':['QQQI','QQQ','TQQQ'],'signal_time':'session_close_t','execution_time':'next_session_open_t_plus_1','cost_bps':10,
  'state_0':{'QQQI':1.0,'QQQ':0.0,'TQQQ':0.0},'state_1':{'QQQI':0.5,'QQQ':0.5,'TQQQ':0.0},'state_2':{'QQQI':0.0,'QQQ':0.25,'TQQQ':0.75}},
 'report':report,'positions':positions,'trades':trade_rows,'attribution':attribution,
 'window_summary':pd.read_csv(vroot/'chronological_split.csv').to_dict('records'),
 'state_summary':[{'state':'state_1','baseline':diag['state_1_capture']['baseline_100_percent_qqq'],'formal':diag['state_1_capture']['bridge_50_qqqi_50_qqq']},
                  {'state':'state_2','baseline':diag['state_2_capture']['baseline'],'formal':diag['state_2_capture']['bridge']}],
 'evidence':{'workflow_run_id':30706201043,'artifact_id':8820398584,'artifact_digest':'sha256:3b4962b11796ee72ec4f74cca12ddf0d40800cf5417af4e42dabfb3a3d81abbf',
  'result_report':'docs/research/qqqi_qqq_tqqq_vxn_bridge_v4_2_result_2026-07-31.md','contract_path':'configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml'},
 'evidence_completeness':{'status':'complete','performance_trace':'retained_exact_daily_trace','holdings':'retained_exact_daily_weights','trades':'retained_exact',
  'attribution':'derived_exact_from_retained_daily_components','missing':[]},
 'interpretation_notes':['Formal v4.2 baseline only; v4.1 and alternative TQQQ experiments are not published to the frontend.','Post-result origin remains disclosed; research_only=true.']
}
v42_meta=write('qqqi_qqq_tqqq_v4_2.json',v42)

# CN x1.0 exact retained window-level evidence
croot=ROOT/'cn/evidence/cn130_xgb_optimization_v1/challenge/cn_10d_xgb_baseline_challenge_v1'
front=json.load(open(croot/'frontend_payload.json'))
win_files=sorted((croot/'windows').glob('*.json'))
windows=[]; positions=[]
account=1.0; bench=1.0
report=[]
for p in win_files:
    d=json.load(open(p)); cand=[x for x in d['comparison_report']['candidates'] if x['orientation']=='original'][0]
    w=p.stem.split('_')[-1]
    if not report: report.append({'date':cand['test_start'],'account':1.0,'bench_hs300':1.0,'turnover':0.0,'trace_frequency':'half_year_window'})
    account*=1+float(cand['total_return']); bench*=1+float(cand['benchmark_return'])
    report.append({'date':cand['test_end'],'account':account,'bench_hs300':bench,'turnover':float(cand['turnover']),
      'period_return':float(cand['total_return']),'benchmark_return':float(cand['benchmark_return']),'excess_return':float(cand['excess_return']),
      'max_drawdown':float(cand['max_drawdown']),'sharpe':float(cand['sharpe']),'icir':float(cand['icir']),'rank_ic':float(cand['rank_ic']),
      'window':w,'trace_frequency':'half_year_window'})
    windows.append({'window':w,'start':cand['test_start'],'end':cand['test_end'],'total_return':cand['total_return'],'benchmark_return':cand['benchmark_return'],
      'simple_excess_return':cand['excess_return'],'max_drawdown':cand['max_drawdown'],'sharpe':cand['sharpe'],'icir':cand['icir'],'rank_ic':cand['rank_ic'],
      'turnover':cand['turnover'],'n_periods':cand['n_periods'],'top_selected_stocks':cand['top_selected_stocks']})
    for rank,s in enumerate(cand['top_selected_stocks'],start=1):
        positions.append({'date':cand['test_end'],'instrument':str(s),'weight':1/15,'rank':rank,'window':w,'snapshot_semantics':'final_top15_for_window'})
metric=front['metrics']['current_best_candidate']
cn={
 'schema_version':'1.0.0','record_type':'formal_model_backtest','backtest_id':'cn_x1_0-formal-30733728747',
 'model_id':'cn_x1_0','display_name':'CN x1.0','market':'cn','benchmark':'000300','publication_status':'accepted_formal_baseline',
 'generated_at':'2026-08-02T05:22:16Z','evidence_cutoff':'2026-06-15','research_only':True,'trade_ready':False,
 'trace_frequency':'half_year_window','date_range':{'start':windows[0]['start'],'end':windows[-1]['end']},
 'metrics':{'Total Return':metric['compounded_total_return'],'Benchmark Return':metric['compounded_benchmark_return'],
  'Compounded Relative Excess Return':metric['compounded_relative_excess_return'],'Mean ICIR':metric['mean_icir'],'Mean Rank IC':metric['mean_rank_ic'],
  'Mean Top-Bottom Spread':metric['mean_spread'],'Max Drawdown':metric['worst_drawdown']},
 'portfolio_contract':{'topk':15,'weighting':'equal_weight','horizon_sessions':10,'rebalance_sessions':10,'cost_bps':20,'universe':'cn_selected_equities_v3'},
 'report':report,'positions':positions,'trades':[],'attribution':[],'window_summary':windows,
 'evidence':{'workflow_run_id':30733728747,'artifact_id':8828889722,'artifact_digest':'sha256:8696b9d12a11b86f8732b571ea225fed3e6c23f27a29f977a7ed925d3bf08307',
  'contract_path':'configs/models/cn_x1_0.yaml','provider_identity':'sha256:bf5fa1373a0b5ebfedcd90c2cf3c4748300efd2b25da0adfbfb1daab8c6405d8'},
 'evidence_completeness':{'status':'partial','performance_trace':'retained_exact_half_year_window_metrics_only','holdings':'retained_final_top15_each_window',
  'trades':'unavailable_source_artifact_did_not_retain_trade_ledger','attribution':'unavailable_source_artifact_did_not_retain_contribution_ledger',
  'missing':['non_overlapping_period_trace','rebalance_trade_ledger','name_contribution_ledger']},
 'interpretation_notes':['The frontend shows exact retained window metrics and final Top-15 selections only.','No daily or rebalance curve is inferred from missing source evidence.']
}
cn_meta=write('cn_x1_0.json',cn)

catalog={
 'schema_version':'1.0.0','published_at':'2026-08-02T14:30:00Z','research_only':True,'trade_ready':False,
 'publication_policy':'formal_named_baselines_only','excluded_record_classes':['exploratory_experiment','candidate_grid','rejected_candidate','shadow_strategy'],
 'records':[
  {'model_id':'qqqi_qqq_tqqq_v4_2','display_name':'QQQ Rotation v4.2','path':v42_meta['path'],'sha256':v42_meta['sha256'],'publication_status':'accepted_formal_baseline','display_order':1},
  {'model_id':'us_x1_1','display_name':'US x1.1','path':us_meta['path'],'sha256':us_meta['sha256'],'publication_status':'accepted_formal_baseline','display_order':2},
  {'model_id':'cn_x1_0','display_name':'CN x1.0','path':cn_meta['path'],'sha256':cn_meta['sha256'],'publication_status':'accepted_formal_baseline','display_order':3},
 ]
}
write('catalog.json',catalog)
print({p.name:p.stat().st_size for p in OUT.iterdir()})
