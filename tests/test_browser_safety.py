"""Independent local portal faults; assert side effects, saved payload and recovery behavior.

These fixtures do not import either mock portal or their scenario implementations.
"""
import json
import logging
import threading
from datetime import date
from html import escape
from pathlib import Path

import pytest
from flask import Flask, request
from werkzeug.serving import make_server
from playwright.sync_api import Locator, TimeoutError as PWTimeout

from agent.runner import Agent
from agent.ledger import Ledger

RECORD = json.loads((Path(__file__).resolve().parents[1] / 'sample_patients.json').read_text())[0]
LABELS = {'first_name':'First name', 'last_name':'Last name', 'sex':'Sex',
          'date_of_birth':'Date of birth', 'patient_zip':'Patient ZIP',
          'insurance_state':'Insurance state', 'rx_bin':'RxBIN', 'rx_pcn':'RxPCN',
          'medication_search':'Medication'}


@pytest.fixture
def portal():
    app = Flask(__name__)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    state = {'posts':0, 'created':[], 'loads':0, 'chosen':None}

    def receipt(case):
        if case == 'explicit_failure':
            return '<h1>Submission not accepted</h1><p>Reason: Plan rejected this request.</p><p>No request was created.</p>'
        vals = {k:RECORD[k] for k in LABELS}
        if case == 'wrong_saved_dob': vals['date_of_birth'] = '01/01/2000'
        if case == 'wrong_saved_drug': vals['medication_search'] = 'Humira 40MG'
        pairs = ''.join(f'<dt>{LABELS[k]}</dt><dd>{escape(v)}</dd>' for k,v in vals.items())
        if case == 'wrong_saved_form': pairs += '<dt>Form</dt><dd>Unknown unrelated form</dd>'
        footer = '<footer>You will hear whether the request is approved or denied.</footer>'
        extra_id = '<p>Reference number: OTHER12345</p>' if case == 'conflicting_references' else ''
        conflict = '<p role="alert">Submission failed</p>' if case == 'conflicting_outcomes' else ''
        return f'<h1>Request received</h1><p>Reference number: NEW12345</p><dl>{pairs}</dl>{conflict}{extra_id}{footer}'

    @app.get('/<case>')
    def home(case):
        if case == 'existing_receipt': return receipt(case)
        controls = ''.join(f'<label>{label}<input name="{k}" value="{escape(RECORD[k])}"></label>'
                           for k,label in LABELS.items() if not (case == 'missing_sex' and k == 'sex'))
        if case == 'unsupplied_group':
            controls += '<label>Rx group<input name="rx_group" value="UNSUPPLIED"></label>'
        if case == 'unsupplied_group_review':
            controls += '<dl><dt>Rx group</dt><dd>UNSUPPLIED</dd></dl>'
        changed_review = '<dl><dt>Date of birth</dt><dd>01/01/2000</dd></dl>' if case == 'wrong_review' else ''
        mutation = '''document.querySelector('[name=last_name]').addEventListener('input',()=>{
          const f=document.querySelector('[name=first_name]'); f.value='Someone'; f.disabled=true;
        });''' if case == 'hydration_reset' else ''
        if case == 'hydration_reset': controls = controls.replace('value="Test"','value=""')
        confirm = "if(!confirm('Continue and create this request?')) return;" if case == 'native_confirm' else ''
        names = ['Texas Medicaid', 'Oklahoma Medicaid']
        forms = case in ('wrong_state', 'api_mismatch', 'api_matches', 'all_wrong_state', 'api_empty', 'wrong_saved_form')
        if case == 'all_wrong_state': names = ['Texas Medicaid', 'Kansas Medicaid']
        buttons = (''.join(f'<section><h2>{name}</h2><button type="button" data-choice="{name}">Start request</button></section>'
                           for name in names) if forms else '<button type="submit">Submit request</button>')
        api_script = "fetch(location.pathname+'/forms').then(r=>r.json()).then(()=>{});" if forms else ''
        # POST document errors test browser form resubmission, not an AJAX redirect.
        if case == 'post_document_error':
            return f'<h1>Authorization</h1><form method="post" action="/{case}/submit">{controls}{buttons}</form>'
        return f'''<h1>Authorization</h1><form>{controls}{changed_review}{buttons}</form><div id="message"></div>
        <script>{mutation}{api_script}
        async function send(e){{e.preventDefault();{confirm}
          const f=document.querySelector('form');
          const data=new FormData(f);data.set('chosen',e.target.dataset.choice||'');
          const r=await fetch(location.pathname+'/submit',{{method:'POST',body:data}});
          const b=await r.json();if(b.url) location.href=b.url;
          else document.querySelector('#message').innerHTML='<p role="alert">'+b.message+'</p>';
        }}
        document.querySelector('form').onsubmit=send;
        document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=send);
        </script>'''

    @app.get('/<case>/forms')
    def forms(case):
        names = ['Texas Medicaid','Oklahoma Medicaid']
        if case == 'api_mismatch': names.reverse()
        if case == 'api_empty': names = []
        if case == 'all_wrong_state': names = ['Texas Medicaid','Kansas Medicaid']
        return {'forms':[{'title':n} for n in names]}

    @app.post('/<case>/submit')
    def submit(case):
        state['posts'] += 1
        if case == 'explicit_not_created' and state['posts'] == 1:
            return {'message':'Your request was not created. Please try again.'},503
        if case == 'explicit_failure': return {'url':f'/{case}/result'}
        state['created'].append(dict(request.form))
        state['chosen'] = request.form.get('chosen')
        if case == 'generic_commit_error':
            return {'message':'Service temporarily unavailable. Please try again.'},503
        if case == 'post_document_error': return '<h1>Error loading Request</h1>',500
        return {'url':f'/{case}/result'}

    @app.get('/<case>/result')
    def result(case):
        state['loads'] += 1
        if case == 'perpetual_load_error' or (case == 'transient_load_error' and state['loads']==1):
            return '<h1>Error loading Request</h1>',500
        return receipt(case)

    server = make_server('127.0.0.1',0,app,threaded=True)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', state
    server.shutdown()
    thread.join(timeout=3)


def run(portal, tmp_path, case):
    base, state = portal
    agent = Agent(base+'/'+case,RECORD,date(2026,11,2),tmp_path/'ledger')
    return agent, agent.run(), state


@pytest.mark.parametrize('case,expected,created,posts',[
    ('existing_receipt','ESCALATED',0,0),
    ('unsupplied_group','ESCALATED',0,0),
    ('unsupplied_group_review','ESCALATED',0,0),
    ('explicit_failure','FAILED',0,1),
    ('missing_sex','ESCALATED',0,0),
    ('wrong_review','ESCALATED',0,0),
    ('wrong_saved_dob','ESCALATED',1,1),
    ('wrong_saved_drug','ESCALATED',1,1),
    ('wrong_saved_form','ESCALATED',1,1),
    ('generic_commit_error','ESCALATED',1,1),
    ('explicit_not_created','SUCCESS',1,2),
    ('denied_in_footer','SUCCESS',1,1),
    ('conflicting_outcomes','ESCALATED',1,1),
    ('native_confirm','ESCALATED',0,0),
    ('transient_load_error','SUCCESS',1,1),
    ('perpetual_load_error','ESCALATED',1,1),
    ('post_document_error','ESCALATED',1,1),
    ('wrong_state','SUCCESS',1,1),
    ('all_wrong_state','ESCALATED',0,0),
    ('api_mismatch','ESCALATED',0,0),
    ('api_empty','ESCALATED',0,0),
    ('conflicting_references','ESCALATED',1,1),
    ('api_matches','SUCCESS',1,1),
    ('hydration_reset','ESCALATED',0,0),
])
def test_independent_portal_fault(portal,tmp_path,case,expected,created,posts):
    agent,res,state = run(portal,tmp_path,case)
    assert res['status'] == expected, res
    assert len(state['created']) == created
    assert state['posts'] == posts
    if expected == 'SUCCESS':
        for k in LABELS:
            assert state['created'][0][k] == RECORD[k]
    if case in ('wrong_state','api_matches'):
        assert state['chosen'] == 'Oklahoma Medicaid'
        assert res['form_selection']['skipped_other_state'] == ['Texas Medicaid']
    if case in ('transient_load_error','perpetual_load_error'):
        assert state['loads'] == 2
        assert sum(e['action']=='reload' for e in agent.log.entries) == 1
    if case == 'post_document_error':
        assert not any(e['action']=='reload' for e in agent.log.entries)
    if case == 'native_confirm':
        assert any(e['action']=='native_dialog' and e['kind']=='confirm' for e in agent.log.entries)
    # A rerun of every uncertain post-click outcome must cause no new submission.
    if expected == 'ESCALATED' and created:
        _,again,state = run(portal,tmp_path,case)
        assert again['status'] == 'ESCALATED'
        assert len(state['created']) == created and state['posts'] == posts


def test_timeout_after_server_commit_never_reclicks(portal,tmp_path,monkeypatch):
    click = Locator.click
    # Use the locator selector instead of reading a locator detached by navigation.
    def timeout(self,*args,**kwargs):
        submitting = not kwargs.get('trial') and self.inner_text() == 'Submit request'
        result = click(self,*args,**kwargs)
        if submitting: raise PWTimeout('Timed out after navigation committed')
        return result
    monkeypatch.setattr(Locator,'click',timeout)
    _,res,state=run(portal,tmp_path,'click_timeout')
    assert res['status']=='ESCALATED'
    assert len(state['created'])==1 and state['posts']==1
    _,res,state=run(portal,tmp_path,'click_timeout')
    assert res['status']=='ESCALATED' and state['posts']==1


def test_ledger_claim_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    gate=threading.Barrier(8)
    def claim(_):
        ledger=Ledger(tmp_path)
        gate.wait()
        return ledger.claim('same-patient')
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(claim,range(8))).count(True)==1
