"""M03 acceptance: temporary SQLite, synthetic chart, no external AI calls."""
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import AISettings, WechatConfig
from app.db import Database, DEFAULT_DB_PATH, utcnow
from app.main import create_app
from app.services.record_ocr import LocalOCR, OCRError, parse_report, worker_python

BASE = "/api/v1/record-documents"


def lines():
    result = []
    for y, row in [(20, ["项目", "结果", "单位", "参考区间"]), (70, ["白细胞", "6.30", "10^9/L", "3.50-9.50"])]:
        for x, text in zip([20, 220, 320, 440], row):
            result.append({"id": "line-" + str(len(result)), "text": text, "confidence": .72 if text == "6.30" else .98,
                           "box": [x, y, x + 100, y + 25]})
    return {"lines": result, "engine": "synthetic test double", "elapsed_ms": 1}


class FakeOCR:
    def recognize(self, data):
        return lines()


def photo(color="white"):
    out = BytesIO()
    Image.new("RGB", (600, 400), color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    original = sqlite3.connect
    def safe_connect(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", safe_connect)
    db = Database(tmp_path / "m03.sqlite3")
    app = create_app(db, ai_settings=AISettings(), wechat_config=WechatConfig())
    app.state.record_ocr = FakeOCR()
    with TestClient(app) as client:
        headers = {}
        for name, role in [("demo-patient-001", "patient"), ("demo-patient-002", "patient"), ("demo-volunteer-001", "volunteer")]:
            token = client.post("/api/v1/auth/demo-login", json={"demo_alias": name, "role": role}).json()["access_token"]
            headers[name] = {"Authorization": "Bearer " + token}
            if role == "patient":
                assert client.post("/api/v1/consents", headers=headers[name], json={"scope": "records_read"}).status_code == 201
        yield client, db, headers, app


def call(rig, method, path="", body=None, code=200, who="demo-patient-001"):
    client, _, headers, _ = rig
    res = client.request(method, BASE + path, headers=headers[who], json=body)
    assert res.status_code == code, res.text
    return res.json()


def upload(rig, data=None):
    client, _, headers, _ = rig
    res = client.post(BASE, headers=headers["demo-patient-001"], files={"file": ("chart.png", data or photo(), "image/png")})
    assert res.status_code == 201, res.text
    return res.json()


def recognized(rig):
    doc = upload(rig)
    return call(rig, "POST", "/" + doc["id"] + "/ocr", {"revision": doc["revision"], "request_id": "recognize-001"})


def review(doc, request_id="confirm-001"):
    draft = deepcopy(doc["draft"])
    draft.pop("source_job_id", None)
    draft["metadata_confirmed"] = True
    draft["visit"] = "2026-10 合成复诊"
    draft["fields"] = [{key: f[key] for key in ("id", "name", "result", "unit", "reference")} | {"confirmed": True} for f in draft["fields"]]
    return draft | {"revision": doc["revision"], "request_id": request_id, "reason": "对照原图更正"}


def test_real_local_cpu_ocr_on_synthetic_chart():
    if not worker_python().is_file():
        pytest.skip("Install isolated OCR worker with setup-ocr.ps1")
    result = LocalOCR().recognize((Path(__file__).parents[1] / "fixtures/records-m03/synthetic-lab.png").read_bytes())
    draft = parse_report(result)
    assert len(draft["fields"]) == 5
    assert draft["fields"][0]["result"] == "6.30"
    assert draft["fields"][2]["result"] == "128"
    assert draft["fields"][4]["result"] == "<5.0"
    assert draft["record_date"] == "2026-10-17"
    assert all(not f["confirmed"] for f in draft["fields"])


def wrapped_table():
    return json.loads((Path(__file__).parents[1] / "fixtures/records-m03/wrapped-table-ocr.json").read_text(encoding="utf-8"))


def test_wrapped_header_keeps_thirteen_rows_and_excludes_sequence_and_flag_columns():
    source = wrapped_table()
    original = deepcopy(source)
    draft = parse_report(source)
    assert source == original
    fields = draft["fields"]
    assert len(fields) == 13
    assert fields[0]["name"] == "白细胞计数WBC"
    assert fields[0]["result"] == "11.8"
    assert fields[1]["result"] == "3.82" and fields[1]["reference"] == "4.3 - 5.8"
    assert fields[3]["reference"] == "40-50"  # the adjacent flag is not part of the range
    assert fields[-2]["name"] == "钠Na+" and fields[-2]["result"] == "138"
    assert fields[-1]["name"] == "肌酐Cr" and fields[-1]["result"] == "72"
    assert fields[2]["unit"] == "7/6"  # retain OCR errors for human correction, never guess units
    assert "line-52" in fields[1]["source_ids"]  # printed flag remains in evidence
    assert all(not field["confirmed"] and field["box"] for field in fields)
    assert parse_report({"lines": list(reversed(source["lines"]))}) == draft
    assert parse_report({"lines": source["lines"][7:]})["fields"] == []  # no header, no invented table


def test_retry_old_empty_extraction_allows_review_and_archive_preserving_prior_job(rig, monkeypatch):
    from app.api import record_documents
    _, _, _, app = rig
    app.state.record_ocr.recognize = lambda data: wrapped_table()
    monkeypatch.setattr(record_documents, "parse_report", lambda result: parse_report({"lines": []}))
    old = recognized(rig)
    assert old["draft"]["fields"] == []
    call(rig, "POST", "/" + old["id"] + "/confirm", review(old), code=422)
    monkeypatch.setattr(record_documents, "parse_report", parse_report)
    doc = call(rig, "POST", "/" + old["id"] + "/ocr", {"revision": old["revision"], "request_id": "retry-table-001"})
    assert len(doc["draft"]["fields"]) == 13
    assert doc["archived_version"] == 0 and not doc["draft"]["metadata_confirmed"]
    assert all(not field["confirmed"] for field in doc["draft"]["fields"])
    old_job = call(rig, "GET", "/" + old["id"] + "/jobs/" + old["job"]["id"])
    assert old_job["result"]["draft"]["fields"] == []
    assert old_job["result"]["lines"] == wrapped_table()["lines"]
    body = review(doc)
    body["fields"][2]["unit"] = "g/L"
    archived = call(rig, "POST", "/" + doc["id"] + "/confirm", body)
    assert archived["archived_version"] == 1
    field = archived["draft"]["fields"][2]
    assert field["unit"] == "g/L" and field["original"]["unit"] == "7/6"


def test_upload_duplicate_original_validation_and_isolation(rig):
    doc = upload(rig)
    assert doc["status"] == "uploaded" and doc["archived_version"] == 0
    assert upload(rig)["duplicate"] and upload(rig)["id"] == doc["id"]
    client, _, h, _ = rig
    image = client.get(BASE + "/" + doc["id"] + "/image?original=true", headers=h["demo-patient-001"])
    assert image.content == photo() and image.headers["cache-control"] == "no-store"
    for suffix in ("", "/image", "/versions/1", "/jobs/unknown"):
        call(rig, "GET", "/" + doc["id"] + suffix, code=404, who="demo-patient-002")
    call(rig, "GET", code=403, who="demo-volunteer-001")
    assert client.get(BASE).status_code == 401
    for data, expected in [(b"not a photo", 422), (b"x" * (8 * 1024 * 1024 + 1), 413)]:
        assert client.post(BASE, headers=h["demo-patient-001"], files={"file": ("fake.png", data, "image/png")}).status_code == expected


def test_full_correction_archive_history_and_restart(rig):
    doc = recognized(rig)
    assert doc["status"] == "review" and doc["draft"]["fields"][0]["confidence"] < .9
    body = review(doc)
    body["fields"][0]["result"] = "6.80"
    confirmed = call(rig, "POST", "/" + doc["id"] + "/confirm", body)
    assert confirmed["status"] == "archived" and confirmed["archived_version"] == 1
    assert confirmed["draft"]["fields"][0]["original"]["result"] == "6.30"
    assert call(rig, "POST", "/" + doc["id"] + "/confirm", body)["archived_version"] == 1
    call(rig, "POST", "/" + doc["id"] + "/confirm", body | {"reason": "changed payload"}, code=409)
    update = review(confirmed, "confirm-002")
    update["fields"][0]["result"] = "6.90"
    newer = call(rig, "POST", "/" + doc["id"] + "/confirm", update)
    assert newer["archived_version"] == 2
    version = call(rig, "GET", "/" + doc["id"] + "/versions/1")
    assert version["snapshot"]["draft"]["fields"][0]["result"] == "6.80"
    change = call(rig, "GET", "/" + doc["id"] + "/versions/2")["changes"]
    assert {"field": "ocr-1.result", "before": "6.80", "after": "6.90"} in change
    client, db, h, _ = rig
    original = client.get(BASE + "/" + doc["id"] + "/image?original=true", headers=h["demo-patient-001"])
    assert original.content == photo()
    with TestClient(create_app(Database(db.path), ai_settings=AISettings())) as reopened:
        assert reopened.get(BASE + "/" + doc["id"], headers=h["demo-patient-001"]).json()["archived_version"] == 2
    call(rig, "DELETE", "/" + doc["id"] + "?revision=" + str(newer["revision"]), code=409)


def test_confirmation_validation_conflict_and_save_draft(rig):
    doc = recognized(rig)
    body = review(doc)
    call(rig, "POST", "/" + doc["id"] + "/confirm", body | {"metadata_confirmed": False}, code=422)
    call(rig, "POST", "/" + doc["id"] + "/confirm", body | {"fields": []}, code=422)
    invalid = deepcopy(body); invalid["fields"][0]["confirmed"] = False
    call(rig, "POST", "/" + doc["id"] + "/confirm", invalid, code=422)
    invalid = deepcopy(body); invalid["fields"][0]["result"] = " "
    call(rig, "POST", "/" + doc["id"] + "/confirm", invalid, code=422)
    for patch in ({"record_date": "2026-02-30"}, {"user_id": "another"}, {"fields": body["fields"] * 2}):
        call(rig, "POST", "/" + doc["id"] + "/confirm", body | patch, code=422)
    saved = call(rig, "PUT", "/" + doc["id"] + "/draft", body)
    assert saved["archived_version"] == 0 and saved["status"] == "review"
    call(rig, "POST", "/" + doc["id"] + "/confirm", body | {"request_id": "stale-001"}, code=409)
    assert call(rig, "GET", "/" + doc["id"])["versions"] == []


def test_failed_ocr_manual_fallback_and_retry_history(rig):
    _, _, _, app = rig
    def fail(data):
        raise OCRError("本地OCR超时")
    app.state.record_ocr.recognize = fail
    doc = recognized(rig)
    assert doc["status"] == "failed" and doc["job"]["error"] == "本地OCR超时"
    body = review(doc)
    body["fields"] = [{"id": "manual-1", "name": "合成项目", "result": "2.1", "unit": "mg/L", "reference": "", "confirmed": True}]
    saved = call(rig, "PUT", "/" + doc["id"] + "/draft", body)
    app.state.record_ocr = FakeOCR()
    retried = call(rig, "POST", "/" + doc["id"] + "/ocr", {"revision": saved["revision"], "request_id": "retry-002"})
    assert len(retried["jobs"]) == 2 and retried["status"] == "review"
    assert call(rig, "GET", "/" + doc["id"] + "/jobs/" + doc["job"]["id"])["status"] == "failed"


def test_manual_archive_after_failure_and_correction_requires_reason(rig):
    doc = upload(rig)
    body = review(doc)
    body["fields"] = [{"id": "manual-1", "name": "合成项目", "result": "阴性", "unit": "", "reference": "", "confirmed": True}]
    doc = call(rig, "POST", "/" + doc["id"] + "/confirm", body)
    assert doc["draft"]["fields"][0]["original"] is None
    call(rig, "POST", "/" + doc["id"] + "/confirm", review(doc, "correct-2") | {"reason": ""}, code=422)
    call(rig, "POST", "/" + doc["id"] + "/ocr", {"revision": doc["revision"], "request_id": "reocr-001"}, code=409)


def test_failed_retry_keeps_previous_field_provenance_and_saved_correction_reason(rig):
    doc = recognized(rig)
    _, _, _, app = rig
    def fail(data):
        raise OCRError("retry failed")
    app.state.record_ocr.recognize = fail
    failed = call(rig, "POST", "/" + doc["id"] + "/ocr", {"revision": doc["revision"], "request_id": "retry-fail"})
    assert failed["status"] == "failed" and failed["draft"]["source_job_id"] == doc["job"]["id"]
    body = review(failed)
    body["fields"][0]["result"] = "6.80"
    saved = call(rig, "PUT", "/" + doc["id"] + "/draft", body)
    assert saved["draft"]["reason"] == body["reason"]
    confirmed = call(rig, "POST", "/" + doc["id"] + "/confirm", review(saved, "confirm-retry"))
    assert confirmed["draft"]["fields"][0]["original"]["result"] == "6.30"
    version = call(rig, "GET", "/" + doc["id"] + "/versions/1")
    assert version["snapshot"]["job_id"] == doc["job"]["id"]


def test_exif_orientation_uses_same_coordinate_space_without_rewriting_original(rig):
    image = Image.new("RGB", (400, 600), "white")
    exif = Image.Exif(); exif[274] = 6
    output = BytesIO(); image.save(output, format="JPEG", exif=exif)
    doc = upload(rig, output.getvalue())
    assert (doc["width"], doc["height"]) == (600, 400)
    client, _, h, _ = rig
    url = BASE + "/" + doc["id"] + "/image"
    preview = Image.open(BytesIO(client.get(url, headers=h["demo-patient-001"]).content))
    assert preview.size == (600, 400)
    assert client.get(url + "?original=true", headers=h["demo-patient-001"]).content == output.getvalue()


@pytest.mark.parametrize("during", ["revoke", "regrant", "logout"])
def test_authorization_change_during_ocr_discards_results(rig, during):
    client, db, h, app = rig
    def recognize(data):
        if during == "logout":
            client.post("/api/v1/auth/logout", headers=h["demo-patient-001"])
        else:
            client.delete("/api/v1/consents/records_read", headers=h["demo-patient-001"])
            if during == "regrant":
                client.post("/api/v1/consents", headers=h["demo-patient-001"], json={"scope": "records_read"})
        return lines()
    app.state.record_ocr.recognize = recognize
    doc = upload(rig)
    call(rig, "POST", "/" + doc["id"] + "/ocr", {"revision": doc["revision"], "request_id": "revoke-001"}, code=401 if during == "logout" else 403)
    with db.transaction() as c:
        row = c.execute("SELECT * FROM record_ocr_jobs").fetchone()
        assert row["status"] == "discarded" and row["result"] is None


def test_revoke_blocks_every_private_read_and_write(rig):
    doc = recognized(rig)
    client, _, h, _ = rig
    client.delete("/api/v1/consents/records_read", headers=h["demo-patient-001"])
    for suffix in ("", "/" + doc["id"], "/" + doc["id"] + "/image", "/" + doc["id"] + "/versions/1",
                   "/" + doc["id"] + "/jobs/" + doc["job"]["id"] + "/fields/ocr-1/image"):
        call(rig, "GET", suffix, code=403)
    call(rig, "POST", "/" + doc["id"] + "/confirm", review(doc), code=403)


@pytest.mark.parametrize("old_version", ["demo-1", "records-local-2"])
def test_old_policy_requires_new_notice_and_keeps_uploaded_document(rig, old_version):
    doc = upload(rig)
    client, db, headers, _ = rig
    auth = headers["demo-patient-001"]
    with db.transaction(write=True) as c:
        c.execute("UPDATE consents SET policy_version=?,recipient='local_demo_process' WHERE scope='records_read'", (old_version,))
    call(rig, "GET", code=403)
    result = client.get("/api/v1/consents", headers=auth).json()
    old = next(item for item in result["items"] if item["scope"] == "records_read")
    assert old["synthetic_only"] is True
    assert client.post("/api/v1/consents", headers=auth, json={
        "scope": "records_read", "recipient": old["recipient"], "policy_version": old_version}).status_code == 409
    policy = result["policies"]["records_read"]
    granted = client.post("/api/v1/consents", headers=auth, json={
        "scope": "records_read", "recipient": policy["recipient"], "policy_version": policy["policy_version"]})
    assert granted.status_code == 201
    consent = granted.json()
    assert consent["synthetic_only"] is False
    assert "record_image" in consent["fields"] and "synthetic_record" not in consent["fields"]
    current = call(rig, "GET", "/" + doc["id"])
    assert current["source"] == "user_upload" and "synthetic_only" not in current
    assert current["draft"] == doc["draft"] and current["revision"] == doc["revision"]
    assert client.get(BASE + "/" + doc["id"] + "/image?original=true", headers=auth).content == photo()


def test_crop_is_private_and_original_ocr_is_immutable(rig):
    doc = recognized(rig)
    client, _, h, _ = rig
    url = BASE + "/" + doc["id"] + "/jobs/" + doc["job"]["id"] + "/fields/ocr-1/image"
    response = client.get(url, headers=h["demo-patient-001"])
    assert response.status_code == 200 and Image.open(BytesIO(response.content)).height < 100
    assert client.get(url, headers=h["demo-patient-002"]).status_code == 404
    body = review(doc); body["fields"][0]["result"] = "9.00"
    call(rig, "POST", "/" + doc["id"] + "/confirm", body)
    result = call(rig, "GET", "/" + doc["id"] + "/jobs/" + doc["job"]["id"])
    assert result["result"]["draft"]["fields"][0]["result"] == "6.30"


def test_crashed_job_is_retryable_but_live_job_cannot_be_overwritten(rig):
    doc = upload(rig)
    _, db, _, _ = rig
    with db.transaction(write=True) as c:
        c.execute("INSERT INTO record_ocr_jobs(id,document_id,request_id,status,started_at) VALUES('crashed',?,'crashed-id','running',?)", (doc["id"], utcnow().isoformat()))
        c.execute("UPDATE record_documents SET latest_job_id='crashed',status='recognizing' WHERE id=?", (doc["id"],))
    call(rig, "POST", "/" + doc["id"] + "/ocr", {"revision": doc["revision"], "request_id": "retry-live"}, code=409)
    with db.transaction(write=True) as c:
        c.execute("UPDATE record_ocr_jobs SET started_at=?", ((utcnow() - timedelta(seconds=120)).isoformat(),))
    result = call(rig, "POST", "/" + doc["id"] + "/ocr", {"revision": doc["revision"], "request_id": "retry-late"})
    assert result["status"] == "review" and len(result["jobs"]) == 2


def test_delete_only_draft_and_transaction_failure_never_archives(rig):
    doc = recognized(rig)
    _, db, _, _ = rig
    with db.transaction(write=True) as c:
        c.execute("CREATE TRIGGER fail_archive BEFORE INSERT ON record_document_versions BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        call(rig, "POST", "/" + doc["id"] + "/confirm", review(doc))
    current = call(rig, "GET", "/" + doc["id"])
    assert current["archived_version"] == 0 and current["status"] == "review"
    call(rig, "DELETE", "/" + doc["id"] + "?revision=" + str(doc["revision"]))
    call(rig, "GET", "/" + doc["id"], code=404)
    with db.transaction() as c:
        assert c.execute("SELECT count(*) FROM record_ocr_jobs").fetchone()[0] == 0


def test_v5_migration_keeps_existing_records_and_m02_m11_data(tmp_path):
    path = tmp_path / "v5.sqlite3"
    schema = (Path(__file__).parents[1] / "app/schema.sql").read_text(encoding="utf-8")
    with sqlite3.connect(path) as c:
        c.executescript(schema.split("-- M03:")[0] + "PRAGMA user_version=5; COMMIT;")
        c.execute("INSERT INTO users(id,role,display_name) VALUES('old-user','patient','existing')")
        c.execute("INSERT INTO medical_records(id,user_id,title,created_at) VALUES('old-note','old-user','retained','2026-10-01')")
    with Database(path).transaction() as c:
        assert c.execute("SELECT title FROM medical_records").fetchone()[0] == "retained"
        assert c.execute("PRAGMA user_version").fetchone()[0] == 12
        assert c.execute("SELECT count(*) FROM record_documents").fetchone()[0] == 0
