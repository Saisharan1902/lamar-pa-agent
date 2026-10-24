"""A success status must not hide a wrong persisted field."""
import copy
import io
import json
from types import SimpleNamespace

import pytest

import run_eval

RECORD=run_eval.SAMPLES['P001_trace_exact']


def saved_record():
    return {'patient':{k:RECORD[k] for k in ('first_name','last_name','sex','date_of_birth','patient_zip','insurance_state')},
            'insurance':{k:RECORD[k] for k in ('rx_bin','rx_pcn','rx_group')},
            'drug':'Simponi Aria 50MG/4ML solution','form':{'title':'Oklahoma Form'}}


@pytest.mark.parametrize('field',['first_name','last_name','sex','date_of_birth','patient_zip','insurance_state',
                                   'rx_bin','rx_pcn','rx_group','drug','form'])
def test_wrong_saved_field_fails_evaluation(monkeypatch,field):
    saved=saved_record()
    if field=='form':saved['form']['title']='Another Form'
    elif field=='drug':saved['drug']='Another medication'
    elif field in saved['patient']:saved['patient'][field]='WRONG'
    else:saved['insurance'][field]='UNSUPPLIED'
    monkeypatch.setattr(run_eval.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(json.dumps({'records':{'REF12345':saved}}).encode()))
    result={'status':'SUCCESS','confirmation_id':'REF12345','form_selection':{'chosen':'Oklahoma Form'}}
    assert run_eval.verify_saved(SimpleNamespace(base='http://test'),RECORD,result)[0] is False


def test_success_without_confirmation_fails_evaluation():
    assert run_eval.verify_saved(SimpleNamespace(base='http://test'),RECORD,{'status':'SUCCESS'})[0] is False


def test_native_date_presentation_is_the_same_calendar_date(monkeypatch):
    saved=saved_record();saved['patient']['date_of_birth']='1986-11-13'
    monkeypatch.setattr(run_eval.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(json.dumps({'records':{'REF12345':saved}}).encode()))
    result={'status':'SUCCESS','confirmation_id':'REF12345','form_selection':{'chosen':'Oklahoma Form'}}
    assert run_eval.verify_saved(SimpleNamespace(base='http://test'),RECORD,result)[0] is True
