# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import json
from itemadapter import ItemAdapter
from pathlib import Path
from datetime import datetime

class TccicPipeline:
    def __init__(self):
        self.processed_urls = set()
        self.json_data = {
            'bank': '',
            'card': '',
            'data': datetime.now().strftime("%Y/%m/%d"),
            'pages': [],
        }

    def process_item(self, item, spider):
        bank_name = item['bank_name']
        card_name = item['card_name']

        # Update bank and card if they are empty
        if bank_name:
            self.json_data['bank'] = bank_name
        if card_name:
            self.json_data['card'] = card_name


        for info in item['info']:
            if info['url'] in self.processed_urls:
                continue
            
            self.json_data['pages'].append({
                'url': info['url'],
                # 'all_text': info['text'],
                'html_content': info['content']
            })

            self.processed_urls.add(info['url'])
        
        # Save the JSON data to a file
        output_dir = Path('data') / bank_name / card_name
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / 'data.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(self.json_data, ensure_ascii=False, indent=4))

        return item
