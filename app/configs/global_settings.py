from typing import Literal, Optional, Dict, Any

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseModel):
    """Base config"""
    api_key: SecretStr
    llm_model_name: str
    temperature: float
    max_tokens: int
    embedding_model_name: str
    gpu: bool


class OpenAIConfig(BaseConfig):
    """OpenAI model config"""
    api_key: SecretStr
    llm_model_name: str = "gpt-4o"
    temperature: float = 0.5
    max_tokens: int = 65536
    embedding_model_name: str = "text-embedding-3-large"
    gpu: bool = False


class GeminiConfig(BaseConfig):
    """Gemini model config"""
    api_key: SecretStr
    llm_model_name: str = "gemini-2.0-flash"
    temperature: float = 0.5
    max_tokens: int = 65536
    embedding_model_name: str = "gemini-embedding-001"
    gpu: bool = False


class HuggingFaceConfig(BaseConfig):
    """HuggingFace model config"""
    api_key: SecretStr
    llm_model_name: str = "Qwen/Qwen3-8B"
    temperature: float = 0.5
    max_tokens: int = 65536
    embedding_model_name: str = "intfloat/multilingual-e5-large"
    gpu: bool = True


class CustomLLMConfig(BaseModel):
    """Custom LLM config"""
    pass


class CustomEmbeddingConfig(BaseModel):
    """Custom Embedding config"""
    pass


class GlobalSettings(BaseSettings):
    """Global settings for the application"""
    # LLM settings
    ACTIVE_LLM_PROVIDER: Literal["openai", "gemini", "huggingface"] = "gemini"
    ACTIVE_EMBEDDING_PROVIDER: Literal["openai", "gemini", "huggingface"] = "openai"

    # API keys
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
    VECTOR_STORE_DIR: str = "app/data_store/vector_store"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_active_llm_config(self) -> BaseConfig:
        """get the active llm config"""
        provider_map = {
            "openai": OpenAIConfig(api_key=self.OPENAI_API_KEY.get_secret_value()),
            "gemini": GeminiConfig(api_key=self.GEMINI_API_KEY.get_secret_value()),
            "huggingface": HuggingFaceConfig(api_key=self.HF_API_KEY.get_secret_value()),
        }
        config = provider_map.get(self.ACTIVE_LLM_PROVIDER)
        if config is None:
            raise ValueError(f"Unsupported LLM Text Provider: {self.ACTIVE_LLM_PROVIDER}")
        return config
    
    def get_active_embedding_config(self) -> BaseConfig:
        """get the active embedding config"""
        provider_map = {
            "openai": OpenAIConfig(api_key=self.OPENAI_API_KEY.get_secret_value()),
            "gemini": GeminiConfig(api_key=self.GEMINI_API_KEY.get_secret_value()),
            "huggingface": HuggingFaceConfig(api_key=self.HF_API_KEY.get_secret_value()),
        }
        config = provider_map.get(self.ACTIVE_EMBEDDING_PROVIDER)
        if config is None:
            raise ValueError(f"Unsupported Embedding Provider: {self.ACTIVE_EMBEDDING_PROVIDER}")
        return config
    
global_settings = GlobalSettings()

if __name__ == "__main__":
    print(global_settings.get_active_embedding_config().api_key.get_secret_value())
    # print(global_settings)