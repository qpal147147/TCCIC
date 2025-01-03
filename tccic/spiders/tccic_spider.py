from pathlib import Path
import scrapy

class TccicSpider(scrapy.Spider):
    name = "tccic"
    
    def __init__(self, url=None, *args, **kwargs):
        super(TccicSpider, self).__init__(*args, **kwargs)
        self.url = url

    def start_requests(self):
        yield scrapy.Request(url=self.url, callback=self.parse)

    def parse(self, response):
        filename = f"output_{response.url.split('/')[-2].replace('?','_')}.html"
        Path(filename).write_bytes(response.body)
        self.log(f"已儲存檔案 {filename}")

