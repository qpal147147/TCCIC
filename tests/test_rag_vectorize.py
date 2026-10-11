"""
Tests for how a card is vectorized: which images reach the model, and how the
card's vectors are replaced.

The LLM, embedder and Milvus are stubbed and the store runs in memory, so these
run offline and cover the two things that matter — a card must never be left
empty because summarization failed, and unchanged content must not be paid for
twice.

Using: pytest tests/test_rag_vectorize.py
"""

import asyncio
import json

import pytest

from app.services.rag import _PROMPT_VER, RAG
from app.services.schema import ImageSummary, SummarySection
from app.services.store import Store

CARD_KEY = "0f5a1c9de4b27a3f8c6d0e1b2a394857c6d0e1b2"
MODEL = "stub-vision-model"


class StubModelConfig:
    chat_model_name = MODEL


def summary(*sections: tuple[str, str]) -> ImageSummary:
    return ImageSummary(sections=[SummarySection(section=s, content=c) for s, c in sections])


class StubLLM:
    """
    Transcribes images, one section each unless `sections_for` says otherwise.
    `fail` reproduces a provider outage; `fail_for` singles out one image, which
    is how a partial failure gets exercised; `unparseable_for` reproduces a reply
    the provider could not parse, which arrives as None rather than as an error.
    """

    model_config = StubModelConfig()

    def __init__(
        self,
        fail: bool = False,
        fail_for: set[str] | None = None,
        unparseable_for: set[str] | None = None,
        sections_for: dict[str, list[tuple[str, str]]] | None = None,
    ):
        self.fail = fail
        self.fail_for = fail_for or set()
        self.unparseable_for = unparseable_for or set()
        self.sections_for = sections_for or {}
        self.seen: list[str] = []

    async def chat(self, prompt, images=None, structured_schema=None):
        image = images[0]
        self.seen.append(image)
        if self.fail or image in self.fail_for:
            raise RuntimeError("HTTP/1.1 500 Internal Server Error")
        if image in self.unparseable_for:
            return None
        return summary(*self.sections_for.get(image, [("其他", f"內容 {image}")]))


class StubEmbedding:
    async def create_embeddings(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class StubVectorManager:
    """Records what was asked of Milvus, and in what order."""

    def __init__(self):
        self.events: list[tuple] = []
        self.inserted: list = []

    def delete(self, key, value):
        self.events.append(("delete", value))

    def insert(self, data):
        self.events.append(("insert", len(data)))
        self.inserted = list(data)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.create_all()
    yield s
    s.close()


@pytest.fixture
def jsonl(tmp_path):
    def _write(count: int):
        path = tmp_path / f"{CARD_KEY}.jsonl"
        rows = [
            {
                "page_url": f"https://bank.test/card#{i}",
                "image_path": f"{i}.png",
                "content_hash": f"hash-{i}",
                "text_len": 100,
                "img_count": 2,
            }
            for i in range(count)
        ]
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        return path

    return _write


def build_rag(llm: StubLLM) -> RAG:
    # Bypass __init__: it would reach for a real Milvus and a real provider.
    rag = RAG.__new__(RAG)
    rag.llm = llm
    rag.embedding = StubEmbedding()
    rag.vector_manager = StubVectorManager()
    rag._rate_limit_sleep_s = 0
    rag._llm_batch_size = 10
    return rag


def vectorize(rag: RAG, path, store: Store):
    return asyncio.run(
        rag.analyze_images_to_vecdb(path, CARD_KEY, "測試卡", "taishin", store)
    )


def seed_cache(store: Store, *indexes: int):
    for i in indexes:
        store.summaries.put(
            f"hash-{i}", MODEL, _PROMPT_VER, summary(("其他", f"快取內容 {i}")).model_dump_json()
        )


# --- failure handling --------------------------------------------------------

def test_total_failure_leaves_the_existing_vectors_alone(jsonl, store):
    """
    An LLM outage must not empty a card that was working. Deleting before the
    replacement exists would do exactly that, and the caller would be left with
    a card holding no vectors at all.
    """
    rag = build_rag(StubLLM(fail=True))

    result = vectorize(rag, jsonl(3), store)

    assert (result.vectorized, result.failed) == (0, 3)
    assert rag.vector_manager.events == []  # nothing deleted, nothing inserted
    assert store.chunks.list_for_card(CARD_KEY) == []


def test_one_failed_image_aborts_the_whole_replacement(jsonl, store):
    """
    A card indexed with two thirds of its content is indistinguishable from a
    complete one once it is being searched, so the previous complete snapshot is
    kept instead of being replaced by a partial one.
    """
    rag = build_rag(StubLLM(fail_for={"1.png"}))

    result = vectorize(rag, jsonl(3), store)

    assert (result.summarized, result.failed, result.vectorized) == (2, 1, 0)
    assert rag.vector_manager.events == []  # the old vectors stay exactly as they were
    assert store.chunks.list_for_card(CARD_KEY) == []


def test_what_succeeded_is_cached_so_a_retry_is_cheap(jsonl, store):
    """
    What makes all-or-nothing affordable: the summaries that worked are cached as
    they arrive, so the retry only pays for the image that failed.
    """
    path = jsonl(3)
    vectorize(build_rag(StubLLM(fail_for={"1.png"})), path, store)
    assert store.summaries.stats()["entries"] == 2

    retry = build_rag(StubLLM())
    result = vectorize(retry, path, store)

    assert retry.llm.seen == ["1.png"]  # the model is asked about nothing else
    assert (result.cached, result.summarized, result.vectorized) == (2, 1, 3)
    assert retry.vector_manager.events == [("delete", CARD_KEY), ("insert", 3)]


def test_a_failed_image_is_not_cached(jsonl, store):
    """Caching an outage would serve the error back on every later crawl."""
    rag = build_rag(StubLLM(fail=True))

    vectorize(rag, jsonl(1), store)

    assert store.summaries.stats()["entries"] == 0


def test_failed_images_are_retried_before_being_given_up_on(jsonl, store):
    rag = build_rag(StubLLM(fail=True))

    vectorize(rag, jsonl(1), store)

    assert len(rag.llm.seen) == 4  # the first attempt plus three retries


def test_a_reply_that_cannot_be_parsed_counts_as_a_failure(jsonl, store):
    """
    A truncated reply reaches us as None, not as an exception. Left unchecked it
    would be cached and vectorized as if the image had been read.
    """
    rag = build_rag(StubLLM(unparseable_for={"1.png"}))

    result = vectorize(rag, jsonl(3), store)

    assert (result.failed, result.vectorized) == (1, 0)
    assert rag.llm.seen.count("1.png") == 4  # retried like any other failure
    assert rag.vector_manager.events == []
    assert store.summaries.stats()["entries"] == 2


# --- sections ----------------------------------------------------------------

def test_each_section_of_an_image_becomes_its_own_record(jsonl, store):
    rag = build_rag(StubLLM(sections_for={
        "0.png": [("優惠活動", "活動甲"), ("優惠活動", "活動乙"), ("年費", "首年免年費")],
    }))

    result = vectorize(rag, jsonl(2), store)

    assert (result.images, result.vectorized) == (2, 4)  # three from 0.png, one from 1.png
    assert rag.vector_manager.events == [("delete", CARD_KEY), ("insert", 4)]


def test_a_record_names_its_card_and_section_in_the_searched_text(jsonl, store):
    """
    Only `text` is searched, so a section that does not say whose it is cannot be
    found by a question that names the card.
    """
    rag = build_rag(StubLLM(sections_for={"0.png": [("年費", "首年免年費")]}))

    vectorize(rag, jsonl(1), store)

    record = rag.vector_manager.inserted[0]
    assert record.text == "測試卡｜年費\n首年免年費"
    assert (record.section, record.card_key) == ("年費", CARD_KEY)
    assert record.url == "https://bank.test/card#0"


def test_an_image_with_no_card_content_is_not_a_failure(jsonl, store):
    """A capture of a blank area has nothing to say; that must not abort the card."""
    rag = build_rag(StubLLM(sections_for={"1.png": []}))

    result = vectorize(rag, jsonl(3), store)

    assert (result.failed, result.vectorized) == (0, 2)
    assert rag.vector_manager.events == [("delete", CARD_KEY), ("insert", 2)]
    assert len(store.chunks.list_for_card(CARD_KEY)) == 3  # still part of the card


def test_a_card_with_no_content_at_all_leaves_the_existing_vectors_alone(jsonl, store):
    rag = build_rag(StubLLM(sections_for={"0.png": [], "1.png": []}))

    result = vectorize(rag, jsonl(2), store)

    assert (result.failed, result.vectorized) == (0, 0)
    assert rag.vector_manager.events == []
    assert store.chunks.list_for_card(CARD_KEY) == []


# --- vector replacement ------------------------------------------------------

def test_a_successful_run_replaces_rather_than_accumulates(jsonl, store):
    rag = build_rag(StubLLM())

    result = vectorize(rag, jsonl(3), store)

    assert (result.images, result.vectorized, result.failed) == (3, 3, 0)
    assert rag.vector_manager.events == [("delete", CARD_KEY), ("insert", 3)]


def test_the_delete_happens_only_once_there_is_something_to_write(jsonl, store):
    """Ordering is the whole point: the old content survives until the new is ready."""
    rag = build_rag(StubLLM())

    vectorize(rag, jsonl(2), store)

    actions = [event[0] for event in rag.vector_manager.events]
    assert actions.index("delete") < actions.index("insert")


# --- summary cache -----------------------------------------------------------

def test_an_unchanged_card_costs_no_model_calls(jsonl, store):
    """The point of fingerprinting: a re-crawl that found nothing new is free."""
    seed_cache(store, 0, 1, 2)
    rag = build_rag(StubLLM())

    result = vectorize(rag, jsonl(3), store)

    assert rag.llm.seen == []  # the vision model was never called
    assert (result.cached, result.summarized, result.vectorized) == (3, 0, 3)
    assert rag.vector_manager.events == [("delete", CARD_KEY), ("insert", 3)]


def test_only_the_changed_images_reach_the_model(jsonl, store):
    """A partial hit pays for the misses alone, not for the whole card."""
    seed_cache(store, 0, 2)
    rag = build_rag(StubLLM())

    result = vectorize(rag, jsonl(3), store)

    assert rag.llm.seen == ["1.png"]
    assert (result.cached, result.summarized) == (2, 1)
    assert rag.vector_manager.events == [("delete", CARD_KEY), ("insert", 3)]


def test_fresh_summaries_are_cached_for_next_time(jsonl, store):
    rag = build_rag(StubLLM())

    vectorize(rag, jsonl(2), store)

    cached = ImageSummary.model_validate_json(store.summaries.get("hash-0", MODEL, _PROMPT_VER))
    assert cached == summary(("其他", "內容 0.png"))
    assert store.summaries.stats()["entries"] == 2


def test_a_cache_entry_that_no_longer_parses_is_a_miss(jsonl, store):
    """Otherwise one bad row would fail that card on every crawl from then on."""
    store.summaries.put("hash-0", MODEL, _PROMPT_VER, "not json")
    rag = build_rag(StubLLM())

    result = vectorize(rag, jsonl(1), store)

    assert rag.llm.seen == ["0.png"]
    assert (result.cached, result.summarized, result.vectorized) == (0, 1, 1)


def test_a_second_run_reuses_what_the_first_one_stored(jsonl, store):
    """End to end: crawl twice, pay once."""
    path = jsonl(3)
    vectorize(build_rag(StubLLM()), path, store)

    second = build_rag(StubLLM())
    result = vectorize(second, path, store)

    assert second.llm.seen == []
    assert result.cached == 3


def test_a_different_model_does_not_reuse_the_old_summaries(jsonl, store):
    """Switching provider must not serve summaries the new model never wrote."""
    store.summaries.put(
        "hash-0", "some-other-model", _PROMPT_VER, summary(("其他", "別的模型的內容")).model_dump_json()
    )
    rag = build_rag(StubLLM())

    result = vectorize(rag, jsonl(1), store)

    assert rag.llm.seen == ["0.png"]
    assert result.cached == 0


# --- card composition --------------------------------------------------------

def test_chunks_record_what_the_card_now_consists_of(jsonl, store):
    """
    card_chunks plus the summary cache are what make the collection rebuildable
    without crawling or paying for a model call.
    """
    rag = build_rag(StubLLM())

    vectorize(rag, jsonl(3), store)

    chunks = store.chunks.list_for_card(CARD_KEY)
    assert [c.content_hash for c in chunks] == ["hash-0", "hash-1", "hash-2"]
    assert [c.seq for c in chunks] == [0, 1, 2]
    assert chunks[0].page_url == "https://bank.test/card#0"


def test_chunks_keep_the_order_the_vectors_were_inserted_in(jsonl, store):
    """A cached image must stay in its original position, not sort to the front."""
    seed_cache(store, 1)
    rag = build_rag(StubLLM())

    vectorize(rag, jsonl(3), store)

    assert [c.content_hash for c in store.chunks.list_for_card(CARD_KEY)] == [
        "hash-0", "hash-1", "hash-2",
    ]


def test_a_shrinking_card_drops_its_stale_chunks(jsonl, store):
    rag = build_rag(StubLLM())
    vectorize(rag, jsonl(3), store)

    vectorize(build_rag(StubLLM()), jsonl(1), store)

    assert len(store.chunks.list_for_card(CARD_KEY)) == 1
