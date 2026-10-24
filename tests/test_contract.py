"""Contract regressions and a medical happy path independent of pharmacy portals."""
import json
import logging
import subprocess
import sys
import threading
from datetime import date
from html import escape
from pathlib import Path

import pytest
from flask import Flask, request, redirect
from werkzeug.serving import make_server

from agent.runner import Agent
from agent.validate import validate_record

ROOT=Path(__file__).resolve().parents[1]
TODAY=date(2026,11,2)
MED={"first_name":"Maria", "last_name":"Gonzalez", "date_of_birth":"1984-03-22", "sex":"F",
     "payer_name":"Aetna", "member_id":"W123456789", "group_number":"GRP-12345678901234567890",
     "subscriber_relationship":"self", "provider_npi":"1003000126", "service_date":"2026-11-10",
     "cpt_code":"97110", "icd10_code":"M54.50", "place_of_service":"11", "urgency":"standard"}
LABELS={"first_name":"First name", "last_name":"Last name", "date_of_birth":"Date of birth",
        "sex":"Sex", "payer_name":"Payer", "member_id":"Member ID", "group_number":"Group number",
        "subscriber_relationship":"Relationship to subscriber", "subscriber_first_name":"Subscriber first name",
        "subscriber_last_name":"Subscriber last name", "subscriber_dob":"Subscriber date of birth",
        "provider_npi":"Provider NPI", "service_date":"Service date", "cpt_code":"CPT code",
        "icd10_code":"ICD-10 code", "place_of_service":"Place of service", "urgency":"Urgency"}


@pytest.mark.parametrize('name',["Mary  Ann", "Anne--Marie", "O’Connor", "José"])
def test_documented_name_characters_are_preserved(name):
    record=dict(MED,first_name=name)
    sent,issues=validate_record(record,TODAY)
    assert not issues and sent['first_name']==name


def test_long_medical_group_and_captured_bin():
    assert not validate_record(MED,TODAY)[1]
    samples=json.loads((ROOT/'sample_patients.json').read_text())
    sent,issues=validate_record(samples[1],TODAY)
    assert not issues and sent['rx_bin']=='22022'
    assert validate_record(dict(samples[1],rx_bin='61060'),TODAY)[1]


@pytest.mark.parametrize('content',['{bad','[]','[{},{}]','null','"patient"'])
def test_invalid_json_always_writes_result_and_log(tmp_path,content):
    patient=tmp_path/'input.json';patient.write_text(content)
    output=tmp_path/'new'/'nested'/'result.json'
    log=tmp_path/'other'/'folder'/'actions.jsonl'
    proc=subprocess.run([sys.executable,'-m','agent.cli','--portal-url','http://127.0.0.1:1',
                         '--patient',str(patient),'--out',str(output),'--log',str(log)],cwd=ROOT,capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    result=json.loads(output.read_text())
    assert result['status']=='ESCALATED' and result['escalation']['field']=='patient_file'
    assert json.loads(log.read_text().splitlines()[-1])['action']=='end'


def test_invalid_date_reports_configuration_issue(tmp_path):
    output=tmp_path/'new'/'result.json'
    proc=subprocess.run([sys.executable,'-m','agent.cli','--portal-url','http://127.0.0.1:1',
                         '--patient','missing.json','--out',str(output),'--as-of','invalid'],cwd=ROOT,capture_output=True,text=True)
    assert proc.returncode==0 and json.loads(output.read_text())['escalation']['field']=='as_of'


@pytest.fixture
def medical_portal():
    app=Flask(__name__);saved=[]
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    @app.get('/<case>')
    def form(case):
        controls=[]
        fields=list(MED)
        if case=='dependent':fields += ['subscriber_first_name','subscriber_last_name','subscriber_dob']
        for k in fields:
            choices={'sex':['M','F','X'],'payer_name':['Aetna','Cigna'],'place_of_service':['11','22'],
                     'subscriber_relationship':['self','spouse','child','other'],'urgency':['standard','expedited']}.get(k)
            if choices:
                control='<select name="'+k+'"><option value=""></option>'+''.join(f'<option>{v}</option>' for v in choices)+'</select>'
            else:control=f'<input name="{k}">'
            controls.append(f'<label>{LABELS[k]}{control}</label>')
        return f'<h1>Authorization intake</h1><form method="post" action="/{case}/submit">'+''.join(controls)+'<button>Submit request</button></form>'
    @app.post('/<case>/submit')
    def submit(case):
        saved.append(dict(request.form));return redirect('/'+case+'/receipt')
    @app.get('/<case>/receipt')
    def receipt(case):
        pairs=''.join(f'<dt>{LABELS[k]}</dt><dd>{escape(v)}</dd>' for k,v in saved[-1].items())
        return '<h1>Request received</h1><p>Reference number: MED123456</p><dl>'+pairs+'</dl>'
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',saved
    server.shutdown();thread.join(timeout=3)


@pytest.mark.parametrize('case',['self','dependent'])
def test_valid_medical_record_completes(medical_portal,tmp_path,case):
    base,saved=medical_portal
    record=dict(MED)
    if case=='dependent':record.update(subscriber_relationship='child',subscriber_first_name='Ana',
                                       subscriber_last_name='Gonzalez',subscriber_dob='1960-04-12')
    agent=Agent(base+'/'+case,record,TODAY,tmp_path/'ledger')
    result=agent.run()
    assert result['status']=='SUCCESS',result
    assert len(saved)==1
    for field,value in record.items():
        expected={'date_of_birth':'03/22/1984','service_date':'11/10/2026','subscriber_dob':'04/12/1960'}.get(field,value)
        assert saved[0][field]==expected,(field,saved[0])


def test_unassociated_portal_error_escalates_without_refilling():
    from agent.errors import Escalate
    from agent.actionlog import ActionLog
    agent=Agent('http://localhost:1',MED,TODAY,Path('/private/tmp')/'lamar-general-error-unit')
    agent._settle=lambda:None
    agent._check_dialogs=lambda:None
    agent.page=object()
    agent._eval=lambda _: {'password':False}
    agent._field_errors=lambda:[(None,'','Supporting clinical document is required.')]
    from unittest.mock import patch
    with patch('agent.runner.interrupts.handle',return_value=False):
        with pytest.raises(Escalate,match='blocked this step'):
            agent._check_errors_after()
