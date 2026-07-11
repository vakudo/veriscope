from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b-instruct"
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    database_url: str | None = None
    search_max_results: int = 6
    evidence_top_k: int = 3
    duplicate_threshold: float = 0.88
    cache_similarity_threshold: float = 0.95
    min_relevance: float = 0.55
    max_claims: int = 3
    cross_lingual_search: bool = True
    result_cache_ttl_seconds: float = 21600.0
    calibration_path: str = "calibration.json"
    request_timeout: float = 120.0
    backend_url: str = "http://localhost:8000"
    telegram_bot_token: str = ""


def get_settings() -> Settings:
    return Settings()
