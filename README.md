# TCCIC
Taiwan Credit Card Information Crawler (TCCIC) API

## TO DO
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
- [ ] Customize llm package
- [ ] Remove the llama-index framework