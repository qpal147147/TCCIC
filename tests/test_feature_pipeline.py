"""
Tests for the card-feature pipeline's artifact handling.

The output directory is named by card_key and therefore reused by every
re-crawl, so these cover what must happen to the previous run's files.

Using: pytest tests/test_feature_pipeline.py
"""

import importlib
import json
import logging

import pytest

from app.configs.global_settings import global_settings
from app.crawler.tccic.items import FeatureItem

# The module's filename carries a trailing comma, so it can only be imported by
# string — which is also how Scrapy loads it in ITEM_PIPELINES.
CardFeaturePipeline = importlib.import_module(
    "app.crawler.tccic.pipelines.card_feature_pipeline,"
).CardFeaturePipeline

CARD_KEY = "0f5a1c9de4b27a3f8c6d0e1b2a394857c6d0e1b2"


class StubSpider:
    name = "card_feature_spider"
    logger = logging.getLogger("stub_spider")

    def __init__(self, file_name=CARD_KEY, bank_code="taishin"):
        self.file_name = file_name
        self.bank_code = bank_code


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "CRAWLER_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def card_dir(data_dir):
    return data_dir / "taishin" / "card_feature" / CARD_KEY


def item(name: str, content_hash: str = "abc") -> FeatureItem:
    return FeatureItem(
        page_url="https://bank.test/card",
        image_path=f"/tmp/{name}",
        content_hash=content_hash,
        text_len=120,
        img_count=3,
    )


def test_a_recrawl_starts_from_an_empty_directory(card_dir):
    """
    Screenshots are named by position, so a card that loses a link would keep
    the previous run's orphaned images — files no record points at.
    """
    card_dir.mkdir(parents=True)
    (card_dir / "0_0_12.png").write_bytes(b"stale")
    (card_dir / f"{CARD_KEY}.jsonl").write_text("stale", encoding="utf-8")

    pipeline = CardFeaturePipeline()
    pipeline.open_spider(StubSpider())

    assert not (card_dir / "0_0_12.png").exists()
    assert list(card_dir.iterdir()) == [card_dir / f"{CARD_KEY}.jsonl"]

    pipeline.close_spider(StubSpider())


def test_each_record_lands_on_its_own_line(card_dir):
    """
    Records used to be joined without a trailing newline, which spliced the last
    row of one run onto the first row of the next into unparseable JSON.
    """
    spider = StubSpider()
    pipeline = CardFeaturePipeline()
    pipeline.open_spider(spider)
    for i in range(3):
        pipeline.process_item(item(f"{i}.png", content_hash=f"hash-{i}"), spider)
    pipeline.close_spider(spider)

    lines = (card_dir / f"{CARD_KEY}.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]

    assert len(records) == 3
    assert [r["content_hash"] for r in records] == ["hash-0", "hash-1", "hash-2"]
    assert records[0]["text_len"] == 120  # fingerprint fields survive the round trip


def test_recrawling_replaces_rather_than_accumulates(card_dir):
    """Two crawls of one card must leave one run's worth of records, not two."""
    for run in range(2):
        spider = StubSpider()
        pipeline = CardFeaturePipeline()
        pipeline.open_spider(spider)
        pipeline.process_item(item("main.png", content_hash=f"run-{run}"), spider)
        pipeline.close_spider(spider)

    lines = (card_dir / f"{CARD_KEY}.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]

    assert len(records) == 1
    assert records[0]["content_hash"] == "run-1"


def test_clearing_refuses_to_escape_the_data_directory(data_dir):
    """rmtree is destructive, so the target is checked before it is called."""
    pipeline = CardFeaturePipeline()

    with pytest.raises(ValueError, match="outside"):
        pipeline.open_spider(StubSpider(file_name="../../../etc"))


def test_other_spiders_are_left_alone(card_dir):
    """The card-list spider shares the pipeline chain and must not be touched."""
    spider = StubSpider()
    spider.name = "card_list_spider"

    pipeline = CardFeaturePipeline()
    pipeline.open_spider(spider)

    assert not card_dir.exists()
    assert pipeline.process_item("untouched", spider) == "untouched"
