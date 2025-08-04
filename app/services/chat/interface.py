from abc import ABC, abstractmethod
from typing import List, Any

from app.configs.global_settings import BaseModelConfig

class ChatInterface(ABC):
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
    async def chat(self, prompt: str, images: List[str]|None, structured_schema: Any|None) -> Any|str:
        """
        Generate a response based on the given prompt and conversation history.
        - prompt: User input.
        - images: If images are provided, pass in a list of image paths. The format should be `png` or `jpg`.
        - structured_schema: Define a `Pydantic` model to specify the format that the language model should adhere to when producing text output.

        - Returns: If the `structured_schema` parameter is provided, the output will be a `structured_schema` object; otherwise, it will be a `string`.
        """
        pass

    @abstractmethod
    async def summary_docs(self, query: str, docs: List[str]) -> str:
        """
        Generate a summary based on the given prompt and documents.
        - query: User input.
        - docs: References used to summarize information.
        """
        pass