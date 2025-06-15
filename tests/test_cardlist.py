import requests
import re
import pytest

@pytest.mark.parametrize(
    ("bank_code, bank_url"),
    [
        ("taishin", "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/"),
        ("dbs", "https://www.dbs.com.tw/personal-zh/cards/dbs-credit-cards/default.page"),
        ("cathaybk", "https://www.cathaybk.com.tw/cathaybk/personal/product/credit-card/cards/"),
        ("sinopac", "https://bank.sinopac.com/sinopacBT/personal/credit-card/introduction/list.html"),
        ("fubon", "https://www.fubon.com/banking/personal/credit_card/all_card/all_card.htm"),
        ("esunbank", "https://www.esunbank.com/zh-tw/personal/credit-card/intro"),
        ("hsbc", "https://www.hsbc.com.tw/credit-cards/"),
        ("ctbcbank", "https://www.ctbcbank.com/twrbo/zh_tw/cc_index/cc_product/cc_introduction_index.html"),
        ("firstbank", "https://card.firstbank.com.tw/sites/card/touch/1565690685468"),
        ("feib", "https://www.feib.com.tw/introduce/cardInfo"),
        ("rakuten", "https://www.card.rakuten.com.tw/corp/product/"),
        ("americanexpress", "https://www.americanexpress.com/zh-tw/credit-cards/all-cards/"),
        ("ubot", "https://card.ubot.com.tw/Card?category=%E7%86%B1%E9%96%80%E6%8E%A8%E8%96%A6"),
        ("yuantabank", "https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do"),
        ("megabank", "https://www.megabank.com.tw/personal/credit-card/card/overview"),
        ("hncb", "https://www.hncb.com.tw/wps/portal/HNCB/card/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8ziDQw93T3cnQ18DQIsDAzMAk3M_UMtwoxCPY30w_EpMDI0148iSj8O4GhApH7cCqLwGx-uH4XPCrAPCJlRkBsaGmGQ6QgAkO1qlw!!/?1dmy&urile=wcm%3Apath%3A/wps/wcm/connect/hncb_v2/site_map/hncb/card/introduce/othercard/cards_overview"),
        ("skbank", "https://www.skbank.com.tw/CC-Creditcard"),
        ("tcb", "https://www.tcb-bank.com.tw/personal-banking/credit-card/intro/overview"),
        ("bankchb", "https://www.bankchb.com/frontend/mashup.jsp?funcId=f0f6e5d215"),
        ("scsb", "https://www.scsb.com.tw/content/card/card03.html"),
        ("sc", "https://www.sc.com/tw/credit-cards/"),
        ("kgibank", "https://www.kgibank.com.tw/zh-tw/personal/credit-card/list"),
        ("landbank", "https://www.landbank.com.tw/Category/Items/%E9%8A%80%E8%A1%8C%E5%8D%A1_"),
        ("bot", "https://ecard.bot.com.tw/Pages/Cards/P10.html"),
        ("tbb", "https://www.tbb.com.tw/zh-tw/personal/cards/products/overview"),
        ("tcbbank", "https://www.tcbbank.com.tw/CreditCard/J_02.html"),
        ("entiebank", "https://www.entiebank.com.tw/entie/1_3_1_2"),
        ("sunnybank", "https://www.sunnybank.com.tw/net/Page/Smenu/125"),
        ("bok", "https://www.bok.com.tw/credit-card"),
        ("obank", "https://www.o-bank.com/retail/debit/cobranded-card"),
    ]
)
def test_bank_has_cards(bank_code, bank_url):
    api_url = "http://127.0.0.1:1108/api/v1/crawler/cards"

    response = requests.get(api_url, params={"bank_code": bank_code, "url": bank_url})
    response.raise_for_status()
    data = response.json()

    if not data.get("data") or not data["data"].get("pages"):
        raise ValueError(f"'{bank_code}' pages is empty!")

    bank_name = data["data"]["bank_name"]
    pages = data["data"]["pages"]
    results = []

    for page in pages:
        for card in page["cards"]:
            clean_title = re.sub(r"\(.*?\)", "", card["title"]).strip()
            results.append({
                "bank_name": bank_name,
                "bank_url": bank_url,
                "title": clean_title,
                "url": card["url"],
                "bank_code": bank_code
            })

    assert len(results) > 0, f"{bank_code} 無卡片資料"