import asyncio
import json
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

from app.services.llm_factory import LLMFactory
from app.services.milvus import MilvusManager
from pydantic import ValidationError

from app.services.schema import (
    VectorDatabaseData, 
    SourceData, 
    LLMResponse, 
    CardInfo, 
    VectorizeResult, 
    ImageSummary,
    CardFacts, 
    QueryRoute, 
    CompareAnswer,
)
from app.services.store import ChunkInput, Store
from app.services.prompts import (
    QA_SYSTEM_PROMPT,
    SUMMARY_PROMPT,
    PROMPT_VER,
    FACTS_PROMPT,
    ROUTE_PROMPT,
    COMPARE_PROMPT,
)
from app.configs.global_settings import global_settings


class RAG():
    def __init__(
        self,
        vector_storage_url: str,
        collection_name: str,
    ):
        self.llm = LLMFactory.get_llm()
        self.embedding = LLMFactory.get_embedding()

        _llm_config = global_settings.get_active_llm_config()
        self._rate_limit_sleep_s = _llm_config.rate_limit_sleep_s
        self._llm_batch_size = _llm_config.llm_batch_size
        
        self.vector_manager = MilvusManager(
            url=vector_storage_url,
            collection_name=collection_name,
            embedding_dim=self.embedding.embedding_dim
        )
        self.vector_manager.create_collection()

    async def _summarized(self, image: str, timeout: float) -> ImageSummary:
        """
        Ask the vision model for one image's sections.
        If the provider cannot parse the image, return None.
        """
        response = await asyncio.wait_for(
            self.llm.chat(SUMMARY_PROMPT, [image], ImageSummary), timeout=timeout
        )
        if not isinstance(response, ImageSummary):
            raise ValueError("The model's reply could not be parsed into sections.")
        return response

    @staticmethod
    def _load_cached(raw: str | None) -> ImageSummary | None:
        """A cache entry that no longer parses is treated as a miss, not as an error."""
        if raw is None:
            return None
        try:
            return ImageSummary.model_validate_json(raw)
        except ValidationError:
            logger.warning("Ignoring a cached summary that could not be parsed.")
            return None

    async def _extract_facts(
        self, texts: list[str], timeout: float, retry_count: int
    ) -> CardFacts | None:
        """
        Condense a card's sections into its facts with one text-only call.
        Returns None once the retries are spent.
        """
        prompt = f"{FACTS_PROMPT}\n\n內容：\n\n" + "\n\n".join(texts)
        for attempt in range(retry_count + 1):
            try:
                response = await asyncio.wait_for(
                    self.llm.chat(prompt, None, CardFacts), timeout=timeout
                )
                if isinstance(response, CardFacts):
                    return response
                error = "the model's reply could not be parsed into facts"
            except Exception as e:
                error = e
            logger.warning(f"Fact extraction attempt {attempt + 1}/{retry_count + 1} failed: {error}")
        return None

    @staticmethod
    def _facts_still_hold(store: Store, card_key: str, hashes: list[str]) -> bool:
        """
        True when the facts on file were made from exactly this content and still
        fit CardFacts — a card that gained a fact field since is extracted again.
        """
        card = store.cards.get(card_key)
        if card is None or not card.facts_json:
            return False
        if [chunk.content_hash for chunk in store.chunks.list_for_card(card_key)] != hashes:
            return False
        try:
            CardFacts.model_validate(card.facts_json)
        except ValidationError:
            return False
        return True

    async def analyze_images_to_vecdb(
        self,
        feature_jsonl_path: str | Path,
        card_key: str,
        card_name: str,
        bank_code: str,
        store: Store,
        model_timeout: float = 30.0,
        retry_count: int = 3,
        embedding_batch_size: int | None = None,
    ) -> VectorizeResult:
        """
        Summarize card feature images via LLM into sections, embed each section,
        and replace the card's vectors in Milvus with the result.

        Summaries are reused per image whenever the captured content
        fingerprints the same as a previous crawl.

        If any image fails to summarize, the card keeps the vectors it already
        had and `vectorized` comes back 0. Summaries that did succeed are
        still cached, so a retry only pays for the images that failed.

        The card's facts are extracted from the same sections and are part of
        the same all-or-nothing: if they cannot be extracted nothing is written,
        so a card's vectors and its facts always come from the same crawl.
        """
        with open(feature_jsonl_path, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]

        model_name = self.llm.model_config.chat_model_name
        entries = [
            {
                "url": row["page_url"],
                "image": row["image_path"],
                "hash": row.get("content_hash"),
                "summary": None,
            }
            for row in rows
        ]

        # step1: load summary cache from database
        for entry in entries:
            entry["summary"] = self._load_cached(
                store.summaries.get(entry["hash"], model_name, PROMPT_VER)
            )

        pending = [e for e in entries if e["summary"] is None]
        cached = len(entries) - len(pending)
        logger.info(
            f"Vectorizing card '{card_name}' ({bank_code}): {len(entries)} images — "
            f"{cached} reused from cache, {len(pending)} to summarize (batch_size={self._llm_batch_size})."
        )

        # step2: for images without summary cached, call the LLM to analyze them (with retry on error).
        failed = 0
        for i in range(0, len(pending), self._llm_batch_size):
            batch = pending[i:i + self._llm_batch_size]
            logger.info(f"Processing LLM batch {i // self._llm_batch_size + 1}: {len(batch)} image(s).")

            responses = await asyncio.gather(
                *(self._summarized(e["image"], model_timeout) for e in batch),
                return_exceptions=True,
            )

            for entry, response in zip(batch, responses):
                # retry failed items individually
                for attempt in range(retry_count):
                    if not isinstance(response, Exception):
                        break
                    logger.warning(f"Retry {attempt + 1}/{retry_count} for image: {entry['image']}.")
                    try:
                        response = await self._summarized(entry["image"], model_timeout)
                    except Exception as e:
                        response = e

                if isinstance(response, Exception):
                    logger.error(
                        f"Skipping image after {retry_count} retries: {entry['image']}. Error: {response}"
                    )
                    failed += 1
                    continue

                entry["summary"] = response
                store.summaries.put(entry["hash"], model_name, PROMPT_VER, response.model_dump_json())

            # flow restrictions vary by model — skip sleep after the last batch
            if i + self._llm_batch_size < len(pending) and self._rate_limit_sleep_s > 0:
                logger.info(f"Rate-limit pause: sleeping {self._rate_limit_sleep_s}s before next batch.")
                await asyncio.sleep(self._rate_limit_sleep_s)

        # step3: if any data failed, abort the task immediately and log the error.
        ready = [e for e in entries if e["summary"] is not None]
        summarized = len(ready) - cached
        logger.info(f"Summarization complete: {cached} cached, {summarized} generated, {failed} failed.")

        if failed:
            logger.warning(f"Aborting vectorization of '{card_name}': {failed} of {len(entries)} image(s).")
            return VectorizeResult(
                images=len(entries), cached=cached, summarized=summarized, failed=failed, vectorized=0
            )

        # step4: repackage analyzed data as input for the embedding stage.
        records = [
            (entry, section.section, f"{card_name}｜{section.section}\n{section.content.strip()}")
            for entry in ready
            for section in entry["summary"].sections
            if section.content.strip()
        ]

        if not records:
            logger.warning(f"Nothing to vectorize for '{card_name}': no card content was found in {len(entries)} image(s).")
            return VectorizeResult(
                images=len(entries), cached=cached, summarized=summarized, failed=0, vectorized=0
            )

        # step5: generate a basic fact of all analyzed chunks for this card and store it in the DB.
        texts = [text for _, _, text in records]
        hashes = [entry["hash"] for entry in ready]

        facts: CardFacts | None = None
        if summarized == 0 and self._facts_still_hold(store, card_key, hashes):
            logger.info(f"Content of '{card_name}' is unchanged: keeping its existing facts.")
        else:
            facts = await self._extract_facts(texts, model_timeout, retry_count)
            if facts is None:
                logger.warning(f"Aborting vectorization of '{card_name}': its facts could not be extracted.")
                return VectorizeResult(images=len(entries), cached=cached, summarized=summarized, failed=0, vectorized=0, facts_extracted=False)

        # setp6: embed all summaries and save them with metadata to the vector DB.
        logger.info(f"Embedding {len(records)} sections from {len(ready)} images ")
        if embedding_batch_size:
            embedding_texts = []
            for j in range(0, len(texts), embedding_batch_size):
                embedding_texts.extend(
                    await self.embedding.create_embeddings(texts[j:j + embedding_batch_size])
                )
        else:
            embedding_texts = await self.embedding.create_embeddings(texts)
        logger.info("Embedding complete.")

        items = [
            VectorDatabaseData(
                text=text,
                vector=embedding,
                url=entry["url"],
                section=section,
                card_key=card_key,
                card_name=card_name,
                bank_code=bank_code,
            )
            for (entry, section, text), embedding in zip(records, embedding_texts)
        ]

        self.vector_manager.delete(key="card_key", value=card_key)
        self.vector_manager.insert(items)
        logger.info(f"Replaced Milvus records for card '{card_name}' ({bank_code}) with {len(items)} new ones.")

        store.chunks.replace_for_card(card_key, [
            ChunkInput(seq=seq, page_url=entry["url"], content_hash=entry["hash"])
            for seq, entry in enumerate(ready)
        ])
        if facts is not None:
            store.cards.update_facts(card_key, facts.model_dump())

        # step7: return data
        return VectorizeResult(
            images=len(entries),
            cached=cached,
            summarized=summarized,
            failed=failed,
            vectorized=len(items),
            facts_extracted=True,
        )


    async def list_cards(self, bank_code: Optional[str] = None) -> list[CardInfo]:
        return self.vector_manager.list_cards(bank_code=bank_code)

    async def delete_card(self, card_key: str):
        self.vector_manager.delete(key="card_key", value=card_key)


    async def chat(
        self,
        query: str,
        store: Store,
        card_key: Optional[str] = None,
        bank_code: Optional[str] = None,
        top_k: int = 10
    ) -> LLMResponse:
        """
        Answer the user's question.

        The question is first analyzed to decide the route:  
        `sql`: reads the card facts from the database without searching the vector database.  
        `vector`: searches the vector database for analysis.

        This strategy speeds up ranking-related questions.
        """
        if not card_key:
            route = await self._route(query)
            if route is not None and route.route == "sql" and route.facts:
                response = await self._answer_from_facts(query, route.facts, store, bank_code)
                if response is not None:
                    return response

        return await self._answer_from_vectors(query, card_key, bank_code, top_k)

    async def _route(self, query: str) -> QueryRoute | None:
        """Decide where to answer from. None when the model cannot say."""
        try:
            response = await self.llm.chat(f"{ROUTE_PROMPT}\n\n使用者問題：{query}", None, QueryRoute)
        except Exception as e:
            logger.warning(f"Routing failed, answering from the vector store: {e}")
            return None
        if not isinstance(response, QueryRoute):
            logger.warning("Routing reply could not be parsed, answering from the vector store.")
            return None
        logger.info(f"Question routed to '{response.route}' with facts {response.facts}.")
        return response

    async def _answer_from_vectors(self, query: str, card_key: Optional[str], bank_code: Optional[str], top_k: int) -> LLMResponse:
        sources = self.vector_manager.hybrid_search(
            query=query,
            query_vector=(await self.embedding.create_embeddings([query]))[0],
            card_key=card_key,
            bank_code=bank_code,
            reranker=True,
            top_k=top_k
        )

        references = [source.text for source in sources]
        response = await self.llm.summary_docs(query, references, QA_SYSTEM_PROMPT)

        return LLMResponse(response=response, route="vector", sources=sources)

    async def _answer_from_facts(self, query: str, facts: list[str], store: Store, bank_code: Optional[str]) -> LLMResponse | None:
        """
        Compare every card on the named facts. None when no card has facts yet.
        """
        cards = store.cards.list_with_facts(bank_code)
        if not cards:
            logger.warning("No card has facts yet, answering from the vector store.")
            return None
        
        # A reward rate means nothing without its form, so these always bring reward_type along.
        reward_facts = {"base_reward", "max_reward", "reward_cap", "overseas_reward", "featured_channels"}
        names = list(dict.fromkeys(facts))
        if reward_facts.intersection(names) and "reward_type" not in names:
            names.insert(0, "reward_type")

        
        # The Chinese name of each fact: the part of its description before "：".
        fact_labels = {
            name: field.description.split("：", 1)[0] for name, field in CardFacts.model_fields.items()
        }

        blocks = [
            f"{card.card_name}（{card.bank_code}）\n"
            + "\n".join(f"{fact_labels[name]}：{card.facts_json.get(name, '未載明')}" for name in names)
            for card in cards
        ]
        references = "\n\n".join(f"資料{i}:\n{block}" for i, block in enumerate(blocks, start=1))
        prompt = f"{QA_SYSTEM_PROMPT}\n\n{COMPARE_PROMPT}\n\n問題：{query}\n\n參考資料：\n\n{references}"
        logger.info(f"Comparing {len(cards)} card(s) on {names}.")

        # get responses and merge answers
        response = await self.llm.chat(prompt, None, CompareAnswer)
        if not isinstance(response, CompareAnswer):
            raise ValueError("The comparison reply could not be parsed.")

        # use a dictionary to remove duplicates while maintaining the original order
        cited = [n for n in dict.fromkeys(response.cited) if 1 <= n <= len(cards)]
        sources = [
            SourceData(
                text=blocks[n - 1],
                url=cards[n - 1].card_url,
                card_key=cards[n - 1].card_key,
                card_name=cards[n - 1].card_name,
                bank_code=cards[n - 1].bank_code,
            )
            for n in cited
        ]
        return LLMResponse(response=response.answer, route="sql", sources=sources)


    def close(self):
        self.vector_manager.close()