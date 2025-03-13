# TCCIC
Taiwan Credit Card Information Crawler (TCCIC) API

## TO DO
- [x] Add Ollama LLM and HuggingFace embedding model
- [x] Fix yaml key error
- [x] Add RAG embedding function
- [x] Add RAG complete function
- [x] Return source information when using RAG
- [x] Gemini flash 2.0
- [x] Improve RAG accuracy 
- [ ] HuggingFace severless api for embedding model
- [ ] Model yaml
- [ ] Parse base64 image from html information

## Note
1. Using RecursiveTextSplitter to split text, but not accurately including the relationship between paragraphs.

2. Tried to use LLM to automatically split paragraphs from a page, but the performance and stability were not satisfactory.

3. Hybird search is not used because the need for an additional model will increase the cost.

4. According to [this article](https://www.anthropic.com/news/contextual-retrieval), including a knowledge base in the prompt is the easiest and most effective way to achieve this.

    >Sometimes the simplest solution is the best. If your knowledge base is smaller than 200,000 tokens (about 500 pages of material), you can just include the entire knowledge base in the prompt that you give the model, with no need for RAG or similar methods.

5. Base on point 4, use LLM to summarize the content of each page and embed the original text in metadata. Besides avoiding additional noise, it also obtains the original text to improve the accuracy of the query stage.