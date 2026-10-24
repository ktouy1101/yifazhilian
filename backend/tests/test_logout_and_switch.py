"""Logout and identity-switch behavior: a revoked session must stop working immediately,
and switching demo identities must never expose one user's rows to another."""
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import DEFAULT_DB_PATH, Database
from app.main import create_app


@pytest.fixture(autouse=True)
def forbid_default_database(monkeypatch):
    original_connect = sqlite3.connect

    def guarded_connect(target, *args, **kwargs):
        if Path(target).resolve() == DEFAULT_DB_PATH.resolve():
            raise AssertionError("Tests must never open the default database")
        return original_connect(target, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)


@pytest.fixture
def database(tmp_path):
    return Database(tmp_path / "logout-switch.sqlite3")


@pytest.fixture
def client(database):
    with TestClient(create_app(database, ai_settings=AISettings())) as value:
        yield value


def login(client, alias="demo-patient-001", role="patient"):
    response = client.post("/api/v1/auth/demo-login", json={"demo_alias": alias, "role": role})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def test_logout_makes_token_invalid_immediately(client, database):
    headers, body = login(client)
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    # The session row is gone, not merely marked expired.
    with database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0

    assert client.get("/api/v1/users/me", headers=headers).status_code == 401


def test_logout_is_idempotent_with_or_without_token(client):
    assert client.post("/api/v1/auth/logout").status_code == 204
    headers, _ = login(client)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    # A second logout on an already-revoked token must not error.
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204


def test_switch_identity_revokes_old_session_and_keeps_rows_separate(client, database):
    patient_a, body_a = login(client, "demo-patient-001")
    # Patient A creates a conversation that only they may read.
    assert client.post("/api/v1/consents", headers=patient_a,
                       json={"scope": "ai_medical"}).status_code == 201
    cid = client.post("/api/v1/conversations", headers=patient_a,
                      json={"domain": "medical"}).json()["id"]

    # Log out A, then log in B.
    assert client.post("/api/v1/auth/logout", headers=patient_a).status_code == 204
    patient_b, body_b = login(client, "demo-patient-002")

    # Old token is dead even though B is now logged in on the same client.
    assert client.get("/api/v1/users/me", headers=patient_a).status_code == 401
    # B's token works and identifies B, not A.
    me = client.get("/api/v1/users/me", headers=patient_b).json()
    assert me["id"] == "demo-patient-002" and me["synthetic"] is True
    # B cannot read A's conversation, and A cannot do anything with the dead token.
    assert client.get(f"/api/v1/conversations/{cid}", headers=patient_b).status_code == 404

    # Two sessions now exist for distinct users; A's row is deleted, B's row remains.
    with database.transaction() as connection:
        rows = list(connection.execute("SELECT user_id FROM sessions"))
    assert sorted(r["user_id"] for r in rows) == ["demo-patient-002"]


def test_volunteer_logout_and_switch_back(client):
    volunteer, _ = login(client, "demo-volunteer-001", "volunteer")
    assert client.get("/api/v1/records", headers=volunteer).status_code == 403
    assert client.post("/api/v1/auth/logout", headers=volunteer).status_code == 204
    assert client.get("/api/v1/users/me", headers=volunteer).status_code == 401

    patient, _ = login(client, "demo-patient-001")
    assert client.get("/api/v1/users/me", headers=patient).json()["role"] == "patient"
