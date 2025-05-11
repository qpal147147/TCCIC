# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class TccicItem(scrapy.Item):
    bank_name = scrapy.Field()
    card_name = scrapy.Field()
    info = scrapy.Field()
    # info = {
    #   'url': response.url,
    #   'text': response.text,
    #   'content': response.xpath
    #}
