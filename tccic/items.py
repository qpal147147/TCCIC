# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class TccicItem(scrapy.Item):
    # define the fields for your item here like:
    bank_name = scrapy.Field()
    card_name = scrapy.Field()
    url = scrapy.Field()
    text = scrapy.Field()
    content = scrapy.Field()
