"""
Integration tests for the card-list crawler API.

Each parametrized test case:
  1. POSTs a crawl job to the API server (must be running at localhost:1108).
  2. Polls the result endpoint until the JSONL file is ready or a timeout is hit.
  3. Asserts that at least one card was returned for the bank.

Run with:
    pytest tests/test_cardlist.py -s
    pytest tests/test_cardlist.py -s -k taishin          # single bank
    pytest tests/test_cardlist.py -s --timeout=600       # override poll timeout
"""

import time
import re
import pytest
import requests


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "http://127.0.0.1:1108/api/v1"
DEFAULT_POLL_TIMEOUT = 180   # seconds — dynamic pages can take up to ~2 min
POLL_INTERVAL = 5            # seconds between status checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def submit_crawl_job(bank_code: str, bank_url: str) -> tuple[str, str]:
    """
    POST a card-list crawl request to the API.
    Returns (job_id, list_id) on success, raises on HTTP error.
    """
    response = requests.post(
        f"{API_BASE}/crawler/card-list",
        json={"bank_code": bank_code, "url": bank_url},
    )
    response.raise_for_status()
    data = response.json()["data"]
    return data["job_id"], data["list_id"]


def poll_for_result(list_id: str, timeout: int = DEFAULT_POLL_TIMEOUT) -> dict:
    """
    Poll GET /crawler/card-list/{list_id} until the spider finishes writing
    the JSONL file (HTTP 200) or the timeout expires.

    The endpoint returns:
      - 200: file exists and has content → done
      - 400: file missing or empty      → spider still running, keep polling
      - Other: unexpected error         → fail immediately
    """
    result_url = f"{API_BASE}/crawler/card-list/{list_id}"
    deadline = time.time() + timeout

    while time.time() < deadline:
        response = requests.get(result_url)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 400:
            # Spider is still running or file is not written yet.
            time.sleep(POLL_INTERVAL)
            continue

        # Unexpected HTTP error — fail the test immediately.
        response.raise_for_status()

    raise TimeoutError(
        f"Timed out after {timeout}s waiting for list_id='{list_id}'. "
        "The spider may still be running or an error occurred."
    )


def extract_cards(result_data: dict) -> list[dict]:
    """Flatten pages → cards into a single list with cleaned titles."""
    bank_name = result_data["data"]["bank_name"]
    bank_code = result_data["data"]["bank_code"]
    cards = []

    for page in result_data["data"]["pages"]:
        for card in page["cards"]:
            clean_title = re.sub(r"\(.*?\)", "", card["title"]).strip()
            cards.append({
                "bank_name": bank_name,
                "bank_code": bank_code,
                "title": clean_title,
                "url": card["url"],
                "page_url": page["page_url"],
            })

    return cards


# ---------------------------------------------------------------------------
# Test cases — (bank_code, listing_url)
# ---------------------------------------------------------------------------

BANKS = [
    ("taishin",        "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/"),
    ("dbs",            "https://www.dbs.com.tw/personal-zh/cards/dbs-credit-cards/default.page"),
    ("cathaybk",       "https://www.cathaybk.com.tw/cathaybk/personal/product/credit-card/cards/"),
    ("sinopac",        "https://bank.sinopac.com/sinopacBT/personal/credit-card/introduction/list.html"),
    ("fubon",          "https://www.fubon.com/banking/personal/credit_card/all_card/all_card.htm"),
    ("esunbank",       "https://www.esunbank.com/zh-tw/personal/credit-card/intro"),
    ("hsbc",           "https://www.hsbc.com.tw/credit-cards/"),
    ("ctbcbank",       "https://www.ctbcbank.com/twrbo/zh_tw/cc_index/cc_product/cc_introduction_index.html"),
    ("firstbank",      "https://card.firstbank.com.tw/sites/card/touch/1565690685468"),
    ("feib",           "https://www.feib.com.tw/introduce/cardInfo"),
    ("rakuten",        "https://www.card.rakuten.com.tw/corp/product/"),
    ("americanexpress","https://www.americanexpress.com/zh-tw/credit-cards/all-cards/"),
    ("ubot",           "https://card.ubot.com.tw/Card?category=%E7%86%B1%E9%96%80%E6%8E%A8%E8%96%A6"),
    ("yuantabank",     "https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do"),
    ("megabank",       "https://www.megabank.com.tw/personal/credit-card/card/overview"),
    ("hncb",           "https://www.hncb.com.tw/wps/portal/HNCB/card/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8ziDQw93T3cnQ18DQIsDAzMAk3M_UMtwoxCPU30w_EpMDI0148iSj8O4GhApH7cCqLwGx-uH4XPCrAPCJlRkBsaGmGQ6QgAkO1qlw!!/?1dmy&urile=wcm%3Apath%3A/wps/wcm/connect/hncb_v2/site_map/hncb/card/introduce/othercard/cards_overview"),
    ("skbank",         "https://www.skbank.com.tw/CC-Creditcard"),
    ("tcb",            "https://www.tcb-bank.com.tw/personal-banking/credit-card/intro/overview"),
    ("bankchb",        "https://www.bankchb.com/frontend/mashup.jsp?funcId=f0f6e5d215"),
    ("scsb",           "https://www.scsb.com.tw/content/card/card03.html"),
    ("sc",             "https://www.sc.com/tw/credit-cards/"),
    ("kgibank",        "https://www.kgibank.com.tw/zh-tw/personal/credit-card/list"),
    ("landbank",       "https://www.landbank.com.tw/Category/Items/%E9%8A%80%E8%A1%8C%E5%8D%A1_"),
    ("bot",            "https://ecard.bot.com.tw/Pages/Cards/P10.html"),
    ("tbb",            "https://www.tbb.com.tw/zh-tw/personal/cards/products/overview"),
    ("tcbbank",        "https://www.tcbbank.com.tw/CreditCard/J_02.html"),
    ("entiebank",      "https://www.entiebank.com.tw/entie/1_3_1_2"),
    ("sunnybank",      "https://www.sunnybank.com.tw/net/Page/Smenu/125"),
    ("bok",            "https://www.bok.com.tw/credit-card"),
    ("obank",          "https://www.o-bank.com/retail/debit/cobranded-card"),
]


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bank_code, bank_url", BANKS, ids=[b[0] for b in BANKS])
def test_bank_has_cards(bank_code: str, bank_url: str):
    """
    Assert that the card-list crawler returns at least one card for a bank.
    Failures may indicate a broken XPath selector, site layout change, or
    network issue rather than a code bug.
    """
    job_id, list_id = submit_crawl_job(bank_code, bank_url)
    print(f"\n[{bank_code}] job_id={job_id}  list_id={list_id}")

    result_data = poll_for_result(list_id)
    cards = extract_cards(result_data)

    print(f"[{bank_code}] Found {len(cards)} card(s):")
    # for card in cards:
    #     print(f"  - {card['title']:30s}  {card['url']}")

    assert len(cards) > 0, (
        f"No cards found for '{bank_code}'. "
        "Check the XPath selectors in app/configs/banks/{bank_code}.yaml."
    )
