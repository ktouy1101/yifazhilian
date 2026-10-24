"""Exercise external-provider consent without credentials or network requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import socket
import sqlite3
from threading import Event

import pytest
import httpx
from fastapi.testclient import TestClient

from app.ai.providers.base import ProviderError
from app.config import AISettings
from app.db import DEFAULT_DB_PATH, Database
from app.main import create_app


class FakeProvider:
    name = "external-test-provider"
    recipient = "test-provider.example.invalid"
    policy_version = "external-test-v1"
    external_network = True
    consent_notice = "测试接收方仅处理合成问题与匹配资料；本测试不会联网。"
    answer = "这是关于用药问题的合成测试回复。"

    def __init__(self, *, block=False, fail=False):
        self.calls = []
        self.started = Event()
        self.release = Event()
        self.block = block
        self.fail = fail

    def generate(self, *, domain, text, context):
        self.calls.append({"domain": domain, "text": text, "context": context})
        self.started.set()
        if self.block and not self.release.wait(timeout=15):
            raise AssertionError("Test failed to release the fake provider")
        if self.fail:
            # A deliberately fabricated diagnostic; never a real credential.
            diagnostic = RuntimeError("synthetic-private-diagnostic-SHOULD-NOT-LEAK")
            raise ProviderError(503, "模型暂不可用，请稍后重试。") from diagnostic
        return self.answer


@pytest.fixture(autouse=True)
def isolated_io(monkeypatch):
    original_connect = sqlite3.connect

    def guarded_database(target, *args, **kwargs):
        if Path(target).resolve() == DEFAULT_DB_PATH.resolve():
            raise AssertionError("AI tests must never open the default database")
        return original_connect(target, *args, **kwargs)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("AI authorization tests must never open network connections")

    async def forbidden_async_http(*args, **kwargs):
        raise AssertionError("AI authorization tests must never send HTTP requests")

    monkeypatch.setattr(sqlite3, "connect", guarded_database)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    # Preserve Windows' local socketpair implementation used by TestClient's loop.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async_http)


@pytest.fixture
def database(tmp_path):
    return Database(tmp_path / "ai-authorization.sqlite3")


@pytest.fixture
def client(database):
    with TestClient(create_app(database, ai_settings=AISettings())) as value:
        yield value


def login(client):
    response = client.post("/api/v1/auth/demo-login", json={"demo_alias": "demo-patient-001"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def current_policy(client, headers, scope="ai_medical"):
    response = client.get("/api/v1/consents", headers=headers)
    assert response.status_code == 200
    return response.json()["policies"][scope]


def grant_current_policy(client, headers, scope="ai_medical"):
    policy = current_policy(client, headers, scope)
    response = client.post("/api/v1/consents", headers=headers, json={
        "scope": scope, "recipient": policy["recipient"],
        "policy_version": policy["policy_version"],
    })
    assert response.status_code == 201
    return response.json()


def test_ai_consent_is_remembered_for_30_days(client, database):
    headers = login(client)
    grant_current_policy(client, headers)
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT expires_at FROM consents WHERE scope='ai_medical'"
        ).fetchone()
    remaining = datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)
    assert 29 * 24 * 3600 < remaining.total_seconds() <= 30 * 24 * 3600 + 60


def conversation(client, headers):
    response = client.post("/api/v1/conversations", headers=headers, json={"domain": "medical"})
    assert response.status_code == 201
    return response.json()["id"]


def send(client, headers, cid):
    return client.post(f"/api/v1/conversations/{cid}/messages", headers=headers, json={"text": "用药"})


def assert_no_saved_turn(database, cid):
    with database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM messages WHERE conversation_id=?", (cid,)).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='message_sources'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE action='conversation_answered' AND object_id=?", (cid,)
        ).fetchone()[0] == 0


def test_local_grant_cannot_be_reused_for_external_provider(client, database):
    headers = login(client)
    assert client.post("/api/v1/consents", headers=headers, json={"scope": "ai_medical"}).status_code == 201
    cid = conversation(client, headers)
    provider = FakeProvider()
    client.app.state.ai_provider = provider

    assert send(client, headers, cid).status_code == 403
    assert client.get(f"/api/v1/conversations/{cid}", headers=headers).status_code == 403
    assert client.post("/api/v1/conversations", headers=headers, json={"domain": "medical"}).status_code == 403
    assert provider.calls == []
    assert_no_saved_turn(database, cid)


@pytest.mark.parametrize("metadata", [
    {},
    {"recipient": FakeProvider.recipient},
    {"policy_version": FakeProvider.policy_version},
    {"recipient": "different.example.invalid", "policy_version": FakeProvider.policy_version},
    {"recipient": FakeProvider.recipient, "policy_version": "outdated-test-policy"},
])
def test_external_grant_requires_matching_recipient_and_notice_version(client, database, metadata):
    headers = login(client)
    provider = FakeProvider()
    client.app.state.ai_provider = provider

    response = client.post("/api/v1/consents", headers=headers, json={"scope": "ai_medical", **metadata})
    assert response.status_code == 409
    assert provider.calls == []
    with database.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM consents").fetchone()[0] == 0


def test_explicit_current_external_consent_allows_one_turn(client, database):
    headers = login(client)
    provider = FakeProvider()
    client.app.state.ai_provider = provider
    expected = {
        "recipient": provider.recipient, "policy_version": provider.policy_version,
        "notice": provider.consent_notice, "external_network": True, "provider": provider.name,
    }
    assert current_policy(client, headers) == expected
    assert current_policy(client, headers, "ai_legal") == expected
    assert current_policy(client, headers, "records_read")["external_network"] is False

    grant = grant_current_policy(client, headers)
    assert grant["recipient"] == provider.recipient
    assert grant["policy_version"] == provider.policy_version
    cid = conversation(client, headers)
    response = send(client, headers, cid)
    assert response.status_code == 200
    assert response.json()["answer"] == provider.answer
    assert response.json()["provider"] == provider.name
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["text"] == "用药" and call["domain"] == "medical"
    assert call["context"] and all(chunk.domain == "medical" for chunk in call["context"])
    history = client.get(f"/api/v1/conversations/{cid}", headers=headers).json()["messages"]
    assert len(history) == 2 and history[-1] == response.json()


@pytest.mark.parametrize("changed_field", ["recipient", "policy_version"])
def test_changed_provider_policy_blocks_dispatch(client, database, changed_field):
    headers = login(client)
    provider = FakeProvider()
    client.app.state.ai_provider = provider
    grant_current_policy(client, headers)
    cid = conversation(client, headers)
    setattr(provider, changed_field, "changed-test-policy")

    assert send(client, headers, cid).status_code == 403
    assert provider.calls == []
    assert_no_saved_turn(database, cid)


def test_revoked_external_consent_never_calls_provider(client, database):
    headers = login(client)
    provider = FakeProvider()
    client.app.state.ai_provider = provider
    grant_current_policy(client, headers)
    cid = conversation(client, headers)
    assert client.delete("/api/v1/consents/ai_medical", headers=headers).status_code == 200

    assert send(client, headers, cid).status_code == 403
    assert provider.calls == []
    assert_no_saved_turn(database, cid)


@pytest.mark.parametrize("regrant", [False, True], ids=["revoke", "revoke-and-regrant"])
def test_revocation_commits_while_provider_runs_and_discards_inflight_turn(client, database, regrant):
    headers = login(client)
    provider = FakeProvider(block=True)
    client.app.state.ai_provider = provider
    original_grant = grant_current_policy(client, headers)
    cid = conversation(client, headers)

    def change_consent():
        # Separate app/connection factory: a Python lock cannot mask SQLite locking.
        with TestClient(create_app(Database(database.path), ai_settings=AISettings())) as peer:
            peer.app.state.ai_provider = provider
            response = peer.delete("/api/v1/consents/ai_medical", headers=headers)
            assert response.status_code == 200
            return grant_current_policy(peer, headers) if regrant else response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(send, client, headers, cid)
        try:
            assert provider.started.wait(timeout=5), "Provider was never entered"
            mutation = pool.submit(change_consent)
            changed = mutation.result(timeout=5)
            # This must complete before releasing the provider, not after its reply.
            assert not pending.done()
            if regrant:
                assert changed["granted"] is True
                assert (changed["id"], changed["created_at"]) != (original_grant["id"], original_grant["created_at"])
            else:
                assert changed["granted"] is False
        finally:
            provider.release.set()
        response = pending.result(timeout=5)

    assert response.status_code == 403
    assert provider.answer not in response.text
    assert len(provider.calls) == 1
    assert_no_saved_turn(database, cid)
    if regrant:
        # The replacement authorization itself remains usable for future requests.
        assert client.get(f"/api/v1/conversations/{cid}", headers=headers).json()["messages"] == []


def test_provider_error_returns_only_safe_message_and_saves_nothing(client, database, caplog):
    headers = login(client)
    provider = FakeProvider(fail=True)
    client.app.state.ai_provider = provider
    grant_current_policy(client, headers)
    cid = conversation(client, headers)

    response = send(client, headers, cid)
    assert response.status_code == 503
    assert response.json() == {"detail": "模型暂不可用，请稍后重试。"}
    assert len(provider.calls) == 1
    assert "synthetic-private-diagnostic-SHOULD-NOT-LEAK" not in response.text + caplog.text
    assert_no_saved_turn(database, cid)
    assert client.get(f"/api/v1/conversations/{cid}", headers=headers).json()["messages"] == []
