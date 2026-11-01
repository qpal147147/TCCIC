"""
Tests for the per-bank crawler config: every committed YAML must load, and
page_focus must stay one level deep.

Using: pytest tests/test_bank_config.py
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.crawler.schemas.bank_config import BankCrawlerConfig, FocusItem
from app.utils.config_utils import get_config

BANKS_DIR = Path(__file__).resolve().parents[1] / "app" / "configs" / "banks"


def test_every_bank_yaml_loads():
    """A config that fails validation only shows up when that bank is crawled."""
    config = BankCrawlerConfig(**get_config(BANKS_DIR))
    assert config.banks


def test_page_focus_one_level_is_allowed():
    item = FocusItem(
        content="//div",
        link=".//a",
        page_focus=[{"content": "//section"}, {"content": "//section", "link": ".//a"}],
    )
    assert len(item.page_focus) == 2
    # A focus area without a link is how page_focus captures sections as they are.
    assert item.page_focus[0].link is None


def test_nested_page_focus_is_rejected():
    with pytest.raises(ValidationError, match="one level"):
        FocusItem(
            content="//div",
            link=".//a",
            page_focus=[{
                "content": "//section",
                "link": ".//a",
                "page_focus": [{"content": "//p"}],
            }],
        )


def test_page_focus_without_link_is_rejected():
    """page_focus applies to the page a link opens; with no link there is none."""
    with pytest.raises(ValidationError, match="needs a link"):
        FocusItem(content="//div", page_focus=[{"content": "//section"}])


def test_yaml_anchor_reuses_a_popup():
    """Anchors are plain YAML, so one popup definition can serve several focus areas."""
    raw = yaml.safe_load("""
focus:
  - content: //a
    link: .//a
    popup: &modal
      content: //div[@class='modal']
      close_button: //button
  - content: //b
    link: .//a
    popup: *modal
""")
    first, second = (FocusItem(**f) for f in raw["focus"])
    assert first.popup == second.popup
    assert second.popup.close_button == "//button"
