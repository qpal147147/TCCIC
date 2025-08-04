import asyncio
import json
from typing import Optional

from app.services.llm_factory import LLMFactory
from app.services.lancedb import lanceDBManager
from app.services.schema import VectorDatabaseData, SourceData, LLMResponse


class RAG():
    def __init__(
        self,
        vector_storage_path: str,
        collection_name: str,
    ):
        self.llm = LLMFactory.get_llm()
        self.embedding = LLMFactory.get_embedding()
        self.vector_manager = lanceDBManager(
            url=vector_storage_path, 
            table_name=collection_name, 
            embedding_dim=self.embedding.embedding_dim
        )

    async def chunk_images_to_vecdb(
        self, 
        feature_jsonl_path: str, 
        card_id: str,
        card_name: str,
        bank_code: str,
        batch_size: int = 30, 
        retry_count: int = 3
    ) -> None:
        prompt = """
        此影像是一個信用卡的資訊頁面，包含活動、特色、注意事項、期間等等關於信用卡的資訊，請讀取影像中的所有文字並製作一個約700字的摘要。
        不要添加"以下是摘要"或"以下是結論"等內容作為開頭。
        範例:

        產品特色：
           切換刷平台： 適用至2025年12月31日，7大方案任選，最高可享3.8%回饋。
           切換刷方案： 天天刷/大筆刷/好饗刷，最高享3.3%回饋，每日皆可切換。
           期間限定韓瘋刷： 指定通路消費最高享10%回饋，新申請優惠期間內回饋額度與SAMSUNG加購相同。
           Richart 新戶獨享： 完成新戶任務，享最高NT$200元用戶禮。
           Mastercard 鈦金卡： 海外消費最高享13.3%回饋及機場接送等優惠。
           JCB 晶緻卡： Agoda 訂房享10.3%、機場接送、五星饗宴等好康。
           保費最高2.7%回饋： 不含國外保費，詳情請見官網。
           新卡預約分期超減壓： 優惠利率分期。
           支援「卡號直連」服務： 繳納帳單更即時。
           高額旅遊平安險： 旅遊平安險最高NT$3,000萬。
           刷卡交易設定： 即時刷卡知賓，交易安心！
           網路交易APP體驗： 享受更快、更安全、更方便的網路交易體驗方式。

        優惠活動：
           頂級美饌85折起： 活動期間為2025年1月1日至2025年12月31日，憑指定卡別至指定餐廳消費享優惠。
           訂房最高12%：
           全球WiFi 63折： 活動對象為台新玫瑰卡/太陽卡(切換刷)的正卡人。
           看電影平日7折：

        申請資格：
           正卡申請人須為成年人；附卡申請人須滿15歲（未成年者，須由法定代理人同意）。
           需為正卡持卡人之配偶、父母、子女、兄弟姊妹或配偶父母。

        年費收費標準：
           活動期間：2025/1/1~2025/12/31
           商務鈦金卡：正卡每卡每年NT$4,500，附卡每卡每年NT$4,500。
           晶緻卡：正卡每卡每年NT$1,500，附卡每卡每年NT$750。
           免年費辦法：玫瑰悠遊Mastercard(鈦金商務卡)：首年免年費，次年起使用新台幣電子/行動簡訊帳單且生效，享免年費優惠。
           太陽悠遊JCB(晶緻卡)：首年免年費，次年起使用新台幣電子/行動簡訊帳單且生效，享免年費優惠。

        其他注意事項：
           部分優惠活動有期間限制，詳情請參閱官網。
           最高3.3%回饋需符合特定條件，例如綁定台新帳戶自動扣繳卡費。
           指定通路單筆消費需滿額才有回饋。
        """.strip()

        with open(feature_jsonl_path, "r", encoding="utf-8") as f:
            feature_data = [json.loads(line) for line in f]
        
        # batch process image
        all_results: list[dict[str, str]] = []
        tasks = [(data["page_url"], data["image_path"]) for data in feature_data]
        for i in range(0, len(tasks), batch_size):
            batch_tasks = tasks[i:i+batch_size]
            
            coroutines = [self.llm.chat(prompt, [image_path]) for _, image_path in batch_tasks]
            batch_responses = await asyncio.gather(*coroutines, return_exceptions=True)

            # combination information
            batch_results = [
                {"url": page_url, "image": image_path, "response": response}
                for (page_url, image_path), response in zip(batch_tasks, batch_responses)
            ]

            # check exception and retry
            for result in batch_results:
                for attemp in range(retry_count):
                    if not isinstance(result["response"], Exception):
                        break
                    
                    try:
                        result["response"] = await self.llm.chat(prompt, [result["image"]])
                    except Exception as e:
                        result["response"] = e
                
                if isinstance(result["response"], Exception):
                    raise result["response"]

            # append results
            all_results.extend(batch_results)
            
            # flow restrictions vary by model
            if i+batch_size < len(tasks):
                await asyncio.sleep(60)

        # embed response
        embedding_texts = await self.embedding.create_embeddings([result["response"] for result in all_results])

        # store in vector database
        items = []
        for i, (result, embedding) in enumerate(zip(all_results, embedding_texts)):
            items.append(VectorDatabaseData(
                text=result["response"],
                vector=embedding,
                url=result["url"],
                card_id=card_id,
                card_name=card_name,
                bank_code=bank_code
            ))

        self.vector_manager.insert(items)


    async def delete_card(self, card_id: str):
        self.vector_manager.delete_rows("card_id", card_id)


    async def chat(
        self, 
        query: str,
        card_id: Optional[str] = None,
        bank_code: Optional[str] = None,
        top_k: int = 10
    ) -> LLMResponse:
        results = self.vector_manager.hybird_search(
            query=query,
            vector=(await self.embedding.create_embeddings([query]))[0],
            card_id=card_id,
            bank_code=bank_code,
            reranker=True,
            top_k=top_k
        )

        sources: list[SourceData] = []
        references: list[str] = []
        for row in results.itertuples(index=True):
            sources.append(SourceData(
                text=row.text,
                url=row.url,
                card_id=row.card_id,
                bank_code=row.bank_code
            ))
            references.append(row.text)

        response = await self.llm.summary_docs(query, references)

        return LLMResponse(
            response=response,
            sources=sources
        )


    async def update_card(self):
        pass