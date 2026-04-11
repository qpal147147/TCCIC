"""
Yuanta Bank (元大銀行) crawl strategy.

The card-listing page uses a server-side POST form for pagination rather
than client-side navigation, so the default tab-following logic does not
apply. This strategy replaces get_tab_requests with FormRequests that
POST the correct page number and form fields for each result page.
"""

from typing import Generator

import scrapy
from scrapy.http import HtmlResponse, FormRequest

from app.crawler.strategies.base import BankStrategy


class YuantabankStrategy(BankStrategy):
    """Override get_tab_requests to handle server-side POST pagination."""

    def get_tab_requests(
        self,
        response: HtmlResponse,
        callback,
        errback,
    ) -> Generator[FormRequest, None, None]:
        """
        Yield one FormRequest per page of the Yuanta card listing.

        The listing page exposes a hidden form (id=form4paging) whose inputs
        encode the total page count and a secondary counter. One POST per
        page index is required to retrieve all cards.
        """
        total_pages = response.css("form#form4paging input#pA::attr(value)").get()
        if not total_pages:
            self.logger.error("Could not find pagination form on Yuanta listing page.")
            return

        ia_value = response.css("form#form4paging input#iA::attr(value)").get()
        self.logger.info(f"Yuanta pagination: {total_pages} page(s) found.")

        for page_number in range(1, int(total_pages) + 1):
            yield scrapy.FormRequest(
                url=response.url,
                formdata={
                    "pN": str(page_number),
                    "pA": total_pages,
                    "iA": ia_value,
                    "creditcard_type": "",
                },
                callback=callback,
                errback=errback,
            )
