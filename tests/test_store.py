"""
Tests for the metadata store.

Runs entirely against an in-memory SQLite database, so nothing here touches the real app/data_store/tccic.db.

Using: pytest tests/test_store.py  
"""

import pytest

from app.services.store import Card, ChunkInput, Store

BANK = "taishin"
CARD_URL = "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg047/card001/"
CARD_NAME = "Richart玫瑰卡"


@pytest.fixture
def store():
    s = Store(":memory:")
    s.create_all()
    yield s
    s.close()


@pytest.fixture
def card_key(store):
    return store.cards.upsert(BANK, CARD_NAME, CARD_URL).card_key


# --- card catalog ------------------------------------------------------------

def test_card_key_is_stable_across_calls():
    """The whole point of card_key: same card always resolves to the same identity."""
    assert Card.make_key(BANK, CARD_URL) == Card.make_key(BANK, CARD_URL)
    assert Card.make_key("dbs", CARD_URL) != Card.make_key(BANK, CARD_URL)


def test_upsert_is_idempotent(store):
    """Re-crawling must reuse the row rather than accumulate duplicates."""
    first = store.cards.upsert(BANK, CARD_NAME, CARD_URL)
    second = store.cards.upsert(BANK, CARD_NAME, CARD_URL)

    assert first.card_key == second.card_key
    assert len(store.cards.list()) == 1
    assert first.first_seen_at == second.first_seen_at


def test_upsert_follows_a_rename(store):
    store.cards.upsert(BANK, CARD_NAME, CARD_URL)
    renamed = store.cards.upsert(BANK, "Richart 玫瑰悠遊卡", CARD_URL)

    assert renamed.card_name == "Richart 玫瑰悠遊卡"
    assert len(store.cards.list()) == 1


def test_get_by_url_and_bank_filter(store, card_key):
    store.cards.upsert("dbs", "eco 永續卡", "https://www.dbs.com.tw/personal-zh/cards/dbs_eco/")

    assert store.cards.get_by_url(CARD_URL).card_key == card_key
    assert store.cards.get(card_key).bank_code == BANK
    assert len(store.cards.list()) == 2
    assert len(store.cards.list(bank_code=BANK)) == 1


def test_delisted_cards_are_hidden_but_kept(store, card_key):
    store.cards.set_status(card_key, "delisted")

    assert store.cards.list() == []
    assert len(store.cards.list(status="delisted")) == 1
    assert store.cards.get(card_key) is not None


def test_facts_json_round_trips_arbitrary_structure(store, card_key):
    """
    Schema-less by design: a new fact must not require a migration, and nested
    or open-ended shapes must survive intact.
    """
    facts = {
        "annual_fee": 3000,
        "cashback_overseas_max": 3.3,
        "facts": [
            {"name": "新戶LINE Pay加碼", "value": "最高10%", "period": "2026/7/1-9/30"},
        ],
    }
    store.cards.update_facts(card_key, facts)

    assert store.cards.get(card_key).facts_json == facts


def test_mark_crawled_separates_looked_from_changed(store, card_key):
    store.cards.mark_crawled(card_key, content_changed=False)
    card = store.cards.get(card_key)
    assert card.last_crawled_at is not None
    assert card.last_changed_at is None

    store.cards.mark_crawled(card_key, content_changed=True)
    assert store.cards.get(card_key).last_changed_at is not None


def test_invalid_card_status_is_rejected(store, card_key):
    with pytest.raises(ValueError):
        store.cards.set_status(card_key, "retired")


# --- crawl jobs --------------------------------------------------------------

def test_job_lifecycle(store, card_key):
    job = store.jobs.create("job-1", "card_feature", BANK, CARD_URL, card_key=card_key)
    assert job.status == "queued"

    store.jobs.mark_running("job-1")
    assert store.jobs.get("job-1").started_at is not None

    store.jobs.mark_completed("job-1", stats={"images": 15, "llm_calls": 3}, artifact_dir="/tmp/x")
    done = store.jobs.get("job-1")
    assert done.status == "completed"
    assert done.stats_json["images"] == 15
    assert done.finished_at is not None


def test_config_broken_is_distinct_from_plain_error(store, card_key):
    """Breakage detection (F1) needs to be tellable apart from a crash."""
    store.jobs.create("job-1", "card_feature", BANK, CARD_URL, card_key=card_key)
    store.jobs.mark_failed("job-1", "focus matched 0 elements", status="config_broken")

    assert store.jobs.get("job-1").status == "config_broken"


def test_invalid_job_type_and_status_are_rejected(store):
    with pytest.raises(ValueError):
        store.jobs.create("job-x", "card_pdf", BANK, CARD_URL)

    store.jobs.create("job-1", "card_list", BANK, CARD_URL)
    with pytest.raises(ValueError):
        store.jobs.mark_failed("job-1", "boom", status="exploded")


def test_find_active_job_backs_idempotency(store, card_key):
    """A duplicate submission must be answerable with the job already in flight."""
    assert store.jobs.find_active_by_card_key(card_key) is None

    store.jobs.create("job-1", "card_feature", BANK, CARD_URL, card_key=card_key)
    assert store.jobs.find_active_by_card_key(card_key).job_id == "job-1"

    store.jobs.mark_running("job-1")
    assert store.jobs.find_active_by_card_key(card_key).job_id == "job-1"

    store.jobs.mark_completed("job-1")
    assert store.jobs.find_active_by_card_key(card_key) is None


def test_last_completed_job_is_the_breakage_baseline(store, card_key):
    for job_id, images in (("job-1", 15), ("job-2", 14)):
        store.jobs.create(job_id, "card_feature", BANK, CARD_URL, card_key=card_key)
        store.jobs.mark_completed(job_id, stats={"images": images})

    store.jobs.create("job-3", "card_feature", BANK, CARD_URL, card_key=card_key)
    store.jobs.mark_failed("job-3", "timeout")

    baseline = store.jobs.last_completed_for_card(card_key)
    assert baseline.job_id == "job-2"
    assert baseline.stats_json["images"] == 14


def test_batch_jobs_stay_grouped(store):
    for i in range(3):
        store.jobs.create(f"job-{i}", "card_list", BANK, CARD_URL, batch_id="batch-1")
    store.jobs.create("job-solo", "card_list", BANK, CARD_URL)

    assert len(store.jobs.list_by_batch("batch-1")) == 3


def test_callback_status_defaults_to_pending_only_when_requested(store):
    with_cb = store.jobs.create("job-1", "card_list", BANK, CARD_URL, callback_url="https://x.test/hook")
    without_cb = store.jobs.create("job-2", "card_list", BANK, CARD_URL)

    assert with_cb.callback_status == "pending"
    assert without_cb.callback_status is None

    store.jobs.set_callback_status("job-1", "delivered")
    assert store.jobs.get("job-1").callback_status == "delivered"


# --- card composition --------------------------------------------------------

def test_replace_for_card_swaps_the_whole_composition(store, card_key):
    """
    Whole-card replacement mirrors the vector store rebuild, so a shrinking card
    must not leave orphan chunks behind.
    """
    store.chunks.replace_for_card(card_key, [
        ChunkInput(seq=i, page_url=CARD_URL, content_hash=f"hash-{i}") for i in range(5)
    ])
    assert len(store.chunks.list_for_card(card_key)) == 5

    store.chunks.replace_for_card(card_key, [
        ChunkInput(seq=0, page_url=CARD_URL, content_hash="hash-new", section="年費"),
    ])
    chunks = store.chunks.list_for_card(card_key)
    assert len(chunks) == 1
    assert chunks[0].content_hash == "hash-new"
    assert chunks[0].section == "年費"


def test_chunks_keep_their_order(store, card_key):
    store.chunks.replace_for_card(card_key, [
        ChunkInput(seq=2, page_url=CARD_URL, content_hash="c"),
        ChunkInput(seq=0, page_url=CARD_URL, content_hash="a"),
        ChunkInput(seq=1, page_url=CARD_URL, content_hash="b"),
    ])

    assert [c.content_hash for c in store.chunks.list_for_card(card_key)] == ["a", "b", "c"]


def test_chunks_are_scoped_per_card(store, card_key):
    other = store.cards.upsert("dbs", "eco 永續卡", "https://www.dbs.com.tw/eco/").card_key
    store.chunks.replace_for_card(card_key, [ChunkInput(seq=0, page_url=CARD_URL, content_hash="a")])
    store.chunks.replace_for_card(other, [ChunkInput(seq=0, page_url="https://dbs", content_hash="b")])

    store.chunks.delete_for_card(card_key)

    assert store.chunks.list_for_card(card_key) == []
    assert len(store.chunks.list_for_card(other)) == 1


# --- summary cache -----------------------------------------------------------

def test_cache_miss_then_hit(store):
    assert store.summaries.get("hash-1", "gemma-4-31b-it", "v1") is None

    store.summaries.put("hash-1", "gemma-4-31b-it", "v1", "年費 NT$3,000")
    assert store.summaries.get("hash-1", "gemma-4-31b-it", "v1") == "年費 NT$3,000"


def test_cache_key_isolates_model_and_prompt(store):
    """
    Switching models or editing the prompt must not serve a stale summary — and
    switching back must find the old cache still intact.
    """
    store.summaries.put("hash-1", "model-a", "v1", "summary A")

    assert store.summaries.get("hash-1", "model-b", "v1") is None
    assert store.summaries.get("hash-1", "model-a", "v2") is None
    assert store.summaries.get("hash-1", "model-a", "v1") == "summary A"


def test_hit_counters_track_reuse(store):
    store.summaries.put("hash-1", "model-a", "v1", "summary")

    store.summaries.get("hash-1", "model-a", "v1")
    store.summaries.get("hash-1", "model-a", "v1")
    store.summaries.get("hash-1", "model-a", "v1", touch=False)

    assert store.summaries.stats() == {"entries": 1, "total_hits": 2}


def test_put_overwrites_same_key(store):
    store.summaries.put("hash-1", "model-a", "v1", "old")
    store.summaries.put("hash-1", "model-a", "v1", "new")

    assert store.summaries.get("hash-1", "model-a", "v1") == "new"
    assert store.summaries.stats()["entries"] == 1


# --- the architectural property this store exists for ------------------------

def test_vector_store_can_be_rebuilt_from_sqlite_alone(store, card_key):
    """
    card_chunks + summary_cache must be enough to reconstruct a card's text in
    order, with no crawling and no LLM calls. This is what makes changing the
    embedding model an offline operation.
    """
    model, prompt_ver = "gemma-4-31b-it", "abc123"
    summaries = ["年費說明", "優惠活動", "申請資格"]

    for i, text in enumerate(summaries):
        store.summaries.put(f"hash-{i}", model, prompt_ver, text)
    store.chunks.replace_for_card(card_key, [
        ChunkInput(seq=i, page_url=CARD_URL, content_hash=f"hash-{i}") for i in range(len(summaries))
    ])

    rebuilt = [
        store.summaries.get(chunk.content_hash, model, prompt_ver, touch=False)
        for chunk in store.chunks.list_for_card(card_key)
    ]

    assert rebuilt == summaries
