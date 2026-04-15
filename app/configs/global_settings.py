from typing import Literal

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseModelConfig(BaseModel):
    """Base model config"""
    api_key: SecretStr
    chat_model_name: str
    temperature: float
    max_tokens: int
    embedding_model_name: str
    embedding_dim: int
    gpu: bool
    rate_limit_sleep_s: float = 0.0  # Seconds to wait between LLM batch calls; set per-provider based on RPM quota
    llm_batch_size: int = 10         # Number of concurrent LLM requests per batch; set per-provider based on RPM quota


class OpenAIConfig(BaseModelConfig):
    """OpenAI model config"""
    api_key: SecretStr
    chat_model_name: str = "gpt-4o"
    temperature: float = 0.5
    max_tokens: int = 65536
    embedding_model_name: str = "text-embedding-3-large"
    embedding_dim: int = 3072
    gpu: bool = False
    rate_limit_sleep_s: float = 2.0  # Tier-1: ~500 RPM
    llm_batch_size: int = 30


class GeminiConfig(BaseModelConfig):
    """Gemini model config"""
    api_key: SecretStr
    chat_model_name: str = "gemma-4-31b-it"
    temperature: float = 0.5
    max_tokens: int = 65536
    embedding_model_name: str = "gemini-embedding-001"
    embedding_dim: int = 1536
    gpu: bool = False
    rate_limit_sleep_s: float = 60.0  # Free tier: 30 RPM
    llm_batch_size: int = 10          # Free tier: 15 req/batch × sleep 60s ≈ 15 RPM


class HuggingFaceConfig(BaseModelConfig):
    """HuggingFace model config"""
    api_key: SecretStr
    chat_model_name: str = "Qwen/Qwen3-8B"
    temperature: float = 0.5
    max_tokens: int = 65536
    embedding_model_name: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024
    gpu: bool = True
    rate_limit_sleep_s: float = 0.0  # Local inference, no rate limit
    llm_batch_size: int = 10          # Memory-bound; adjust based on VRAM


class CustomLLMConfig(BaseModelConfig):
    """Custom LLM config"""
    pass


class CustomEmbeddingConfig(BaseModelConfig):
    """Custom Embedding config"""
    pass


class GlobalSettings(BaseSettings):
    """Global settings for the application"""
    # LLM settings
    ACTIVE_LLM_PROVIDER: Literal["openai", "gemini", "huggingface"] = "gemini"
    ACTIVE_EMBEDDING_PROVIDER: Literal["openai", "gemini", "huggingface"] = "gemini"

    # API keys
    AUTH_KEY: SecretStr  # API header for authentication
    OPENAI_API_KEY: SecretStr
    GEMINI_API_KEY: SecretStr
    HF_API_KEY: SecretStr

    # Logging settings
    LOG_LEVEL: Literal["NOTSET", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"  # https://docs.python.org/3/library/logging.html#logging-levels
    LOG_DIR: str = "logs"
    LOG_FILENAME: str = "app.log"
    LOG_WHEN: Literal["S", "M", "H", "D", "W0", "W1", "W2", "W3", "W4", "W5", "W6", "midnight"] = "midnight"    # https://docs.python.org/3/library/logging.handlers.html#timedrotatingfilehandler
    LOG_INTERVAL: int = 1
    LOG_BACKUP_COUNT: int = 30
    LOG_UTC: bool = False

    # data store settings
    CRAWLER_DATA_DIR: str = "app/data_store/raw_json"
    VECTOR_CLIENT_URL: str = "http://localhost:19530"
    VECTOR_COLLECTION_NAME: str = "TaiwanCard"

    # Crawler concurrency settings
    CRAWL_MAX_CONCURRENT_JOBS: int = 3    # Max simultaneous Playwright subprocesses per worker process
    CRAWL_QUEUE_MAX_SIZE: int = 50        # Max jobs waiting in queue; returns 503 when full
    CRAWL_BATCH_MAX_SIZE: int = 50        # Max items allowed per batch request

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_active_llm_config(self) -> BaseModelConfig:
        """get the active llm config"""
        provider_map = {
            "openai": OpenAIConfig(api_key=self.OPENAI_API_KEY),
            "gemini": GeminiConfig(api_key=self.GEMINI_API_KEY),
            "huggingface": HuggingFaceConfig(api_key=self.HF_API_KEY),
        }
        config = provider_map.get(self.ACTIVE_LLM_PROVIDER)
        if config is None:
            raise ValueError(f"Unsupported LLM Text Provider: {self.ACTIVE_LLM_PROVIDER}")
        return config
    
    def get_active_embedding_config(self) -> BaseModelConfig:
        """get the active embedding config"""
        provider_map = {
            "openai": OpenAIConfig(api_key=self.OPENAI_API_KEY),
            "gemini": GeminiConfig(api_key=self.GEMINI_API_KEY),
            "huggingface": HuggingFaceConfig(api_key=self.HF_API_KEY),
        }
        config = provider_map.get(self.ACTIVE_EMBEDDING_PROVIDER)
        if config is None:
            raise ValueError(f"Unsupported Embedding Provider: {self.ACTIVE_EMBEDDING_PROVIDER}")
        return config
    
global_settings = GlobalSettings()

if __name__ == "__main__":
    print(global_settings)