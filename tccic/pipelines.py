# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
from pathlib import Path
from markdownify import markdownify as md

class TccicPipeline:
    def __init__(self):
        self.processed_urls = set()

    def process_item(self, item, spider):
        bank_name = item['bank_name']
        card_name = item['card_name']

        for info in item['info']:
            if info['url'] in self.processed_urls:
                continue

            filename_base = info['url'].split('/')[-1]
            mdt_filename = f"temp/output_{bank_name}_{card_name}_{filename_base}.md"
            
            md_text = md(info['content'])
            Path(mdt_filename).write_text(md_text)

            self.processed_urls.add(info['url'])
        
        return item
