import json
import shutil
from pathlib import Path
from itemadapter import ItemAdapter

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
        self._reset_dir(spider)
        self.json_path = self.json_dir / f"{self.file_name}.jsonl"
        spider.logger.debug(f"JSON path: {self.json_path}")

        self.data = []

        try:
            self.file = open(self.json_path, "w", encoding="utf-8")
        except:
            spider.logger.error(f"Failed to open file: {self.json_path}")
            self.file = None
            raise

    def _reset_dir(self, spider):
        """
        Start every crawl from an empty directory, so what is left on disk
        afterwards is exactly what this run captured.
        """
        root = Path(global_settings.CRAWLER_DATA_DIR).resolve()
        target = self.json_dir.resolve()

        # Guard a destructive call: never delete outside the crawler data dir.
        if root not in target.parents:
            raise ValueError(f"Refusing to clear '{target}': it is outside '{root}'.")

        if target.exists():
            shutil.rmtree(target)
            spider.logger.info(f"Cleared previous artifacts at {target}.")
        target.mkdir(parents=True, exist_ok=True)

    def close_spider(self, spider):
        if not self.enabled:
            return

        if self.file:
            for row in self.data:
                self.file.write(f"{row}\n")
            self.file.close()
            spider.logger.info(f"The file has been saved to {self.json_path}")

    def process_item(self, item, spider):
        if self.enabled and self.file and item is not None:
            item = json.dumps(ItemAdapter(item).asdict(), ensure_ascii=False)
            self.data.append(item)

        return item