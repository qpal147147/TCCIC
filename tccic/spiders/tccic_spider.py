import scrapy
from scrapy import Selector
from scrapy.http.response.html import HtmlResponse

from tccic.items import TccicItem
from utils.config_utils import get_bank_config


class TccicSpider(scrapy.Spider):
    name = "tccic"

    def __init__(self, url=None, card_name=None, bank_code=None, config=None, *args, **kwargs):
        super(TccicSpider, self).__init__(*args, **kwargs)
        if url is None or card_name is None or bank_code is None:
            raise ValueError("url or card_name or bank_code is required")
        
        self.start_urls = [url]
        self.card_name = card_name
        self.bank_code = bank_code
        self.bank_config = get_bank_config(config, self.bank_code)

    def parse(self, response: HtmlResponse):
        if response.status != 200:
            raise ValueError(f"Response status is not 200: {response.status}")
        
        if self.bank_config is None:
            raise ValueError(f"Bank config not found for bank code: {self.bank_code}")
        
        # init item object
        item = TccicItem()
        item['bank_name'] = self.bank_config['bank_name']
        item['card_name'] = self.card_name
        item['info'] = []

        content_xpaths = self.bank_config['content_xpath']
 
        # searching for valid xpaths 
        content = ""
        for xpath in content_xpaths:
            content = response.xpath(xpath).get(default="")
            if content:
                break
        
        if not content:
            raise ValueError(f"The xpath content cannot be found, please check your bank code or xpath.")
        
        # save main page content
        main_info = {
            'url': response.url,
            'content': content
        }
        item['info'].append(main_info)

        # get all sublinks from main page
        selector = Selector(text=content)
        sublinks = selector.xpath('//a/@href').getall()
        self.logger.info(f"Found {len(sublinks)} sublinks in {response.url}")

        # get subpage content
        for sublink in sublinks:
            if not sublink.startswith("javascript"):
                yield response.follow(
                    sublink, 
                    self.parse_subpage,
                    meta={'item': item, 'content_xpaths': content_xpaths}
                )

        yield item

    def parse_subpage(self, response: HtmlResponse):
        item = response.meta['item']
        content_xpaths = response.meta['content_xpaths']
        
        # searching for valid xpaths 
        content = ""
        for xpath in content_xpaths:
            content = response.xpath(xpath).get(default="")
            if content:
                break
        
        if not content:
            self.logger.warning(f"Empty content in {response.url}")
            return
        
        # save subpage content 
        subpage_info = {
            'url': response.url,
            'content': content
        }
        item['info'].append(subpage_info)

        yield item