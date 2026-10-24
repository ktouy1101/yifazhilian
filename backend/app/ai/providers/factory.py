from app.ai.providers.base import AIProvider, ProviderError
from app.ai.providers.mock import MockProvider
from app.config import AISettings


def create_provider(settings: AISettings) -> AIProvider:
    if settings.provider == "mock":
        return MockProvider()
    if settings.provider in ("openai_compatible", "deepseek"):
        from app.ai.providers.compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(settings)
    raise ProviderError(503, "AI provider配置不受支持；请在本机检查配置。")
