from app.ai.base import LLMProvider
from app.core.config import Settings
from app.core.errors import ConfigurationError


def create_llm_provider(settings: Settings) -> LLMProvider:
    name = settings.llm_provider.lower()
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is not set")
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, settings.llm_model)
    if name == "fake":
        from app.ai.fake import FakeLLMProvider

        return FakeLLMProvider(lambda s, m: "I'm running in fake LLM mode.")
    raise ConfigurationError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'")


class LazyLLMProvider(LLMProvider):
    """Defers provider construction (and its config errors) until the first LLM call, so endpoints
    that never talk to the model (create/get conversation) work without an API key."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._provider: LLMProvider | None = None

    def stream(self, system, messages, tools):
        if self._provider is None:
            self._provider = create_llm_provider(self._settings)
        return self._provider.stream(system, messages, tools)
