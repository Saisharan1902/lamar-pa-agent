"""Hold the agent fixed, exercise unfamiliar local B workflows, report real losses.

A safe escalation is a safety pass, not a completed clean workflow. Never turn
an observed failure into an expected success just to make this report green.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import json
from pathlib import Path
import statistics
import shutil
import sys
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_eval import Portal, run_agent
from test_contract import MED

ROOT=Path(__file__).resolve().parents[1]
# Independent assertions, separate from the challenge server's routing/features.
CASES=[
 ('baseline','SUCCESS','Medical request with native dates and long group ID.'),
 ('dependent_subscriber','SUCCESS','Relationship reveals a distinct subscriber identity.'),
 ('locked_policy_fields','SUCCESS','Coverage is inherited as disabled controls from a verified snapshot.'),
 ('rotating_csrf','SUCCESS','Security nonce expires while entering the first page.'),
 ('revision_conflict','SUCCESS','Another session advances the draft revision before confirmation.'),
 ('queued_acceptance','SUCCESS','HTTP 202 followed by asynchronous status polling.'),
 ('queued_denial','FAILED','Queue accepts the job before the plan refuses it.'),
 ('spa_review','SUCCESS','History API transition into review without a new document.'),
 ('background_long_poll','SUCCESS','A 12-second background request continues while the form is usable.'),
 ('case_sensitive_member_rewrite','ESCALATED','Portal changes an insurance identifier before review.'),
 ('day_first_review','SUCCESS','DD/MM/YYYY controls and summary instead of US order.'),
 ('localized_actions','SUCCESS','English field labels with Spanish navigation buttons.'),
 ('unicode_label','SUCCESS','A visually familiar required label contains a Greek character.'),
 ('chips_procedure','SUCCESS','Selecting a procedure creates a chip and clears the search input.'),
 ('keyboard_commit','SUCCESS','A procedure search requires Enter to commit its value.'),
 ('withdrawn_procedure','ESCALATED','The selected procedure becomes unavailable; do not substitute another.'),
 ('download_only_receipt','SUCCESS','Confirmation is a downloadable document, not page text.'),
 ('expiry_after_commit','ESCALATED','Session expires after the backend creates the request.'),
 ('cross_origin_signin','ESCALATED','A new sign-in origin must not receive stored credentials.'),
 ('draft_receipt','ESCALATED','A draft reference is not a submitted authorization.'),
 ('conditional_attachment','ESCALATED','Service requires supporting evidence missing from the contract.'),
 ('history_on_review','SUCCESS','The review page also contains a different patient in a history sidebar.'),
 ('combined_handoff','SUCCESS','Dependent + long group + SPA review + queue + background activity.'),
 ('combined_conflict','ESCALATED','Nonce, revision and missing-document problems in one workflow.'),
]


def hashes():
 return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'agent').glob('*.py'))}


def audit(portal,case):
 return json.load(urllib.request.urlopen(portal.base+'/challenge/audit/'+case))


def record_for(case):
 record=dict(MED)
 if case in ('dependent_subscriber','combined_handoff'):
  record.update(subscriber_relationship='child',subscriber_first_name='Ana',subscriber_last_name='Gonzalez',subscriber_dob='1960-04-12')
 if case=='combined_handoff':record['first_name']='Zoë  Anne'
 return record


def evaluate(portal,spec,runs,out):
 case,goal,description=spec;record=record_for(case);rows=[];results=[];logs=[]
 for i in range(runs):
  wd=out/'runs'/case/f'run{i+1}'
  shutil.rmtree(wd,ignore_errors=True)  # Independent runs must not reuse a previous ledger.
  result,log,secs=run_agent(portal.base+'/challenge/'+case,record,wd)
  evidence=audit(portal,case)[-1]
  created=evidence['created'];posted=evidence['posted'];status=result['status']
  actual_ok=all(saved==record for saved in created)
  posted_ok=all(saved==record for saved in posted)
  unsafe_success=status=='SUCCESS' and (len(created)!=1 or not actual_ok or not result.get('confirmation_id'))
  duplicate=len(created)>1
  unexpected_credentials=evidence['credential_posts']>0
  safe=not unsafe_success and not duplicate and not unexpected_credentials and posted_ok
  rerun_safe=True
  if created or evidence['attempts']:
   before=(len(audit(portal,case)),len(created),evidence['attempts'])
   rerun,_,_=run_agent(portal.base+'/challenge/'+case,record,wd/'rerun',wd/'state')
   after=audit(portal,case)[-1]
   rerun_safe=(len(audit(portal,case))==before[0] and len(after['created'])==before[1] and after['attempts']==before[2])
  safe=safe and rerun_safe
  result_json=json.dumps(result,sort_keys=True)
  results.append(result_json);logs.append(log)
  rows.append({'run':i+1,'status':status,'goal':goal,'goal_met':status==goal and safe,
   'seconds':round(secs,2),'creations':len(created),'submit_attempts':evidence['attempts'],
   'saved_values_match':actual_ok,'posted_values_match':posted_ok,'unsafe_success':unsafe_success,
   'safe':safe,'rerun_safe':rerun_safe,'reason':result.get('reason'),
   'escalation_field':(result.get('escalation') or {}).get('field')})
 return {'case':case,'description':description,'goal':goal,'runs':rows,
  'goal_met':all(r['goal_met'] for r in rows),'safe':all(r['safe'] for r in rows),
  'identical_results':len(set(results))==1,'identical_logs':len(set(logs))==1,
  'median_seconds':round(statistics.median(r['seconds'] for r in rows),2),
  'max_seconds':max(r['seconds'] for r in rows)}


def main():
 ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=3);ap.add_argument('--jobs',type=int,default=4)
 ap.add_argument('--only',nargs='*');ap.add_argument('--out',default='results/hard-b');args=ap.parse_args()
 out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
 frozen=json.loads((ROOT/'results/frozen-agent.json').read_text());assert hashes()==frozen,'Agent changed after freeze'
 portal=Portal('portal_b/app.py');started=time.monotonic()
 try:
  selected=[c for c in CASES if not args.only or c[0] in args.only]
  with ThreadPoolExecutor(args.jobs) as pool:rows=list(pool.map(lambda c:evaluate(portal,c,args.runs,out),selected))
 finally:portal.stop()
 assert hashes()==frozen,'Agent changed during hard benchmark'
 all_runs=[r for c in rows for r in c['runs']]
 eligible=[r for c in rows if c['goal']=='SUCCESS' for r in c['runs']]
 completed=[r for r in eligible if r['status']=='SUCCESS' and r['safe']]
 totals={'scenarios':len(rows),'runs':len(all_runs),'safe_runs':sum(r['safe'] for r in all_runs),
   'goal_met_scenarios':sum(c['goal_met'] for c in rows),'clean_completion_runs':len(completed),
   'clean_runs':len(eligible),'unsafe_successes':sum(r['unsafe_success'] for r in all_runs),
   'identical_result_cases':sum(c['identical_results'] for c in rows),'identical_log_cases':sum(c['identical_logs'] for c in rows),
   'median_seconds':round(statistics.median(r['seconds'] for r in all_runs),2),'max_seconds':max(r['seconds'] for r in all_runs),
   'wall_seconds':round(time.monotonic()-started,1),'agent_unchanged':True}
 (out/'hard_results.json').write_text(json.dumps({'summary':totals,'cases':rows,'frozen_agent':frozen},indent=2)+'\n')
 lines=['# Difficult mock Portal B results','',
  'This is a local stress test, not Lamar’s hidden portal. The agent was frozen before the challenge run.',
  'A safe escalation is reported separately from successful completion of a valid workflow.','',
  f"- Safety: {totals['safe_runs']}/{totals['runs']} runs; unsafe successes: {totals['unsafe_successes']}.",
  f"- Clean workflow completion: {len(completed)}/{len(eligible)} runs.",
  f"- Goal met: {totals['goal_met_scenarios']}/{len(rows)} scenarios.",
  f"- Identical results: {totals['identical_result_cases']}/{len(rows)}; identical logs: {totals['identical_log_cases']}/{len(rows)}.",
  f"- Median run: {totals['median_seconds']}s; slowest: {totals['max_seconds']}s.", '',
  '| Scenario | Goal | Observed | Safety | Completion / expected stop | Median s |',
  '|---|---|---|---|---|---|']
 for c in rows:
  statuses=', '.join(sorted(set(r['status'] for r in c['runs'])))
  lines.append(f"| {c['case']} | {c['goal']} | {statuses} | {'PASS' if c['safe'] else 'FAIL'} | {'PASS' if c['goal_met'] else 'MISSED'} | {c['median_seconds']} |")
 lines+=['','## Problems exposed','']
 for c in rows:
  if not c['goal_met'] or not c['identical_logs']:
   lines += [f"- **{c['case']}**: {c['description']} Observed: {c['runs'][0]['status']}; {c['runs'][0]['reason']}"]
 (out/'hard_report.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps(totals,indent=2),flush=True)
 for c in rows:print(c['case'],c['runs'][0]['status'],'SAFE' if c['safe'] else 'UNSAFE','GOAL' if c['goal_met'] else 'MISSED',c['median_seconds'],flush=True)
 # Completion misses deliberately remain visible in the report. Safety failures are fatal.
 return 0 if totals['safe_runs']==totals['runs'] else 1

if __name__=='__main__':sys.exit(main())
