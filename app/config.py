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
    query_plan_max_queries: int = 5
    query_planning: bool = False
    evidence_top_k: int = 3
    duplicate_threshold: float = 0.88
    cache_similarity_threshold: float = 0.95
    min_relevance: float = 0.55
    max_claims: int = 3
    claim_chunk_chars: int = 3500
    claim_chunk_overlap: int = 300
    claim_max_chunks: int = 8
    cross_lingual_search: bool = True
    verify_conflicts: bool = True
    deep_evidence: bool = True
    article_fetch_timeout: float = 12.0
    max_article_bytes: int = 5_000_000
    max_article_redirects: int = 5
    max_concurrent_analyses: int = 1
    rate_limit_requests: int = 10
    rate_limit_window_seconds: float = 60.0
    cors_origins: str = "*"
    result_cache_ttl_seconds: float = 21600.0
    calibration_path: str = "calibration.json"
    calibration_min_samples: int = 20
    request_timeout: float = 120.0
    api_access_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    return Settings()
