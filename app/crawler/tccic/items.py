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
    title = scrapy.Field()
    url = scrapy.Field()
