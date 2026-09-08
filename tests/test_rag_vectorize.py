"""
Tests for how a card's vectors are replaced.

The LLM, embedder and Milvus are stubbed, so these run offline and cover the
ordering that matters: a card must never be left empty because summarization
failed.

Using: pytest tests/test_rag_vectorize.py
"""

import asyncio
import json

import pytest

from app.services.rag import RAG

CARD_KEY = "0f5a1c9de4b27a3f8c6d0e1b2a394857c6d0e1b2"


class StubLLM:
    """Summarizes images, or fails every call the way an outage does."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    async def chat(self, prompt, images=None, structured_schema=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("HTTP/1.1 500 Internal Server Error")
        return f"摘要 {images[0]}"


class StubEmbedding:
    async def create_embeddings(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class StubVectorManager:
    """Records what was asked of Milvus, and in what order."""

    def __init__(self):
        self.events: list[tuple] = []

    def delete(self, key, value):
        self.events.append(("delete", value))

    def insert(self, data):
        self.events.append(("insert", len(data)))


def build_rag(llm: StubLLM) -> RAG:
    # Bypass __init__: it would reach for a real Milvus and a real provider.
    rag = RAG.__new__(RAG)
    rag.llm = llm
    rag.embedding = StubEmbedding()
    rag.vector_manager = StubVectorManager()
    rag._rate_limit_sleep_s = 0
    rag._llm_batch_size = 10
    return rag


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


def vectorize(rag: RAG, path) -> tuple[int, int]:
    return asyncio.run(rag.chunk_images_to_vecdb(path, CARD_KEY, "測試卡", "taishin"))


def test_total_failure_leaves_the_existing_vectors_alone(jsonl):
    """
    An LLM outage must not empty a card that was working. Deleting before the
    replacement exists would do exactly that, and the caller would see a card
    with no vectors at all.
    """
    rag = build_rag(StubLLM(fail=True))

    success, failed = vectorize(rag, jsonl(3))

    assert (success, failed) == (0, 3)
    assert rag.vector_manager.events == []  # nothing deleted, nothing inserted


def test_a_successful_run_replaces_rather_than_accumulates(jsonl):
    rag = build_rag(StubLLM())

    success, failed = vectorize(rag, jsonl(3))

    assert (success, failed) == (3, 0)
    assert rag.vector_manager.events == [("delete", CARD_KEY), ("insert", 3)]


def test_the_delete_happens_only_once_there_is_something_to_write(jsonl):
    """Ordering is the whole point: the old content survives until the new is ready."""
    rag = build_rag(StubLLM())

    vectorize(rag, jsonl(2))

    actions = [event[0] for event in rag.vector_manager.events]
    assert actions.index("delete") < actions.index("insert")


def test_failed_images_are_retried_before_being_given_up_on(jsonl):
    rag = build_rag(StubLLM(fail=True))

    vectorize(rag, jsonl(1))

    assert rag.llm.calls == 4  # the first attempt plus three retries
