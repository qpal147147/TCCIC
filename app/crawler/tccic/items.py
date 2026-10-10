# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy

class CardItem(scrapy.Item):
    """
    CardsItem
    """
    bank_name = scrapy.Field()
    bank_code = scrapy.Field()
    page_url = scrapy.Field()
    card_title = scrapy.Field()
    card_url = scrapy.Field()

class FeatureItem(scrapy.Item):
    """One captured screenshot and the fingerprint of the content it shows.

    Attributes:
        content_hash: Hash of the page content. Recorded but not yet acted on.
        text_len: Length of the extracted text.
        img_count: Number of images on the page.

    When content_hash differs between two crawls, text_len and img_count
    show whether the text or the imagery moved.
    """
    page_url = scrapy.Field()
    image_path = scrapy.Field()
    content_hash = scrapy.Field()
    text_len = scrapy.Field()
    img_count = scrapy.Field()
