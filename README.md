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

### v4.0.0
- [x] API Key authentication
- [x] Async job queue worker pool to prevent CPU exhaustion under high request volume
- [x] Batch request size limit & queue full protection
- [x] File locking for concurrent job status writes
- [x] Add `GET /health` endpoint
- [x] Add `GET /card/` list cards endpoint
- [x] Job status changed from boolean to enum (`pending` / `completed` / `error`)
- [x] Prompt injection defense for Q&A
- [x] LLM batch size and rate limit sleep configurable per provider

### v5.0.0
- [x] Add SQLite to save metadata
- [x] Record the crawler status to the SQLite database.
- [x] Add `jobs` API has been added to replace the previous query endpoint. The query now uses the `job_id`, and the easily confused `card_id` and `list_id` have been removed.
- [x] Prevent duplicate card crawls and check unfinished jobs at system startup.
- [x] Add summary cache-hit path to reduce LLM usage
- [x] Added analysis of all chunks within a single card to extract established facts for fast search.
- [x] Routes the user's question to `vector` or `SQL` search based on its type.
- [x] Add a callback parameter to the API to notify when a job completes

</details>

## To Do
- [ ] Add more banks

## System Architecture
<img src="https://github.com/qpal147147/TCCIC/blob/main/docs/System_Architecture.png" height="700">

## Development Environment
**OS:** Ubuntu 22.04.3 LTS  
**Python Version:**  3.11.13  
**Docker Version:** 27.0.3

### Installation
1. Install the vector database(Milvus)  
Follow the installation guide on [this page](https://milvus.io/docs/install_standalone-docker.md).

2. Create a conda environment and installing dependencies
    ```bash
    conda create -n tccic python=3.11
    git clone https://github.com/qpal147147/TCCIC.git
    cd TCCIC
    pip install -r requirement.txt
    playwright install
    ```

3. Modify project settings
    * Choose your [LLM provider](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/configs/global_settings.py#L64) and [Embedding provider](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/configs/global_settings.py#L65)
        ```python
        ACTIVE_LLM_PROVIDER: Literal["openai", "gemini", "huggingface"] = "gemini"
        ACTIVE_EMBEDDING_PROVIDER: Literal["openai", "gemini", "huggingface"] = "gemini"
        ```
        If your provider is not listed, refer to [this guide](https://github.com/qpal147147/TCCIC?tab=readme-ov-file#additional-notes) to customize your own option.
    * Vector database [URL](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/configs/global_settings.py#L83)
        ```python
        VECTOR_CLIENT_URL: str = "http://localhost:19530"
        ```
    * API Key  
    Copy [.env.example](.env.example) to `.env` and fill in your keys. `.env` is ignored by git, so your keys are never committed.
        ```bash
        cp .env.example .env
        ```
        `AUTH_KEY` is the key your clients send in the `X-API-Key` header. It also signs [callbacks](#callback).

4. Run API Server
    ```python
    python -m app.main
    ```
    The SQLite database that stores jobs, cards and the summary cache is created automatically on first start, and its schema is upgraded on every start. No setup is needed.
## Additional Notes
1. [Log settings](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/configs/global_settings.py#L81)

2. [Data storage location settings](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/configs/global_settings.py#L90)

3. [Crawler concurrency settings](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/configs/global_settings.py#L95)

4. Callback settings  
    Defined in `GlobalSettings` in `app/configs/global_settings.py`.
    ```python
    CALLBACK_ALLOW_PRIVATE: bool = False  # Allow localhost / private targets; development only
    CALLBACK_TIMEOUT_S: float = 10.0      # Per-attempt timeout
    CALLBACK_RETRY_DELAYS_S: tuple[float, ...] = (5.0, 30.0, 120.0)  # Waits between attempts
    CALLBACK_MAX_WORKERS: int = 4         # Threads delivering callbacks concurrently
    ```

5. Custom LLM and Embedding
    1. Implement basic parameters in [your class](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/configs/global_settings.py#L7).  
    Extend `BaseModelConfig` and set its fields; `rate_limit_sleep_s` and `llm_batch_size` have defaults.
        ```python
        class CustomLLMConfig(BaseModelConfig):
            """Custom LLM config"""
            chat_model_name: str = "your-chat-model"
            temperature: float = 0.5
            max_tokens: int = 8192
            embedding_model_name: str = "your-embedding-model"
            embedding_dim: int = 1024
            gpu: bool = False
            rate_limit_sleep_s: float = 0.0
            llm_batch_size: int = 10
        ```
    2. Add custom options to lists and functions
        ```python
        # LLM settings
        ACTIVE_LLM_PROVIDER: Literal["openai", "gemini", "huggingface", "custom"] = "custom"
        ACTIVE_EMBEDDING_PROVIDER: Literal["openai", "gemini", "huggingface", "custom"] = "custom"
        ```

        ```python
        def get_active_llm_config(self)
            # ...
            provider_map = {
                "openai": OpenAIConfig(...),
                "gemini": GeminiConfig(...),
                "huggingface": HuggingFaceConfig(...),
                "custom": CustomLLMConfig(...),
            }
            # ...
        
        def get_active_embedding_config(self)
            # ...
            provider_map = {
                "openai": OpenAIConfig(...),
                "gemini": GeminiConfig(...),
                "huggingface": HuggingFaceConfig(...),
                "custom": CustomLLMConfig(...),
            }
            # ...
        ```
    
    3. Implement methods for invoking LLM and Embedding models.You need to create your own class and implement the interface.
        ```python
        # Example
        # app.services.chat
        # app.services.embedding
        
        class CustomChat(ChatInterface):
            def __init__(...)
            async def chat(...)
            async def summary_docs(...)

        class CustomEmbedding(EmbeddingInterface):
            def __init__(...)
            async def create_embeddings(...)
        ```
    
    4. Register your class in the factory pattern.
        ```python
        # app.services.llm_factory
        class LLMFactory:
            def get_llm():
                if llm_provider == "custom":
                    return CustomChat(...)

            def get_embedding():
                if llm_provider == "custom":
                    return CustomEmbedding(...)
        ```
    
6. Customize Crawling Scope  
    Each bank has its own crawler configuration file in [app/configs/banks/](app/configs/banks), named `<bank_code>.yaml`.
    Each parameter defines the scope of data extraction on the webpage.  
    To modify the crawler behavior, adjust [Card List Spider](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/crawler/tccic/spiders/card_list_spider.py) and [Card Feature Spider](https://github.com/qpal147147/TCCIC/blob/12dcc9c79ac329ce837854958af9c0ac0e97430b/app/crawler/tccic/spiders/card_feature_spider.py) to implement your custom crawling logic.



## RESTful API
A RESTful API for web crawling, data retrieval, and conversation.

> **Authentication:** All endpoints except `GET /health` require a valid `X-API-Key` header.
> ```
> X-API-Key: your-api-key
> ```

### Health

1. #### Check service status
    ```
    GET http://localhost:1108/api/v1/health
    ```

    #### Return
    ```json
    {
        "status": "success",
        "message": "Service is healthy.",
        "data": null,
        "error": null
    }
    ```
    Returns `200` if healthy, `503` if Milvus is unreachable.

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
        "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/",
        "callback_url": "https://your-server.example.com/tccic-hook"
    }
    ```
    * **bank_code** string, Required  
    The bank’s unique identifier. Only lowercase letters, digits, `-` and `_` are allowed.

    * **url** string, Required  
    The URL of the bank’s card overview page

    * **callback_url** string, Optional  
    The URL to be notified when the job finishes. See [Callback](#callback).

    #### Return
    ```json
    {
        "status": "success",
        "message": "The crawling job has been submitted successfully.",
        "data": {
            "job_id": "85cc5f76-8184-4d1d-8936-ea0ca1ca84f3",
            "bank_code": "taishin",
            "card_name": null,
            "card_key": null
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
        The execution job ID, which is unique for each run. Use it to query the status and result in [Jobs](#jobs).

        * **bank_code** string or null  
        The bank code crawled for this task.

        * **card_name** string or null  
        The card name crawled for this task. Always `null` for card list jobs.

        * **card_key** string or null  
        The card’s unique key. Always `null` for card list jobs.
    
    * **error** string or null  
    If an error occurs during execution, this field records the error message.

    Returns `202` when the job is queued, `422` if a parameter is invalid, and `503` if the job queue is full (retry after the `Retry-After` header).

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
                "bank_code": "taishin",
                "card_name": null,
                "card_key": null
            },
            {
                "job_id": "0d3a5e21-6f7b-4c1e-9a52-3b8e4f1c7d90",
                "bank_code": "ctbcbank",
                "card_name": null,
                "card_key": null
            }
        ],
        "error": null
    }
    ```
    The parameters are the same as the non-batch list crawler, with only the `data` field changed to an array format. Each item is a separate job with its own `job_id`; all jobs in one request share a `batch_id`.

    Returns `400` if the request has more items than the batch limit (default `50`).

3. #### Crawl card details information and save it as vectors
    ```
    POST http://localhost:1108/api/v1/crawler/card-feature
    ```

    #### Request
    Content-Type: application/json
    ```json
    {
        "bank_code": "taishin",
        "card_name": "FlyGo卡",
        "card_url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg018/flygo/",
        "callback_url": "https://your-server.example.com/tccic-hook"
    }
    ```
    * **bank_code** string, Required  
    The bank’s unique identifier. Only lowercase letters, digits, `-` and `_` are allowed.

    * **card_name** string, Required  
    Card name

    * **card_url** string, Required  
    Card URL. Must start with `http://` or `https://`.

    * **callback_url** string, Optional  
    The URL to be notified when the job finishes. See [Callback](#callback).

    #### Return
    ```json
    {
        "status": "success",
        "message": "The crawling job has been submitted successfully.",
        "data": {
            "job_id": "38be2bcf-67ca-4882-b241-18f8b8af32bf",
            "bank_code": "taishin",
            "card_name": "FlyGo卡",
            "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1"
        },
        "error": null
    }
    ```
    * **job_id** string  
    The execution job ID, which is unique for each run. Use it to query the status and result in [Jobs](#jobs).

    * **bank_code** string or null  
    The bank code crawled for this task.

    * **card_name** string or null  
    The card name crawled for this task.

    * **card_key** string or null  
    The card’s unique key, derived from the bank code and card URL. It stays the same when the card is re-crawled, so it can be stored permanently and used for conversation and deletion.

    Returns `202` when the job is queued. If the same card is already queued or running, no new job is created: the existing `job_id` is returned with `200`, and the `callback_url` of this request is also notified when that job finishes. Returns `422` if a parameter is invalid, and `503` if the job queue is full.

4. #### Batch Crawl card details information and save it as vectors
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
                "bank_code": "taishin",
                "card_name": "FlyGo卡",
                "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1"
            },
            {
                "job_id": "4abbb502-2301-43f4-916e-ad72a034c35f",
                "bank_code": "taishin",
                "card_name": "太陽卡/玫瑰卡",
                "card_key": "2c7e4b9a1d3f5e6c8a0b2d4f6e8a1c3e5b7d9f0a"
            }
        ],
        "error": null
    }
    ```
    The parameters are the same as the non-batch card crawler, with only the `data` field changed to an array format. A card that is already queued or running returns its existing `job_id`, the same as the non-batch crawler.

    Returns `202` if any new job is queued, `200` if every card is already queued or running, and `400` if the request has more items than the batch limit (default `50`).

### Callback
If a crawler request includes `callback_url`, the service sends one `POST` request to that URL when the job finishes, whether it succeeded or failed. You need to provide an endpoint that accepts the request below. Polling [Jobs](#jobs) still works with or without a callback.

1. #### Request sent to your endpoint
    Headers
    ```
    Content-Type: application/json
    X-TCCIC-Job-Id: 38be2bcf-67ca-4882-b241-18f8b8af32bf
    X-TCCIC-Timestamp: 1760720440
    X-TCCIC-Signature: sha256=5f2c8e...
    ```
    * **X-TCCIC-Job-Id** string  
    The job that finished.

    * **X-TCCIC-Timestamp** string  
    Unix time in seconds when the request was sent. Reject old timestamps to prevent replayed requests.

    * **X-TCCIC-Signature** string  
    `sha256=` followed by the hex HMAC-SHA256 of `{timestamp}.{raw body}`, signed with your API key.

    The body is the same as the `data` of [Retrieve the job status](#jobs). It does not include the crawl result; retrieve it from [Retrieve the job result](#jobs).

2. #### Verify the signature
    ```python
    import hashlib
    import hmac

    def verify(api_key: str, timestamp: str, body: bytes, signature: str) -> bool:
        expected = hmac.new(api_key.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
        return hmac.compare_digest(f"sha256={expected.hexdigest()}", signature)
    ```
    Verify against the raw request body. Parsing and re-serializing the JSON changes the bytes and the signature will not match.

3. #### Response from your endpoint
    Return any `2xx` status code. `5xx`, `408`, `429`, timeouts and connection errors are retried, up to 4 attempts in total (waiting 5, 30 and 120 seconds). Other `4xx` status codes are not retried.

    `callback_url` must start with `http://` or `https://` and must not point to `localhost` or a private network address, otherwise the crawler request returns `422`. To test locally, set `CALLBACK_ALLOW_PRIVATE = True` in `global_settings.py` and run the [example receiver](scripts/callback_receiver.py):
    ```bash
    python -m scripts.callback_receiver --port 9000
    ```

### Jobs

1. #### Retrieve the job status
    ```
    GET http://localhost:1108/api/v1/jobs/{job_id}
    ```

    #### Request
    Path parameters
    ```
    http://localhost:1108/api/v1/jobs/38be2bcf-67ca-4882-b241-18f8b8af32bf
    ```
    * **job_id** string, Required  
    The execution job ID returned by the crawler API. Works for both card list and card feature jobs.

    #### Return
    ```json
    {
        "status": "success",
        "message": "Query job status successfully.",
        "data": {
            "job_id": "38be2bcf-67ca-4882-b241-18f8b8af32bf",
            "job_type": "card_feature",
            "status": "completed",
            "bank_code": "taishin",
            "target_url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/cg018/flygo/",
            "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1",
            "batch_id": null,
            "error": null,
            "stats": {
                "images": 21,
                "cached": 21,
                "summarized": 0,
                "failed": 0,
                "vectorized": 88,
                "facts_extracted": true
            },
            "created_at": "2026-10-17T08:00:00.000000Z",
            "started_at": "2026-10-17T08:00:01.000000Z",
            "finished_at": "2026-10-17T08:03:12.000000Z"
        },
        "error": null
    }
    ```
    * **job_id** string  
    The execution job ID

    * **job_type** string  
    `card_list` or `card_feature`

    * **status** string  
    The status of the job: `queued` (waiting in the queue), `running` (in progress), `completed` (success), `error` (failed), `config_broken` (the crawler settings no longer match the page).

    * **bank_code** string  
    The bank code crawled for this task.

    * **target_url** string  
    The URL crawled for this task.

    * **card_key** string or null  
    The card’s unique key. `null` for card list jobs.

    * **batch_id** string or null  
    Shared by all jobs submitted in one batch request. `null` for non-batch requests.

    * **error** string or null  
    The reason the job failed.

    * **stats** object or null  
    What the job produced. Card list jobs report `cards` and `pages`. Card feature jobs report `images` (screenshots), `cached` (summaries reused without calling the LLM), `summarized` (summaries newly generated), `failed` (images that could not be summarized), `vectorized` (records saved to the vector database) and `facts_extracted`.

    * **created_at**, **started_at**, **finished_at** string or null  
    When the job was submitted, started and finished, in UTC.

    Returns `404` if the job does not exist.

2. #### Retrieve the job result
    ```
    GET http://localhost:1108/api/v1/jobs/{job_id}/result
    ```

    #### Request
    Path parameters
    ```
    http://localhost:1108/api/v1/jobs/85cc5f76-8184-4d1d-8936-ea0ca1ca84f3/result
    ```
    * **job_id** string, Required  
    The execution job ID

    #### Return (card list job)
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
                        }
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

    #### Return (card feature job)
    ```json
    {
        "status": "success",
        "message": "Card feature crawl completed and vectorized.",
        "data": {
            "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1",
            "card_name": "FlyGo卡",
            "bank_code": "taishin",
            "stats": {
                "images": 21,
                "cached": 21,
                "summarized": 0,
                "failed": 0,
                "vectorized": 88,
                "facts_extracted": true
            }
        },
        "error": null
    }
    ```
    The card content is saved in the vector database. Use `card_key` in [Card](#card) to chat about or delete it.

    | Status code | Meaning |
    |-------------|---------|
    | `200` | The job completed. |
    | `400` | The job failed; `error` holds the reason. |
    | `404` | The job does not exist. |
    | `409` | The job is still `queued` or `running`; retry after the `Retry-After` header. |
    | `410` | The job completed but its result file has been deleted. |


### Card

1. #### List all vectorized cards
    ```
    GET http://localhost:1108/api/v1/card
    ```

    #### Request
    Query parameters (optional)
    ```
    http://localhost:1108/api/v1/card?bank_code=taishin
    ```
    * **bank_code** string, Optional  
    Filter results by bank code. Omit to return all cards.

    #### Return
    ```json
    {
        "status": "success",
        "message": "Found 2 card(s).",
        "data": [
            {
                "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1",
                "card_name": "FlyGo卡",
                "bank_code": "taishin"
            },
            {
                "card_key": "2c7e4b9a1d3f5e6c8a0b2d4f6e8a1c3e5b7d9f0a",
                "card_name": "太陽卡/玫瑰卡",
                "bank_code": "taishin"
            }
        ],
        "error": null
    }
    ```

2. #### Chat
    ```
    POST http://localhost:1108/api/v1/card/qa
    ```

    #### Request
    Content-Type: application/json
    ```json
    {
        "question": "FlyGo卡的海外回饋是多少？",
        "bank_code": "taishin",
        "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1"
    }
    ```
    * **question** string, Required  
    User’s question

    * **bank_code** string or null  
    Bank code used to restrict bank queries.

    * **card_key** string or null  
    Card key used to restrict card queries.

    You may use any combination of `bank_code` and `card_key` to restrict the search range.

    The question is answered in one of two ways, reported in `route`:
    * **vector**: searches the card content in the vector database. Used when `card_key` is given, and for questions about details such as a card’s offers or conditions.
    * **sql**: compares the facts of every card, such as annual fee, rewards and travel benefits. Used for questions that rank cards, such as "哪張卡年費最低？". Rewards in different forms (cash, points, miles) are listed separately rather than compared directly.

    #### Return
    ```json
    {
        "status": "success",
        "message": "Query successfully.",
        "data": {
            "response": "FlyGo卡海外消費最高享3%回饋...",
            "route": "vector",
            "sources": [
                {
                    "text": "FlyGo卡｜回饋\n海外消費：最高3%回饋...",
                    "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/future/bf0a55e5-1f47-11f0-b432-0050568c09e3",
                    "section": "回饋",
                    "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1",
                    "card_name": "FlyGo卡",
                    "bank_code": "taishin"
                },
                {
                    "text": "FlyGo卡｜優惠活動\n精選航旅最高5%回饋...",
                    "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/future/89cd913a-8172-11ef-b432-0050568c09e3",
                    "section": "優惠活動",
                    "card_key": "9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1",
                    "card_name": "FlyGo卡",
                    "bank_code": "taishin"
                }
            ]
        },
        "error": null
    }
    ```
    * **response** string  
    AI’s summary response

    * **route** string  
    How the question was answered: `vector` or `sql`.

    * **sources** array
        * **text** string  
        Source text of the data. On the `sql` route, the facts of the card that were compared.

        * **url** string  
        Source url of the data

        * **section** string or null  
        Topic of the source text: `產品特色`, `回饋`, `優惠活動`, `年費`, `申請資格`, `注意事項` or `其他`. `null` on the `sql` route.

        * **card_key** string  
        Source card key of the data

        * **card_name** string  
        Source card name of the data

        * **bank_code** string  
        Source bank code of the data

3. #### Delete Card
    ```
    DELETE http://localhost:1108/api/v1/card/{card_key}
    ```

    #### Request
    Path parameters
    ```
    http://localhost:1108/api/v1/card/9a1f0c3e7b2d4856a0e1f2c3b4d5e6f7a8b9c0d1
    ```
    * **card_key**: string, Required  
    The card’s unique key

    #### Return
    * Status: 204(Success)

    Deletes the card’s vectors and facts. The card itself is kept, and crawling it again restores them.
