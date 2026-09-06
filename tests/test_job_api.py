"""
Tests for crawl submission and the unified job endpoints.

The app under test gets a stand-in lifespan that supplies an in-memory store and
plain queues, so nothing here starts a spider, touches Milvus, or writes to the
real database.

Using: pytest tests/test_job_api.py
"""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routers.v1.api import router as v1_router
from app.configs.global_settings import global_settings
from app.services.store import Card, ChunkInput, CrawlJob, Store

QUEUE_SIZE = 3
BANK = "taishin"
LIST_URL = "https://www.taishinbank.com.tw/TSB/personal/credit/intro/"
CARD_URL = "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg047/card001/"
CARD_NAME = "Richart玫瑰卡"


@pytest.fixture
def store():
    s = Store(":memory:")
    s.create_all()
    yield s
    s.close()


class StubRAG:
    """Stands in for the vector store so card deletion can be tested without Milvus."""

    def __init__(self):
        self.deleted: list[str] = []

    async def delete_card(self, card_id: str):
        self.deleted.append(card_id)


@pytest.fixture
def rag():
    return StubRAG()


@pytest.fixture
def client(store, rag):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield {
            "store": store,
            "rag": rag,
            "feature_queue": asyncio.Queue(maxsize=QUEUE_SIZE),
            "list_queue": asyncio.Queue(maxsize=QUEUE_SIZE),
        }

    app = FastAPI(lifespan=lifespan)
    app.include_router(v1_router, prefix="/api/v1")

    with TestClient(app) as c:
        c.headers["X-API-Key"] = global_settings.AUTH_KEY.get_secret_value()
        yield c


def submit_card_list(client) -> str:
    r = client.post("/api/v1/crawler/card-list", json={"bank_code": BANK, "url": LIST_URL})
    assert r.status_code == 202
    return r.json()["data"]["job_id"]


def submit_card_feature(client) -> dict:
    r = client.post(
        "/api/v1/crawler/card-feature",
        json={"bank_code": BANK, "card_name": CARD_NAME, "card_url": CARD_URL},
    )
    assert r.status_code == 202
    return r.json()["data"]


# --- submission --------------------------------------------------------------

def test_card_list_submission_is_recorded(client, store):
    """card-list jobs used to leave no trace at all; now they are queryable."""
    job_id = submit_card_list(client)

    job = store.jobs.get(job_id)
    assert job.job_type == "card_list"
    assert job.status == "queued"
    assert job.bank_code == BANK


def test_card_feature_submission_registers_the_card(client, store):
    data = submit_card_feature(client)

    assert data["card_key"] == Card.make_key(BANK, CARD_URL)
    assert store.cards.get(data["card_key"]).card_name == CARD_NAME
    assert store.jobs.get(data["job_id"]).card_key == data["card_key"]


def test_recrawling_reuses_the_catalog_entry(client, store):
    """
    A second crawl of the same card is a new job against the same card: card_key
    is derived from the URL, not generated, so the catalog never grows a twin.
    """
    first = submit_card_feature(client)
    store.jobs.mark_completed(first["job_id"])

    second = submit_card_feature(client)

    assert second["job_id"] != first["job_id"]
    assert second["card_key"] == first["card_key"]
    assert len(store.cards.list()) == 1


def test_batch_submission_shares_a_batch_id(client, store):
    r = client.post(
        "/api/v1/crawler/batch/card-list",
        json=[{"bank_code": BANK, "url": f"{LIST_URL}?p={i}"} for i in range(3)],
    )
    assert r.status_code == 202

    job_ids = [item["job_id"] for item in r.json()["data"]]
    batch_ids = {store.jobs.get(jid).batch_id for jid in job_ids}
    assert len(batch_ids) == 1
    assert None not in batch_ids


def test_batch_over_limit_is_rejected(client):
    oversized = [{"bank_code": BANK, "url": LIST_URL}] * (global_settings.CRAWL_BATCH_MAX_SIZE + 1)
    r = client.post("/api/v1/crawler/batch/card-list", json=oversized)

    assert r.status_code == 400


def test_full_queue_returns_503_and_fails_the_job(client, store):
    """A rejected submission must not leave a job stranded in 'queued'."""
    for _ in range(QUEUE_SIZE):
        submit_card_list(client)

    r = client.post("/api/v1/crawler/card-list", json={"bank_code": BANK, "url": LIST_URL})
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "60"

    with store.session_factory() as session:
        errored = session.scalars(select(CrawlJob).where(CrawlJob.status == "error")).all()
    assert len(errored) == 1
    assert errored[0].error == "Job queue is full."


def test_invalid_bank_code_is_rejected(client):
    r = client.post("/api/v1/crawler/card-list", json={"bank_code": "../etc", "url": LIST_URL})
    assert r.status_code == 422


def test_api_key_is_required(store):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield {"store": store, "feature_queue": asyncio.Queue(), "list_queue": asyncio.Queue()}

    app = FastAPI(lifespan=lifespan)
    app.include_router(v1_router, prefix="/api/v1")

    with TestClient(app) as c:
        r = c.get("/api/v1/jobs/anything", headers={"X-API-Key": "wrong"})
        assert r.status_code == 401


# --- status ------------------------------------------------------------------

def test_status_reports_the_full_lifecycle(client, store):
    job_id = submit_card_list(client)

    assert client.get(f"/api/v1/jobs/{job_id}").json()["data"]["status"] == "queued"

    store.jobs.mark_running(job_id)
    assert client.get(f"/api/v1/jobs/{job_id}").json()["data"]["status"] == "running"

    store.jobs.mark_completed(job_id, stats={"cards": 48, "pages": 5})
    body = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
    assert body["status"] == "completed"
    assert body["stats"] == {"cards": 48, "pages": 5}
    assert body["finished_at"] is not None


def test_status_serves_both_job_types(client, store):
    list_job = submit_card_list(client)
    feature = submit_card_feature(client)

    assert client.get(f"/api/v1/jobs/{list_job}").json()["data"]["job_type"] == "card_list"

    body = client.get(f"/api/v1/jobs/{feature['job_id']}").json()["data"]
    assert body["job_type"] == "card_feature"
    assert body["card_key"] == feature["card_key"]


def test_unknown_job_is_404(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404


def test_config_broken_is_visible_to_callers(client, store):
    job_id = submit_card_list(client)
    store.jobs.mark_failed(job_id, "focus matched 0 elements", status="config_broken")

    assert client.get(f"/api/v1/jobs/{job_id}").json()["data"]["status"] == "config_broken"


# --- results -----------------------------------------------------------------

def test_result_distinguishes_waiting_from_failing(client, store):
    job_id = submit_card_list(client)

    r = client.get(f"/api/v1/jobs/{job_id}/result")
    assert r.status_code == 409  # still queued: keep waiting

    store.jobs.mark_running(job_id)
    assert client.get(f"/api/v1/jobs/{job_id}/result").status_code == 409

    store.jobs.mark_failed(job_id, "timeout")
    r = client.get(f"/api/v1/jobs/{job_id}/result")
    assert r.status_code == 400  # give up
    assert "timeout" in r.json()["error"]


def test_unknown_job_result_is_404(client):
    assert client.get("/api/v1/jobs/does-not-exist/result").status_code == 404


def test_card_list_result_is_deduplicated_and_grouped(client, store, tmp_path):
    job_id = submit_card_list(client)

    jsonl = tmp_path / f"{job_id}.jsonl"
    rows = [
        {"bank_code": BANK, "bank_name": "台新銀行", "page_url": "p1", "card_title": "A", "card_url": "u1"},
        {"bank_code": BANK, "bank_name": "台新銀行", "page_url": "p1", "card_title": "A", "card_url": "u1"},
        {"bank_code": BANK, "bank_name": "台新銀行", "page_url": "p1", "card_title": "B", "card_url": "u2"},
        {"bank_code": BANK, "bank_name": "台新銀行", "page_url": "p2", "card_title": "C", "card_url": "u3"},
    ]
    jsonl.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    store.jobs.mark_completed(job_id, artifact_dir=str(jsonl), stats={"cards": 3, "pages": 2})

    data = client.get(f"/api/v1/jobs/{job_id}/result").json()["data"]

    assert data["bank_name"] == "台新銀行"
    assert len(data["pages"]) == 2
    page1 = next(p for p in data["pages"] if p["page_url"] == "p1")
    assert len(page1["cards"]) == 2  # the duplicate row collapsed


def test_card_feature_result_returns_the_card_handle(client, store):
    feature = submit_card_feature(client)
    store.jobs.mark_completed(feature["job_id"], stats={"images": 15, "vectorized": 15, "failed": 0})

    data = client.get(f"/api/v1/jobs/{feature['job_id']}/result").json()["data"]

    assert data["card_key"] == feature["card_key"]
    assert data["card_name"] == CARD_NAME
    assert data["stats"]["images"] == 15


def test_missing_artifact_is_reported_as_gone(client, store, tmp_path):
    """A completed job whose file was cleaned up must not look like a crawl failure."""
    job_id = submit_card_list(client)
    store.jobs.mark_completed(job_id, artifact_dir=str(tmp_path / "vanished.jsonl"))

    assert client.get(f"/api/v1/jobs/{job_id}/result").status_code == 410


# --- idempotency -------------------------------------------------------------

def test_resubmitting_an_active_card_returns_the_same_job(client, store):
    """
    Two crawls of one card would each delete and re-insert its vectors, so the
    second request must join the first rather than start a rival crawl.
    """
    first = submit_card_feature(client)

    r = client.post(
        "/api/v1/crawler/card-feature",
        json={"bank_code": BANK, "card_name": CARD_NAME, "card_url": CARD_URL},
    )

    assert r.status_code == 200  # nothing new was accepted
    assert r.json()["data"]["job_id"] == first["job_id"]

    with store.session_factory() as session:
        assert len(session.scalars(select(CrawlJob)).all()) == 1


def test_a_running_card_also_blocks_resubmission(client, store):
    first = submit_card_feature(client)
    store.jobs.mark_running(first["job_id"])

    r = client.post(
        "/api/v1/crawler/card-feature",
        json={"bank_code": BANK, "card_name": CARD_NAME, "card_url": CARD_URL},
    )

    assert r.status_code == 200
    assert r.json()["data"]["job_id"] == first["job_id"]


def test_a_failed_card_can_be_retried(client, store):
    """Idempotency must not become a permanent lock — retrying is the point."""
    first = submit_card_feature(client)
    store.jobs.mark_failed(first["job_id"], "timeout")

    assert submit_card_feature(client)["job_id"] != first["job_id"]


def test_batch_skips_cards_already_in_flight(client, store):
    """A duplicate inside a batch must not hold up the rest of it."""
    first = submit_card_feature(client)
    other_url = "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg046/card001/"

    r = client.post(
        "/api/v1/crawler/batch/card-feature",
        json=[
            {"bank_code": BANK, "card_name": CARD_NAME, "card_url": CARD_URL},
            {"bank_code": BANK, "card_name": "太陽卡", "card_url": other_url},
        ],
    )

    assert r.status_code == 202  # something was still accepted
    data = r.json()["data"]
    assert data[0]["job_id"] == first["job_id"]   # deduplicated
    assert data[1]["job_id"] != first["job_id"]   # newly queued
    assert "1 card(s) are already being crawled" in r.json()["message"]


def test_batch_deduplicates_within_itself(client, store):
    """The same card listed twice in one batch is crawled once."""
    r = client.post(
        "/api/v1/crawler/batch/card-feature",
        json=[{"bank_code": BANK, "card_name": CARD_NAME, "card_url": CARD_URL}] * 3,
    )

    assert r.status_code == 202
    job_ids = {item["job_id"] for item in r.json()["data"]}
    assert len(job_ids) == 1

    with store.session_factory() as session:
        assert len(session.scalars(select(CrawlJob)).all()) == 1


def test_batch_of_only_duplicates_queues_nothing(client, store):
    first = submit_card_feature(client)

    r = client.post(
        "/api/v1/crawler/batch/card-feature",
        json=[{"bank_code": BANK, "card_name": CARD_NAME, "card_url": CARD_URL}],
    )

    assert r.status_code == 200  # nothing accepted for processing
    assert r.json()["data"][0]["job_id"] == first["job_id"]


def test_card_list_is_not_deduplicated(client, store):
    """
    Repeat card-list crawls are merely wasteful, not harmful: each writes its own
    snapshot. Only card-feature contends over shared vectors.
    """
    first = submit_card_list(client)
    second = submit_card_list(client)

    assert first != second


# --- card deletion -----------------------------------------------------------

def test_delete_card_unindexes_without_delisting(client, store, rag):
    """
    Deleting an index is an operator action, not a statement about the bank:
    the catalog keeps the card and leaves its status alone.
    """
    feature = submit_card_feature(client)
    card_key = feature["card_key"]
    store.cards.mark_crawled(card_key, content_changed=True)
    store.chunks.replace_for_card(card_key, [
        ChunkInput(seq=0, page_url=CARD_URL, content_hash="hash-0"),
        ChunkInput(seq=1, page_url=CARD_URL, content_hash="hash-1"),
    ])

    assert client.delete(f"/api/v1/card/{card_key}").status_code == 204

    assert rag.deleted == [card_key]
    card = store.cards.get(card_key)
    assert card is not None                 # the card is still known
    assert card.status == "active"          # still on sale as far as we know
    assert card.last_crawled_at is None     # but no longer indexed
    assert store.chunks.list_for_card(card_key) == []


def test_deleted_card_leaves_nothing_to_rebuild(client, store):
    """
    Chunks must go with the vectors, or a later rebuild from SQLite would
    resurrect a card the operator deleted.
    """
    card_key = submit_card_feature(client)["card_key"]
    store.chunks.replace_for_card(card_key, [
        ChunkInput(seq=0, page_url=CARD_URL, content_hash="hash-0"),
    ])

    client.delete(f"/api/v1/card/{card_key}")

    assert store.chunks.list_for_card(card_key) == []


# --- retired endpoints -------------------------------------------------------

def test_old_query_endpoints_are_gone(client):
    assert client.get("/api/v1/crawler/card-list/some-list-id").status_code == 404
    assert client.get("/api/v1/crawler/card-feature/some-job-id/status").status_code == 404
