from typing import Type, TypeVar
from pydantic import BaseModel
from pathlib import Path

from google import genai
from google.genai import types

from app.services.chat.interface import ChatInterface
from app.configs.global_settings import BaseModelConfig

T = TypeVar('T', bound=BaseModel)

class GeminiChat(ChatInterface):
    def __init__(self, model_config: BaseModelConfig):
        super().__init__(model_config)
        
        self.client = genai.Client(api_key=model_config.api_key.get_secret_value())
    
    async def chat(self, prompt: str, images: list[str]|None = None, structured_schema: Type[T]|None = None) -> T|str:
        image_parts = []
        for image in images or []:
            ext = Path(image).suffix.lower()
            match ext:
                case ".jpg" | ".JPG" | ".jpeg" | ".JPEG":
                    ext = "jpg"
                case ".png" | ".PNG":
                    ext = "png"
                case _:
                    raise ValueError(f"Unsupported image format: {ext}")

            with open(image, 'rb') as f:
                img_bytes = f.read()

            image_parts.append(types.Part.from_bytes(
                data=img_bytes,
                mime_type=f'image/{ext}'
            ))

        response = await self.client.aio.models.generate_content(
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
        
    async def summary_docs(self, query: str, docs: list[str]) -> str:
        prompt="""
        你是資訊問答助手，你將盡可能詳盡地使用以下資訊回答問題。  
        僅根據提供的來源資料提供答案，不要擅自假設。
        最後回傳的答案不要包含任何類似"以下是摘要"或"以下是結論"等內容作為開頭。
        答案盡可能的簡短精要，切勿延伸話題。

        問題: {question}
        """

        references = []
        for i, doc in enumerate(docs, start=1):
            references.append(f"資料{i}:\n{doc}")


        response = await self.client.aio.models.generate_content(
            model=self.model_config.chat_model_name,
            contents=[
                prompt.format(question=query),
                *references
            ],
            config=types.GenerateContentConfig(
                temperature=self.model_config.temperature,
                max_output_tokens=self.model_config.max_tokens
            )
        )

        return response.text