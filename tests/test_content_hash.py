"""
Tests for the content fingerprint.

Only the pure part is tested here — collecting the ingredients needs a real
browser, and is verified by crawling the same card twice and comparing the
hashes recorded in the JSONL.

Using: pytest tests/test_content_hash.py
"""

from app.crawler.content_hash import Fingerprint, _build, digest

TEXT = "年費 首年免年費 次年起 NT$1,800 玩數位 2% 樂饗購 2%"
SRCS = [
    "https://www.cathay-cube.com.tw/dam/cube-hero.jpg",
    "https://www.cathay-cube.com.tw/dam/cube-card.png",
]


def test_same_content_gives_the_same_hash():
    """The whole premise: an unchanged page must fingerprint identically."""
    assert digest(TEXT, SRCS) == digest(TEXT, SRCS)


def test_image_order_does_not_matter():
    """A carousel reshuffling the same images is not a content change."""
    assert digest(TEXT, SRCS) == digest(TEXT, list(reversed(SRCS)))


def test_repeated_images_do_not_matter():
    assert digest(TEXT, SRCS) == digest(TEXT, SRCS + [SRCS[0]])


def test_changed_text_changes_the_hash():
    assert digest(TEXT, SRCS) != digest(TEXT.replace("NT$1,800", "NT$2,400"), SRCS)


def test_a_new_promo_image_changes_the_hash():
    """Roughly 70% of a card page's promotional detail is imagery, so this is
    the case text alone would miss."""
    swapped = [SRCS[0], "https://www.cathay-cube.com.tw/dam/cube-autumn-2026.jpg"]
    assert digest(TEXT, SRCS) != digest(TEXT, swapped)


def test_dropping_an_image_changes_the_hash():
    assert digest(TEXT, SRCS) != digest(TEXT, SRCS[:1])


def test_text_and_images_are_not_interchangeable():
    """Moving a value between the two ingredients must not collide."""
    assert digest("a", ["b"]) != digest("b", ["a"])


def test_empty_content_is_still_hashable():
    assert len(digest("", [])) == 64


def test_build_normalises_and_counts():
    fingerprint = _build({"text": TEXT, "srcs": SRCS + [SRCS[0]]})

    assert isinstance(fingerprint, Fingerprint)
    assert fingerprint.text_len == len(TEXT)
    assert fingerprint.img_count == 2  # counted after de-duplication, as hashed
    assert fingerprint.content_hash == digest(TEXT, SRCS)


def test_build_tolerates_missing_keys():
    """A page that yields nothing must produce a fingerprint, not an exception."""
    fingerprint = _build({})

    assert fingerprint.text_len == 0
    assert fingerprint.img_count == 0
    assert fingerprint.content_hash == digest("", [])
