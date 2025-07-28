from abc import ABC, abstractmethod

from app.configs.global_settings import BaseModelConfig

class EmbeddingInterface(ABC):
    """
    Interface for chat.
    All chat models should implement this interface.
    """

    def __init__(self, model_config: BaseModelConfig):
        self.model_config = model_config
        self.validate_config()
        
        
    def validate_config(self):
        """
        An optional helper method used to verify whether the incoming `model_config` contain valid values.
        Subclasses may override this method to perform stricter validation.
        """
        pass


    @abstractmethod
    def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embedding vectors for a set of texts.
        - texts: A list containing multiple strings.
        """
        pass
