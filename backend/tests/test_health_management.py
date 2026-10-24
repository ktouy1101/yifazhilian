"""M04 acceptance: isolated databases, user reports only, no external providers."""
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from app.config import AISettings, WechatConfig
from app.db import Database, DEFAULT_DB_PATH, utcnow
from app.main import create_app
from app.api import health_management as hm

BASE = '/api/v1/health-management'
P, Q, V = 'demo-patient-001', 'demo-patient-002', 'demo-volunteer-001'


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect
    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', isolated)
    now = utcnow().astimezone(hm.LOCAL).replace(hour=12, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(hm, 'utcnow', lambda: now.astimezone(timezone.utc))
    db = Database(tmp_path / 'health.sqlite3')
    with TestClient(create_app(db, ai_settings=AISettings(), wechat_config=WechatConfig())) as client:
        headers = {}
        for who in (P, Q, V):
            login = client.post('/api/v1/auth/demo-login', json={'demo_alias': who, 'role': 'volunteer' if who == V else 'patient'})
            headers[who] = {'Authorization': 'Bearer ' + login.json()['access_token']}
        yield client, db, headers, now


def grant(rig, who=P):
    client, _, headers, _ = rig
    policy = client.get('/api/v1/consents', headers=headers[who]).json()['policies']['vitals']
    assert policy['policy_version'] == 'health-records-1' and not policy['external_network']
    result = client.post('/api/v1/consents', headers=headers[who], json={'scope': 'vitals', 'policy_version': policy['policy_version'], 'recipient': policy['recipient']})
    assert result.status_code == 201
    assert not result.json()['synthetic_only']


def call(rig, method, path='/overview', body=None, code=200, who=P):
    client, _, headers, _ = rig
    result = client.request(method, BASE + path, headers=headers[who], json=body)
    assert result.status_code == code, result.text
    return result.json()


def at(rig, clock, days=0):
    return datetime.combine(rig[3].date() + timedelta(days=days), time.fromisoformat(clock), hm.LOCAL).isoformat()


def entry(rig, **extra):
    return {'request_id': 'entry-one', 'kind': 'heart_rate', 'source': 'manual', 'value': 72,
            'measured_at': at(rig, '08:00'), **extra}


def plan(rig, **extra):
    return {'request_id': 'plan-one', 'name': '合成测试药品', 'dose': '1 测试单位', 'times': ['08:00', '20:00'],
            'start_date': (rig[3].date() - timedelta(days=1)).isoformat(), **extra}


def update_payload(p, **extra):
    return {k: p[k] for k in ('revision', 'name', 'dose', 'strength', 'times', 'start_date', 'end_date', 'note', 'status')} | extra


def report(d, **extra):
    return {k: d[k] for k in ('plan_id', 'plan_revision', 'scheduled_at', 'revision')} | {'status': 'taken', **extra}


def test_consent_is_current_explicit_and_revocation_blocks_all(rig):
    call(rig, 'GET', code=403)
    call(rig, 'POST', '/entries', entry(rig), code=403)
    client, _, headers, _ = rig
    assert client.get('/api/v1/medications', headers=headers[P]).status_code == 403
    assert client.post('/api/v1/medications', headers=headers[P], json={'name': 'test'}).status_code == 410
    assert client.delete('/api/v1/medications/test', headers=headers[P]).status_code == 410
    grant(rig)
    assert call(rig, 'GET')['entries'] == []
    client, db, headers, _ = rig
    with db.transaction(write=True) as c:
        c.execute("UPDATE consents SET policy_version='old' WHERE user_id=? AND scope='vitals'", (P,))
    call(rig, 'GET', code=403)
    grant(rig)
    client.delete('/api/v1/consents/vitals', headers=headers[P])
    call(rig, 'GET', code=403)
    call(rig, 'POST', '/plans', plan(rig), code=403)
    grant(rig)
    with db.transaction(write=True) as c:
        c.execute("UPDATE consents SET expires_at='2000-01-01T00:00:00+00:00' WHERE user_id=? AND scope='vitals'", (P,))
    call(rig, 'GET', code=403)


def test_entries_real_source_time_pair_and_idempotency(rig):
    grant(rig)
    payload = entry(rig, kind='blood_pressure', value=120, secondary_value=80, source='report')
    saved = call(rig, 'POST', '/entries', payload, 201)
    assert saved['source'] == 'report' and saved['unit'] == 'mmHg'
    assert saved['measured_at'] == hm.stamp(datetime.fromisoformat(payload['measured_at']))
    assert 'alert' not in saved
    assert call(rig, 'POST', '/entries', payload, 201)['id'] == saved['id']
    call(rig, 'POST', '/entries', payload | {'value': 121}, 409)
    corrected = {k: saved[k] for k in ('kind', 'source', 'measured_at', 'value', 'secondary_value', 'title', 'note', 'revision')} | {'value': 125}
    result = call(rig, 'PUT', '/entries/' + saved['id'], corrected)
    assert result['revision'] == 2
    assert call(rig, 'PUT', '/entries/' + saved['id'], corrected)['revision'] == 2
    call(rig, 'PUT', '/entries/' + saved['id'], corrected | {'value': 130}, 409)
    call(rig, 'DELETE', '/entries/' + saved['id'] + '?revision=1', code=409)
    call(rig, 'DELETE', '/entries/' + saved['id'] + '?revision=2')
    assert call(rig, 'GET')['entry_count'] == 0


@pytest.mark.parametrize('extra', [
    {'source': 'demo_device'}, {'source': 'hospital'}, {'kind': 'spo2', 'value': 101},
    {'value': 0}, {'kind': 'blood_pressure', 'secondary_value': 80},
    {'kind': 'blood_pressure', 'value': 120}, {'kind': 'heart_rate', 'secondary_value': 10},
    {'measured_at': '2020-02-01T12:00:00'}, {'measured_at': '2099-02-01T12:00:00+08:00'},
    {'user_id': Q}, {'kind': 'symptom', 'title': '自述', 'note': '身体感受'},
])
def test_reject_invalid_or_forged_entry(rig, extra):
    grant(rig)
    call(rig, 'POST', '/entries', entry(rig, **extra), 422)


def test_symptom_without_measurement_and_private_ownership(rig):
    grant(rig); grant(rig, Q)
    data = entry(rig, kind='symptom', value=None, title='自述睡眠', note='合成记录')
    row = call(rig, 'POST', '/entries', data, 201)
    assert call(rig, 'GET', who=Q)['entries'] == []
    call(rig, 'DELETE', '/entries/' + row['id'] + '?revision=1', code=404, who=Q)
    call(rig, 'GET', code=403, who=V)
    call(rig, 'POST', '/entries', data, 403, who=V)


def test_schedule_and_actual_report_are_separate_retry_safe_and_correctable(rig):
    grant(rig)
    p = call(rig, 'POST', '/plans', plan(rig), 201)
    assert call(rig, 'POST', '/plans', plan(rig), 201)['id'] == p['id']
    doses = call(rig, 'GET')['doses']
    assert len(doses) == 2 and all(d['status'] == 'pending' and d['actual_at'] is None for d in doses)
    payload = report(doses[0], actual_at=at(rig, '08:13'))
    saved = call(rig, 'PUT', '/doses', payload)
    assert saved['actual_at'] != saved['scheduled_at'] and saved['revision'] == 1
    assert call(rig, 'PUT', '/doses', payload)['revision'] == 1
    call(rig, 'PUT', '/doses', payload | {'status': 'skipped', 'actual_at': None}, 409)
    restored = call(rig, 'PUT', '/doses', report(saved, status='pending'))
    assert restored['actual_at'] is None and restored['revision'] == 2
    skipped = call(rig, 'PUT', '/doses', report(restored, status='skipped', note='本人确认'))
    assert skipped['status'] == 'skipped' and skipped['actual_at'] is None
    call(rig, 'PUT', '/doses', report(skipped), 422)  # actual time required
    call(rig, 'PUT', '/doses', report(skipped, actual_at=at(rig, '20:00')), 422)
    call(rig, 'PUT', '/doses', report(doses[1], scheduled_at=at(rig, '20:00', 1), actual_at=at(rig, '08:00')), 422)
    call(rig, 'PUT', '/doses', report(doses[1], plan_revision=999, actual_at=at(rig, '08:00')), 409)


def test_plan_versions_keep_past_and_change_future_with_snapshot(rig):
    grant(rig)
    p = call(rig, 'POST', '/plans', plan(rig), 201)
    first, future = call(rig, 'GET')['doses']
    call(rig, 'PUT', '/doses', report(first, actual_at=at(rig, '08:10')))
    updated = call(rig, 'PUT', '/plans/' + p['id'], update_payload(p, dose='2 测试单位'))
    rows = call(rig, 'GET')['doses']
    assert rows[0]['dose'] == '1 测试单位' and rows[0]['status'] == 'taken'
    assert rows[1]['dose'] == '2 测试单位' and rows[1]['plan_revision'] == 2
    call(rig, 'PUT', '/doses', report(future, actual_at=at(rig, '09:00')), 409)
    summary = call(rig, 'GET', '/summary?days=7')
    assert sorted(item['dose'] for item in summary['medication']['by_plan']) == ['1 测试单位', '2 测试单位']
    yesterday = call(rig, 'GET', '/overview?day=' + (rig[3].date() - timedelta(days=1)).isoformat())
    assert len(yesterday['doses']) == 2 and all(d['dose'] == '1 测试单位' for d in yesterday['doses'])
    paused = call(rig, 'PUT', '/plans/' + p['id'], update_payload(updated, status='paused'))
    rows = call(rig, 'GET')['doses']
    assert len(rows) == 1 and rows[0]['status'] == 'taken'
    call(rig, 'DELETE', '/plans/' + p['id'] + '?revision=' + str(paused['revision']))
    overview = call(rig, 'GET')
    assert not overview['plans'] and not overview['doses']


def test_postponement_is_task_only_and_cancelled_future_tasks_do_not_return(rig, monkeypatch):
    grant(rig)
    p = call(rig, 'POST', '/plans', plan(rig), 201)
    future = call(rig, 'GET')['doses'][1]
    saved = call(rig, 'PUT', '/doses', report(future, status='postponed', postponed_until=at(rig, '21:00')))
    assert saved['actual_at'] is None and saved['status'] == 'postponed'
    call(rig, 'PUT', '/plans/' + p['id'], update_payload(p, status='paused'))
    monkeypatch.setattr(hm, 'utcnow', lambda: (rig[3] + timedelta(hours=10)).astimezone(timezone.utc))
    assert len(call(rig, 'GET')['doses']) == 1


def test_plan_dates_times_and_owner_validation(rig):
    grant(rig); grant(rig, Q)
    for extra in ({'times': ['25:00']}, {'times': ['08:00', '08:00']}, {'times': []},
                  {'dose': '  '}, {'end_date': '2000-01-01'}, {'user_id': Q}):
        call(rig, 'POST', '/plans', plan(rig, **extra), 422)
    p = call(rig, 'POST', '/plans', plan(rig), 201)
    call(rig, 'PUT', '/plans/' + p['id'], update_payload(p), 404, who=Q)
    call(rig, 'DELETE', '/plans/' + p['id'] + '?revision=1', code=404, who=Q)
    row = call(rig, 'GET')['doses'][0]
    call(rig, 'PUT', '/doses', report(row, actual_at=at(rig, '08:10')), 404, who=Q)
    assert call(rig, 'GET', who=Q)['plans'] == []


def test_followup_retry_completion_isolation_and_delete(rig):
    grant(rig); grant(rig, Q)
    payload = {'request_id': 'followup-one', 'title': '合成复查', 'due_at': at(rig, '08:00', 1), 'note': '自填'}
    row = call(rig, 'POST', '/followups', payload, 201)
    assert call(rig, 'POST', '/followups', payload, 201)['id'] == row['id']
    call(rig, 'POST', '/followups', payload | {'title': '其他'}, 409)
    call(rig, 'PATCH', '/followups/' + row['id'], {'done': True}, 404, who=Q)
    call(rig, 'PATCH', '/followups/' + row['id'], {'done': True})
    assert call(rig, 'GET')['followups'][0]['done']
    call(rig, 'DELETE', '/followups/' + row['id'])
    assert call(rig, 'GET')['followups'] == []


def test_visit_summary_counts_due_unrecorded_upcoming_and_does_not_grade(rig):
    grant(rig); grant(rig, Q)
    call(rig, 'POST', '/entries', entry(rig), 201)
    call(rig, 'POST', '/entries', entry(rig, request_id='entry-symptom', kind='symptom', value=None,
                                         title='合成感受', note='用于摘要'), 201)
    p = call(rig, 'POST', '/plans', plan(rig), 201)
    assert p['name'] == '合成测试药品'
    today = call(rig, 'GET')['doses']
    yesterday = call(rig, 'GET', '/overview?day=' + (rig[3].date() - timedelta(days=1)).isoformat())['doses']
    assert len(today) == 2 and len(yesterday) == 2
    call(rig, 'PUT', '/doses', report(today[0], actual_at=at(rig, '08:13')))
    call(rig, 'PUT', '/doses', report(yesterday[0], status='skipped'))
    call(rig, 'POST', '/followups', {'request_id': 'summary-followup', 'title': '合成复查',
                                     'due_at': at(rig, '08:00', 1), 'note': ''}, 201)
    data = call(rig, 'GET', '/summary?days=7')
    assert data['start'] == (rig[3].date() - timedelta(days=6)).isoformat()
    assert data['end'] == rig[3].date().isoformat() and data['days'] == 7
    assert data['entries']['total'] == 2 and not data['entries']['truncated']
    assert data['entries']['by_kind'] == {'heart_rate': 1, 'spo2': 0, 'blood_pressure': 0, 'symptom': 1}
    assert data['entries']['latest'][0]['kind'] == 'heart_rate'
    assert data['symptoms']['count'] == 1 and data['symptoms']['items'][0]['title'] == '合成感受'
    med = data['medication']
    assert med['plans_in_period'] == 1 and med['total'] == 4 and med['due'] == 3
    assert (med['taken'], med['skipped'], med['postponed'], med['unrecorded'], med['upcoming']) == (1, 1, 0, 1, 1)
    assert med['by_plan'][0]['name'] == '合成测试药品' and med['by_plan'][0]['dose'] == '1 测试单位'
    assert data['followups']['pending_count'] == 1
    assert data['followups']['items'][0]['title'] == '合成复查'
    assert 'adherence' not in json.dumps(data, ensure_ascii=False)
    one_day = call(rig, 'GET', '/summary?days=1')['medication']
    assert (one_day['total'], one_day['due'], one_day['taken'], one_day['unrecorded'], one_day['upcoming']) == (2, 1, 1, 0, 1)
    other = call(rig, 'GET', '/summary?days=7', who=Q)
    assert other['entries']['total'] == 0 and other['medication']['total'] == 0
    call(rig, 'GET', '/summary?days=7', who=V, code=403)
    call(rig, 'GET', '/summary?days=0', code=422)
    call(rig, 'GET', '/summary?days=91', code=422)
    client, _, headers, _ = rig
    client.delete('/api/v1/consents/vitals', headers=headers[P])
    call(rig, 'GET', '/summary?days=7', code=403)


def test_v6_migration_pauses_legacy_medicine_without_promoting_demo_vitals(tmp_path):
    path = tmp_path / 'v6.sqlite3'
    schema = (Path(__file__).parents[1] / 'app/schema.sql').read_text(encoding='utf-8')
    with sqlite3.connect(path) as c:
        c.executescript(schema.split('-- M04:')[0] + 'PRAGMA user_version=6; COMMIT;')
        c.execute("INSERT INTO users(id,role,display_name) VALUES('legacy','patient','test')")
        c.execute("INSERT INTO medications(id,user_id,name,dose,scheduled_time,note,created_at) VALUES('old','legacy','test',NULL,'8:00','retained','2020-01-01')")
    db = Database(path)
    with db.transaction(write=True) as c:
        row = c.execute('SELECT * FROM health_medication_plans').fetchone()
        payload = json.loads(row['payload'])
        assert row['id'] == 'old' and payload['status'] == 'paused' and payload['times'] == ['08:00']
        assert payload['dose'] == '' and payload['note'] == 'retained'
        assert c.execute('SELECT count(*) FROM health_entries').fetchone()[0] == 0
        assert c.execute('PRAGMA user_version').fetchone()[0] == 10
        c.execute("DELETE FROM health_medication_plans WHERE id='old'")
    with Database(path).transaction() as c:
        assert c.execute('SELECT count(*) FROM health_medication_plans').fetchone()[0] == 0


def test_local_health_consent_is_remembered_for_30_days(rig):
    grant(rig)
    with rig[1].transaction() as connection:
        row = connection.execute("SELECT expires_at FROM consents WHERE user_id=? AND scope='vitals'", (P,)).fetchone()
        expires = datetime.fromisoformat(row['expires_at'])
        assert expires > datetime.now(timezone.utc) + timedelta(days=29)


def test_overview_exposes_latest_archived_record_only_after_records_consent(rig):
    client, db, headers, now = rig
    grant(rig)
    assert call(rig, 'GET')['latest_record'] is None
    policy = client.get('/api/v1/consents', headers=headers[P]).json()['policies']['records_read']
    assert client.post('/api/v1/consents', headers=headers[P], json={
        'scope': 'records_read', 'policy_version': policy['policy_version'],
        'recipient': policy['recipient']}).status_code == 201
    draft = {'title': '合成检验单', 'record_type': '检验单', 'record_date': '2026-10-17',
             'institution': '合成医院', 'visit': '合成复诊',
             'fields': [{'id': 'f1', 'name': '合成项目', 'result': '2.1', 'unit': 'mg/L',
                         'reference': '0-1', 'confirmed': True},
                        {'id': 'f2', 'name': '白细胞', 'result': '6.2', 'unit': '10^9/L',
                         'reference': '3.5-9.5', 'confirmed': True}]}
    with db.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO record_documents(id,user_id,sha256,image,mime,width,height,status,draft,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('doc-summary', P, 'a' * 64, sqlite3.Binary(b'png'), 'image/png', 1, 1,
             'archived', json.dumps(draft, ensure_ascii=False), now.isoformat(), now.isoformat()))
    result = call(rig, 'GET')
    assert result['record_count'] == 1
    assert result['latest_record']['title'] == '合成检验单'
    assert result['latest_record']['record_date'] == '2026-10-17'
    assert result['latest_record']['fields'][0]['name'] == '合成项目'
    assert result['latest_record']['fields'][0]['result'] == '2.1'
