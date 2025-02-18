import scrapy

from tccic.items import TccicItem
from tccic.utils.config_utils import get_config, get_card_config

class TccicSpider(scrapy.Spider):
    name = "tccic"
    config_path = './tccic/parse.yaml'

    def __init__(self, url=None, bank=None, *args, **kwargs):
        super(TccicSpider, self).__init__(*args, **kwargs)
        if url is None or bank is None:
            raise ValueError("url or bank is required")
        
        self.start_urls = [url]
        self.bank = bank
        
        self.config = get_config(self.config_path)

    def parse(self, response):
        bank_config = self.config[self.bank]
        card_config = get_card_config(bank_config, response.url)
        card_xpaths = card_config['xpaths']

        if card_config is None:
            raise ValueError(f"Card not found for {response.url}")
        
        item = TccicItem()
        item['bank_name'] = bank_config['bank_name']
        item['card_name'] = card_config['card_name']
        item['url'] = response.url
        item['text'] = response.text
        item['content'] = response.xpath(card_xpaths['content']).get()
        yield item