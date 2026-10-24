"""Ensure challenge workflows are solvable fixtures, not impossible benchmark traps."""
import importlib.util
import io
from pathlib import Path
import re
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'portal_b'))
spec=importlib.util.spec_from_file_location('hard_fixture_app',ROOT/'portal_b/app.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from test_contract import MED


@pytest.fixture
def client():
    module.app.config['TESTING']=True
    return module.app.test_client()


def enter(client,case):
    response=client.get('/challenge/'+case,follow_redirects=True)
    data=dict(MED)
    if case in ('dependent_subscriber','combined_handoff'):
        data.update(subscriber_relationship='child',subscriber_first_name='Ana',subscriber_last_name='Gonzalez',subscriber_dob='1960-04-12')
    if case=='combined_handoff':data['first_name']='Zoë  Anne'
    from challenges import FIELDS
    for step in ('patient','coverage','service'):
        form={k:data.get(k,'') for k in FIELDS[step]}
        if case=='day_first_review':
            from datetime import datetime
            for k in ('date_of_birth','subscriber_dob','service_date'):
                if form.get(k):form[k]=datetime.strptime(form[k],'%Y-%m-%d').strftime('%d/%m/%Y')
        if case=='locked_policy_fields' and step=='coverage':form={}
        response=client.post(f'/challenge/{case}/{step}',data=form,follow_redirects=True)
        if response.status_code==419:
            response=client.get(f'/challenge/{case}/{step}')
            token=re.search(r'name="csrf" value="([^"]+)"',response.text).group(1)
            response=client.post(f'/challenge/{case}/{step}',data={**form,'csrf':token},follow_redirects=True)
        assert response.status_code==200,(case,step,response.status_code)
    return data


@pytest.mark.parametrize('case',['baseline','dependent_subscriber','locked_policy_fields','rotating_csrf',
 'revision_conflict','queued_acceptance','queued_denial','spa_review','day_first_review','localized_actions',
 'unicode_label','chips_procedure','keyboard_commit','download_only_receipt','draft_receipt','history_on_review','combined_handoff'])
def test_human_can_complete_or_verify_fixture(client,case):
    data=enter(client,case)
    response=client.post(f'/challenge/{case}/review',data={'revision':'1'},follow_redirects=True)
    if case=='revision_conflict':
        assert response.status_code==409
        response=client.post(f'/challenge/{case}/review',data={'revision':'2'},follow_redirects=True)
    if case in ('queued_acceptance','queued_denial','combined_handoff'):
        for _ in range(4):response=client.get(f'/challenge/{case}/job')
        assert response.json['html']
    audit=client.get('/challenge/audit/'+case).json[-1]
    if case in ('queued_denial','draft_receipt'):
        assert audit['created']==[]
    else:
        assert audit['created']==[data]
    if case=='download_only_receipt':
        assert 'Download receipt' in response.text
        document=client.get(f'/challenge/{case}/receipt.txt')
        assert document.mimetype=='text/plain' and audit['ref'] in document.text
