from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"

    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str = ""

    deepgram_api_key: str = ""
    deepgram_stt_model: str = "nova-2"
    deepgram_tts_model: str = "aura-asteria-en"

    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    default_domain_profile_id: str = "00000000-0000-0000-0000-0000000000a1"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
