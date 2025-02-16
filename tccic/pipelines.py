# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
from pathlib import Path
from markdownify import markdownify as md

class TccicPipeline:
    def process_item(self, item, spider):
        html_filename = f"temp/output_{item['url'].split('/')[-2].replace('?','_')}.html"
        mdt_filename = f"temp/output_{item['url'].split('/')[-2].replace('?','_')}.md"

        Path(html_filename).write_bytes(item['body'])

        md_text = md(item['text'])
        Path(mdt_filename).write_text(md_text)
        return item
