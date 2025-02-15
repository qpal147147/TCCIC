from pathlib import Path
from markdownify import markdownify as md
import scrapy

class TccicSpider(scrapy.Spider):
    name = "tccic"
    
    def __init__(self, url=None, *args, **kwargs):
        super(TccicSpider, self).__init__(*args, **kwargs)
        self.url = url

    def start_requests(self):
        yield scrapy.Request(url=self.url, callback=self.parse)

    def parse(self, response):
        html_filename = f"output_{response.url.split('/')[-2].replace('?','_')}.html"
        mdt_filename = f"output_{response.url.split('/')[-2].replace('?','_')}.md"

        Path(html_filename).write_bytes(response.body)
        self.log(f"已儲存檔案 {html_filename}")

        md_text = md(response.text)
        Path(mdt_filename).write_text(md_text)