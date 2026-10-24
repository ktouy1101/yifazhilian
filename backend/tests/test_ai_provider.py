"""No real credentials or network: all providers use fake values/MockTransport."""
import asyncio
import json

import httpx
import pytest

from app.ai.providers.base import KnowledgeChunk, ProviderError
from app.ai.providers.compatible import MAX_RESPONSE_BYTES, OpenAICompatibleProvider
from app.ai.providers.factory import create_provider
from app.ai.providers.mock import MockProvider
from app.ai.redaction import redact_outbound
from app.config import AISettings, read_ai_settings
from app.services.rag import CORPORA, respond

FAKE_KEY = "sk-unit-test-not-a-real-key-0123456789"


def settings(**overrides):
    return AISettings(**({"provider": "openai_compatible", "base_url": "https://api.deepseek.com",
                         "model": "deepseek-flash", "api_key": FAKE_KEY, "display_name": "DeepSeek"} | overrides))


def provider(handler, **overrides):
    return OpenAICompatibleProvider(settings(**overrides), transport=httpx.MockTransport(handler))


def success(answer="可先向医院病案管理部门核实办理方式。"):
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": answer, "reasoning_content": "never return this"}}]})


def generate(subject, text="知情同意是什么？"):
    return subject.generate(domain="legal", text=text, context=CORPORA["legal"][:1])


def test_auth_payload_minimization_and_outbound_redaction():
    seen = []
    sensitive = ["13812345678", "11010519491231002X", "demo.patient@example.com", "sk-synthetic-in-question-0123456789"]

    def handler(request):
        seen.append(request)
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer " + FAKE_KEY
        assert request.headers["accept-encoding"] == "identity"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash" and payload["max_tokens"] == 600
        assert payload["thinking"] == {"type": "disabled"} and payload["stream"] is False
        assert len(payload["messages"]) == 2
        question = json.loads(payload["messages"][1]["content"])
        assert set(question) == {"question", "references"}
        assert set(question["references"][0]) == {"id", "title", "text"}
        body = request.content.decode()
        assert FAKE_KEY not in body
        assert all(value not in body for value in sensitive)
        assert "patient_id" not in body and "conversation_id" not in body and "history" not in body
        return success()

    subject = provider(handler)
    answer = generate(subject, "请解释知情同意，演示输入：" + "，".join(sensitive))
    assert "病案管理" in answer and len(seen) == 1
    assert subject.name == "deepseek" and subject.external_network is True
    assert "DeepSeek" in subject.recipient and "30天" in subject.consent_notice
    assert "已发送的数据无法收回" in subject.consent_notice


@pytest.mark.parametrize("status,fragment", [(302, "重定向"), (401, "鉴权"), (403, "鉴权"), (402, "余额不足"), (429, "限流"), (500, "服务错误")])
def test_upstream_errors_redirects_never_leak_or_retry(status, fragment):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(status, headers={"Location": "https://untrusted.invalid/collect"},
                              text="private upstream error " + FAKE_KEY)

    with pytest.raises(ProviderError) as error:
        generate(provider(handler))
    assert fragment in error.value.safe_message
    assert FAKE_KEY not in str(error.value) and "private upstream" not in repr(error.value)
    assert len(calls) == 1


def test_timeout_is_safe_and_does_not_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("hidden-key=" + FAKE_KEY, request=request)

    with pytest.raises(ProviderError) as error:
        generate(provider(handler))
    assert error.value.status_code == 504 and FAKE_KEY not in str(error.value)
    assert len(calls) == 1


def test_total_timeout_cancels_slow_transport(monkeypatch):
    from app.ai.providers import compatible
    monkeypatch.setattr(compatible, "TOTAL_TIMEOUT_SECONDS", 0.01)
    cancelled = []

    async def slow(_request):
        try:
            await asyncio.sleep(2)
        finally:
            cancelled.append(True)
        return success()

    with pytest.raises(ProviderError) as error:
        generate(provider(slow))
    assert error.value.status_code == 504 and cancelled == [True]


@pytest.mark.parametrize("response", [
    httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)),
    httpx.Response(200, text="invalid-json-do-not-surface"),
    httpx.Response(200, json={"choices": []}),
    httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "truncated"}}]}),
])
def test_response_limits_and_shape_are_safe(response):
    with pytest.raises(ProviderError) as error:
        generate(provider(lambda _: response))
    assert error.value.status_code == 502
    assert "invalid-json" not in str(error.value) and "truncated" not in str(error.value)


def test_provider_independent_safety_blocks_egress_and_isolates_corpora():
    called = []

    def handler(request):
        called.append(json.loads(request.content))
        return success()

    subject = provider(handler)
    urgent = respond("medical", "胸闷伴呼吸困难", subject)
    unknown = respond("legal", "明天会不会下雨", subject)
    assert called == []
    assert urgent["provider"] == unknown["provider"] == "local_safety"
    assert "立即联系病区医护" in urgent["answer"] and unknown["sources"] == []
    result = respond("legal", "用药的知情同意", subject)
    assert len(called) == 1 and all(source["domain"] == "legal" for source in result["sources"])
    outbound = json.loads(called[0]["messages"][1]["content"])
    assert all(ref["id"].startswith("law-") for ref in outbound["references"])
    assert "sources_label" not in result
    with pytest.raises(ProviderError):
        subject.generate(domain="legal", text="病历", context=CORPORA["medical"])
    assert len(called) == 1


def test_generic_compatible_does_not_receive_deepseek_extension():
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        assert str(request.url) == "https://models.example.invalid/v1/chat/completions"
        return success()

    subject = provider(handler, base_url="https://models.example.invalid/v1/", model="another-model", display_name="Example")
    generate(subject)
    assert subject.name == "openai_compatible" and "thinking" not in received[0]


@pytest.mark.parametrize("url", ["http://api.deepseek.com", "https://key@api.deepseek.com", "https://api.deepseek.com?key=secret", "https://api.deepseek.com/#fragment", "https://api.deepseek.com/"])
def test_url_validation(url):
    if url.endswith("/") and "#" not in url:
        assert create_provider(settings(base_url=url)).external_network is True
    else:
        with pytest.raises(ProviderError):
            create_provider(settings(base_url=url))


def test_configuration_precedence_repr_and_no_import_network(tmp_path, monkeypatch):
    # The fake temporary file is the only credentials-like file this test reads.
    fake = tmp_path / "test.env"
    fake.write_text("YIFAZHILIAN_AI_PROVIDER=openai_compatible\nYIFAZHILIAN_AI_BASE_URL=https://models.example.invalid\nYIFAZHILIAN_AI_MODEL=test-model\nYIFAZHILIAN_AI_API_KEY='fake-file-key'\nYIFAZHILIAN_AI_DISPLAY_NAME=Example\n", encoding="utf-8")
    monkeypatch.setattr(httpx.AsyncClient, "send", lambda *_args, **_kwargs: pytest.fail("Configuration must not send requests"))
    loaded = read_ai_settings(env_file=fake, environ={"YIFAZHILIAN_AI_API_KEY": "fake-env-key"})
    assert loaded.api_key == "fake-env-key" and "fake-env-key" not in repr(loaded)
    assert create_provider(loaded).name == "openai_compatible"
    disabled = read_ai_settings(env_file=fake, environ={"YIFAZHILIAN_AI_PROVIDER": "mock"})
    assert isinstance(create_provider(disabled), MockProvider)
    empty = read_ai_settings(env_file=tmp_path / "absent.env", environ={})
    assert isinstance(create_provider(empty), MockProvider)
    with pytest.raises(ProviderError, match="密钥"):
        create_provider(settings(api_key=""))
    with pytest.raises(ProviderError, match="不受支持"):
        create_provider(AISettings(provider="unknown"))


def test_client_disables_environment_proxy_and_redirects(monkeypatch):
    original = httpx.AsyncClient
    options = []

    def recording_client(*args, **kwargs):
        options.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", recording_client)
    generate(provider(lambda _: success()))
    assert options[0]["trust_env"] is False and options[0]["follow_redirects"] is False


def test_redaction_handles_keys_touching_chinese_and_response_text():
    fake_key = "sk-another-fake-secret-9876543210"
    phrase = "我的密钥" + fake_key + "请保护，邮箱demo@example.com，手机号13812345678"
    cleaned = redact_outbound(phrase)
    assert fake_key not in cleaned and "demo@example.com" not in cleaned and "13812345678" not in cleaned
    outbound = []

    def handler(request):
        outbound.append(request.content.decode())
        return success(phrase)

    answer = generate(provider(handler), "知情同意。" + phrase)
    assert fake_key not in outbound[0] and fake_key not in answer
    assert "demo@example.com" not in answer and "13812345678" not in answer


def test_compressed_response_is_rejected_before_reading():
    subject = provider(lambda _: httpx.Response(200, headers={"Content-Encoding": "gzip"},
                                                stream=httpx.ByteStream(b"not-read-or-inflated")))
    with pytest.raises(ProviderError, match="压缩响应"):
        generate(subject)
