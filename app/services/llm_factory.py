from app.services.chat.gemini import GeminiChat
from app.services.embedding.gemini import GeminiEmbedding
from app.configs.global_settings import global_settings

class LLMFactory:
    @staticmethod
    def get_llm():
        llm_provider = global_settings.ACTIVE_LLM_PROVIDER
        if llm_provider == "gemini":
            return GeminiChat(global_settings.get_active_llm_config())
        else:
            raise ValueError(f"Unsupported LLM Provider: {llm_provider}")

    @staticmethod
    def get_embedding():
        embedding_provider = global_settings.ACTIVE_EMBEDDING_PROVIDER
        if embedding_provider == "gemini":
            return GeminiEmbedding(global_settings.get_active_embedding_config())
        else:
            raise ValueError(f"Unsupported Embedding Provider: {embedding_provider}")