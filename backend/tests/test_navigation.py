"""M11 API acceptance. All data and photos are synthetic, in temporary databases."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import sqlite3
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.config import AISettings, WechatConfig
from app.db import DEFAULT_DB_PATH, Database
from app.main import create_app

BASE = "/api/v1/navigation"
V, R, P = "demo-volunteer-001", "demo-reviewer-001", "demo-patient-001"
NODES = [
    {"node_key": "start", "position": 0, "kind": "start", "floor": "1F", "description": "大厅"},
    {"node_key": "turn", "position": 1, "kind": "turn", "floor": "1F", "direction": "右转", "description": "大厅尽头的检验科指示牌"},
    {"node_key": "end", "position": 2, "kind": "end", "floor": "1F", "description": "检验科"},
]


@pytest.fixture(autouse=True)
def forbid_default_database(monkeypatch):
    original = sqlite3.connect
    def connect(target, *args, **kwargs):
        assert Path(target).resolve() != DEFAULT_DB_PATH.resolve(), "Never touch the daily demo database"
        return original(target, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)


@pytest.fixture
def database(tmp_path):
    return Database(tmp_path / "navigation.sqlite3")


@pytest.fixture
def client(database):
    with TestClient(create_app(database, ai_settings=AISettings(), wechat_config=WechatConfig())) as value:
        yield value


def login(client, alias):
    result = client.post("/api/v1/auth/demo-login", json={"demo_alias": alias, "role": "patient" if alias == P else "volunteer"})
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer " + result.json()["access_token"]}


@pytest.fixture
def accounts(client):
    return {a: login(client, a) for a in (V, R, P)}


def req(client, accounts, who, method, path, body=None, code=200):
    response = client.request(method, BASE + path, headers=accounts[who], json=body)
    assert response.status_code == code, response.text
    return response.json()


def image_bytes(color="white"):
    stream = BytesIO()
    exif = Image.Exif()
    exif[270] = "synthetic-metadata-must-be-removed"
    Image.new("RGB", (32, 24), color).save(stream, format="JPEG", exif=exif)
    return stream.getvalue()


def draft(client, accounts, who=V):
    req(client, accounts, who, "POST", "/tasks/task-lab-a/claim")
    sub = req(client, accounts, who, "POST", "/submissions", {
        "task_id": "task-lab-a", "title": "大厅到检验科", "request_id": "create-1"}, 201)
    return req(client, accounts, who, "PUT", "/submissions/" + sub["id"],
               {"revision": sub["revision"], "title": sub["title"], "nodes": NODES})


def upload(client, accounts, sub, key, who=V, content=None, upload_id=""):
    response = client.post(BASE + "/submissions/" + sub["id"] + "/media", headers=accounts[who],
        data={"node_key": key, "revision": sub["revision"], "client_upload_id": upload_id},
        files={"file": ("test.jpg", content if content is not None else image_bytes(), "image/jpeg")})
    return response


def ready(client, accounts, who=V):
    sub = draft(client, accounts, who)
    for n in sub["nodes"]:
        result = upload(client, accounts, sub, n["node_key"], who)
        assert result.status_code == 201, result.text
        sub["revision"] = result.json()["submission_revision"]
    return req(client, accounts, who, "GET", "/submissions/" + sub["id"])


def submitted(client, accounts):
    sub = ready(client, accounts)
    return req(client, accounts, V, "POST", "/submissions/" + sub["id"] + "/submit",
               {"revision": sub["revision"], "privacy_confirmed": True})


def decision(sub, action="approve"):
    return {"revision": sub["revision"], "decision": action, "walkthrough_confirmed": action == "approve",
            "note": "2026-10-17 独立实走，连续通行；此路线有台阶，不适合轮椅" if action == "approve" else "请重拍转弯节点，标牌不清楚"}


def published(client, accounts):
    sub = submitted(client, accounts)
    return req(client, accounts, R, "POST", "/submissions/" + sub["id"] + "/review", decision(sub))


def test_permissions_and_claim_requirement(client, accounts):
    assert req(client, accounts, V, "GET", "/me")["permissions"]["collect"]
    assert req(client, accounts, R, "GET", "/me")["permissions"]["review"]
    assert not req(client, accounts, P, "GET", "/me")["permissions"]["collect"]
    req(client, accounts, P, "POST", "/tasks/task-lab-a/claim", code=403)
    req(client, accounts, V, "POST", "/submissions",
        {"task_id": "task-lab-a", "title": "未领取", "request_id": "skip"}, 403)
    req(client, accounts, V, "POST", "/tasks/task-lab-a/claim")
    assert req(client, accounts, V, "POST", "/tasks/task-lab-a/claim")["idempotent"]
    req(client, accounts, V, "GET", "/submissions?scope=review", code=403)


def test_duplicate_create_and_concurrent_claim(client, accounts, database):
    with database.transaction(write=True) as c:
        c.execute("UPDATE navigation_memberships SET can_collect=1 WHERE user_id=?", (R,))
    def claim(who):
        return client.post(BASE + "/tasks/task-lab-a/claim", headers=accounts[who]).status_code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, (V, R)))
    assert sorted(results) == [200, 409]
    winner, loser = (V, R) if results[0] == 200 else (R, V)
    body = {"task_id": "task-lab-a", "title": "路线", "request_id": "same"}
    first = req(client, accounts, winner, "POST", "/submissions", body, 201)
    for key in ("same", "different"):
        assert req(client, accounts, winner, "POST", "/submissions", body | {"request_id": key}, 201)["id"] == first["id"]
    req(client, accounts, loser, "POST", "/submissions", body, 403)


def test_end_to_end_publication_feedback_disable_and_retry(client, accounts):
    sub = ready(client, accounts)
    sid, mid = sub["id"], sub["media"][0]["id"]
    req(client, accounts, P, "GET", "/submissions/" + sid, code=403)
    assert client.get(BASE + "/media/" + mid, headers=accounts[P]).status_code == 403
    assert not req(client, accounts, P, "GET", "/routes")["items"]
    payload = {"revision": sub["revision"], "privacy_confirmed": True}
    sub = req(client, accounts, V, "POST", f"/submissions/{sid}/submit", payload)
    assert req(client, accounts, V, "POST", f"/submissions/{sid}/submit", payload)["revision"] == sub["revision"]
    req(client, accounts, V, "PUT", f"/submissions/{sid}",
        {"revision": sub["revision"], "title": "偷偷修改", "nodes": NODES}, 409)
    req(client, accounts, V, "POST", f"/submissions/{sid}/review", decision(sub), 403)
    approval = decision(sub)
    req(client, accounts, R, "POST", f"/submissions/{sid}/review", approval | {"walkthrough_confirmed": False}, 422)
    sub = req(client, accounts, R, "POST", f"/submissions/{sid}/review", approval)
    assert not sub["ar_ready"] and sub["status"] == "published"
    assert req(client, accounts, R, "POST", f"/submissions/{sid}/review", approval)["revision"] == sub["revision"]
    route = req(client, accounts, P, "GET", "/routes/" + sid)
    assert route["status"] == "published" and route["nodes"][0]["media_id"]
    assert "collector_id" not in route and "review_note" not in route
    listing = req(client, accounts, P, "GET", "/routes")["items"]
    assert len(listing) == 1
    assert listing[0]["start"] == {"description": "大厅", "floor": "1F"}
    assert listing[0]["end"] == {"description": "检验科", "floor": "1F"}
    assert listing[0]["node_count"] == 3 and listing[0]["floors"] == ["1F"]
    assert not listing[0]["has_stairs"]
    assert not {"nodes", "collector_id", "review_note", "media"} & listing[0].keys()
    assert client.get(BASE + "/media/" + mid, headers=accounts[P]).status_code == 200
    fb = {"request_id": "feedback-1", "category": "closed", "note": "通道封闭"}
    a = req(client, accounts, P, "POST", f"/routes/{sid}/feedback", fb, 201)
    assert req(client, accounts, P, "POST", f"/routes/{sid}/feedback", fb, 201) == a
    req(client, accounts, P, "POST", f"/routes/{sid}/feedback", fb | {"note": "不同内容"}, 409)
    assert req(client, accounts, R, "GET", "/submissions/" + sid)["feedback"][0]["note"] == "通道封闭"
    disable = {"revision": sub["revision"], "reason": "封路，待重新采集"}
    sub = req(client, accounts, R, "POST", f"/submissions/{sid}/disable", disable)
    assert sub["status"] == "disabled"
    assert req(client, accounts, R, "POST", f"/submissions/{sid}/disable", disable)["revision"] == sub["revision"]
    assert not req(client, accounts, P, "GET", "/routes")["items"]
    req(client, accounts, P, "GET", "/routes/" + sid, code=404)
    assert client.get(BASE + "/media/" + mid, headers=accounts[P]).status_code == 403


@pytest.mark.parametrize("action", ["approve", "request_changes"])
def test_dual_role_collector_cannot_self_review(client, accounts, database, action):
    sub = submitted(client, accounts)
    with database.transaction(write=True) as c:
        c.execute("UPDATE navigation_memberships SET can_review=1 WHERE user_id=?", (V,))
    error = req(client, accounts, V, "POST", f"/submissions/{sub['id']}/review", decision(sub, action), 403)
    assert "采集者不能" in error["detail"]
    assert not req(client, accounts, V, "GET", "/submissions?scope=review")["items"]
    assert req(client, accounts, V, "GET", "/submissions?scope=mine")["items"][0]["id"] == sub["id"]


def test_return_retake_history_and_stale_approval(client, accounts):
    sub = submitted(client, accounts)
    sid, first_version, old_mid = sub["id"], sub["revision"], sub["media"][0]["id"]
    old_approval = decision(sub)
    sub = req(client, accounts, R, "POST", f"/submissions/{sid}/review", decision(sub, "request_changes"))
    new = upload(client, accounts, sub, "start", content=image_bytes("blue"))
    assert new.status_code == 201
    sub = req(client, accounts, V, "GET", "/submissions/" + sid)
    sub = req(client, accounts, V, "POST", f"/submissions/{sid}/submit",
              {"revision": sub["revision"], "privacy_confirmed": True})
    assert len(sub["versions"]) == 2
    req(client, accounts, R, "POST", f"/submissions/{sid}/review", old_approval, 409)
    old = req(client, accounts, R, "GET", f"/submissions/{sid}/versions/{first_version}")
    assert old["media"][0]["id"] == old_mid
    photo = client.get(BASE + f"/submissions/{sid}/versions/{first_version}/media/start", headers=accounts[R])
    assert photo.status_code == 200
    with Image.open(BytesIO(photo.content)) as im:
        assert im.getpixel((0, 0))[0] > 240
    req(client, accounts, P, "GET", f"/submissions/{sid}/versions/{first_version}", code=403)
    req(client, accounts, R, "POST", f"/submissions/{sid}/review", decision(sub))


def test_cross_hospital_review_disable_and_media(client, accounts, database):
    sub = published(client, accounts)
    sid, mid = sub["id"], sub["media"][0]["id"]
    with database.transaction(write=True) as c:
        c.execute("UPDATE navigation_memberships SET hospital_id='other-hospital' WHERE user_id=?", (R,))
    req(client, accounts, R, "POST", f"/submissions/{sid}/disable",
        {"revision": sub["revision"], "reason": "越院操作"}, 403)
    req(client, accounts, R, "POST", f"/submissions/{sid}/review", decision(sub), 403)
    req(client, accounts, R, "GET", f"/submissions/{sid}", code=403)
    assert client.get(BASE + "/media/" + mid, headers=accounts[R]).status_code == 403
    assert not req(client, accounts, R, "GET", "/submissions?scope=review")["items"]


def test_two_reviewers_conflict_without_duplicate_publication(client, accounts, database):
    sub = submitted(client, accounts)
    with database.transaction(write=True) as c:
        c.execute("UPDATE navigation_memberships SET can_review=1 WHERE user_id=?", (P,))
    path, body = BASE + f"/submissions/{sub['id']}/review", decision(sub)
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(lambda who: client.post(path, headers=accounts[who], json=body).status_code, (P, R)))
    assert sorted(statuses) == [200, 409]
    assert len(req(client, accounts, P, "GET", "/routes")["items"]) == 1


def test_image_validation_metadata_and_idempotent_upload(client, accounts):
    sub = draft(client, accounts)
    assert upload(client, accounts, sub, "start", content=b"not an image").status_code == 422
    assert upload(client, accounts, sub, "start", content=b"x" * (5 * 1024 * 1024 + 1)).status_code == 413
    up = upload(client, accounts, sub, "start", upload_id="photo-retry")
    assert up.status_code == 201
    repeated = upload(client, accounts, sub, "start", upload_id="photo-retry")
    assert repeated.json() == {key: up.json()[key] for key in ("id", "node_key", "revision", "submission_revision")}
    assert upload(client, accounts, sub, "start", upload_id="photo-retry", content=image_bytes("red")).status_code == 409
    photo = client.get(BASE + "/media/" + up.json()["id"], headers=accounts[V])
    assert photo.headers["cache-control"] == "no-store"
    with Image.open(BytesIO(photo.content)) as im:
        assert not im.getexif()
    assert upload(client, accounts, sub, "end").status_code == 409


def test_missing_photos_and_edit_invalidation(client, accounts):
    sub = ready(client, accounts)
    nodes = [dict(n) for n in NODES]
    nodes[1]["floor"] = "2F"
    sub = req(client, accounts, V, "PUT", "/submissions/" + sub["id"],
              {"revision": sub["revision"], "title": sub["title"], "nodes": nodes})
    assert not any(m["node_key"] == "turn" for m in sub["media"])
    req(client, accounts, V, "POST", f"/submissions/{sub['id']}/submit",
        {"revision": sub["revision"], "privacy_confirmed": True}, 422)
    req(client, accounts, V, "POST", f"/submissions/{sub['id']}/submit",
        {"revision": sub["revision"], "privacy_confirmed": False}, 422)
    malformed = [dict(n) for n in NODES]
    malformed[0]["kind"] = "turn"
    req(client, accounts, V, "PUT", "/submissions/" + sub["id"],
        {"revision": sub["revision"], "title": sub["title"], "nodes": malformed}, 422)


@pytest.mark.parametrize("action", ["approve", "request_changes"])
def test_review_requires_meaningful_note(client, accounts, action):
    sub = submitted(client, accounts)
    req(client, accounts, R, "POST", f"/submissions/{sub['id']}/review", decision(sub, action) | {"note": "  "}, 422)


def test_pending_cannot_disable_and_collector_permission_revocation(client, accounts, database):
    sub = ready(client, accounts)
    req(client, accounts, R, "POST", f"/submissions/{sub['id']}/disable",
        {"revision": sub["revision"], "reason": "无效状态"}, 409)
    with database.transaction(write=True) as c:
        c.execute("UPDATE navigation_memberships SET can_collect=0 WHERE user_id=?", (V,))
    req(client, accounts, V, "POST", f"/submissions/{sub['id']}/submit",
        {"revision": sub["revision"], "privacy_confirmed": True}, 403)
    assert upload(client, accounts, sub, "start").status_code == 403


def test_persistence_across_reopening(client, accounts, database):
    sub = published(client, accounts)
    reopened = Database(database.path)
    with TestClient(create_app(reopened, ai_settings=AISettings(), wechat_config=WechatConfig())) as again:
        route = req(again, accounts, P, "GET", "/routes/" + sub["id"])
        assert route["revision"] == sub["revision"]
        saved = req(again, accounts, R, "GET", "/submissions/" + sub["id"])
        assert len(saved["versions"]) == 1 and saved["history"][-1]["action"] == "approve"
    with reopened.transaction() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 10


def test_actual_v4_schema_migrates_without_replacing_existing_data(tmp_path):
    legacy_path = tmp_path / "legacy-v4.sqlite3"
    schema = (Path(__file__).parents[1] / "app/schema.sql").read_text(encoding="utf-8")
    legacy_schema = schema.split("-- Immutable submitted versions")[0] + "PRAGMA user_version=4; COMMIT;"
    with sqlite3.connect(legacy_path) as c:
        c.executescript(legacy_schema)
        c.execute("INSERT INTO users(id,role,display_name,synthetic) VALUES('legacy','volunteer','旧采集者',1)")
        c.execute("INSERT INTO navigation_tasks(id,title,status,claimed_by,created_at) VALUES('legacy-task','保留任务','claimed','legacy','2026-10-01')")
        c.execute("INSERT INTO navigation_submissions(id,task_id,collector_id,title,status,created_at,updated_at) VALUES('legacy-sub','legacy-task','legacy','保留草稿','draft','2026-10-01','2026-10-01')")
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='navigation_versions'").fetchone()
    upgraded = Database(legacy_path)
    with upgraded.transaction() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 10
        assert c.execute("SELECT title FROM navigation_submissions WHERE id='legacy-sub'").fetchone()[0] == "保留草稿"
        assert c.execute("SELECT claimed_by FROM navigation_tasks WHERE id='legacy-task'").fetchone()[0] == "legacy"
        assert c.execute("SELECT count(*) FROM navigation_versions").fetchone()[0] == 0


def test_revision_and_rollback_withdraw_until_independent_review(client, accounts):
    original = published(client, accounts)
    sid = original["id"]
    source = original["versions"][0]["revision"]
    restore = {"revision": original["revision"], "source_revision": source}
    req(client, accounts, R, "POST", f"/submissions/{sid}/revise", restore, 403)
    revised = req(client, accounts, V, "POST", f"/submissions/{sid}/revise", restore)
    assert revised["status"] == "draft" and not revised["walkthrough_confirmed"]
    assert not req(client, accounts, P, "GET", "/routes")["items"]
    assert req(client, accounts, V, "POST", f"/submissions/{sid}/revise", restore)["revision"] == revised["revision"]
    revised = req(client, accounts, V, "PUT", f"/submissions/{sid}",
                  {"revision": revised["revision"], "title": "新版路线标题", "nodes": NODES})
    revised = req(client, accounts, V, "POST", f"/submissions/{sid}/submit",
                  {"revision": revised["revision"], "privacy_confirmed": True})
    revised = req(client, accounts, R, "POST", f"/submissions/{sid}/review", decision(revised))
    assert req(client, accounts, P, "GET", f"/routes/{sid}")["title"] == "新版路线标题"
    restored = req(client, accounts, V, "POST", f"/submissions/{sid}/revise",
                   {"revision": revised["revision"], "source_revision": source})
    assert restored["title"] == original["title"]
    assert len(restored["media"]) == 3 and len(restored["versions"]) == 2
    req(client, accounts, P, "GET", f"/routes/{sid}", code=404)
    req(client, accounts, R, "POST", f"/submissions/{sid}/review", decision(revised), 409)
    restored = req(client, accounts, V, "POST", f"/submissions/{sid}/submit",
                   {"revision": restored["revision"], "privacy_confirmed": True})
    req(client, accounts, R, "POST", f"/submissions/{sid}/review", decision(restored))
    assert req(client, accounts, P, "GET", f"/routes/{sid}")["title"] == original["title"]


@pytest.mark.parametrize("field", ["floor", "description"])
def test_photos_alone_cannot_submit_without_wayfinding_details(client, accounts, field):
    sub = ready(client, accounts)
    nodes = [dict(n) for n in NODES]
    nodes[0][field] = "   "
    sub = req(client, accounts, V, "PUT", f"/submissions/{sub['id']}",
              {"revision": sub["revision"], "title": sub["title"], "nodes": nodes})
    photo = upload(client, accounts, sub, "start")
    assert photo.status_code == 201
    error = req(client, accounts, V, "POST", f"/submissions/{sub['id']}/submit",
                {"revision": photo.json()["submission_revision"], "privacy_confirmed": True}, 422)
    assert "位置说明" in error["detail"]
    assert not req(client, accounts, P, "GET", "/routes")["items"]


def test_legacy_incomplete_submission_must_be_returned_before_publication(client, accounts, database):
    sub = submitted(client, accounts)
    with database.transaction(write=True) as c:
        c.execute("UPDATE navigation_nodes SET description='' WHERE submission_id=? AND node_key='start'", (sub["id"],))
    req(client, accounts, R, "POST", f"/submissions/{sub['id']}/review", decision(sub), 422)
    returned = req(client, accounts, R, "POST", f"/submissions/{sub['id']}/review", decision(sub, "request_changes"))
    assert returned["status"] == "changes_requested"

