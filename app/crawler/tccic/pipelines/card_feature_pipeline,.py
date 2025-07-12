from pathlib import Path

from app.configs.global_settings import global_settings

class CardFeaturePipeline:
    def open_spider(self, spider):
        self.enabled = (spider.name == 'card_feature_spider')

        if not self.enabled:
            return
        
        self.bank_code = getattr(spider, 'bank_code', "unknown")
        self.file_name = getattr(spider, 'file_name')
        if self.bank_code == "unknown":
            spider.logger.warning("Bank code not found in spider. Using 'unknown' as default.")
        
        self.json_dir = Path(global_settings.CRAWLER_DATA_DIR) / f"{self.bank_code}" / "card_feature" / self.file_name
        self.json_dir.mkdir(parents=True, exist_ok=True)

    def close_spider(self, spider):
        pass

    def process_item(self, item, spider):
        pass