from typing import Any
from pathlib import Path

from google import genai
from google.genai import types

from app.llm_handler.chat.interface import ChatInterface
from app.configs.global_settings import BaseModelConfig

class GeminiChat(ChatInterface):
    def __init__(self, model_config: BaseModelConfig):
        super().__init__(model_config)

        self.client = genai.Client(api_key=model_config.api_key.get_secret_value())
    
    def chat(self, prompt: str, images: list[str]|None = None, structured_schema: Any|None = None) -> Any|str:
        image_parts = []
        for image in images or []:
            ext = Path(image).suffix.lower()
            match ext:
                case ".jpg" | ".JPG" | ".jpeg" | ".JPEG":
                    ext = "jpg"
                case ".png" | ".PNG":
                    ext = "png"
                case _:
                    return ValueError(f"Unsupported image format: {ext}")

            with open(image, 'rb') as f:
                img_bytes = f.read()

            image_parts.append(types.Part.from_bytes(
                data=img_bytes,
                mime_type=f'image/{ext}'
            ))

        response = self.client.models.generate_content(
            model=self.model_config.chat_model_name,
            contents=[
                prompt,
                *image_parts
            ],
            config=types.GenerateContentConfig(
                temperature=self.model_config.temperature,
                response_mime_type="application/json" if structured_schema else None,
                response_schema=structured_schema if structured_schema else None,
                max_output_tokens=self.model_config.max_tokens
            )
        )

        if structured_schema:
            return response.parsed
        else:
            return response.text