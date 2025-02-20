import scrapy
from pathlib import Path

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
        
        # init item object
        item = TccicItem()
        item['bank_name'] = bank_config['bank_name']
        item['card_name'] = card_config['card_name']
        item['info'] = []

        # main page content
        main_info = {
            'url': response.url,
            'text': response.text,
            'content': response.xpath(card_xpaths['content']).get()
        }
        item['info'].append(main_info)

        # sub page content
        if card_xpaths['sublinks']:
            sublinks = response.xpath(card_xpaths['sublinks']).getall()
            for sublink in sublinks:
                yield response.follow(
                    sublink, 
                    self.parse_subpage,
                    meta={'item': item, 'card_xpaths': card_xpaths}
                )
        else:
            yield item
        
        # if main page has image, download it
        if card_xpaths['image']:
            image_url = response.xpath(card_xpaths['image']).get()
            yield response.follow(image_url, self.download_image)

    def parse_subpage(self, response):
        item = response.meta['item']
        card_xpaths = response.meta['card_xpaths']
        
        subpage_info = {
            'url': response.url,
            'text': response.text,
            'content': response.xpath(card_xpaths['content']).get()
        }
        item['info'].append(subpage_info)

        yield item

    def download_image(self, response):
        ROOT = Path('images')
        ROOT.mkdir(exist_ok=True, parents=True)
        
        image_name = response.url.split("/")[-1]
        image_path = ROOT / image_name

        with open(image_path, 'wb') as f:
            f.write(response.body)