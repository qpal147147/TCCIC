import scrapy

class TccicSpider(scrapy.Spider):
    name = "tccic"
    
    def __init__(self, url=None, *args, **kwargs):
        super(TccicSpider, self).__init__(*args, **kwargs)
        self.start_urls = [url]

    def parse(self, response):
        item = {}
        item['url'] = response.url
        item['body'] = response.body
        item['text'] = response.text
        yield item