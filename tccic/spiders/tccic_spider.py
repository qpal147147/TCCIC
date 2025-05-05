import io
import scrapy
import base64
from PIL import Image
from scrapy import Selector
from scrapy.http.response.html import HtmlResponse

from tccic.items import TccicItem
from utils.config_utils import get_config, get_bank_config


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
        self.image_config = get_config(config)["image"]
        self.height_limit, self.width_limit  = self.image_config["height"], self.image_config["width"]

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
            self.logger.error(f"The xpath content cannot be found, please check your bank code or xpath.")
            yield item
        
        # save main page content
        main_info = {
            'url': response.url,
            'content': content
        }
        item['info'].append(main_info)

        # get all sublinks from page
        selector = Selector(text=content)
        sublinks = selector.xpath('//a/@href').getall()
        self.logger.info(f"Found {len(sublinks)} sublinks in {response.url}")

        # get all image from page
        image_urls = selector.xpath('//img/@src').getall()
        self.logger.info(f"Found {len(image_urls)} image in {response.url}")

        # get image content
        for image_url in image_urls:
            yield response.follow(
                image_url, 
                self.parse_image_to_base64,
                errback=self.errback_httpbin,
                meta={'item': item}
            )
        
        # get subpage content
        for sublink in sublinks:
            if not sublink.startswith("javascript"):
                yield response.follow(
                    sublink, 
                    self.parse_subpage,
                    errback=self.errback_httpbin,
                    meta={'item': item, 'content_xpaths': content_xpaths}
                )

        yield item

    def errback_httpbin(self, failure):
        url = failure.request.url
        err_msg = failure.getErrorMessage()

        self.logger.error(f"{err_msg} <GET {url}>")

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

        # get all image from page
        selector = Selector(text=content)
        image_urls = selector.xpath('//img/@src').getall()
        self.logger.info(f"Found {len(image_urls)} image in {response.url}")

        # get image content
        for image_url in image_urls:
            yield response.follow(
                image_url, 
                self.parse_image_to_base64,
                errback=self.errback_httpbin,
                meta={'item': item}
            )

        yield item

    def parse_image_to_base64(self, response: HtmlResponse):
        item = response.meta['item']

        try:
            image = Image.open(io.BytesIO(response.body))
            width, height = image.size
            format = image.format

            if format.upper() != 'GIF':
                if width >= self.width_limit and height >= self.height_limit:
                    image_data = response.body
                    image_base64 = base64.b64encode(image_data).decode("utf-8")
                    image_info = {
                        'url': response.url,
                        'content': image_base64
                    }
                    item['info'].append(image_info)
                else:
                    self.logger.info(f"Image too small ({width}x{height}), skipped: {response.url}")
            else:
                self.logger.info(f"Image is GIF, skipped: {response.url}")

        except Exception as e:
            self.logger.error(f"Failed to process image {response.url}: {e}")

        return item