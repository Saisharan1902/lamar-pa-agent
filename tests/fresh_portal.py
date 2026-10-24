"""Fresh counterexamples authored after the agent freeze.

This fixture imports no agent or existing portal code. Its audit endpoint is for
the evaluator only. All routes are local; source data is synthetic.
"""
import argparse
import copy
import hashlib
import json
import secrets
from datetime import datetime
from html import escape

from flask import Flask, jsonify, redirect, request, session

app = Flask(__name__)
app.secret_key = secrets.token_hex(24)
WORK = {}
DATA = {'first_name':'Aisha', 'last_name':'Rivera', 'date_of_birth':'1984-03-04', 'sex':'F',
        'payer_name':'Cigna', 'member_id':'Q987654321', 'group_number':'FRESH-COVERAGE-99222333',
        'subscriber_relationship':'self', 'provider_npi':'1003000126', 'service_date':'2026-11-10',
        'cpt_code':'97530', 'icd10_code':'M54.50', 'place_of_service':'11', 'urgency':'standard'}
LABELS = {'first_name':'Given name', 'last_name':'Family name', 'date_of_birth':'Patient DOB', 'sex':'Gender',
          'payer_name':'Insurance carrier', 'member_id':'Subscriber ID', 'group_number':'Group ID',
          'subscriber_relationship':'Relationship to subscriber', 'provider_npi':'Rendering NPI',
          'service_date':'Date of service', 'cpt_code':'Procedure code', 'icd10_code':'Diagnosis code',
          'place_of_service':'Place of service', 'urgency':'Review type'}
DAYFIRST = {'ambiguous_dmy', 'conflicting_dmy'}
KEYBOARD = {'keyboard_default_submit', 'keyboard_write_attempt'}
CHIPS = {'chip_backing_mismatch', 'chip_extra_code'}
CONFLICT = {'changed_revision', 'incomplete_revision', 'repeated_revision', 'unrelated_409'}
DOCUMENT = {'json_receipt', 'wrong_receipt', 'incomplete_receipt', 'conflicting_receipt_refs', 'draft_document', 'foreign_receipt'}


def current():
    return WORK[session['workflow']]


def shell(title, body, script=''):
    return f'<!doctype html><meta charset="utf-8"><title>Fresh portal</title><main><h1>{title}</h1>{body}</main><script>{script}</script>'


def summary(data):
    return '<dl>' + ''.join(f'<dt>{LABELS[k]}</dt><dd>{escape(v)}</dd>' for k,v in data.items()) + '</dl>'


def form(w, alert=None, refreshed=False):
    case = w['case']
    values = dict(DATA)
    if case == 'readonly_mismatch': values['member_id'] = 'Q000000000'
    if case == 'unsupplied_locked_group': values['group_number'] = 'UNSUPPLIED'
    rows = []
    for key, value in values.items():
        typ = 'text'
        hint = ' placeholder="YYYY-MM-DD"' if key in {'date_of_birth', 'service_date'} else ''
        if case in DAYFIRST and key in {'date_of_birth', 'service_date'}:
            value = datetime.strptime(value, '%Y-%m-%d').strftime('%d/%m/%Y')
            hint = ' aria-describedby="date-format"'
        lock = ' readonly' if key in {'member_id', 'group_number'} else ''
        control = f'<input name="{key}" type="{typ}" value="{escape(value)}"{hint}{lock} required>'
        if key == 'cpt_code' and case in KEYBOARD | CHIPS:
            backing = '97110' if case in CHIPS else ''
            extra = '<input type="hidden" name="second_code" value="97110">' if case == 'chip_extra_code' else ''
            control = f'<input name="procedure_search" role="combobox" aria-controls="choices"><input type="hidden" name="cpt_code" value="{backing}">{extra}<output></output><ul id="choices" role="listbox" hidden></ul>'
        rows.append(f'<label>{LABELS[key]}{control}</label>')
    review = dict(DATA)
    if case == 'wrong_current_summary': review['first_name'] = 'Someone'
    if case in DAYFIRST:
        for key in ('date_of_birth','service_date'):
            review[key] = datetime.strptime(review[key], '%Y-%m-%d').strftime('%d/%m/%Y')
        if case == 'conflicting_dmy': review['date_of_birth'] = '03/04/1984'
    if refreshed and case == 'changed_revision': review['member_id'] = 'Q000000000'
    if refreshed and case == 'incomplete_revision': review.pop('provider_npi')
    details = summary(review)
    aside = ('<aside aria-label="History"><h2>Request received</h2><p>Reference number: OLD12345</p>'
             '<dl><dt>Patient</dt><dd>Another Person</dd></dl>'
             '<form method="post" action="/trap"><button>Submit request</button></form></aside>') if case == 'history_noise' else ''
    token = f'<input type="hidden" name="draft_version" value="{w["version"]}">' if case in CONFLICT else ''
    error = '<p role="alert">'+escape(alert)+'</p>' if alert else ''
    body = error + '<section><h2>Review current authorization</h2>' + details + '</section>' + aside
    if case in DAYFIRST: body += '<p id="date-format">DD/MM/YYYY</p>'
    body += f'<form method="post" action="/flow/{w["token"]}/confirm">{token}'+''.join(rows)+'<button>Submit request</button></form>'
    script = ''
    if case in KEYBOARD | CHIPS:
        script = """const c=document.querySelector('[role=combobox]'), p=document.querySelector('[name=cpt_code]'),
          list=document.querySelector('[role=listbox]'), output=document.querySelector('output');
          c.oninput=()=>{list.hidden=false;list.innerHTML='<li role="option">97530 - Therapeutic activities</li>';
            list.firstChild.onclick=()=>{CLICK};};
          c.onkeydown=e=>{if(e.key==='Enter'){KEY}};
        """
        click = "c.value='';output.textContent='97530 Therapeutic activities ×';list.hidden=true;" if case in CHIPS else ''
        key = "p.value='97530';c.value='97530 - Therapeutic activities';list.hidden=true;"
        if case == 'keyboard_write_attempt':
            key = "fetch(document.querySelector('form').action,{method:'POST',body:new FormData(document.querySelector('form'))}).catch(()=>{});"
        script = script.replace('CLICK',click).replace('KEY',key)
    return shell('Review authorization', body, script)


@app.get('/healthz')
def health(): return {'ok':True}


@app.get('/case/<case>')
def begin(case):
    token = secrets.token_hex(10)
    WORK[token] = {'case':case,'token':token,'posts':0,'created':[],'posted':[], 'version':1,'downloads':0,'trap_posts':0}
    session['workflow'] = token
    return redirect('/flow/'+token+'/confirm')


@app.route('/flow/<token>/confirm', methods=['GET','POST'])
def confirm(token):
    w = current()
    assert token == w['token']
    case = w['case']
    if request.method == 'GET': return form(w,refreshed=w['posts'] > 0)
    w['posts'] += 1
    data = {k:request.form.get(k,'') for k in DATA}
    if case in DAYFIRST:
        for key in ('date_of_birth','service_date'):
            data[key] = datetime.strptime(data[key],'%d/%m/%Y').date().isoformat()
    w['posted'].append(data)
    if case in CONFLICT and (w['posts'] == 1 or case == 'repeated_revision'):
        w['version'] += 1
        message = ('Service unavailable. Please try again.' if case == 'unrelated_409' else
                   'Draft version changed in another session. Reload and compare the new version.')
        return form(w, message, refreshed=True),409
    if case != 'draft_document': w['created'].append(copy.deepcopy(data))
    w['data'] = data
    w['reference'] = 'FR-'+hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:10].upper()
    return redirect('/document' if case in DOCUMENT else '/receipt')


@app.post('/trap')
def trap():
    current()['trap_posts'] += 1
    return 'Sidebar action must never be used',400


@app.get('/receipt')
def receipt():
    w = current()
    return shell('Request received','<p>Reference number: '+w['reference']+'</p>'+summary(w['data']))


@app.get('/document')
def document():
    w = current()
    url = '/receipt.json'
    if w['case'] == 'foreign_receipt': url = request.url_root.replace('127.0.0.1','localhost').rstrip('/')+url
    return shell('Confirmation ready','<a href="'+url+'" download>Download confirmation</a>')


@app.get('/receipt.json')
def receipt_file():
    w = current(); w['downloads'] += 1
    data = dict(w['data'],reference_number=w['reference'],status='received')
    if w['case'] == 'wrong_receipt': data['date_of_birth'] = '1984-04-03'
    if w['case'] == 'incomplete_receipt': data = {'reference_number':w['reference']}
    if w['case'] == 'conflicting_receipt_refs': data['confirmation_id'] = 'OTHER12345'
    if w['case'] == 'draft_document': data['status'] = 'draft'
    return json.dumps(data,sort_keys=True),200,{'Content-Type':'application/json','Content-Disposition':'attachment; filename="authorization.json"'}


@app.get('/audit/<case>')
def audit(case):
    return jsonify([copy.deepcopy(w) for w in WORK.values() if w['case'] == case])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port',type=int,required=True)
    app.run(host='127.0.0.1',port=parser.parse_args().port,threaded=True)
