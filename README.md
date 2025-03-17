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
- [ ] Smarter crawlers
    - [ ] A simpler, more extensible, and more maintainable crawler template(card.yaml)
    - [ ] Modify the JSON data saving method
- [ ] Modify the RAG encoding method
- [ ] Hybrid search

## Note
1. Using RecursiveTextSplitter to split text, but not accurately including the relationship between paragraphs.

2. Tried to use LLM to automatically split paragraphs from a page, but the performance and stability were not satisfactory.

3. Hybird search is not used because the need for an additional model will increase the cost.

4. According to [this article](https://www.anthropic.com/news/contextual-retrieval), including a knowledge base in the prompt is the easiest and most effective way to achieve this.

    >Sometimes the simplest solution is the best. If your knowledge base is smaller than 200,000 tokens (about 500 pages of material), you can just include the entire knowledge base in the prompt that you give the model, with no need for RAG or similar methods.

5. Base on point 4, use LLM to summarize the content of each page and embed the original text in metadata. Besides avoiding additional noise, it also obtains the original text to improve the accuracy of the query stage.

6. The summary text length is limited to 500 characters, because the embedding model allows a maximum of 512 tokens.