# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy

class CardsItem(scrapy.Item):
    """
    CardsItem
    """
    bank_name = scrapy.Field()
    bank_code = scrapy.Field()
    page_url = scrapy.Field()
    card_title = scrapy.Field()
    card_url = scrapy.Field()
