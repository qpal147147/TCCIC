from typing import Any
from pathlib import Path

import numpy as np
from numpy.linalg import norm
from google import genai
from google.genai import types

from app.llm_handler.embedding.interface import EmbeddingInterface
from app.configs.global_settings import BaseModelConfig


class GeminiEmbedding(EmbeddingInterface):
    def __init__(self, model_config: BaseModelConfig):
        super().__init__(model_config)
        self.client = genai.Client(api_key=model_config.api_key.get_secret_value())

    def create_embeddings(self, texts: list[str], dim: int) -> list[list[float]]:
        result = self.client.models.embed_content(
            model=self.model_config.embedding_model_name,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="SEMANTIC_SIMILARITY",
                output_dimensionality=dim # 3072, 1536, 768. https://ai.google.dev/gemini-api/docs/embeddings#control-embedding-size
            ),
        )

        # Normalization is required for all values except 3072.
        normed_embeddings = []
        for embedding_obj in result.embeddings:
            embedding_values_np = np.array(embedding_obj.values)
            normed_embeddings.append(embedding_values_np / np.linalg.norm(embedding_values_np))

        return normed_embeddings