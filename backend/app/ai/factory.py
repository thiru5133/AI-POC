from app.ai.base import LLMProvider
from app.core.config import Settings
from app.core.errors import ConfigurationError

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5-5"


def create_llm_provider(settings: Settings) -> LLMProvider:
    name = settings.llm_provider.lower()
    if name == "groq":
        if not settings.groq_api_key:
            raise ConfigurationError("GROQ_API_KEY is not set")
        from app.ai.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            settings.groq_api_key, settings.llm_model or GROQ_DEFAULT_MODEL, GROQ_BASE_URL
        )
    if name == "openai_compatible":  # OpenAI, Gemini compat endpoint, Ollama, ...
        if not settings.llm_base_url or not settings.llm_model:
            raise ConfigurationError("LLM_BASE_URL and LLM_MODEL are required for openai_compatible")
        from app.ai.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings.llm_api_key, settings.llm_model, settings.llm_base_url)
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY is not set")
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, settings.llm_model or ANTHROPIC_DEFAULT_MODEL)
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
