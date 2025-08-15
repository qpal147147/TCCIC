# TCCIC
Taiwan Credit Card Information Crawler (TCCIC) API

## Version History
<details>
<summary>Expand</summary>

### v1.0.0
- [x] Add Ollama LLM and HuggingFace embedding model
- [x] Fix yaml key error
- [x] Add RAG embedding function
- [x] Add RAG complete function
- [x] Return source information when using RAG
- [x] Gemini flash 2.0
- [x] Improve RAG accuracy 
- [x] HuggingFace severless api for embedding model
- [x] Model yaml

### v2.0.0
- [x] Smarter crawlers
    - [x] A simpler, more extensible, and more maintainable crawler template(card.yaml)
    - [x] Modify the JSON data saving method
- [x] Modify the RAG encoding method
- [x] Logger
- [x] Contextual retrieval
- [x] BM25
- [x] Hybrid search
- [x] Reranker
- [x] Support image crawling

### v3.0.0
- [x] Refactor project structure, Make it more modular
- [X] RESTful API style
- [x] Make crawlers more automated
    - [x] Automatically search all cards
    - [x] Support dynamic web crawler
    - [x] Crawl the bank card lists
    - [x] Crawl the card features
- [x] Support image retrieval
- [x] Customize llm package
- [x] Remove the llama-index framework
- [x] Add batch crawler API
</details>

## To Do
- Add more banks

## RESTful API
A RESTful API for web crawling, data retrieval, and conversation.

### Crawler

1. #### Crawl all cards from the specified bank.  
    ```
    POST http://localhost:1108/api/v1/crawler/card-list
    ```

    #### Request
    Content-Type: application/json
    ```json
    {
        "bank_code": "taishin",
        "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/"
    }
    ```
    * **bank_code** string, Required  
    The bank’s unique identifier

    * **url** string, Required  
    The URL of the bank’s card overview page

    #### Return
    ```json
    {
        "status": "success",
        "message": "The crawling job has been submitted successfully.",
        "data": {
            "job_id": "85cc5f76-8184-4d1d-8936-ea0ca1ca84f3",
            "list_id": "list-73e807e2472d415888e968ceeeb63e87",
            "bank_code": "taishin",
            "card_name": null,
            "card_id": null
        },
        "error": null
    }
    ```
    * **status** string  
    The execution status of the API, either `success` or `fail`.

    * **message** string  
    A brief status message of the API execution.

    * **data** object or null  
        * **job_id** string  
        The execution job ID, which is unique for each run.

        * **list_id** string or null  
        The list ID that stores the crawling information, used for retrieval.

        * **bank_code** string or null  
        The bank code crawled for this task.

        * **card_name** string or null  
        The card name crawled for this task.

        * **card_id** string or null  
        The unique card ID used for conversation and deletion; each card has a different ID.
    
    * **error** string or null  
    If an error occurs during execution, this field records the error message.

2. #### Batch crawl all cards from the specified bank
    ```
    POST http://localhost:1108/api/v1/crawler/batch/card-list
    ```

    #### Request
    Content-Type: application/json
    ```json
    [
        {
            "bank_code": "taishin",
            "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/"
        },
        {
            "bank_code": "ctbcbank",
            "url": "https://www.ctbcbank.com/twrbo/zh_tw/cc_index/cc_product/cc_introduction_index.html"
        }
    ]
    ```
    The parameters are the same as the non-batch list crawler, except they are modified to `array` format.

    #### Return
    ```json
    {
        "status": "success",
        "message": "The crawling job has been submitted successfully.",
        "data": [
            {
                "job_id": "cbf76934-815a-4128-bb97-f7e86145a79b",
                "list_id": "list-928db6b5417e47edbe9985d14c2d1c93",
                "bank_code": "taishin",
                "card_name": null,
                "card_id": null
            },
            {
                "job_id": "cbf76934-815a-4128-bb97-f7e86145a79b",
                "list_id": "list-d6a617d06cc54867a59eb63611dd061f",
                "bank_code": "ctbcbank",
                "card_name": null,
                "card_id": null
            }
        ],
        "error": null
    }
    ```
    The parameters are the same as the non-batch list crawler, with only the `data` field changed to an array format.

3. #### Retrieve the card list information.
    ```
    GET http://localhost:1108/api/v1/crawler/card-list/{list_id}
    ```

    #### Request
    Path parameters
    ```
    http://localhost:1108/api/v1/crawler/card-list/list-928db6b5417e47edbe9985d14c2d1c93
    ```
    * **list_id** string, Required  
    The list ID used for querying information.

    #### Return
    ```json
    {
        "status": "success",
        "message": "Successfully crawled all card information.",
        "data": {
            "bank_code": "taishin",
            "bank_name": "台新銀行",
            "pages": [
                {
                    "page_url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/index.html?type=type1",
                    "cards": [
                        {
                            "title": "太陽卡/玫瑰卡(切換刷方案)",
                            "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg046/card001/"
                        },
                        {
                            "title": "@GoGo卡",
                            "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg021/card001/"
                        },
                    ]
                },
                {
                    "page_url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/index.html?type=type3",
                    "cards": [
                        {
                            "title": "玫瑰卡",
                            "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg013/card0001/"
                        },
                    ]
                }
            ]
        },
        "error": null
    }
    ```
    * **bank_code** string  
    The bank code crawled for this task.

    * **bank_name** string  
    The bank name crawled for this task.

    * **pages** array
        * **page_url** string  
        The URL of the card list.

        * **cards** array
            * **title** string  
            Card name

            * **url** string  
            Card URL

4. #### Crawl card details information and save it as vectors
    ```
    POST http://localhost:1108/api/v1/crawler/card-feature
    ```

    #### Request
    Content-Type: application/json
    ```json
    {
        "bank_code": "taishin",
        "card_name": "FlyGo卡",
        "card_url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg018/flygo/"
    }
    ```
    * **bank_code** string, Required  
    The bank’s unique identifier

    * **card_name** string, Required  
    Card name

    * **card_url** string, Required  
    Card URL 

    #### Return
    ```json
    {
        "status": "success",
        "message": "The crawling job has been submitted successfully.",
        "data": {
            "job_id": "38be2bcf-67ca-4882-b241-18f8b8af32bf",
            "list_id": null,
            "bank_code": "taishin",
            "card_name": "FlyGo卡",
            "card_id": "card-870283de1f264befabbae33cdb1bf5c3"
        },
        "error": null
    }
    ```
    * **job_id** string  
    The execution job ID, which is unique for each run.

    * **list_id** string or null  
    The list ID that stores the crawling information, used for retrieval.

    * **bank_code** string or null  
    The bank code crawled for this task.

    * **card_name** string or null  
    The card name crawled for this task.

    * **card_id** string or null  
    The unique card ID used for conversation and deletion; each card has a different ID.

5. #### Batch Crawl card details information and save it as vectors
    ```
    POST http://localhost:1108/api/v1/crawler/batch/card-feature
    ```

    #### Request
    Content-Type: application/json
    ```json
    [
        {
            "bank_code": "taishin",
            "card_name": "FlyGo卡",
            "card_url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg018/flygo/"
        },
        {
            "bank_code": "taishin",
            "card_name": "太陽卡/玫瑰卡",
            "card_url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg046/card001/"
        }
    ]
    ```
    The parameters are the same as the non-batch card crawler, except they are modified to `array` format.

    #### Return
    ```json
    {
        "status": "success",
        "message": "The crawling job has been submitted successfully.",
        "data": [
            {
                "job_id": "38be2bcf-67ca-4882-b241-18f8b8af32bf",
                "list_id": null,
                "bank_code": "taishin",
                "card_name": "FlyGo卡",
                "card_id": "card-870283de1f264befabbae33cdb1bf5c3"
            },
            {
                "job_id": "4abbb502-2301-73f4-216e-ad72a034c35f",
                "list_id": null,
                "bank_code": "taishin",
                "card_name": "太陽卡/玫瑰卡",
                "card_id": "card-870283de1f264befabbae33cdb1bf5c3"
            },
        ],
        "error": null
    }
    ```
    The parameters are the same as the non-batch card crawler, with only the `data` field changed to an array format.

6. #### Retrieve the processing status of the card details information.
    ```
    GET http://localhost:1108/api/v1/crawler/card-feature/{job_id}/status
    ```

    #### Request
    Path parameters
    ```
    http://localhost:1108/api/v1/crawler/card-feature/38be2bcf-67ca-4882-b241-18f8b8af32bf/status
    ```
    * **job_id** string, Required  
    The execution job ID

    #### Return
    ```json
    {
        "status": "success",
        "message": "Query job status successfully.",
        "data": {
            "job_status": true
        },
        "error": null
    }
    ```
    * **job_status** boolean  
    The status of the execution job.


### Card

1. #### Chat
    ```
    POST http://localhost:1108/api/v1/card/qa
    ```

    #### Request
    Content-Type: application/json
    ```json
    {
        "question": "信用卡的回饋額度",
        "bank_code": "taishin",
        "card_id": "card-870283de1f264befabbae33cdb1bf5c3"
    }
    ```
    * **question** string, Required  
    User’s question

    * **bank_code** string or null  
    Bank code used to restrict bank queries.

    * **card_id** string or null  
    Card ID used to restrict card queries.

    You may use any combination of `bank_code` and `card_id` to restrict the search range.

    #### Return
    ```json
    {
        "status": "success",
        "message": "Query successfully.",
        "data": {
            "response": "台新銀行信用卡的相關回饋額度如下...",
            "sources": [
                {
                    "text": "這是一張台新銀行信用卡的資訊頁面，主要介紹了 FlyGo...", 
                    "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/future/bf0a55e5-1f47-11f0-b432-0050568c09e3",
                    "card_id": "card-c1e620f1afb049dea8bcd238e29b80c1",
                    "bank_code": "taishin"
                },
                {
                    "text": "台新銀行FlyGo卡提供精選航旅最高5%，海外最高3%回饋...",
                    "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/future/89cd913a-8172-11ef-b432-0050568c09e3",
                    "card_id": "card-c1e620f1afb049dea8bcd238e29b80c1",
                    "bank_code": "taishin"
                },
            ]
        },
        "error": null
    }
    ```
    * **response** string  
    AI’s summary response

    * **sources** array
        * **text** string  
        Source text of the data

        * **url** string  
        Source url of the data

        * **card_id** string  
        Source card ID of the data

        * **bank_code** string  
        Source bank code of the data

2. #### Delete Card
    ```
    DELETE http://localhost:1108/api/v1/card/{card_id}
    ```

    #### Request
    Path parameters
    ```
    http://localhost:1108/api/v1/card/card-c1e620f1afb049dea8bcd238e29b80c1
    ```
    * **card_id**: string, Required
    The card’s unique ID

    #### Return
    * Status: 204(Success)
