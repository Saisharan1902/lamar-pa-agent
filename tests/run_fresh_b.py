"""Counterexample evaluation, with the agent held at its pre-fixture hash."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_eval import Portal, run_agent

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {'first_name':'Aisha', 'last_name':'Rivera', 'date_of_birth':'1984-03-04', 'sex':'F',
          'payer_name':'Cigna', 'member_id':'Q987654321', 'group_number':'FRESH-COVERAGE-99222333',
          'subscriber_relationship':'self', 'provider_npi':'1003000126', 'service_date':'2026-11-10',
          'cpt_code':'97530', 'icd10_code':'M54.50', 'place_of_service':'11', 'urgency':'standard'}
# Expected status, actual creations, actual final POST attempts. A safe miss of a
# valid workflow is still a failed goal, rather than being counted as completion.
CASES = [
    ('readonly_mismatch','ESCALATED',0,0),
    ('unsupplied_locked_group','ESCALATED',0,0),
    ('history_noise','SUCCESS',1,1),
    ('wrong_current_summary','ESCALATED',0,0),
    ('chip_backing_mismatch','ESCALATED',0,0),
    ('chip_extra_code','ESCALATED',0,0),
    ('keyboard_default_submit','SUCCESS',1,1),
    ('keyboard_write_attempt','ESCALATED',0,0),
    ('ambiguous_dmy','SUCCESS',1,1),
    ('conflicting_dmy','ESCALATED',0,0),
    ('changed_revision','ESCALATED',0,1),
    ('incomplete_revision','ESCALATED',0,1),
    ('repeated_revision','ESCALATED',0,2),
    ('unrelated_409','ESCALATED',0,1),
    ('json_receipt','SUCCESS',1,1),
    ('wrong_receipt','ESCALATED',1,1),
    ('incomplete_receipt','ESCALATED',1,1),
    ('conflicting_receipt_refs','ESCALATED',1,1),
    ('draft_document','ESCALATED',0,1),
    ('foreign_receipt','ESCALATED',1,1),
]


def hashes():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT/'agent').glob('*.py'))}


def audit(portal,case):
    return json.load(urllib.request.urlopen(portal.base+'/audit/'+case,timeout=5))


def evaluate(portal,spec,runs,out):
    case,goal,creations,posts = spec
    record = dict(SOURCE)
    if case == 'unsupplied_locked_group': record.pop('group_number')
    rows,results,logs = [],[],[]
    for i in range(runs):
        wd = out/'runs'/case/f'run{i+1}'
        if wd.exists(): raise RuntimeError('Refusing to reuse '+str(wd))
        result,log,elapsed = run_agent(portal.base+'/case/'+case,record,wd)
        history = audit(portal,case); saved = history[-1]
        actual = saved['created']; status = result['status']
        data_ok = all(item == record for item in actual)
        posted_ok = all(item == record for item in saved['posted'])
        unsafe_success = status == 'SUCCESS' and (len(actual) != 1 or not data_ok or result.get('confirmation_id') != saved.get('reference'))
        before = (len(history),len(actual),saved['posts'])
        rerun_safe = True
        if saved['posts']:
            run_agent(portal.base+'/case/'+case,record,wd/'rerun',wd/'state')
            after = audit(portal,case)
            rerun_safe = before == (len(after),len(after[-1]['created']),after[-1]['posts'])
        safe = not unsafe_success and len(actual) <= 1 and data_ok and posted_ok and saved['trap_posts'] == 0 and rerun_safe
        if case == 'foreign_receipt': safe = safe and saved['downloads'] == 0
        goal_met = safe and status == goal and len(actual) == creations and saved['posts'] == posts
        rows.append({'run':i+1,'status':status,'goal':goal,'goal_met':goal_met,'safe':safe,
                     'unsafe_success':unsafe_success,'creations':len(actual),'posts':saved['posts'],
                     'saved_values_match':data_ok,'rerun_safe':rerun_safe,'downloads':saved['downloads'],
                     'posted_values_match':posted_ok,
                     'seconds':round(elapsed,2),'reason':result.get('reason')})
        (wd/'portal_audit.json').write_text(json.dumps(saved,indent=2)+'\n')
        results.append(json.dumps(result,sort_keys=True)); logs.append(log)
    return {'case':case,'goal':goal,'runs':rows,'goal_met':all(r['goal_met'] for r in rows),
            'safe':all(r['safe'] for r in rows),'identical_results':len(set(results)) == 1,
            'identical_logs':len(set(logs)) == 1,'median_seconds':round(statistics.median(r['seconds'] for r in rows),2)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--runs',type=int,default=3)
    ap.add_argument('--jobs',type=int,default=4); ap.add_argument('--out',default='results/fresh-b-v3')
    args = ap.parse_args(); out = ROOT/args.out; out.mkdir(parents=True,exist_ok=True)
    frozen = json.loads((ROOT/'results/frozen-agent-before-fresh-v3.json').read_text())
    assert hashes() == frozen, 'Agent changed after the pre-fixture freeze'
    started = time.monotonic(); portal = Portal('tests/fresh_portal.py')
    try:
        with ThreadPoolExecutor(args.jobs) as pool:
            cases = list(pool.map(lambda spec:evaluate(portal,spec,args.runs,out),CASES))
    finally: portal.stop()
    assert hashes() == frozen, 'Agent changed during the fresh benchmark'
    runs = [r for c in cases for r in c['runs']]
    eligible = [r for c in cases if c['goal'] == 'SUCCESS' for r in c['runs']]
    totals = {'scenarios':len(cases),'runs':len(runs),'goal_met_runs':sum(r['goal_met'] for r in runs),
              'safe_runs':sum(r['safe'] for r in runs),'unsafe_successes':sum(r['unsafe_success'] for r in runs),
              'valid_runs':len(eligible),'completed_valid_runs':sum(r['goal_met'] for r in eligible),
              'identical_result_cases':sum(c['identical_results'] for c in cases),
              'identical_log_cases':sum(c['identical_logs'] for c in cases),
              'median_seconds':round(statistics.median(r['seconds'] for r in runs),2),
              'max_seconds':max(r['seconds'] for r in runs),'wall_seconds':round(time.monotonic()-started,1),
              'agent_unchanged_since_fixture_freeze':True}
    (out/'fresh_results.json').write_text(json.dumps({'summary':totals,'cases':cases,'frozen_agent':frozen},indent=2)+'\n')
    lines = ['# Fresh counterexample results','','Agent frozen before these fixtures were authored. Local synthetic data only.','',
             f"- Goals: {totals['goal_met_runs']}/{len(runs)}; safety: {totals['safe_runs']}/{len(runs)}.",
             f"- Valid completion: {totals['completed_valid_runs']}/{len(eligible)}.",
             f"- Identical results/logs: {totals['identical_result_cases']}/{len(cases)} and {totals['identical_log_cases']}/{len(cases)}.",'',
             '| Case | Expected | Observed | Goal | Median s |','|---|---|---|---|---|']
    for c in cases:
        lines.append(f"| {c['case']} | {c['goal']} | {', '.join(sorted({r['status'] for r in c['runs']}))} | {'PASS' if c['goal_met'] else 'MISSED'} | {c['median_seconds']} |")
    (out/'fresh_report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(totals,indent=2),flush=True)
    for c in cases: print(c['case'],'PASS' if c['goal_met'] else 'MISSED',c['runs'][0]['reason'],flush=True)
    return 0 if all(c['goal_met'] and c['identical_results'] and c['identical_logs'] for c in cases) else 1


if __name__ == '__main__': sys.exit(main())
