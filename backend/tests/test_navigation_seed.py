"""Test fixture import on a temporary database, never the user's daily DB."""
from fastapi.testclient import TestClient
import pytest
from app.config import AISettings, WechatConfig
from app.db import Database
from app.main import create_app
from scripts.seed_navigation_demo import ACCOUNTS, COLLECTOR, REVIEWER, PATIENT, SCENARIOS, seed


def test_seed_preserves_existing_data_and_user_changes_on_rerun(tmp_path):
    database = Database(tmp_path / "fixtures.db")
    with database.transaction(write=True) as c:
        c.execute("INSERT INTO users(id,role,display_name,synthetic) VALUES('existing','patient','已有账号',0)")
    result = seed(database)
    assert len(result["created"]) == 7 and result["skipped"] == []
    with database.transaction() as c:
        assert c.execute("SELECT display_name FROM users WHERE id='existing'").fetchone()[0] == "已有账号"
        counts = dict(c.execute("SELECT status,count(*) FROM navigation_submissions WHERE task_id LIKE 'm11-fixture-v1-%' GROUP BY status").fetchall())
        assert counts == {"published": 2, "submitted": 1, "changes_requested": 1, "draft": 1, "disabled": 1}
        assert c.execute("SELECT count(*) FROM navigation_media").fetchone()[0] == 18
        assert c.execute("SELECT count(*) FROM navigation_versions").fetchone()[0] == 5
        assert c.execute("SELECT count(*) FROM navigation_feedback").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM sessions WHERE user_id LIKE 'm11-test-%'").fetchone()[0] == 0
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []

    with TestClient(create_app(database, ai_settings=AISettings(), wechat_config=WechatConfig())) as client:
        auth = {}
        for uid, role, *_ in ACCOUNTS:
            r = client.post('/api/v1/auth/demo-login', json={'demo_alias': uid, 'role': role})
            assert r.status_code == 200
            auth[uid] = {'Authorization': 'Bearer ' + r.json()['access_token']}
        routes = client.get('/api/v1/navigation/routes', headers=auth[PATIENT]).json()['items']
        assert len(routes) == 2
        detail = client.get('/api/v1/navigation/routes/' + routes[0]['id'], headers=auth[PATIENT]).json()
        assert len(detail['nodes']) == 3
        assert client.get('/api/v1/navigation/media/' + detail['nodes'][0]['media_id'], headers=auth[PATIENT]).status_code == 200
        queue = client.get('/api/v1/navigation/submissions?scope=review', headers=auth[REVIEWER]).json()['items']
        pending = next(row for row in queue if row['status'] == 'submitted')
        attempt = client.post('/api/v1/navigation/submissions/' + pending['id'] + '/review', headers=auth[COLLECTOR],
                              json={'revision': pending['revision'], 'decision': 'approve', 'note': '自审尝试', 'walkthrough_confirmed': True})
        assert attempt.status_code == 403
        disabled = client.post('/api/v1/navigation/submissions/' + routes[0]['id'] + '/disable', headers=auth[REVIEWER],
                               json={'revision': routes[0]['revision'], 'reason': '用户测试后停用，重导入不可覆盖'})
        assert disabled.status_code == 200
        retry = seed(database)
        assert retry['created'] == [] and len(retry['skipped']) == len(SCENARIOS)
        assert len(client.get('/api/v1/navigation/routes', headers=auth[PATIENT]).json()['items']) == 1


def test_demo_selector_cannot_login_non_synthetic_user_by_id(tmp_path):
    database = Database(tmp_path / 'auth.db')
    with database.transaction(write=True) as c:
        c.execute("INSERT INTO users(id,role,display_name,synthetic) VALUES('real-user','patient','非测试用户',0)")
    with TestClient(create_app(database, ai_settings=AISettings(), wechat_config=WechatConfig())) as client:
        response = client.post('/api/v1/auth/demo-login', json={'demo_alias': 'real-user', 'role': 'patient'})
        assert response.status_code == 422


@pytest.mark.parametrize('link', ['phone', 'openid'])
def test_test_flag_does_not_bypass_linked_account_login(tmp_path, link):
    database = Database(tmp_path / 'linked-auth.db')
    with database.transaction(write=True) as c:
        c.execute(f"INSERT INTO users(id,role,display_name,synthetic,{link}) VALUES('linked-test','patient','测试体验员',1,?)",
                  ('19900000000' if link == 'phone' else 'fixture-openid',))
    with TestClient(create_app(database, ai_settings=AISettings(), wechat_config=WechatConfig())) as client:
        response = client.post('/api/v1/auth/demo-login', json={'demo_alias': 'linked-test', 'role': 'patient'})
        assert response.status_code == 422
        if link == 'phone':
            code = client.post('/api/v1/auth/send-code', json={'phone': '19900000000'}).json()['dev_code']
            response = client.post('/api/v1/auth/phone-login', json={'phone': '19900000000', 'code': code})
            assert response.status_code == 200
            assert response.json()['user']['id'] == 'linked-test'
            assert response.json()['user']['synthetic'] is True
